# pylint: disable=invalid-sequence-index
"""Unit tests for ModuleTOTP (52% -> high)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest
import pyotp

from app.module.auth.ModuleTOTP import ModuleTOTP
from app.utils import errors as err
from app.utils.exceptions import BugException, RequestException


class TestStatics:
    def test_generate_secret_is_base32(self):
        import base64
        secret = ModuleTOTP.generate_secret()
        assert len(secret) >= 16
        base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8))

    def test_provisioning_uri(self):
        uri = ModuleTOTP.get_provisioning_uri("JBSWY3DPEHPK3PXP", "user@example.org")
        assert uri.startswith("otpauth://totp/")
        assert "user%40example.org" in uri
        assert "issuer=SOGo%206" in uri

    def test_verify_code_valid(self):
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        assert ModuleTOTP.verify_code(secret, totp.now()) is True

    def test_verify_code_invalid(self):
        assert ModuleTOTP.verify_code("JBSWY3DPEHPK3PXP", "000000") is False


@pytest.fixture
def totp():
    db = mock.MagicMock()
    with mock.patch(
        "app.module.auth.ModuleTOTP.import_and_instantiate_manager",
        return_value=db,
    ) as iim:
        t = ModuleTOTP()
        yield t, db, iim


class TestInit:
    def test_builds_db(self, totp):
        t, db, iim = totp
        iim.assert_called_once()
        db.connect.assert_called_once()


class TestRowToDict:
    def test_empty(self, totp):
        t, db, iim = totp
        assert t._row_to_dict(None) is None
        assert t._row_to_dict([]) is None

    def test_maps_row(self, totp):
        t, db, iim = totp
        with mock.patch(
            "app.module.auth.ModuleTOTP.decrypt_password",
            return_value="SECRET",
        ) as dec:
            d = t._row_to_dict((1, "u", "enc", True, "ts"))
        assert d == {"id": 1, "user_uid": "u", "secret": "SECRET",
                     "enabled": True, "created_at": "ts"}
        dec.assert_called_once_with("enc")


class TestGetConfig:
    def test_found(self, totp):
        t, db, iim = totp
        db.select_from_table.return_value = [(1, "u", "enc", True, "ts")]
        with mock.patch("app.module.auth.ModuleTOTP.decrypt_password",
                        return_value="SECRET"):
            cfg = t.get_config("u")
        assert cfg["secret"] == "SECRET"
        assert cfg["enabled"] is True

    def test_missing(self, totp):
        t, db, iim = totp
        db.select_from_table.return_value = []
        assert t.get_config("u") is None

    def test_db_error_returns_none(self, totp):
        t, db, iim = totp
        db.select_from_table.side_effect = BugException("db down")
        assert t.get_config("u") is None

    def test_is_enabled(self, totp):
        t, db, iim = totp
        db.select_from_table.return_value = [(1, "u", "enc", True, "ts")]
        with mock.patch("app.module.auth.ModuleTOTP.decrypt_password",
                        return_value="S"):
            assert t.is_enabled("u") is True
        db.select_from_table.return_value = [(1, "u", "enc", False, "ts")]
        with mock.patch("app.module.auth.ModuleTOTP.decrypt_password",
                        return_value="S"):
            assert t.is_enabled("u") is False
        db.select_from_table.return_value = []
        assert t.is_enabled("u") is False


class TestCreateOrUpdate:
    def test_insert_new(self, totp):
        t, db, iim = totp
        db.select_from_table.return_value = []
        with mock.patch("app.module.auth.ModuleTOTP.encrypt_password",
                        return_value="enc"):
            t.create_or_update_secret("u", "SECRET")
        kwargs = db.insert_in_table.call_args.kwargs
        assert kwargs["column_tuple"] == ("user_uid", "secret", "enabled", "created_at")
        assert kwargs["values_tuple"][0][:3] == ["u", "enc", False]

    def test_update_existing(self, totp):
        t, db, iim = totp
        db.select_from_table.return_value = [(1, "u", "old", True, "ts")]
        with mock.patch("app.module.auth.ModuleTOTP.decrypt_password",
                        return_value="old"), \
                mock.patch("app.module.auth.ModuleTOTP.encrypt_password",
                           return_value="enc"):
            t.create_or_update_secret("u", "NEW")
        kwargs = db.update_in_table.call_args.kwargs
        assert kwargs["column_tuple"] == ("secret", "enabled", "created_at")
        assert kwargs["values_list"][:2] == ["enc", False]


class TestEnableDisable:
    def test_enable_ok(self, totp):
        t, db, iim = totp
        db.select_from_table.return_value = [(1, "u", "enc", False, "ts")]
        with mock.patch("app.module.auth.ModuleTOTP.decrypt_password",
                        return_value="S"):
            t.enable("u")
        db.update_in_table.assert_called_once_with(
            t.TABLE_NAME, column_tuple=("enabled",), values_list=[True],
            condition=mock.ANY)

    def test_enable_requires_setup(self, totp):
        t, db, iim = totp
        db.select_from_table.return_value = []
        with pytest.raises(RequestException) as e:
            t.enable("u")
        assert e.value.error.c == err.ERROR_MFA_TOTP_SETUP_REQUIRED.c

    def test_enable_already_enabled(self, totp):
        t, db, iim = totp
        db.select_from_table.return_value = [(1, "u", "enc", True, "ts")]
        with mock.patch("app.module.auth.ModuleTOTP.decrypt_password",
                        return_value="S"):
            with pytest.raises(RequestException) as e:
                t.enable("u")
        assert e.value.error.c == err.ERROR_MFA_TOTP_ALREADY_ENABLED.c

    def test_disable_ok(self, totp):
        t, db, iim = totp
        db.select_from_table.return_value = [(1, "u", "enc", True, "ts")]
        with mock.patch("app.module.auth.ModuleTOTP.decrypt_password",
                        return_value="S"):
            t.disable("u")
        db.update_in_table.assert_called_once()

    def test_disable_not_enabled(self, totp):
        t, db, iim = totp
        db.select_from_table.return_value = [(1, "u", "enc", False, "ts")]
        with mock.patch("app.module.auth.ModuleTOTP.decrypt_password",
                        return_value="S"):
            with pytest.raises(RequestException) as e:
                t.disable("u")
        assert e.value.error.c == err.ERROR_MFA_TOTP_NOT_ENABLED.c

    def test_disable_missing(self, totp):
        t, db, iim = totp
        db.select_from_table.return_value = []
        with pytest.raises(RequestException) as e:
            t.disable("u")
        assert e.value.error.c == err.ERROR_MFA_TOTP_NOT_ENABLED.c


class TestGetSecret:
    def test_returns_secret(self, totp):
        t, db, iim = totp
        db.select_from_table.return_value = [(1, "u", "enc", True, "ts")]
        with mock.patch("app.module.auth.ModuleTOTP.decrypt_password",
                        return_value="SECRET"):
            assert t.get_secret("u") == "SECRET"

    def test_missing(self, totp):
        t, db, iim = totp
        db.select_from_table.return_value = []
        assert t.get_secret("u") is None
