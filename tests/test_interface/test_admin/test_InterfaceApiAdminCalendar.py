# pylint: disable=invalid-sequence-index
"""Unit tests for InterfaceApiAdminCalendar (53% -> high)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

from app.interface.admin.InterfaceApiAdminCalendar import InterfaceApiAdminCalendar
from app.utils import errors as err
from app.utils.exceptions import RequestException


def make_iface():
    process = mock.MagicMock()
    with mock.patch("app.interface.admin.InterfaceApiAdminCalendar.ModuleCalendar") as mc:
        iface = InterfaceApiAdminCalendar(process)
    return iface, mc


class TestClean:
    def test_no_target(self):
        iface, _ = make_iface()
        resp, code = iface.clean()
        assert code == err.ERROR_CALENDAR_MAINTENANCE_REQUIRE_TARGET.h
        assert resp["error_code"] == err.ERROR_CALENDAR_MAINTENANCE_REQUIRE_TARGET.c

    def test_by_user(self):
        iface, mc = make_iface()
        mc.return_value.clean.return_value = 3
        resp, code = iface.clean(user_uid="u1")
        assert code == 200
        assert resp["data"]["purged_rows"] == 3
        mc.return_value.clean.assert_called_once_with(user_uid="u1", calendar_key=None)

    def test_by_calendar_key(self):
        iface, mc = make_iface()
        mc.return_value.clean.return_value = 0
        resp, code = iface.clean(calendar_key="ck")
        assert code == 200
        mc.return_value.clean.assert_called_once_with(user_uid=None, calendar_key="ck")

    def test_request_exception(self):
        iface, mc = make_iface()
        mc.return_value.clean.side_effect = RequestException("boom", err.ERROR_CALENDAR_MAINTENANCE_REQUIRE_TARGET)
        resp, code = iface.clean(user_uid="u")
        assert code == err.ERROR_CALENDAR_MAINTENANCE_REQUIRE_TARGET.h
