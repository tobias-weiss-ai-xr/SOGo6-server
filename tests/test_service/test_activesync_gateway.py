# pylint: disable=invalid-sequence-index
"""Unit tests for ActiveSyncGateway (58% -> high)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest

from app.service.activesync.ActiveSyncGateway import ActiveSyncGateway


@pytest.fixture
def gw():
    process = mock.MagicMock()
    user = mock.MagicMock()
    user.uid = "user@example.org"
    uds = {"MAIL_SETTINGS": {"SOGO_D_MAIL_HOST": "imap.example.org"}}
    with mock.patch(
        "app.service.activesync.ActiveSyncGateway.ModuleMail"
    ) as module_cls:
        g = ActiveSyncGateway(process, uds, user)
        yield g, module_cls


class TestInit:
    def test_builds_mail_settings(self, gw):
        g, module_cls = gw
        module_cls.assert_called_once()
        assert g.user.uid == "user@example.org"
        assert g.mail_settings.SOGO_D_MAIL_HOST == "imap.example.org"

    def test_empty_domain_settings(self):
        process = mock.MagicMock()
        user = mock.MagicMock()
        with mock.patch(
            "app.service.activesync.ActiveSyncGateway.ModuleMail"
        ) as module_cls:
            g = ActiveSyncGateway(process, {}, user)
        module_cls.assert_called_once()
        assert g.mail_settings is not None


class TestFolderStore:
    def test_list_mailbox_rows(self, gw):
        g, module_cls = gw
        g.module.get_folder_list.return_value = [{"name": "INBOX"}]
        assert g.list_mailbox_rows("acc1") == [{"name": "INBOX"}]
        g.module.get_folder_list.assert_called_once_with("acc1")

    def test_get_folder_mails_paging(self, gw):
        g, module_cls = gw
        g.module.get_folder_mails.return_value = ([{"uid": 5}], 1)
        with mock.patch(
            "app.utils.api.paginate_sort_filter.CollectionPaginateArgs"
        ) as cpa:
            cpa.return_value = object()
            out = g.get_folder_mails("acc1", "INBOX", limit=10, offset=20)
        assert out == ([{"uid": 5}], 1)
        cpa.assert_called_once_with(page=3, page_size=10, fields="uid",
                                    fields_action="include")

    def test_get_folder_mails_zero_limit(self, gw):
        g, module_cls = gw
        g.module.get_folder_mails.return_value = ([], 0)
        with mock.patch(
            "app.utils.api.paginate_sort_filter.CollectionPaginateArgs"
        ) as cpa:
            out = g.get_folder_mails("acc1", "INBOX", limit=0, offset=0)
        assert out == ([], 0)
        cpa.assert_called_once_with(page=1, page_size=1, fields="uid",
                                    fields_action="include")

    def test_get_mail_detail(self, gw):
        g, module_cls = gw
        g.module.get_mail_detail.return_value = {"subject": "hi"}
        assert g.get_mail_detail("a", "INBOX", "7") == {"subject": "hi"}

    def test_get_mail_raw(self, gw):
        g, module_cls = gw
        g.module.get_mail_raw.return_value = {"raw": "From: x"}
        assert g.get_mail_raw("a", "INBOX", "7") == "From: x"

    def test_destroy_mail(self, gw):
        g, module_cls = gw
        g.destroy_mail("a", "INBOX", "7")
        g.module.delete_mails.assert_called_once_with("a", "INBOX", "7")


class TestSend:
    def test_send_message(self, gw):
        g, module_cls = gw
        with mock.patch(
            "app.service.activesync.ActiveSyncGateway.ModuleMailOutgoing"
        ) as outgoing_cls:
            g.send_message("acc1", "RAW MSG")
        outgoing_cls.assert_called_once_with(g.user, g.mail_settings)
        outgoing_cls.return_value.send_raw_message.assert_called_once_with(
            "acc1", "RAW MSG")


class TestEasFolderType:
    def test_inbox(self):
        assert ActiveSyncGateway.eas_folder_type("INBOX", "", "") == 2

    def test_drafts_alias(self):
        assert ActiveSyncGateway.eas_folder_type("Draft", "", "") == 3

    def test_sent(self):
        assert ActiveSyncGateway.eas_folder_type("Sent", "", "") == 5

    def test_junk_spam(self):
        assert ActiveSyncGateway.eas_folder_type("Spam", "", "") == 12

    def test_trash_deleted(self):
        assert ActiveSyncGateway.eas_folder_type("Trash", "", "") == 4

    def test_other_default(self):
        assert ActiveSyncGateway.eas_folder_type("Misc", "x/y", "custom") == 1

    def test_none_falls_back_to_path(self):
        assert ActiveSyncGateway.eas_folder_type(None, "/INBOX/sub", "") == 2
