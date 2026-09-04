# pylint: disable=invalid-sequence-index
"""Unit tests for InterfaceAdminAuth (42% -> high)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

from app.interface.admin.InterfaceApiAdminAuth import InterfaceAdminAuth
from app.utils import errors as err
from app.utils.exceptions import RequestException


def make_iface():
    process = mock.MagicMock()
    with mock.patch("app.interface.admin.InterfaceApiAdminAuth.ModuleAdminAuth") as ma:
        iface = InterfaceAdminAuth(process)
    return iface, ma


class TestAdminLogin:
    def test_failed_credentials(self):
        iface, ma = make_iface()
        ma.return_value.check_admin_login.return_value = False
        resp, code = iface.admin_login("u", "p")
        assert code == err.ERROR_ADMIN_LOGIN_FAILED.h
        assert resp["error_code"] == err.ERROR_ADMIN_LOGIN_FAILED.c
        ma.return_value.generate_voucher_from_admin.assert_not_called()

    def test_success(self):
        iface, ma = make_iface()
        ma.return_value.check_admin_login.return_value = True
        ma.return_value.generate_voucher_from_admin.return_value = {"jwt_token": "tok"}
        resp, code = iface.admin_login("admin", "pw")
        assert code == 200
        assert resp["data"]["jwt_token"] == "tok"
        ma.return_value.generate_voucher_from_admin.assert_called_once_with("admin")

    def test_request_exception(self):
        iface, ma = make_iface()
        ma.return_value.check_admin_login.side_effect = RequestException("boom", err.ERROR_ADMIN_AUTH_NOT_CONFIG)
        resp, code = iface.admin_login("u", "p")
        assert code == err.ERROR_ADMIN_AUTH_NOT_CONFIG.h


class TestAdminLogout:
    def test_ok(self):
        iface, ma = make_iface()
        resp, code = iface.admin_logout("jwt")
        assert code == 200
        ma.return_value.logout_admin.assert_called_once_with("jwt")

    def test_request_exception(self):
        iface, ma = make_iface()
        ma.return_value.logout_admin.side_effect = RequestException("boom", err.ERROR_ADMIN_AUTH_NOT_CONFIG)
        resp, code = iface.admin_logout("jwt")
        assert code == err.ERROR_ADMIN_AUTH_NOT_CONFIG.h
