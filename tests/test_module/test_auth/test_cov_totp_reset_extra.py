"""Extra coverage tests for ModuleTOTP and ModulePasswordReset.

Complements the existing ``test_moduleTOTP.py`` and
``test_modulePasswordReset.py`` suites by re-exercising (offline, from this
file alone) the remaining branches:

* TOTP: clock-drift verification (widened window), row-mapping edge cases,
  DB-error swallow paths, insert-vs-update secret handling, every enable /
  disable failure code.
* Password reset: token expiry handling for all storage shapes (aware /
  naive datetime and numeric timestamps), used-token rejection, repeated
  lookup, recent-token counting across datetime/naive/numeric/None created
  values, LDAP-update failure wrapping, and SMTP success/failure including
  host/port override paths.

Everything external (DB, LDAP, SMTP) is mocked — no live infrastructure.
"""
from __future__ import annotations

import os
import smtplib
import time
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from unittest import mock
from unittest.mock import MagicMock, patch

# ProcessSetting reads these at import time.
os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest
import pyotp

import app.module.auth.ModuleTOTP as totp_mod
import app.module.auth.ModulePasswordReset as reset_mod
from app.module.auth.ModuleTOTP import ModuleTOTP
from app.module.auth.ModulePasswordReset import (
    DEFAULT_TOKEN_TTL_SECONDS,
    TOKEN_BYTES,
    ModulePasswordReset,
)
from app.utils import errors as err
from app.utils.exceptions import AggravatedException, BugException, RequestException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeSettings:
    """Minimal process settings stand-in."""
    SOGO_P_DB_TYPE = "PostgreSQL"
    SOGO_P_SMTP_SERVER = "smtp.example.com"
    SOGO_P_SMTP_PORT = 587
    SOGO_P_SMTP_FROM = "noreply@example.com"

    def get_db_settings(self):
        return {"host": "localhost", "database": "test"}


class _BareSettings:
    """Settings without SMTP attributes -> module defaults must kick in."""
    SOGO_P_DB_TYPE = "Test"

    def get_db_settings(self):
        return {"host": "localhost"}


class _FakeClientSQL:
    """Records calls and plays back scripted select results."""

    def __init__(self):
        self.connected = False
        self.insert_calls = []
        self.select_calls = []
        self.update_calls = []
        self.select_rows = []
        self.select_sequence = []

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
def totp_db():
    return _FakeClientSQL()


@pytest.fixture
def totp_module(totp_db):
    with patch(
        "app.module.auth.ModuleTOTP.import_and_instantiate_manager",
        return_value=totp_db,
    ):
        mod = ModuleTOTP()
        return mod, totp_db


# ---------------------------------------------------------------------------
# ModuleTOTP — static crypto
# ---------------------------------------------------------------------------

class TestTOTPStatics:
    def test_generate_secret_is_valid_base32(self):
        import base64
        secret = ModuleTOTP.generate_secret()
        assert len(secret) >= 16
        padded = secret + "=" * ((8 - len(secret) % 8) % 8)
        base64.b32decode(padded)  # must not raise

    def test_provisioning_uri_uses_email_issuer_and_secret(self):
        secret = pyotp.random_base32()
        uri = ModuleTOTP.get_provisioning_uri(secret, "bob@corp.example")
        assert uri.startswith("otpauth://totp/SOGo%206:bob%40corp.example")
        assert f"secret={secret}" in uri
        assert "issuer=SOGo%206" in uri

    def test_provisioning_uri_custom_issuer(self):
        uri = ModuleTOTP.get_provisioning_uri(
            "JBSWY3DPEHPK3PXP", "a@b.c", issuer="Example Corp"
        )
        assert "issuer=Example%20Corp" in uri

    def test_verify_code_accepts_current(self):
        secret = pyotp.random_base32()
        assert ModuleTOTP.verify_code(secret, pyotp.TOTP(secret).now()) is True

    def test_verify_code_rejects_garbage(self):
        assert ModuleTOTP.verify_code("JBSWY3DPEHPK3PXP", "000000") is False

    def test_verify_code_rejects_far_past_with_zero_window(self):
        # A code 6 steps in the past must NOT verify with the default window.
        secret = pyotp.random_base32()
        old = pyotp.TOTP(secret).at(int(time.time()) - 6 * 30)
        assert ModuleTOTP.verify_code(secret, old, valid_window=0) is False

    def test_verify_code_accepts_past_with_clock_drift_window(self):
        # Same old code verifies once the window is wide enough (clock drift).
        secret = pyotp.random_base32()
        old = pyotp.TOTP(secret).at(int(time.time()) - 6 * 30)
        assert ModuleTOTP.verify_code(secret, old, valid_window=7) is True

    def test_verify_code_rejects_future_with_zero_window(self):
        secret = pyotp.random_base32()
        future = pyotp.TOTP(secret).at(int(time.time()) + 6 * 30)
        assert ModuleTOTP.verify_code(secret, future, valid_window=0) is False

    def test_verify_code_accepts_future_with_clock_drift_window(self):
        secret = pyotp.random_base32()
        future = pyotp.TOTP(secret).at(int(time.time()) + 6 * 30)
        assert ModuleTOTP.verify_code(secret, future, valid_window=7) is True


