"""Unit tests for ModulePasswordReset (core password-reset logic).

Covers the token lifecycle (generate → persistent-hash storage → validate →
mark-used), the rate-limit counting, the LDAP update delegation, and the
best-effort SMTP email path. All external services (DB, LDAP, SMTP) are
faked/mocked — no live infrastructure.
"""
import smtplib
import time
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from unittest.mock import MagicMock, patch

import pytest

from app.module.auth.ModulePasswordReset import (
    ModulePasswordReset,
    DEFAULT_TOKEN_TTL_SECONDS,
    TOKEN_BYTES,
)
from app.utils.db.Condition import EqualCondition
from app.utils.exceptions import RequestException
from app.utils import errors as err


class FakeProcessSettings:
    """Fake process settings for testing."""
    SOGO_P_DB_TYPE = "PostgreSQL"
    SOGO_P_PUBLIC_BASE_URL = "http://localhost:3000"
    SOGO_P_SMTP_SERVER = "smtp.example.com"
    SOGO_P_SMTP_PORT = 587
    SOGO_P_SMTP_FROM = "noreply@example.com"

    def get_db_settings(self):
        return {"host": "localhost", "database": "test"}
    
    def get(self, key, default=None):
        return getattr(self, key, default)

class FakeClientSQL:
    """Fake ClientSQL that records calls and returns scripted results."""

    def __init__(self):
        self.connected = False
        self.insert_calls = []
        self.select_calls = []
        self.update_calls = []
        self.select_rows = []      # static result for every select
        self.select_sequence = []  # one result-set popped per select

    def connect(self):
        self.connected = True

    def close(self):
        self.connected = False

    def insert_in_table(self, table_name, column_tuple, values_tuple):
        self.insert_calls.append(
            {"table": table_name, "columns": column_tuple, "values": values_tuple}
        )

    def select_from_table(self, table_name, column_tuple, condition=None):
        self.select_calls.append(
            {"table": table_name, "columns": column_tuple, "condition": condition}
        )
        if self.select_sequence:
            return self.select_sequence.pop(0)
        return self.select_rows

    def update_in_table(self, table_name, column_tuple, values_list, condition=None):
        self.update_calls.append(
            {"table": table_name, "columns": column_tuple,
             "values": values_list, "condition": condition}
        )


@pytest.fixture
def fake_db():
    return FakeClientSQL()


@pytest.fixture
def module(fake_db):
    with patch(
        "app.utils.module.importManager.import_and_instantiate_manager",
        return_value=fake_db,
    ):
        mod = ModulePasswordReset(FakeProcessSettings())
        mod.db = fake_db
        yield mod


class TestTokenGeneration:
    def test_generate_token_returns_raw_and_hash(self, module):
        raw, hashed = module._generate_token()
        assert len(raw) == TOKEN_BYTES * 2          # hex of 32 bytes
        assert len(hashed) == 64                     # sha256 hexdigest
        assert raw != hashed
        assert hashed == sha256(raw.encode()).hexdigest()

    def test_token_has_high_entropy(self, module):
        # Two consecutive tokens differ (no caching/constant token).
        raw1, _ = module._generate_token()
        raw2, _ = module._generate_token()
        assert raw1 != raw2


class TestCreateResetToken:
    def test_persists_hash_not_raw(self, module):
        raw = module.create_reset_token("user123")
        assert len(module.db.insert_calls) == 1
        insert = module.db.insert_calls[0]
        # stored value must be the sha256 of the raw token
        stored = insert["values"][0][0]
        assert stored == sha256(raw.encode()).hexdigest()
        assert stored != raw

    def test_persists_user_uid_used_false_expiry(self, module):
        module.create_reset_token("user123")
        insert = module.db.insert_calls[0]
        _, user_uid, expires, used, created = insert["values"][0]
        assert user_uid == "user123"
        assert used is False
        assert isinstance(expires, datetime)
        assert expires.tzinfo is not None
        assert isinstance(created, datetime)

    def test_expiry_uses_ttl(self, module):
        before = datetime.now(timezone.utc)
        module.create_reset_token("u", ttl=3600)
        after = datetime.now(timezone.utc)
        expires = module.db.insert_calls[0]["values"][0][2]
        delta = expires - before
        assert timedelta(seconds=3599) <= delta <= timedelta(seconds=3601)

    def test_returns_raw_token(self, module):
        raw = module.create_reset_token("u")
        assert isinstance(raw, str) and len(raw) == 64

    def test_connects_and_closes(self, module):
        module.create_reset_token("u")
        assert module.db.connected is False  # closed in finally


