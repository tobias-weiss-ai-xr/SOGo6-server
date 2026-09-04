# pylint: disable=invalid-sequence-index
"""Unit tests for InterfaceUserPreferences (31% -> high)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

from marshmallow import ValidationError

from app.interface.user.InterfaceUserPreferences import InterfaceUserPreferences
from app.utils import errors as err
from app.utils.exceptions import RequestException


def make_iface():
    process = mock.MagicMock()
    domain = {}
    user = mock.MagicMock()
    user.uid = "user@example.org"
    with mock.patch("app.interface.user.InterfaceUserPreferences.ModuleUserProfile") as mp:
        iface = InterfaceUserPreferences(process, domain, user)
    return iface, mp


class TestGetAll:
    def test_ok(self):
        iface, mp = make_iface()
        mp.return_value.get_user_preferences.return_value = {"USER_GENERAL": {}}
        resp, code = iface.get_all_preferences()
        assert code == 200
        assert resp["data"] == {"USER_GENERAL": {}}
        mp.return_value.get_user_preferences.assert_called_once_with("user@example.org")

    def test_request_exception(self):
        iface, mp = make_iface()
        mp.return_value.get_user_preferences.side_effect = RequestException("boom", err.ERROR_NOT_FOUND)
        resp, code = iface.get_all_preferences()
        assert code == err.ERROR_NOT_FOUND.h
        assert resp["error_code"] == err.ERROR_NOT_FOUND.c


class TestGetPartial:
    def test_ok(self):
        iface, mp = make_iface()
        mp.return_value.get_partial_user_preferences.return_value = {"sub": {}}
        resp, code = iface.get_partial_preferences("USER_GENERAL")
        assert code == 200
        mp.return_value.get_partial_user_preferences.assert_called_once_with(
            "user@example.org", "USER_GENERAL")

    def test_request_exception(self):
        iface, mp = make_iface()
        mp.return_value.get_partial_user_preferences.side_effect = RequestException("boom", err.ERROR_NOT_FOUND)
        resp, code = iface.get_partial_preferences("USER_GENERAL")
        assert code == err.ERROR_NOT_FOUND.h


class TestUpdateAll:
    def test_ok(self):
        iface, mp = make_iface()
        mp.return_value.update_user_preferences.return_value = {"saved": True}
        resp, code = iface.update_all_preferences({"USER_GENERAL": {}})
        assert code == 200
        mp.return_value.update_user_preferences.assert_called_once_with(
            "user@example.org", {"USER_GENERAL": {}})

    def test_validation_error(self):
        iface, mp = make_iface()
        mp.return_value.update_user_preferences.side_effect = ValidationError({"a": ["required"]})
        resp, code = iface.update_all_preferences({"x": 1})
        assert code == err.ERROR_VALIDATION_ERROR.h
        assert resp["error_code"] == err.ERROR_VALIDATION_ERROR.c

    def test_request_exception(self):
        iface, mp = make_iface()
        mp.return_value.update_user_preferences.side_effect = RequestException("boom", err.ERROR_NOT_FOUND)
        resp, code = iface.update_all_preferences({"x": 1})
        assert code == err.ERROR_NOT_FOUND.h


class TestUpdatePartial:
    def test_ok(self):
        iface, mp = make_iface()
        mp.return_value.update_user_preferences.return_value = {"ok": True}
        resp, code = iface.update_partial_preferences({"x": 1}, "USER_GENERAL")
        assert code == 200
        mp.return_value.update_user_preferences.assert_called_once_with(
            "user@example.org", {"x": 1}, "USER_GENERAL")

    def test_validation_error(self):
        iface, mp = make_iface()
        mp.return_value.update_user_preferences.side_effect = ValidationError({"a": ["bad"]})
        resp, code = iface.update_partial_preferences({"x": 1}, "USER_GENERAL")
        assert code == err.ERROR_VALIDATION_ERROR.h

    def test_request_exception(self):
        iface, mp = make_iface()
        mp.return_value.update_user_preferences.side_effect = RequestException("boom", err.ERROR_NOT_FOUND)
        resp, code = iface.update_partial_preferences({"x": 1}, "USER_GENERAL")
        assert code == err.ERROR_NOT_FOUND.h