# ---------------------------------------------------------------------------
# ModuleTOTP — construction & row mapping
# ---------------------------------------------------------------------------

class TestTOTPInitAndMapping:
    def test_init_connects_db(self, totp_module):
        mod, db = totp_module
        assert db.connected is True

    def test_row_to_dict_none(self, totp_module):
        mod, _db = totp_module
        assert mod._row_to_dict(None) is None
        assert mod._row_to_dict(()) is None

    def test_row_to_dict_maps_and_decrypts(self, totp_module):
        mod, _db = totp_module
        with patch.object(totp_mod, "decrypt_password", return_value="PLAIN") as dec:
            d = mod._row_to_dict((7, "u1", "enc", False, "ts"))
        assert d == {"id": 7, "user_uid": "u1", "secret": "PLAIN",
                     "enabled": False, "created_at": "ts"}
        dec.assert_called_once_with("enc")


# ---------------------------------------------------------------------------
# ModuleTOTP — DB queries
# ---------------------------------------------------------------------------

_TOTP_ROW = (1, "u1", "enc-secret", True, "2024-01-01T00:00:00")


class TestTOTPGetConfig:
    def test_found(self, totp_module):
        mod, db = totp_module
        db.select_rows = [_TOTP_ROW]
        with patch.object(totp_mod, "decrypt_password", return_value="S"):
            cfg = mod.get_config("u1")
        assert cfg["secret"] == "S"
        assert cfg["enabled"] is True
        assert cfg["user_uid"] == "u1"

    def test_missing_returns_none(self, totp_module):
        mod, db = totp_module
        db.select_rows = []
        assert mod.get_config("u1") is None

    def test_bug_exception_is_swallowed(self, totp_module):
        mod, db = totp_module
        with patch.object(db, "select_from_table", side_effect=BugException("boom")):
            assert mod.get_config("u1") is None

    def test_aggravated_exception_is_swallowed(self, totp_module):
        mod, db = totp_module
        with patch.object(
            db, "select_from_table", side_effect=AggravatedException("db down")
        ):
            assert mod.get_config("u1") is None


class TestTOTPIsEnabled:
    def test_enabled_true(self, totp_module):
        mod, db = totp_module
        db.select_rows = [_TOTP_ROW]
        with patch.object(totp_mod, "decrypt_password", return_value="S"):
            assert mod.is_enabled("u1") is True

    def test_enabled_false_config(self, totp_module):
        mod, db = totp_module
        db.select_rows = [(1, "u1", "enc", False, "ts")]
        with patch.object(totp_mod, "decrypt_password", return_value="S"):
            assert mod.is_enabled("u1") is False

    def test_enabled_false_no_config(self, totp_module):
        mod, db = totp_module
        db.select_rows = []
        assert mod.is_enabled("u1") is False


# ---------------------------------------------------------------------------
# ModuleTOTP — create/update/enable/disable/secret
# ---------------------------------------------------------------------------

