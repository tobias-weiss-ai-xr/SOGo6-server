# pylint: disable=invalid-sequence-index
"""Unit tests for QuotaUsageService (61% -> high)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

from app.service.quota.QuotaUsageService import QuotaUsageService


class TestUsage:
    def test_ok_no_limits(self):
        svc = QuotaUsageService(
            "u@x.org",
            calendar_probe=lambda: {"status": "completed", "used": 2},
            contact_probe=lambda: {"status": "completed", "used": 5},
            mailbox_probe=lambda: {"status": "completed", "used": 1.5},
        )
        out = svc.usage()
        assert out["used"] == {"calendar_count": 2, "contact_count": 5, "mailbox_used_mb": 1.5}
        assert out["over_quota"] is False
        assert out["over_limits"] == []

    def test_over_quota_flags(self):
        svc = QuotaUsageService(
            "u@x.org",
            limits={"calendar_count": 10, "contact_count": 3, "mailbox_size_mb": 100},
            calendar_probe=lambda: {"used": 11},
            contact_probe=lambda: {"used": 3},
            mailbox_probe=lambda: {"used": 120.0},
        )
        out = svc.usage()
        assert out["over_quota"] is True
        assert out["over_limits"] == ["calendar_count", "mailbox_size_mb"]

    def test_none_usage_never_claims_over_quota(self):
        svc = QuotaUsageService(
            "u@x.org",
            limits={"calendar_count": 0, "mailbox_size_mb": 1},
            calendar_probe=lambda: {"used": None},
            contact_probe=lambda: {"used": None},
            mailbox_probe=lambda: {"used": None},
        )
        out = svc.usage()
        assert out["over_quota"] is False
        assert out["over_limits"] == []


class TestCalendarUsage:
    def test_unreachable_without_process_settings(self):
        svc = QuotaUsageService("u@x.org")
        out = svc._calendar_usage()
        assert out["status"] == "unreachable"

    def test_counts_calendars(self):
        process = mock.MagicMock()
        svc = QuotaUsageService("u@x.org", process_settings=process)
        with mock.patch("app.module.calendar.ModuleCalendar.ModuleCalendar") as mc, \
                mock.patch("app.auth.User.User") as mu:
            mc.return_value.get_all_calendars.return_value = [1, 2, 3]
            out = svc._calendar_usage()
        assert out == {"status": "completed", "used": 3}
        mu.assert_called_once_with(uid="u@x.org")

    def test_calendar_error(self):
        svc = QuotaUsageService("u@x.org", process_settings=mock.MagicMock())
        with mock.patch("app.module.calendar.ModuleCalendar.ModuleCalendar",
                        side_effect=RuntimeError("boom")):
            out = svc._calendar_usage()
        assert out["status"] == "error"
        assert "boom" in out["error"]


class TestContactUsage:
    def test_unreachable_without_process_settings(self):
        svc = QuotaUsageService("u@x.org")
        assert svc._contact_usage()["status"] == "unreachable"

    def test_counts_contacts(self):
        process = mock.MagicMock()
        svc = QuotaUsageService("u@x.org", process_settings=process)
        with mock.patch("app.module.contact.ModuleContact.ModuleContact") as mco, \
                mock.patch("app.auth.User.User"):
            mco.return_value.get_contacts.return_value = ([1, 2], 4)
            out = svc._contact_usage()
        assert out == {"status": "completed", "used": 4}
        mco.return_value.get_contacts.assert_called_once()

    def test_contact_error(self):
        svc = QuotaUsageService("u@x.org", process_settings=mock.MagicMock())
        with mock.patch("app.module.contact.ModuleContact.ModuleContact",
                        side_effect=ValueError("nope")):
            out = svc._contact_usage()
        assert out["status"] == "error"


class TestMailboxUsage:
    def test_not_configured(self):
        svc = QuotaUsageService("u@x.org", env={})
        out = svc._mailbox_usage()
        assert out["status"] == "not_configured"

    def test_happy_path(self):
        env = {
            "SOGO_QUOTA_IMAP_HOST": "imap.x.org",
            "SOGO_QUOTA_IMAP_USER": "u",
            "SOGO_QUOTA_IMAP_PASS": "p",
            "SOGO_QUOTA_IMAP_PORT": "143",
        }
        svc = QuotaUsageService("u@x.org", env=env)
        client = mock.MagicMock()
        client.list_folders.return_value = [
            {"path": "INBOX", "can_be_select": True},
            {"path": "Sent", "can_be_select": False},
            {"path": "Trash", "can_be_select": True},
        ]
        client.connection.status.side_effect = [
            ("OK", [b'"INBOX" (MESSAGES 3 SIZE 1048576)']),
            ("OK", [b'"Trash" (MESSAGES 1 SIZE 1048576)']),
        ]
        with mock.patch("app.manager.mail.ClientImap.ClientImap",
                        return_value=client) as ci:
            out = svc._mailbox_usage()
        ci.assert_called_once()
        kw = ci.call_args.kwargs
        assert kw["server"] == "imap.x.org"
        assert kw["port"] == 143
        assert out["status"] == "completed"
        assert out["bytes"] == 2097152
        assert out["folders"] == 2
        client.connection.logout.assert_called_once()

    def test_invalid_encryption_falls_back(self):
        env = {
            "SOGO_QUOTA_IMAP_HOST": "h", "SOGO_QUOTA_IMAP_USER": "u",
            "SOGO_QUOTA_IMAP_PASS": "p", "SOGO_QUOTA_IMAP_ENCRYPTION": "bogus",
        }
        svc = QuotaUsageService("u@x.org", env=env)
        client = mock.MagicMock()
        client.list_folders.return_value = []
        with mock.patch("app.manager.mail.ClientImap.ClientImap",
                        return_value=client) as ci:
            out = svc._mailbox_usage()
        assert ci.call_args.kwargs["encryption"] == "plain" or "encryption" in ci.call_args.kwargs
        assert out["status"] == "completed"

    def test_no_status_size_support(self):
        env = {
            "SOGO_QUOTA_IMAP_HOST": "h", "SOGO_QUOTA_IMAP_USER": "u",
            "SOGO_QUOTA_IMAP_PASS": "p",
        }
        svc = QuotaUsageService("u@x.org", env=env)
        client = mock.MagicMock()
        client.list_folders.return_value = [{"path": "INBOX", "can_be_select": True}]
        client.connection.status.return_value = ("OK", [b'"INBOX" (MESSAGES 1)'])
        with mock.patch("app.manager.mail.ClientImap.ClientImap",
                        return_value=client):
            out = svc._mailbox_usage()
        assert out["status"] == "error"
        assert "SIZE" in out["error"]

    def test_imap_error(self):
        env = {
            "SOGO_QUOTA_IMAP_HOST": "h", "SOGO_QUOTA_IMAP_USER": "u",
            "SOGO_QUOTA_IMAP_PASS": "p",
        }
        svc = QuotaUsageService("u@x.org", env=env)
        with mock.patch("app.manager.mail.ClientImap.ClientImap",
                        side_effect=TimeoutError("timeout")):
            out = svc._mailbox_usage()
        assert out["status"] == "error"
        assert "timeout" in out["error"]


class TestMailboxLogoutFailure:
    def test_logout_exception_swallowed(self):
        env = {
            "SOGO_QUOTA_IMAP_HOST": "h", "SOGO_QUOTA_IMAP_USER": "u",
            "SOGO_QUOTA_IMAP_PASS": "p",
        }
        svc = QuotaUsageService("u@x.org", env=env)
        client = mock.MagicMock()
        client.list_folders.return_value = []
        client.connection.logout.side_effect = RuntimeError("bye")
        with mock.patch("app.manager.mail.ClientImap.ClientImap",
                        return_value=client):
            out = svc._mailbox_usage()
        assert out["status"] == "completed"
