"""SPDX-License-Identifier: AGPL-3.0-or-later

Coverage tests (round: sogo-cov-65) for ``app.service.jmap.JmapMailGateway``.

The checked-out ``JmapMailGateway`` only exposes the mailbox/email delegation
methods and the ``role_for_folder`` RFC-8621 mapper — there is **no** id codec
(base64url padding) or session/``accountNotFound`` member present in this
module. Per the task instruction ("only if present", "Skip gracefully if the
module does not have those members") those branches are skipped; this file
drives the real members to ~100% statement coverage instead.

Offline, deterministic: ``ModuleMail`` is replaced by a mock so no IMAP/socket
connection is ever opened.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config.settings.DomainSettings import MailSettings, MailSettingsObj
from app.service.jmap.JmapMailGateway import JmapMailGateway


# --------------------------------------------------------------------------- #
#  Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def mock_user():
    """Minimal user stub (SimpleNamespace keeps things dependency-free)."""
    from types import SimpleNamespace

    return SimpleNamespace(
        uid="u1@example.org",
        login_mail_server="u1",
        password="secret",
        mail="u1@example.org",
    )


@pytest.fixture
def domain_settings() -> dict:
    """user_domain_settings with a nested MailSettings section."""
    return {MailSettings.subparent: {"SOGO_D_MAIL_SERVER_TYPE": "imap"}}


@pytest.fixture
def gateway(mock_user, domain_settings):
    """Gateway with ModuleMail patched out to avoid any real connection."""
    with patch("app.service.jmap.JmapMailGateway.ModuleMail") as mock_module_cls:
        gw = JmapMailGateway(None, domain_settings, mock_user)
        gw.module = mock_module_cls.return_value
        yield gw


# --------------------------------------------------------------------------- #
#  __init__ (constructor) branches
# --------------------------------------------------------------------------- #

class TestInit:
    def test_constructor_with_domain_settings(self, mock_user, domain_settings):
        """Non-empty settings dict populates MailSettingsObj from the subparent."""
        with patch("app.service.jmap.JmapMailGateway.ModuleMail") as mock_cls:
            gw = JmapMailGateway(None, domain_settings, mock_user)
            assert gw.user is mock_user
            assert isinstance(gw.mail_settings, MailSettingsObj)
            mock_cls.assert_called_once_with(mock_user, gw.mail_settings)

    def test_constructor_with_none_domain_settings(self, mock_user):
        """``user_domain_settings or {}`` fallback: None -> empty MailSettingsObj."""
        with patch("app.service.jmap.JmapMailGateway.ModuleMail") as mock_cls:
            gw = JmapMailGateway(None, None, mock_user)
            assert isinstance(gw.mail_settings, MailSettingsObj)
            # defaults from the schema apply
            assert gw.mail_settings.SOGO_D_MAIL_SERVER_TYPE == "imap"
            assert gw.mail_settings.SOGO_D_IMAP_PORT == 143
            mock_cls.assert_called_once_with(mock_user, gw.mail_settings)

    def test_constructor_with_empty_dict_domain_settings(self, mock_user):
        """``user_domain_settings or {}`` literal-empty dict is also falsy."""
        with patch("app.service.jmap.JmapMailGateway.ModuleMail"):
            gw = JmapMailGateway(None, {}, mock_user)
            assert isinstance(gw.mail_settings, MailSettingsObj)

    def test_constructor_settings_override(self, mock_user):
        """Values from the subparent dict are applied to MailSettingsObj."""
        with patch("app.service.jmap.JmapMailGateway.ModuleMail"):
            gw = JmapMailGateway(
                None,
                {MailSettings.subparent: {"SOGO_D_IMAP_PORT": 993}},
                mock_user,
            )
            assert gw.mail_settings.SOGO_D_IMAP_PORT == 993


# --------------------------------------------------------------------------- #
#  Mailbox listing / management delegation
# --------------------------------------------------------------------------- #

class TestMailboxMethods:
    def test_list_mailbox_rows_delegates(self, gateway):
        gateway.module.get_folder_list.return_value = [{"name": "INBOX", "count": 3}]
        res = gateway.list_mailbox_rows("acc-0")
        assert res == [{"name": "INBOX", "count": 3}]
        gateway.module.get_folder_list.assert_called_once_with("acc-0")

    def test_list_mailbox_rows_propagates_error(self, gateway):
        from app.utils.exceptions import RequestException

        gateway.module.get_folder_list.side_effect = RequestException("imap down")
        with pytest.raises(RequestException):
            gateway.list_mailbox_rows("acc-0")

    def test_create_mailbox_with_parent(self, gateway):
        gateway.module.create_folder.return_value = {"name": "Holiday", "path": "INBOX/Holiday"}
        res = gateway.create_mailbox("acc-0", "Holiday", "INBOX")
        assert res == {"name": "Holiday", "path": "INBOX/Holiday"}
        gateway.module.create_folder.assert_called_once_with("acc-0", "Holiday", "INBOX")

    def test_create_mailbox_default_parent(self, gateway):
        """Default ``parent_path=""`` reaches the module unchanged."""
        gateway.module.create_folder.return_value = {"name": "Tmp", "path": "Tmp"}
        res = gateway.create_mailbox("acc-0", "Tmp")
        assert res == {"name": "Tmp", "path": "Tmp"}
        gateway.module.create_folder.assert_called_once_with("acc-0", "Tmp", "")

    def test_delete_mailbox_delegates(self, gateway):
        gateway.delete_mailbox("acc-0", "Trash/OldStuff")
        gateway.module.delete_folder.assert_called_once_with("acc-0", "Trash/OldStuff")


# --------------------------------------------------------------------------- #
#  Email access delegation
# --------------------------------------------------------------------------- #

class TestMailAccess:
    def test_get_mail_delegates(self, gateway):
        gateway.module.get_mail_detail.return_value = {"uid": "77", "subject": "hi"}
        res = gateway.get_mail("acc-0", "INBOX", "77")
        assert res == {"uid": "77", "subject": "hi"}
        gateway.module.get_mail_detail.assert_called_once_with("acc-0", "INBOX", "77")

    def test_get_mail_propagates_error(self, gateway):
        from app.utils.exceptions import RequestException

        gateway.module.get_mail_detail.side_effect = RequestException("no such uid")
        with pytest.raises(RequestException):
            gateway.get_mail("acc-0", "INBOX", "999")

    def test_get_mails_page_computation(self, gateway):
        """offset=20, limit=10 -> page 3; CollectionPaginateArgs carries uid include."""
        gateway.module.get_folder_mails.return_value = ([{"uid": "1"}], 1)
        res, total = gateway.get_mails("acc-0", "INBOX", limit=10, offset=20)
        assert res == [{"uid": "1"}]
        assert total == 1
        args, _ = gateway.module.get_folder_mails.call_args
        assert args[0] == "acc-0"
        assert args[1] == "INBOX"
        assert args[2].page == 3
        assert args[2].page_size == 10
        assert args[2].fields == "uid"
        assert args[2].fields_action == "include"

    def test_get_mails_first_page(self, gateway):
        """offset=0, limit=50 -> page 1."""
        gateway.module.get_folder_mails.return_value = ([], 0)
        gateway.get_mails("acc-0", "INBOX", limit=50, offset=0)
        args, _ = gateway.module.get_folder_mails.call_args
        assert args[2].page == 1
        assert args[2].page_size == 50

    def test_get_mails_limit_zero(self, gateway):
        """``max(limit, 1)`` clamps a zero limit up to 1 for page arithmetic."""
        gateway.module.get_folder_mails.return_value = ([], 0)
        gateway.get_mails("acc-0", "INBOX", limit=0, offset=7)
        args, _ = gateway.module.get_folder_mails.call_args
        assert args[2].page == 8  # 7 // 1 + 1
        assert args[2].page_size == 1

    def test_destroy_mail_delegates(self, gateway):
        gateway.destroy_mail("acc-0", "INBOX", "99")
        gateway.module.delete_mails.assert_called_once_with("acc-0", "INBOX", "99")

    def test_move_mail_delegates(self, gateway):
        """move_mail wraps the single int uid in a list before delegating."""
        gateway.move_mail("acc-0", "INBOX", 55, "Archive")
        gateway.module.move_mails.assert_called_once_with("acc-0", "INBOX", [55], "Archive")


# --------------------------------------------------------------------------- #
#  role_for_folder — RFC 8621 §2.1 mapper (the only pure-logic surface)
# --------------------------------------------------------------------------- #

class TestRoleForFolder:
    """Mirrors the task's focus on malformed/edge inputs driving the mapper."""

    @pytest.mark.parametrize(
        "folder_type, path, name, expected",
        [
            # inbox — detected by type, path or name
            ("inbox", "x", "x", "inbox"),
            ("INBOX", "x", "x", "inbox"),
            (None, "inbox", "x", "inbox"),
            (None, "x", "Inbox", "inbox"),
            (None, "x", "INBOX", "inbox"),
            # sent
            ("sent", "x", "x", "sent"),
            (None, "Sent Items", "x", "sent"),
            (None, "x/sent", "x", "sent"),
            # drafts
            ("drafts", "x", "x", "drafts"),
            (None, "Drafts", "x", "drafts"),
            (None, "x.draft", "x", "drafts"),
            # trash
            ("trash", "x", "x", "trash"),
            (None, "Trash", "x", "trash"),
            # junk — via type, "junk" path, or "spam" path
            ("junk", "x", "x", "junk"),
            (None, "Junk Mail", "x", "junk"),
            (None, "Spam", "x", "junk"),
            (None, "spam", "x", "junk"),
            # archive
            ("archive", "x", "x", "archive"),
            (None, "Archive", "x", "archive"),
        ],
    )
    def test_role_for_folder_matches(self, folder_type, path, name, expected):
        assert JmapMailGateway.role_for_folder(folder_type, path, name) == expected

    @pytest.mark.parametrize(
        "folder_type, path, name",
        [
            (None, "Mail/Personal", "Personal"),   # plain folder
            ("custom", "x", "x"),                  # unknown type
            ("", "x", "x"),                        # empty-but-truthy type -> no role
            (None, "x", "x"),                      # no hints at all
            (None, "", ""),                        # fully empty
        ],
    )
    def test_role_for_folder_none(self, folder_type, path, name):
        assert JmapMailGateway.role_for_folder(folder_type, path, name) is None

    def test_role_for_folder_check_order_inbox_wins(self):
        """Inbox is checked first: path='INBOX' beats folder_type='sent'."""
        assert JmapMailGateway.role_for_folder("sent", "INBOX", "x") == "inbox"

    def test_role_for_folder_empty_string_type_falls_back_to_path(self):
        assert JmapMailGateway.role_for_folder("", "INBOX", "x") == "inbox"