class TestTOTPCreateOrUpdate:
    def test_insert_new_secret(self, totp_module):
        mod, db = totp_module
        db.select_rows = []
        with patch.object(totp_mod, "encrypt_password", return_value="enc"):
            mod.create_or_update_secret("u1", "NEWSECRET")
        assert len(db.insert_calls) == 1
        cols = db.insert_calls[0]["columns"]
        vals = db.insert_calls[0]["values"][0]
        assert cols == ("user_uid", "secret", "enabled", "created_at")
        assert vals[:3] == ["u1", "enc", False]
        assert isinstance(vals[3], datetime)

    def test_update_existing_secret(self, totp_module):
        mod, db = totp_module
        db.select_rows = [_TOTP_ROW]  # existing, enabled=True -> must reset to False
        with patch.object(totp_mod, "decrypt_password", return_value="old"), \
                patch.object(totp_mod, "encrypt_password", return_value="enc"):
            mod.create_or_update_secret("u1", "NEW")
        assert len(db.update_calls) == 1
        upd = db.update_calls[0]
        assert upd["columns"] == ("secret", "enabled", "created_at")
        assert upd["values"][:2] == ["enc", False]

    def test_update_records_timestamp(self, totp_module):
        mod, db = totp_module
        db.select_rows = [_TOTP_ROW]
        with patch.object(totp_mod, "decrypt_password", return_value="old"), \
                patch.object(totp_mod, "encrypt_password", return_value="enc"):
            mod.create_or_update_secret("u1", "NEW")
        created = db.update_calls[0]["values"][2]
        assert isinstance(created, datetime)
        assert created.tzinfo is not None


class TestTOTPEnable:
    def test_enable_ok(self, totp_module):
        mod, db = totp_module
        db.select_rows = [(1, "u1", "enc", False, "ts")]
        with patch.object(totp_mod, "decrypt_password", return_value="S"):
            mod.enable("u1")
        assert db.update_calls == [{
            "table": ModuleTOTP.TABLE_NAME,
            "columns": ("enabled",),
            "values": [True],
            "condition": mock.ANY,
        }]

    def test_enable_requires_setup(self, totp_module):
        mod, db = totp_module
        db.select_rows = []
        with pytest.raises(RequestException) as exc:
            mod.enable("u1")
        assert exc.value.error.c == err.ERROR_MFA_TOTP_SETUP_REQUIRED.c

    def test_enable_already_enabled(self, totp_module):
        mod, db = totp_module
        db.select_rows = [_TOTP_ROW]
        with patch.object(totp_mod, "decrypt_password", return_value="S"):
            with pytest.raises(RequestException) as exc:
                mod.enable("u1")
        assert exc.value.error.c == err.ERROR_MFA_TOTP_ALREADY_ENABLED.c


class TestTOTPDisable:
    def test_disable_ok(self, totp_module):
        mod, db = totp_module
        db.select_rows = [_TOTP_ROW]
        with patch.object(totp_mod, "decrypt_password", return_value="S"):
            mod.disable("u1")
        assert db.update_calls[0]["values"] == [False]

    def test_disable_missing_config(self, totp_module):
        mod, db = totp_module
        db.select_rows = []
        with pytest.raises(RequestException) as exc:
            mod.disable("u1")
        assert exc.value.error.c == err.ERROR_MFA_TOTP_NOT_ENABLED.c

    def test_disable_not_enabled(self, totp_module):
        mod, db = totp_module
        db.select_rows = [(1, "u1", "enc", False, "ts")]
        with patch.object(totp_mod, "decrypt_password", return_value="S"):
            with pytest.raises(RequestException) as exc:
                mod.disable("u1")
        assert exc.value.error.c == err.ERROR_MFA_TOTP_NOT_ENABLED.c
        assert exc.value.http_status == err.ERROR_MFA_TOTP_NOT_ENABLED.h


class TestTOTPGetSecret:
    def test_returns_secret(self, totp_module):
        mod, db = totp_module
        db.select_rows = [_TOTP_ROW]
        with patch.object(totp_mod, "decrypt_password", return_value="SECRET"):
            assert mod.get_secret("u1") == "SECRET"

    def test_missing_returns_none(self, totp_module):
        mod, db = totp_module
        db.select_rows = []
        assert mod.get_secret("u1") is None


# ---------------------------------------------------------------------------
# ModulePasswordReset — construction & token generation
# ---------------------------------------------------------------------------

@pytest.fixture
def reset_db():
    return _FakeClientSQL()


@pytest.fixture
def reset_module(reset_db):
    with patch(
        "app.utils.module.importManager.import_and_instantiate_manager",
        return_value=reset_db,
    ) as iim:
        mod = ModulePasswordReset(_FakeSettings())
        mod.db = reset_db
        yield mod, reset_db, iim


