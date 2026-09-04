# pylint: disable=invalid-sequence-index
"""Unit tests for InterfaceApiAdminUser CRUD branches (companion file)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

from app.interface.admin.InterfaceApiAdminUser import InterfaceApiAdminUser
from app.utils import errors as err
from app.utils.exceptions import RequestException


def make_env():
    process = mock.MagicMock()
    with mock.patch(
        "app.interface.admin.InterfaceApiAdminUser.ModuleAdminUser"
    ) as module_cls:
        iface = InterfaceApiAdminUser(process)
        module_cls.assert_called_once_with(process_settings=process)
        return iface, module_cls


class TestListUsers:
    def test_ok(self):
        iface, module_cls = make_env()
        module_cls.return_value.list_users.return_value = (3, [{"uid": "a"}])
        resp, code = iface.list_users(query="jo", page=2, per_page=5)
        assert code == 200
        assert resp["data"] == [{"uid": "a"}]
        module_cls.return_value.list_users.assert_called_once_with(
            query="jo", page=2, per_page=5, sort_by="uid", sort_order="asc")

    def test_defaults(self):
        iface, module_cls = make_env()
        module_cls.return_value.list_users.return_value = (0, [])
        iface.list_users()
        module_cls.return_value.list_users.assert_called_once_with(
            query=None, page=1, per_page=20, sort_by="uid", sort_order="asc")

    def test_request_exception(self):
        iface, module_cls = make_env()
        module_cls.return_value.list_users.side_effect = RequestException(
            "x", err.ERROR_USER_PROFILE_NOT_FOUND)
        resp, code = iface.list_users()
        assert code == err.ERROR_USER_PROFILE_NOT_FOUND.h
        assert resp["error_code"] == err.ERROR_USER_PROFILE_NOT_FOUND.c


class TestGetUser:
    def test_ok(self):
        iface, module_cls = make_env()
        module_cls.return_value.get_user.return_value = {"uid": "jo"}
        resp, code = iface.get_user("jo")
        assert resp["data"] == {"uid": "jo"}
        module_cls.return_value.get_user.assert_called_once_with("jo")

    def test_request_exception(self):
        iface, module_cls = make_env()
        module_cls.return_value.get_user.side_effect = RequestException(
            "x", err.ERROR_USER_PROFILE_NOT_FOUND)
        resp, code = iface.get_user("missing")
        assert code == err.ERROR_USER_PROFILE_NOT_FOUND.h


class TestCreateUser:
    def test_ok(self):
        iface, module_cls = make_env()
        module_cls.return_value.create_user.return_value = {"uid": "new"}
        data = {"uid": "new", "password": "pw"}
        resp, code = iface.create_user(data)
        assert resp["data"] == {"uid": "new"}
        module_cls.return_value.create_user.assert_called_once_with(data)

    def test_request_exception(self):
        iface, module_cls = make_env()
        module_cls.return_value.create_user.side_effect = RequestException(
            "x", err.ERROR_USER_PROFILE_CREATION_FAILED)
        resp, code = iface.create_user({})
        assert code == err.ERROR_USER_PROFILE_CREATION_FAILED.h


class TestUpdateUser:
    def test_ok_no_password(self):
        iface, module_cls = make_env()
        module_cls.return_value.update_user.return_value = {"uid": "jo"}
        resp, code = iface.update_user("jo", {"cn": "New"})
        assert resp["data"] == {"uid": "jo"}

    def test_ok_with_password_revokes(self):
        iface, module_cls = make_env()
        module_cls.return_value.update_user.return_value = {"uid": "jo"}
        with mock.patch("app.service.sogo_cache") as sc:
            sc.return_value.revoke_user_sessions_by_uid.return_value = 1
            sc.return_value.close.return_value = None
            resp, code = iface.update_user("jo", {"password": "secret1"})
        assert code == 200
        sc.return_value.revoke_user_sessions_by_uid.assert_called_once_with(["jo"])
        sc.return_value.close.assert_called_once()

    def test_ok_password_cache_failure_swallowed(self):
        iface, module_cls = make_env()
        module_cls.return_value.update_user.return_value = {"uid": "jo"}
        with mock.patch("app.service.sogo_cache") as sc:
            sc.side_effect = RuntimeError("redis down")
            resp, code = iface.update_user("jo", {"password": "secret1"})
        assert code == 200

    def test_request_exception(self):
        iface, module_cls = make_env()
        module_cls.return_value.update_user.side_effect = RequestException(
            "x", err.ERROR_USER_PROFILE_UPDATE_FAILED)
        resp, code = iface.update_user("jo", {})
        assert code == err.ERROR_USER_PROFILE_UPDATE_FAILED.h


class TestDeleteUser:
    def test_ok(self):
        iface, module_cls = make_env()
        module_cls.return_value.delete_user.return_value = True
        resp, code = iface.delete_user("jo")
        assert resp["data"] is True
        module_cls.return_value.delete_user.assert_called_once_with("jo")

    def test_request_exception(self):
        iface, module_cls = make_env()
        module_cls.return_value.delete_user.side_effect = RequestException(
            "x", err.ERROR_USER_PROFILE_NOT_FOUND)
        resp, code = iface.delete_user("missing")
        assert code == err.ERROR_USER_PROFILE_NOT_FOUND.h
