# pylint: disable=invalid-sequence-index
"""Coverage tests for the remaining branches of ModuleTOTP + ModulePasswordReset.

Task sogo-cov-59: extend past the existing TOTP / password-reset suites with
the uncovered branches:

* TOTP  — verify window / clock-drift (``valid_window``), invalid/reused codes,
  all DB persistence branches (insert vs. update, enable/disable guards) and
  the decryption/encryption seams.
  (Recovery codes / rate limiting do *not* exist in ModuleTOTP in the checked
  out code — they live in the interface/API layer — so those branches are
  covered to the extent they surface here; see deviation note.)
* Password-reset — token expiry (aware/naive/numeric timestamps), token reuse
  (used flag), invalid token, ``count_recent_tokens`` naive-datetime branch,
  numeric-created branch, None-created branch, LDAP update success /
  RequestException passthrough / generic-exception wrapping, and the SMTP
  mailbox path including the success-logging branch and the silent-failure
  branch with default vs. explicit SMTP host/port.

Everything runs fully offline: DB, LDAP and SMTP collaborators are mocked.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from unittest.mock import MagicMock, patch

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest
import pyotp

from app.module.auth.ModulePasswordReset import (
    DEFAULT_TOKEN_TTL_SECONDS,
    TOKEN_BYTES,
    ModulePasswordReset,
)
from app.module.auth.ModuleTOTP import ModuleTOTP
from app.utils import errors as err
from app.utils.exceptions import BugException, RequestException

# ---------------------------------------------------------------------------
# Shared fakes / fixtures
# ---------------------------------------------------------------------------


class _FakeDB:
    """In-memory stand-in for ClientSQL used by both modules."""

    def __init__(self):
        self.select_rows = []
        self.insert_calls = []
        self.update_calls = []
        self.connected = False

    def connect(self):
        self.connected = True

    def close(self):
        self.connected = False

    def select_from_table(self, table_name=None, column_tuple=(), condition=None):
        return self.select_rows

    def insert_in_table(self, table_name, column_tuple, values_tuple):
        self.insert_calls.append(
            {"table": table_name, "columns": column_tuple, "values": values_tuple}
        )

    def update_in_table(self, table_name, column_tuple, values_list, condition=None):
        self.update_calls.append(
            {
                "table": table_name,
                "columns": column_tuple,
                "values": values_list,
                "condition": condition,
            }
        )


class _FakeProcessSettings:
    """Fake process settings — configurable, with/without SMTP attrs."""

    SOGO_P_DB_TYPE = "PostgreSQL"

    def __init__(self, **attrs):
        self._attrs = attrs

    def get_db_settings(self):
        return {"host": "localhost", "database": "test"}

    def __getattr__(self, name):
        try:
            return self._attrs[name]
        except KeyError:
            raise AttributeError(name) from None


@pytest.fixture
def totp():
    """ModuleTOTP backed by the fake DB (all real DB calls mocked)."""
    db = _FakeDB()
    with patch(
        "app.module.auth.ModuleTOTP.import_and_instantiate_manager", return_value=db
    ):
        t = ModuleTOTP()
    yield t, db


@pytest.fixture
def reset_module():
    """ModulePasswordReset backed by the fake DB."""
    db = _FakeDB()
    with patch(
        "app.utils.module.importManager.import_and_instantiate_manager",
        return_value=db,
    ):
        mod = ModulePasswordReset(_FakeProcessSettings())
    mod.db = db
    yield mod, db


def _decrypt(monkeypatch, value="SECRET"):
    monkeypatch.setattr(
        "app.module.auth.ModuleTOTP.decrypt_password", lambda _row: value
    )


def _encrypt(monkeypatch, value="enc"):
    monkeypatch.setattr(
        "app.module.auth.ModuleTOTP.encrypt_password", lambda _secret: value
    )


def _row(enabled=True, secret="S"):
    return [(1, "u1", "enc", enabled, "2026-01-01T00:00:00Z")]


# ---------------------------------------------------------------------------
# ModuleTOTP — statics: secret, provisioning URI, verify window / clock drift
# ---------------------------------------------------------------------------


class TestTotpStatics:
    def test_generate_secret_random_base32(self):
        secrets = {ModuleTOTP.generate_secret() for _ in range(5)}
        assert len(secrets) == 5
        for s in secrets:
            assert len(s) >= 16

    def test_provisioning_uri_custom_issuer(self):
        uri = ModuleTOTP.get_provisioning_uri(
            "JBSWY3DPEHPK3PXP", "bob@example.org", issuer="Uni Marburg"
        )
        assert uri.startswith("otpauth://totp/")
        assert "issuer=Uni%20Marburg" in uri

    def test_verify_code_accepts_clock_drift_window(self):
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        # A code from ~3 steps (90s) in the past — valid with valid_window=3.
        old_code = totp.at(datetime.now(timezone.utc) - timedelta(seconds=90))
        assert ModuleTOTP.verify_code(secret, old_code, valid_window=3) is True

    def test_verify_code_rejects_outside_small_window(self):
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        old_code = totp.at(datetime.now(timezone.utc) - timedelta(seconds=90))
        # Default window of 1 step must reject a 3-step-old code.
        assert ModuleTOTP.verify_code(secret, old_code) is False
        assert ModuleTOTP.verify_code(secret, old_code, valid_window=1) is False

    def test_verify_code_rejects_garbage(self):
        assert ModuleTOTP.verify_code("JBSWY3DPEHPK3PXP", "000000") is False
        assert ModuleTOTP.verify_code("JBSWY3DPEHPK3PXP", "abcdef") is False


# ---------------------------------------------------------------------------
# ModuleTOTP — DB persistence branches
# ---------------------------------------------------------------------------


class TestTotpConfigBranches:
    def test_row_to_dict_none_for_empty(self, totp, monkeypatch):
        mod, _ = totp
        _decrypt(monkeypatch)
        assert mod._row_to_dict(None) is None
        assert mod._row_to_dict(()) is None

    def test_get_config_found(self, totp, monkeypatch):
        mod, db = totp
        db.select_rows = _row()
        _decrypt(monkeypatch, value="PLAINTEXT")
        cfg = mod.get_config("u1")
        assert cfg == {
            "id": 1,
            "user_uid": "u1",
            "secret": "PLAINTEXT",
            "enabled": True,
            "created_at": "2026-01-01T00:00:00Z",
        }

    def test_get_config_agg_exception_returns_none(self, totp, monkeypatch):
        mod, _ = totp
        from app.utils.exceptions import AggravatedException

        class _RaisingDB:
            def select_from_table(self, *a, **k):
                raise AggravatedException("db unreachable")

        mod._db = _RaisingDB()  # type: ignore[assignment]
        assert mod.get_config("u1") is None

    def test_get_config_bug_exception_returns_none(self, totp, monkeypatch):
        mod, _ = totp

        class _RaisingDB:
            def select_from_table(self, *a, **k):
                raise BugException("schema mismatch")

        mod._db = _RaisingDB()  # type: ignore[assignment]
        assert mod.get_config("u1") is None

    def test_is_enabled_true_false_missing(self, totp, monkeypatch):
        mod, db = totp
        for enabled, expected in ((True, True), (False, False)):
            db.select_rows = _row(enabled=enabled)
            _decrypt(monkeypatch)
            assert mod.is_enabled("u1") is expected
        db.select_rows = []
        assert mod.is_enabled("u1") is False

    def test_create_or_update_secret_insert(self, totp, monkeypatch):
        mod, db = totp
        db.select_rows = []
        _encrypt(monkeypatch, value="enc")
        mod.create_or_update_secret("u1", "NEW")
        insert = db.insert_calls[-1]
        assert insert["columns"] == ("user_uid", "secret", "enabled", "created_at")
        assert insert["values"][0][:3] == ["u1", "enc", False]

    def test_create_or_update_secret_update_existing(self, totp, monkeypatch):
        mod, db = totp
        db.select_rows = _row(enabled=True)
        _decrypt(monkeypatch)
        _encrypt(monkeypatch, value="enc2")
        mod.create_or_update_secret("u1", "NEWER")
        update = db.update_calls[-1]
        assert update["columns"] == ("secret", "enabled", "created_at")
        assert update["values"][:2] == ["enc2", False]

    def test_enable_ok(self, totp, monkeypatch):
        mod, db = totp
        db.select_rows = _row(enabled=False)
        _decrypt(monkeypatch)
        mod.enable("u1")
        assert db.update_calls[-1]["values"] == [True]

    def test_enable_setup_required(self, totp):
        mod, db = totp
        db.select_rows = []
        with pytest.raises(RequestException) as exc:
            mod.enable("u1")
        assert exc.value.error.c == err.ERROR_MFA_TOTP_SETUP_REQUIRED.c

    def test_enable_already_enabled(self, totp, monkeypatch):
        mod, db = totp
        db.select_rows = _row(enabled=True)
        _decrypt(monkeypatch)
        with pytest.raises(RequestException) as exc:
            mod.enable("u1")
        assert exc.value.error.c == err.ERROR_MFA_TOTP_ALREADY_ENABLED.c

    def test_disable_ok(self, totp, monkeypatch):
        mod, db = totp
        db.select_rows = _row(enabled=True)
        _decrypt(monkeypatch)
        mod.disable("u1")
        assert db.update_calls[-1]["values"] == [False]

    def test_disable_not_enabled(self, totp, monkeypatch):
        mod, db = totp
        db.select_rows = _row(enabled=False)
        _decrypt(monkeypatch)
        with pytest.raises(RequestException) as exc:
            mod.disable("u1")
        assert exc.value.error.c == err.ERROR_MFA_TOTP_NOT_ENABLED.c

    def test_disable_missing_config(self, totp):
        mod, db = totp
        db.select_rows = []
        with pytest.raises(RequestException) as exc:
            mod.disable("u1")
        assert exc.value.error.c == err.ERROR_MFA_TOTP_NOT_ENABLED.c

    def test_get_secret_found_and_missing(self, totp, monkeypatch):
        mod, db = totp
        db.select_rows = _row()
        _decrypt(monkeypatch, value="THE-SECRET")
        assert mod.get_secret("u1") == "THE-SECRET"
        db.select_rows = []
        assert mod.get_secret("u1") is None


# ---------------------------------------------------------------------------
# ModulePasswordReset — token lifecycle
# ---------------------------------------------------------------------------


class TestResetTokenLifecycle:
    def test_generate_token_shape(self, reset_module):
        mod, _ = reset_module
        raw, hashed = mod._generate_token()
        assert len(raw) == TOKEN_BYTES * 2
        assert len(hashed) == 64
        assert hashed == sha256(raw.encode()).hexdigest()
        raw2, _ = mod._generate_token()
        assert raw2 != raw

    def test_create_reset_token_stores_hash_not_raw(self, reset_module):
        mod, db = reset_module
        raw = mod.create_reset_token("user123", ttl=1800)
        insert = db.insert_calls[-1]
        stored = insert["values"][0][0]
        assert stored == sha256(raw.encode()).hexdigest()
        assert stored != raw
        # every column present in the right order
        assert insert["columns"] == (
            "token_hash",
            "user_uid",
            "expires_at",
            "used",
            "created_at",
        )

    def test_create_reset_token_expiry_and_connect_close(self, reset_module):
        mod, db = reset_module
        before = datetime.now(timezone.utc)
        mod.create_reset_token("u", ttl=60)
        after = datetime.now(timezone.utc)
        expires = db.insert_calls[-1]["values"][0][2]
        assert isinstance(expires, datetime)
        assert before + timedelta(seconds=59) <= expires <= after + timedelta(seconds=61)
        assert db.connected is False  # closed in finally

    def test_default_ttl_constant(self, reset_module):
        assert DEFAULT_TOKEN_TTL_SECONDS == 3600

    def test_lookup_token_not_found(self, reset_module):
        mod, db = reset_module
        db.select_rows = []
        assert mod._lookup_token("missing") is None

    def test_validate_token_valid_aware_datetime(self, reset_module):
        mod, db = reset_module
        db.select_rows = [[42, "h", "u9", datetime.now(timezone.utc) + timedelta(hours=1), False]]
        assert mod.validate_token("raw") == {"user_uid": "u9", "id": 42}

    def test_validate_token_expired_aware_datetime(self, reset_module):
        mod, db = reset_module
        db.select_rows = [[42, "h", "u9", datetime.now(timezone.utc) - timedelta(seconds=1), False]]
        with pytest.raises(RequestException) as exc:
            mod.validate_token("raw")
        assert exc.value.error.c == err.ERROR_PWD_RESET_TOKEN_EXPIRED.c

    def test_validate_token_invalid(self, reset_module):
        mod, db = reset_module
        db.select_rows = []
        with pytest.raises(RequestException) as exc:
            mod.validate_token("nope")
        assert exc.value.error.c == err.ERROR_PWD_RESET_TOKEN_INVALID.c

    def test_validate_token_reuse_raises(self, reset_module):
        mod, db = reset_module
        db.select_rows = [[42, "h", "u9", datetime.now(timezone.utc) + timedelta(hours=1), True]]
        with pytest.raises(RequestException) as exc:
            mod.validate_token("raw")
        assert exc.value.error.c == err.ERROR_PWD_RESET_TOKEN_USED.c

    def test_validate_token_naive_datetime_future_ok(self, reset_module):
        mod, db = reset_module
        # naive UTC datetime, still in the future -> must be normalized, not
        # treated as expired
        naive = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2)
        db.select_rows = [[42, "h", "u9", naive, False]]
        assert mod.validate_token("raw") == {"user_uid": "u9", "id": 42}

    def test_validate_token_numeric_timestamp_expired(self, reset_module):
        mod, db = reset_module
        db.select_rows = [[42, "h", "u9", time.time() - 3600, False]]
        with pytest.raises(RequestException) as exc:
            mod.validate_token("raw")
        assert exc.value.error.c == err.ERROR_PWD_RESET_TOKEN_EXPIRED.c

    def test_validate_token_numeric_timestamp_future_ok(self, reset_module):
        mod, db = reset_module
        db.select_rows = [[42, "h", "u9", time.time() + 3600, False]]
        assert mod.validate_token("raw") == {"user_uid": "u9", "id": 42}

    def test_validate_token_none_expiry_skips_check(self, reset_module):
        mod, db = reset_module
        db.select_rows = [[42, "h", "u9", None, False]]
        assert mod.validate_token("raw") == {"user_uid": "u9", "id": 42}

    def test_mark_token_used(self, reset_module):
        mod, db = reset_module
        mod.mark_token_used(7)
        update = db.update_calls[-1]
        assert update["values"] == [True]
        assert update["columns"] == ("used",)
        assert db.connected is False


class TestCountRecentTokens:
    def test_empty(self, reset_module):
        mod, db = reset_module
        db.select_rows = []
        assert mod.count_recent_tokens("u") == 0

    def test_naive_datetime_recent_counted(self, reset_module):
        mod, db = reset_module
        now = datetime.now(timezone.utc)
        db.select_rows = [
            [1, now - timedelta(seconds=30)],                 # aware recent
            [2, (now - timedelta(seconds=120)).replace(tzinfo=None)],  # NAIVE recent  (line-199 branch)
            [3, now - timedelta(hours=2)],                     # old
            [4, None],                                         # None branch
        ]
        assert mod.count_recent_tokens("u", within_seconds=300) == 2

    def test_numeric_created_branch(self, reset_module):
        mod, db = reset_module
        db.select_rows = [
            [1, time.time() - 10],
            [2, time.time() - 600],
        ]
        assert mod.count_recent_tokens("u", within_seconds=300) == 1


# ---------------------------------------------------------------------------
# ModulePasswordReset — LDAP password update branches
# ---------------------------------------------------------------------------


class TestResetPassword:
    def test_calls_admin_update_user(self, reset_module, monkeypatch):
        mod, _ = reset_module
        admin = MagicMock()
        monkeypatch.setattr(
            "app.module.admin.ModuleAdminUser.ModuleAdminUser",
            lambda **kwargs: admin,
        )
        mod.reset_password("u1", "newpass")
        admin.update_user.assert_called_once_with("u1", {"password": "newpass"})

    def test_forwards_request_exception(self, reset_module, monkeypatch):
        mod, _ = reset_module
        admin = MagicMock()
        admin.update_user.side_effect = RequestException(
            err.ERROR_PWD_RESET_UPDATE_FAILED.m, err.ERROR_PWD_RESET_UPDATE_FAILED
        )
        monkeypatch.setattr(
            "app.module.admin.ModuleAdminUser.ModuleAdminUser",
            lambda **kwargs: admin,
        )
        with pytest.raises(RequestException) as exc:
            mod.reset_password("u1", "x")
        assert exc.value.error.c == err.ERROR_PWD_RESET_UPDATE_FAILED.c

    def test_wraps_generic_exception(self, reset_module, monkeypatch):
        mod, _ = reset_module
        admin = MagicMock()
        admin.update_user.side_effect = RuntimeError("LDAP unreachable")
        monkeypatch.setattr(
            "app.module.admin.ModuleAdminUser.ModuleAdminUser",
            lambda **kwargs: admin,
        )
        with pytest.raises(RequestException) as exc:
            mod.reset_password("u1", "x")
        assert exc.value.error.c == err.ERROR_PWD_RESET_UPDATE_FAILED.c
        assert isinstance(exc.value.__cause__, RuntimeError)


# ---------------------------------------------------------------------------
# ModulePasswordReset — SMTP mailbox path (success + silent failure)
# ---------------------------------------------------------------------------


class TestSendResetEmail:
    def _patch_smtp(self, monkeypatch):
        mock_smtp = MagicMock()
        monkeypatch.setattr(
            "app.module.auth.ModulePasswordReset.smtplib.SMTP", mock_smtp
        )
        server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = server
        return mock_smtp, server

    def test_success_logs_and_sends(self, reset_module, monkeypatch):
        mod, _ = reset_module
        mock_smtp, server = self._patch_smtp(monkeypatch)
        # settings WITHOUT SOGO_P_SMTP_* -> getattr defaults kick in
        default_settings = _FakeProcessSettings(SOGO_P_DB_TYPE="PostgreSQL")
        mod.process_settings = default_settings
        mod.send_reset_email(
            recipient_email="a@example.org",
            recipient_name="Alice",
            reset_link="http://x/reset?t=abc",
        )
        mock_smtp.assert_called_once_with(
            host="sogo6-stalwart", port=20025, timeout=10
        )
        server.send_message.assert_called_once()

    def test_explicit_host_port_used(self, reset_module, monkeypatch):
        mod, _ = reset_module
        mock_smtp, server = self._patch_smtp(monkeypatch)
        custom = _FakeProcessSettings(
            SOGO_P_DB_TYPE="PostgreSQL",
            SOGO_P_SMTP_SERVER="relay.example.com",
            SOGO_P_SMTP_PORT=465,
            SOGO_P_SMTP_FROM="reset@example.com",
        )
        mod.process_settings = custom
        mod.send_reset_email(
            recipient_email="b@example.org",
            recipient_name="Bob",
            reset_link="http://x/t",
            smtp_host="explicit.smtp",
            smtp_port=2525,
        )
        mock_smtp.assert_called_once_with(
            host="explicit.smtp", port=2525, timeout=10
        )
        server.send_message.assert_called_once()

    def test_mailbox_failure_is_silent(self, reset_module, monkeypatch):
        mod, _ = reset_module
        mock_smtp = MagicMock()
        mock_smtp.return_value.__enter__.side_effect = OSError("connection refused")
        monkeypatch.setattr(
            "app.module.auth.ModulePasswordReset.smtplib.SMTP", mock_smtp
        )
        # Must NOT raise (avoids leaking whether the mailbox exists).
        result = mod.send_reset_email(
            recipient_email="c@example.org",
            recipient_name="Carol",
            reset_link="http://x/t?key=z",
        )
        assert result is None