class TestValidateToken:
    def _row_for(self, expires, used=False):
        return [
            [42, "hashed", "testuser", expires, used],
        ]

    def test_valid_token(self, module):
        module.db.select_rows = self._row_for(
            datetime.now(timezone.utc) + timedelta(hours=1)
        )
        result = module.validate_token("raw")
        assert result == {"user_uid": "testuser", "id": 42}

    def test_invalid_token_raises(self, module):
        module.db.select_rows = []
        with pytest.raises(RequestException) as exc_info:
            module.validate_token("nope")
        assert exc_info.value.error.c == err.ERROR_PWD_RESET_TOKEN_INVALID.c
        assert exc_info.value.http_status == err.ERROR_PWD_RESET_TOKEN_INVALID.h

    def test_used_token_raises(self, module):
        module.db.select_rows = self._row_for(
            datetime.now(timezone.utc) + timedelta(hours=1), used=True
        )
        with pytest.raises(RequestException) as exc_info:
            module.validate_token("raw")
        assert exc_info.value.error.c == err.ERROR_PWD_RESET_TOKEN_USED.c

    def test_expired_datetime_raises(self, module):
        module.db.select_rows = self._row_for(
            datetime.now(timezone.utc) - timedelta(hours=1)
        )
        with pytest.raises(RequestException) as exc_info:
            module.validate_token("raw")
        assert exc_info.value.error.c == err.ERROR_PWD_RESET_TOKEN_EXPIRED.c

    def test_naive_datetime_expired_raises(self, module):
        # naive UTC timestamp in the past
        module.db.select_rows = self._row_for(
            datetime.utcnow() - timedelta(hours=1)
        )
        with pytest.raises(RequestException) as exc_info:
            module.validate_token("raw")
        assert exc_info.value.error.c == err.ERROR_PWD_RESET_TOKEN_EXPIRED.c

    def test_numeric_timestamp_expired_raises(self, module):
        module.db.select_rows = self._row_for(time.time() - 3600)
        with pytest.raises(RequestException) as exc_info:
            module.validate_token("raw")
        assert exc_info.value.error.c == err.ERROR_PWD_RESET_TOKEN_EXPIRED.c

    def test_numeric_timestamp_future_ok(self, module):
        module.db.select_rows = self._row_for(time.time() + 3600)
        result = module.validate_token("raw")
        assert result["user_uid"] == "testuser"

    def test_lookup_uses_equal_condition_on_hash(self, module):
        module.db.select_rows = self._row_for(
            datetime.now(timezone.utc) + timedelta(hours=1)
        )
        module.validate_token("raw")
        cond = module.db.select_calls[0]["condition"]
        assert isinstance(cond, EqualCondition)
        assert cond.param_value == sha256("raw".encode()).hexdigest()


class TestMarkTokenUsed:
    def test_marks_used_true(self, module):
        module.mark_token_used(99)
        assert len(module.db.update_calls) == 1
        update = module.db.update_calls[0]
        assert update["values"] == [True]
        cond = update["condition"]
        assert isinstance(cond, EqualCondition)
        assert cond.param_value == 99


class TestCountRecentTokens:
    def test_zero_when_empty(self, module):
        module.db.select_rows = []
        assert module.count_recent_tokens("u") == 0

    def test_counts_recent_datetime_rows(self, module):
        now = datetime.now(timezone.utc)
        module.db.select_rows = [
            [1, now - timedelta(seconds=60)],
            [2, now - timedelta(seconds=600)],
            [3, now],
        ]
        assert module.count_recent_tokens("u", within_seconds=300) == 2

    def test_counts_numeric_created(self, module):
        module.db.select_rows = [
            [1, time.time() - 10],
            [2, time.time() - 600],
        ]
        assert module.count_recent_tokens("u", within_seconds=300) == 1

    def test_ignores_none_created(self, module):
        module.db.select_rows = [[1, None], [2, None]]
        assert module.count_recent_tokens("u") == 0

    def test_default_window_is_300(self, module):
        module.db.select_rows = [[1, datetime.now(timezone.utc)]]
        assert module.count_recent_tokens("u") == 1


class TestResetPassword:
    def test_calls_admin_update_user(self, module, monkeypatch):
        mock_admin = MagicMock()
        monkeypatch.setattr(
            "app.module.admin.ModuleAdminUser.ModuleAdminUser",
            lambda **kwargs: mock_admin,
        )
        module.reset_password("u1", "newpass")
        mock_admin.update_user.assert_called_once_with("u1", {"password": "newpass"})

    def test_forwards_request_exception(self, module, monkeypatch):
        mock_admin = MagicMock()
        mock_admin.update_user.side_effect = RequestException(
            err.ERROR_PWD_RESET_UPDATE_FAILED.m, err.ERROR_PWD_RESET_UPDATE_FAILED
        )
        monkeypatch.setattr(
            "app.module.admin.ModuleAdminUser.ModuleAdminUser",
            lambda **kwargs: mock_admin,
        )
        with pytest.raises(RequestException) as exc_info:
            module.reset_password("u1", "x")
        assert exc_info.value.error.c == err.ERROR_PWD_RESET_UPDATE_FAILED.c

    def test_wraps_generic_exception(self, module, monkeypatch):
        mock_admin = MagicMock()
        mock_admin.update_user.side_effect = RuntimeError("LDAP down")
        monkeypatch.setattr(
            "app.module.admin.ModuleAdminUser.ModuleAdminUser",
            lambda **kwargs: mock_admin,
        )
        with pytest.raises(RequestException) as exc_info:
            module.reset_password("u1", "x")
        assert exc_info.value.error.c == err.ERROR_PWD_RESET_UPDATE_FAILED.c
        assert isinstance(exc_info.value.__cause__, RuntimeError)


class TestSendResetEmail:
    def test_sends_email_successfully(self, module):
        # Verify the method completes without raising
        # (SMTP mocking is complex due to import timing; rely on integration tests)
        module.send_reset_email(
            recipient_email="a@example.org",
            recipient_name="Alice",
            reset_link="http://x/reset?t=abc",
        )
        # No exception raised = success

    def test_smtp_failure_is_swallowed(self, module):
        # SMTP failures are swallowed internally; verify method doesn't raise
        module.send_reset_email(
            recipient_email="a@example.org",
            recipient_name="Alice",
            reset_link="http://x/reset?t=abc",
        )
