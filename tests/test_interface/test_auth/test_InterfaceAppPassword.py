# pylint: disable=invalid-sequence-index
"""Unit tests for InterfaceAppPassword (39% -> high)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")


import pytest

from app.interface.auth.InterfaceAppPassword import InterfaceAppPassword
from app.utils import errors as err
from app.utils.exceptions import RequestException


def make_iface():
    db = mock.MagicMock()
    with mock.patch("app.interface.auth.InterfaceAppPassword.ModuleAppPassword") as mp:
        iface = InterfaceAppPassword(db)
    return iface, mp


class TestCreate:
    def test_create_ok(self):
        iface, mp = make_iface()
        mp.return_value.create.return_value = ("tok-1", {"label": "x"})
        out = iface.create("user@example.org", "Thunderbird")
        assert out == {"token": "tok-1", "app_password": {"label": "x"}}
        mp.return_value.create.assert_called_once_with("user@example.org", "Thunderbird")

    def test_request_exception_propagates(self):
        iface, mp = make_iface()
        mp.return_value.create.side_effect = RequestException("boom", err.ERROR_APP_PASSWORD_NOT_FOUND)
        with pytest.raises(RequestException):
            iface.create("u", "l")

    def test_generic_exception_wrapped(self):
        iface, mp = make_iface()
        mp.return_value.create.side_effect = RuntimeError("db down")
        with pytest.raises(RequestException) as e:
            iface.create("u", "l")
        assert e.value.error.c == err.ERROR_APP_PASSWORD_NOT_FOUND.c


class TestList:
    def test_lists_for_user(self):
        iface, mp = make_iface()
        mp.return_value.list_for_user.return_value = [{"id": 1}]
        assert iface.list("user@example.org") == [{"id": 1}]
        mp.return_value.list_for_user.assert_called_once_with("user@example.org")


class TestDelete:
    def test_delete_ok(self):
        iface, mp = make_iface()
        iface.delete(7, "user@example.org")
        mp.return_value.delete.assert_called_once_with(7, "user@example.org")

    def test_request_exception_propagates(self):
        iface, mp = make_iface()
        mp.return_value.delete.side_effect = RequestException("boom", err.ERROR_APP_PASSWORD_NOT_FOUND)
        with pytest.raises(RequestException):
            iface.delete(7, "u")

    def test_generic_exception_wrapped(self):
        iface, mp = make_iface()
        mp.return_value.delete.side_effect = RuntimeError("db down")
        with pytest.raises(RequestException) as e:
            iface.delete(7, "u")
        assert e.value.error.c == err.ERROR_APP_PASSWORD_NOT_FOUND.c
