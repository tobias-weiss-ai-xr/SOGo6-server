# pylint: disable=invalid-sequence-index
"""Unit tests for InterfaceUserProfile.change_password branches (companion file)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

from app.interface.user.InterfaceUserProfile import InterfaceUserProfile
from app.utils import errors as err
from app.utils.exceptions import RequestException


def domain_settings(pwd_change=True, pwd_policy=False):
    return {
        "AUTH_SETTINGS": {"SOGO_D_PWD_CHANGE_ENABLED": pwd_change},
        "USER_SOURCE": {"US_PWD_POLICY": pwd_policy, "US_CAN_AUTH": True},
    }


def make_iface(**overrides):
    process = mock.MagicMock()
    user = mock.MagicMock()
    user.uid = "user@example.org"
    user.domain = "example.org"
    user.source_id = "default"
    ud = domain_settings(**overrides)
    with mock.patch("app.interface.user.InterfaceUserProfile.ModuleUserProfile"):
        iface = InterfaceUserProfile(process, ud, user)
    return iface, ud


class TestChangeDisabled:
    def test_returns_disabled(self):
        iface, _ = make_iface(pwd_change=False)
        resp, code = iface.change_password("old", "new")
        assert code == err.ERROR_PWD_CHANGE_DISABLED.h
        assert resp["error_code"] == err.ERROR_PWD_CHANGE_DISABLED.c


def patch_reauth_ok():
    """Patch ModuleUserSource so login verification succeeds."""
    from contextlib import ExitStack
    stack = ExitStack()
    mus = stack.enter_context(
        mock.patch("app.module.auth.ModuleUserSource.ModuleUserSource"))
    init_ret = mock.MagicMock()
    init_ret.check_login.return_value = True
    mus.init_from_domain_settings.return_value = init_ret
    stack.enter_context(mock.patch("app.auth.User.User"))
    return stack, init_ret


class TestReauth:
    def test_failed_login(self):
        iface, _ = make_iface()
        with mock.patch("app.module.auth.ModuleUserSource.ModuleUserSource") as mus, \
                mock.patch("app.auth.User.User") as user_cls:
            init_ret = mock.MagicMock()
            mus.init_from_domain_settings.return_value = init_ret
            init_ret.check_login.return_value = False
            resp, code = iface.change_password("old", "new")
        assert code == err.ERROR_PWD_CHANGE_REAUTH_FAILED.h
        user_cls.assert_called_once()

    def test_login_exception(self):
        iface, _ = make_iface()
        with mock.patch("app.module.auth.ModuleUserSource.ModuleUserSource") as mus:
            init_ret = mock.MagicMock()
            mus.init_from_domain_settings.return_value = init_ret
            init_ret.check_login.side_effect = RuntimeError("boom")
            resp, code = iface.change_password("old", "new")
        assert code == err.ERROR_PWD_CHANGE_REAUTH_FAILED.h


class TestPolicy:
    def test_policy_violation(self):
        iface, _ = make_iface(pwd_policy=True)
        with mock.patch("app.module.auth.ModuleUserSource.ModuleUserSource") as mus, \
                mock.patch("app.utils.maths.password_policy.validate_password_policy",
                           return_value=["too short"]):
            init_ret = mock.MagicMock()
            init_ret.check_login.return_value = True
            mus.init_from_domain_settings.return_value = init_ret
            resp, code = iface.change_password("old", "new")
        assert code == err.ERROR_PWD_POLICY_VIOLATION.h
        assert resp["error_code"] == err.ERROR_PWD_POLICY_VIOLATION.c

    def test_policy_ok(self):
        iface, _ = make_iface(pwd_policy=True)
        with mock.patch("app.module.auth.ModuleUserSource.ModuleUserSource") as mus, \
                mock.patch("app.utils.maths.password_policy.validate_password_policy",
                           return_value=[]), \
                mock.patch("app.module.admin.ModuleAdminUser.ModuleAdminUser") as mau, \
                mock.patch("app.service.sogo_cache") as sc:
            init_ret = mock.MagicMock()
            init_ret.check_login.return_value = True
            mus.init_from_domain_settings.return_value = init_ret
            cache = sc.return_value
            resp, code = iface.change_password("old", "newPass1!")
        assert code == 200
        assert resp["data"]["changed"] is True
        mau.return_value.update_user.assert_called_once_with(
            "user@example.org", {"password": "newPass1!"})
        cache.revoke_user_sessions_by_uid.assert_called_once_with(["user@example.org"])


class TestUpdate:
    def test_request_exception(self):
        iface, _ = make_iface()
        with mock.patch("app.module.auth.ModuleUserSource.ModuleUserSource") as mus, \
                mock.patch("app.module.admin.ModuleAdminUser.ModuleAdminUser") as mau:
            init_ret = mock.MagicMock()
            init_ret.check_login.return_value = True
            mus.init_from_domain_settings.return_value = init_ret
            mau.return_value.update_user.side_effect = RequestException(
                "boom", err.ERROR_PWD_CHANGE_REAUTH_FAILED)
            resp, code = iface.change_password("old", "newPass1!")
        assert code == err.ERROR_PWD_CHANGE_REAUTH_FAILED.h

    def test_generic_exception(self):
        iface, _ = make_iface()
        with mock.patch("app.module.auth.ModuleUserSource.ModuleUserSource") as mus, \
                mock.patch("app.module.admin.ModuleAdminUser.ModuleAdminUser") as mau:
            init_ret = mock.MagicMock()
            init_ret.check_login.return_value = True
            mus.init_from_domain_settings.return_value = init_ret
            mau.return_value.update_user.side_effect = RuntimeError("db down")
            resp, code = iface.change_password("old", "newPass1!")
        assert code == err.ERROR_PWD_CHANGE_FAILED.h


class TestCacheRevoke:
    def test_cache_failure_swallowed(self):
        iface, _ = make_iface()
        with mock.patch("app.module.auth.ModuleUserSource.ModuleUserSource") as mus, \
                mock.patch("app.module.admin.ModuleAdminUser.ModuleAdminUser") as mau, \
                mock.patch("app.service.sogo_cache") as sc:
            init_ret = mock.MagicMock()
            init_ret.check_login.return_value = True
            mus.init_from_domain_settings.return_value = init_ret
            sc.side_effect = RuntimeError("redis down")
            resp, code = iface.change_password("old", "newPass1!")
        assert code == 200
        assert resp["data"]["changed"] is True
