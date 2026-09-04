# pylint: disable=invalid-sequence-index
"""Unit tests for ModuleAdminAuth (37% -> high)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")


import pytest

from app.module.admin.ModuleAdminAuth import ModuleAdminAuth
from app.utils import errors as err
from app.utils.exceptions import RequestException


def make_process(**overrides):
    class _P:
        SOGO_P_ADMIN = "admin"
        SOGO_P_ADMIN_PWD = "secret"

    p = _P()
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


class TestInit:
    def test_ok(self):
        ModuleAdminAuth(make_process())

    def test_missing_admin(self):
        with pytest.raises(RequestException) as e:
            ModuleAdminAuth(make_process(SOGO_P_ADMIN=None))
        assert e.value.error.c == err.ERROR_ADMIN_AUTH_NOT_CONFIG.c

    def test_missing_pwd(self):
        with pytest.raises(RequestException) as e:
            ModuleAdminAuth(make_process(SOGO_P_ADMIN_PWD=None))
        assert e.value.error.c == err.ERROR_ADMIN_AUTH_NOT_CONFIG.c


class TestCheckAdminLogin:
    def test_correct(self):
        m = ModuleAdminAuth(make_process())
        assert m.check_admin_login("admin", "secret") is True

    def test_wrong_user(self):
        m = ModuleAdminAuth(make_process())
        assert m.check_admin_login("nobody", "secret") is False

    def test_wrong_pwd(self):
        m = ModuleAdminAuth(make_process())
        assert m.check_admin_login("admin", "nope") is False

    def test_missing_attrs_returns_false(self):
        m = ModuleAdminAuth(make_process())
        m.process_settings = object()  # no attrs
        assert m.check_admin_login("admin", "secret") is False


class TestGenerateVoucher:
    def test_generates_voucher(self):
        m = ModuleAdminAuth(make_process())
        with mock.patch("app.module.admin.ModuleAdminAuth.VoucherAdminService") as vs:
            vs.return_value.generate_voucher_from_admin.return_value = "jwt-abc"
            out = m.generate_voucher_from_admin("admin")
        assert out == {"jwt_token": "jwt-abc"}
        vs.assert_called_once()
        vs.return_value.generate_voucher_from_admin.assert_called_once_with("admin")


class TestLogout:
    def test_revokes_session(self):
        m = ModuleAdminAuth(make_process())
        with mock.patch("app.module.admin.ModuleAdminAuth.VoucherAdminService") as vs, \
                mock.patch("app.module.admin.ModuleAdminAuth.sogo_cache") as sc:
            vs.return_value.get_redis_session_key_from_voucher.return_value = (None, "redis:key")
            cache = sc.return_value
            m.logout_admin("some-jwt")
        vs.return_value.get_redis_session_key_from_voucher.assert_called_once_with("some-jwt")
        cache.revoke_user_sessions_by_key.assert_called_once_with(["redis:key"])
        cache.close.assert_called_once()