class TestResetInit:
    def test_builds_db(self, reset_module):
        mod, db, iim = reset_module
        assert db.connected is False
        iim.assert_called_once()


class TestResetTokenGeneration:
    def test_generate_token_shape(self, reset_module):
        mod, _db, _iim = reset_module
        raw, hashed = mod._generate_token()
        assert len(raw) == TOKEN_BYTES * 2
        assert hashed == sha256(raw.encode()).hexdigest()

    def test_generate_token_differs(self, reset_module):
        mod, _db, _iim = reset_module
        r1, _ = mod._generate_token()
        r2, _ = mod._generate_token()
        assert r1 != r2


class TestResetCreateToken:
    def test_stores_hash_and_metadata(self, reset_module):
        mod, db, _iim = reset_module
        raw = mod.create_reset_token("user1")
        row = db.insert_calls[0]["values"][0]
        assert row[0] == sha256(raw.encode()).hexdigest()
        assert row[1] == "user1"
        assert row[3] is False
        assert row[2].tzinfo is not None
        assert row[4].tzinfo is not None

    def test_ttl_controls_expiry(self, reset_module):
        mod, db, _iim = reset_module
        before = datetime.now(timezone.utc)
        mod.create_reset_token("user1", ttl=60)
        after = datetime.now(timezone.utc)
        expires = db.insert_calls[0]["values"][0][2]
        assert before + timedelta(seconds=59) <= expires <= after + timedelta(seconds=61)

    def test_default_ttl_used(self, reset_module):
        mod, _db, _iim = reset_module
        raw = mod.create_reset_token("user1")
        assert isinstance(raw, str) and len(raw) == 64
        assert DEFAULT_TOKEN_TTL_SECONDS == 3600

    def test_returns_raw_and_logs(self, reset_module):
        mod, _db, _iim = reset_module
        with patch.object(reset_mod.logger_api, "info") as info:
            raw = mod.create_reset_token("user1")
        info.assert_called_once()
        assert "user1" in info.call_args.args[1]


# ---------------------------------------------------------------------------
# ModulePasswordReset — token lookup & validation
# ---------------------------------------------------------------------------

class TestResetLookup:
    def test_lookup_found(self, reset_module):
        mod, db, _iim = reset_module
        db.select_rows = [[42, "hash", "user1", "exp", False]]
        rec = mod._lookup_token("raw")
        assert rec == {"id": 42, "user_uid": "user1", "expires_at": "exp", "used": False}
        assert db.connected is False  # closed in finally

    def test_lookup_missing(self, reset_module):
        mod, db, _iim = reset_module
        db.select_rows = []
        assert mod._lookup_token("raw") is None


class TestResetValidate:
    def _row(self, expires, used=False):
        return [[42, "hash", "user1", expires, used]]

    def test_valid_aware_datetime(self, reset_module):
        mod, db, _iim = reset_module
        db.select_rows = self._row(datetime.now(timezone.utc) + timedelta(hours=1))
        assert mod.validate_token("raw") == {"user_uid": "user1", "id": 42}

    def test_invalid_token(self, reset_module):
        mod, db, _iim = reset_module
        db.select_rows = []
        with pytest.raises(RequestException) as exc:
            mod.validate_token("raw")
        assert exc.value.error.c == err.ERROR_PWD_RESET_TOKEN_INVALID.c
        assert exc.value.http_status == err.ERROR_PWD_RESET_TOKEN_INVALID.h

    def test_used_token_rejected(self, reset_module):
        mod, db, _iim = reset_module
        db.select_rows = self._row(
            datetime.now(timezone.utc) + timedelta(hours=1), used=True
        )
        with pytest.raises(RequestException) as exc:
            mod.validate_token("raw")
        assert exc.value.error.c == err.ERROR_PWD_RESET_TOKEN_USED.c

    def test_expired_aware_datetime(self, reset_module):
        mod, db, _iim = reset_module
        db.select_rows = self._row(datetime.now(timezone.utc) - timedelta(hours=2))
        with pytest.raises(RequestException) as exc:
            mod.validate_token("raw")
        assert exc.value.error.c == err.ERROR_PWD_RESET_TOKEN_EXPIRED.c

    def test_expired_naive_datetime(self, reset_module):
        mod, db, _iim = reset_module
        db.select_rows = self._row(datetime.now(timezone.utc) - timedelta(hours=2))
        row = db.select_rows[0]
        row[3] = row[3].replace(tzinfo=None)  # naive, in the past
        with pytest.raises(RequestException) as exc:
            mod.validate_token("raw")
        assert exc.value.error.c == err.ERROR_PWD_RESET_TOKEN_EXPIRED.c

    def test_valid_naive_datetime_future(self, reset_module):
        # naive datetime in the future -> normalized then accepted
        mod, db, _iim = reset_module
        naive = (datetime.now(timezone.utc) + timedelta(hours=5)).replace(tzinfo=None)
        db.select_rows = self._row(naive)
        assert mod.validate_token("raw") == {"user_uid": "user1", "id": 42}

    def test_expired_numeric_timestamp(self, reset_module):
        mod, db, _iim = reset_module
        db.select_rows = self._row(time.time() - 7200)
        with pytest.raises(RequestException) as exc:
            mod.validate_token("raw")
        assert exc.value.error.c == err.ERROR_PWD_RESET_TOKEN_EXPIRED.c

    def test_valid_numeric_timestamp_future(self, reset_module):
        mod, db, _iim = reset_module
        db.select_rows = self._row(time.time() + 7200)
        assert mod.validate_token("raw")["user_uid"] == "user1"

    def test_none_expires_accepted(self, reset_module):
        # ``expires_at`` column is nullable -> None short-circuits to valid
        mod, db, _iim = reset_module
        db.select_rows = self._row(None)
        assert mod.validate_token("raw") == {"user_uid": "user1", "id": 42}

    def test_lookup_uses_sha256_hash_in_condition(self, reset_module):
        mod, db, _iim = reset_module
        db.select_rows = self._row(datetime.now(timezone.utc) + timedelta(hours=1))
        mod.validate_token("token123")
        cond = db.select_calls[0]["condition"]
        assert cond.param_value == sha256("token123".encode()).hexdigest()


class TestResetMarkUsed:
    def test_marks_used(self, reset_module):
        mod, db, _iim = reset_module
        mod.mark_token_used(99)
        upd = db.update_calls[0]
        assert upd["values"] == [True]
        assert upd["condition"].param_value == 99
        assert db.connected is False


# ---------------------------------------------------------------------------
# ModulePasswordReset — rate-limit counting
# ---------------------------------------------------------------------------

class TestResetCountRecent:
    def test_empty(self, reset_module):
        mod, db, _iim = reset_module
        db.select_rows = []
        assert mod.count_recent_tokens("user1") == 0

    def test_mixed_datetime_rows(self, reset_module):
        mod, db, _iim = reset_module
        now = datetime.now(timezone.utc)
        db.select_rows = [
            [1, now - timedelta(seconds=30)],   # recent
            [2, now - timedelta(seconds=600)],  # old
            [3, (now - timedelta(seconds=60)).replace(tzinfo=None)],  # naive recent
            [4, (now - timedelta(seconds=3600)).replace(tzinfo=None)],  # naive old
        ]
        assert mod.count_recent_tokens("user1", within_seconds=300) == 2

    def test_numeric_created(self, reset_module):
        mod, db, _iim = reset_module
        db.select_rows = [
            [1, time.time() - 10],    # recent
            [2, time.time() - 3600],  # old
        ]
        assert mod.count_recent_tokens("user1", within_seconds=300) == 1

    def test_none_created_ignored(self, reset_module):
        mod, db, _iim = reset_module
        db.select_rows = [[1, None]]
        assert mod.count_recent_tokens("user1") == 0

    def test_default_window_300(self, reset_module):
        mod, db, _iim = reset_module
        db.select_rows = [[1, datetime.now(timezone.utc) - timedelta(seconds=299)]]
        assert mod.count_recent_tokens("user1") == 1


# ---------------------------------------------------------------------------
# ModulePasswordReset — LDAP password update
# ---------------------------------------------------------------------------

class TestResetPasswordUpdate:
    def test_calls_admin_module(self, reset_module):
        mod, _db, _iim = reset_module
        admin = MagicMock()
        with patch(
            "app.module.admin.ModuleAdminUser.ModuleAdminUser",
            return_value=admin,
        ):
            mod.reset_password("user1", "NewPass!123")
        admin.update_user.assert_called_once_with("user1", {"password": "NewPass!123"})

    def test_forwards_request_exception(self, reset_module):
        mod, _db, _iim = reset_module
        admin = MagicMock()
        admin.update_user.side_effect = RequestException(
            err.ERROR_PWD_RESET_UPDATE_FAILED.m, err.ERROR_PWD_RESET_UPDATE_FAILED
        )
        with patch(
            "app.module.admin.ModuleAdminUser.ModuleAdminUser",
            return_value=admin,
        ):
            with pytest.raises(RequestException) as exc:
                mod.reset_password("user1", "x")
        assert exc.value.error.c == err.ERROR_PWD_RESET_UPDATE_FAILED.c

    def test_wraps_generic_exception(self, reset_module):
        mod, _db, _iim = reset_module
        admin = MagicMock()
        admin.update_user.side_effect = RuntimeError("LDAP unreachable")
        with patch(
            "app.module.admin.ModuleAdminUser.ModuleAdminUser",
            return_value=admin,
        ):
            with pytest.raises(RequestException) as exc:
                mod.reset_password("user1", "x")
        assert exc.value.error.c == err.ERROR_PWD_RESET_UPDATE_FAILED.c
        assert isinstance(exc.value.__cause__, RuntimeError)


# ---------------------------------------------------------------------------
# ModulePasswordReset — SMTP email
# ---------------------------------------------------------------------------

class TestResetSendEmail:
    def _mock_smtp(self):
        smtp_cls = MagicMock()
        instance = smtp_cls.return_value
        instance.__enter__.return_value = instance
        instance.__exit__.return_value = False
        return smtp_cls, instance

    def test_uses_settings_defaults(self, reset_module):
        mod, _db, _iim = reset_module
        smtp_cls, instance = self._mock_smtp()
        with patch.object(reset_mod.smtplib, "SMTP", smtp_cls):
            mod.send_reset_email(
                recipient_email="a@example.org",
                recipient_name="Alice",
                reset_link="http://localhost/reset?t=abc",
            )
        smtp_cls.assert_called_once_with(host="smtp.example.com", port=587, timeout=10)
        instance.send_message.assert_called_once()

    def test_uses_explicit_host_port_override(self, reset_module):
        mod, _db, _iim = reset_module
        smtp_cls, instance = self._mock_smtp()
        with patch.object(reset_mod.smtplib, "SMTP", smtp_cls):
            mod.send_reset_email(
                recipient_email="b@example.org",
                recipient_name="Bob",
                reset_link="http://x/r",
                smtp_host="relay.internal",
                smtp_port=2525,
            )
        smtp_cls.assert_called_once_with(host="relay.internal", port=2525, timeout=10)
        instance.send_message.assert_called_once()

    def test_settings_without_smtp_attrs_falls_back_to_defaults(self, reset_db):
        with patch(
            "app.utils.module.importManager.import_and_instantiate_manager",
            return_value=reset_db,
        ):
            mod = ModulePasswordReset(_BareSettings())
            mod.db = reset_db
        smtp_cls, _instance = self._mock_smtp()
        with patch.object(reset_mod.smtplib, "SMTP", smtp_cls):
            mod.send_reset_email("c@example.org", "Carol", "http://x/r")
        smtp_cls.assert_called_once_with(
            host="sogo6-stalwart", port=20025, timeout=10
        )

    def test_smtp_failure_is_swallowed(self, reset_module):
        mod, _db, _iim = reset_module
        smtp_cls, instance = self._mock_smtp()
        instance.send_message.side_effect = smtplib.SMTPException("relay down")
        with patch.object(reset_mod.smtplib, "SMTP", smtp_cls):
            # must not raise
            mod.send_reset_email("d@example.org", "Dave", "http://x/r")

    def test_smtp_connect_failure_is_swallowed(self, reset_module):
        mod, _db, _iim = reset_module
        smtp_cls, _instance = self._mock_smtp()
        smtp_cls.side_effect = OSError("connection refused")
        with patch.object(reset_mod.smtplib, "SMTP", smtp_cls):
            mod.send_reset_email("e@example.org", "Eve", "http://x/r")
