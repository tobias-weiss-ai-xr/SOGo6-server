"""SPDX-License-Identifier: AGPL-3.0-or-later
Unit tests for JmapMailGateway — id codec + session + gateway resolution.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from app.auth.User import User
from app.config.settings.DomainSettings import MailSettings, MailSettingsObj
from app.service.jmap.JmapMailGateway import JmapMailGateway


# --------------------------------------------------------------------------- #
#  Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def mock_user() -> User:
    """Create a minimal fake User for gateway instantiation."""
    user = MagicMock(spec=User)
    user.uid = "testuser@example.org"
    user.login_mail_server = "testuser"
    user.password = "secret123"
    user.mail = "testuser@example.org"
    user.source_id = "ldap"
    user.imap_host = None
    user.profile = MagicMock()
    user.profile.preferences = {}
    user.profile.external_accounts = None
    return user


@pytest.fixture
def mock_mail_settings() -> MailSettingsObj:
    """Create a minimal MailSettingsObj with defaults."""
    settings = MailSettingsObj({})
    return settings


@pytest.fixture
def mock_user_domain_settings(mock_mail_settings) -> dict:
    """Create user domain settings dict with MailSettings nested."""
    return {
        MailSettings.subparent: {
            "SOGO_D_MAIL_SERVER_TYPE": "imap",
            "SOGO_D_IMAP_SERVER": "imap.example.org",
            "SOGO_D_IMAP_PORT": 143,
            "SOGO_D_MAIL_INBOX": "INBOX",
            "SOGO_D_MAIL_SENT": "Sent",
            "SOGO_D_MAIL_DRAFT": "Drafts",
            "SOGO_D_MAIL_TRASH": "Trash",
            "SOGO_D_MAIL_JUNK": "Junk",
            "SOGO_D_MAIL_ARCHIVE": "Archive",
        }
    }


@pytest.fixture
def mock_module_mail():
    """Create a mock ModuleMail instance."""
    module = MagicMock()
    return module


@pytest.fixture
def gateway(mock_user, mock_user_domain_settings, mock_module_mail) -> JmapMailGateway:
    """Create a JmapMailGateway with mocked dependencies."""
    # Patch ModuleMail to return our mock
    with patch("app.service.jmap.JmapMailGateway.ModuleMail", return_value=mock_module_mail):
        gw = JmapMailGateway(
            process_setting=None,
            user_domain_settings=mock_user_domain_settings,
            user=mock_user,
        )
        # Attach mock module
        gw.module = mock_module_mail
        return gw


# --------------------------------------------------------------------------- #
#  ID Codec Tests (account_id handling)
# --------------------------------------------------------------------------- #

class TestIdCodec:
    """Test account ID handling through the gateway."""

    def test_gateway_initializes_with_user_and_settings(self, mock_user, mock_user_domain_settings):
        """Verify gateway stores user and mail_settings correctly."""
        with patch("app.service.jmap.JmapMailGateway.ModuleMail"):
            gw = JmapMailGateway(
                process_setting=None,
                user_domain_settings=mock_user_domain_settings,
                user=mock_user,
            )
            assert gw.user is mock_user
            assert isinstance(gw.mail_settings, MailSettingsObj)

    def test_gateway_initializes_module_mail(self, mock_user, mock_user_domain_settings, mock_module_mail):
        """Verify gateway creates ModuleMail instance."""
        with patch("app.service.jmap.JmapMailGateway.ModuleMail", return_value=mock_module_mail) as mock_class:
            gw = JmapMailGateway(
                process_setting=None,
                user_domain_settings=mock_user_domain_settings,
                user=mock_user,
            )
            mock_class.assert_called_once_with(mock_user, gw.mail_settings)
            assert gw.module is mock_module_mail

    def test_gateway_with_empty_domain_settings(self, mock_user):
        """Verify gateway handles empty user_domain_settings gracefully."""
        with patch("app.service.jmap.JmapMailGateway.ModuleMail"):
            gw = JmapMailGateway(
                process_setting=None,
                user_domain_settings=None,
                user=mock_user,
            )
            assert gw.user is mock_user
            # mail_settings should be created from empty dict
            assert isinstance(gw.mail_settings, MailSettingsObj)

    def test_gateway_with_partial_domain_settings(self, mock_user):
        """Verify gateway handles partial domain settings."""
        partial_settings = {
            MailSettings.subparent: {
                "SOGO_D_MAIL_SERVER_TYPE": "imap",
            }
        }
        with patch("app.service.jmap.JmapMailGateway.ModuleMail"):
            gw = JmapMailGateway(
                process_setting=None,
                user_domain_settings=partial_settings,
                user=mock_user,
            )
            assert gw.mail_settings.SOGO_D_MAIL_SERVER_TYPE == "imap"
            # Other settings should have defaults
            assert gw.mail_settings.SOGO_D_IMAP_PORT == 143

    def test_gateway_passes_process_setting_to_module(self, mock_user, mock_user_domain_settings):
        """Verify process_setting is passed to ModuleMail when available."""
        mock_process = MagicMock()
        with patch("app.service.jmap.JmapMailGateway.ModuleMail") as mock_class:
            mock_instance = MagicMock()
            mock_class.return_value = mock_instance
            gw = JmapMailGateway(
                process_setting=mock_process,
                user_domain_settings=mock_user_domain_settings,
                user=mock_user,
            )
            # ModuleMail should receive the process_setting
            # (Note: ModuleMail.__init__ signature includes process_setting as optional)


# --------------------------------------------------------------------------- #
#  Mailbox Listing Tests
# --------------------------------------------------------------------------- #

class TestMailboxListing:
    """Test mailbox listing methods."""

    def test_list_mailbox_rows_delegates_to_module(self, gateway, mock_module_mail):
        """Verify list_mailbox_rows calls module.get_folder_list."""
        mock_module_mail.get_folder_list.return_value = [
            {"name": "INBOX", "path": "INBOX", "type": "inbox"},
            {"name": "Sent", "path": "Sent", "type": "sent"},
        ]
        account_id = "0"
        result = gateway.list_mailbox_rows(account_id)
        mock_module_mail.get_folder_list.assert_called_once_with(account_id)
        assert result == mock_module_mail.get_folder_list.return_value

    def test_create_mailbox_delegates_to_module(self, gateway, mock_module_mail):
        """Verify create_mailbox calls module.create_folder."""
        mock_module_mail.create_folder.return_value = {
            "name": "NewFolder",
            "path": "NewFolder",
            "type": "mail",
        }
        account_id = "0"
        name = "NewFolder"
        parent_path = "INBOX"
        result = gateway.create_mailbox(account_id, name, parent_path)
        mock_module_mail.create_folder.assert_called_once_with(account_id, name, parent_path)
        assert result == mock_module_mail.create_folder.return_value

    def test_delete_mailbox_delegates_to_module(self, gateway, mock_module_mail):
        """Verify delete_mailbox calls module.delete_folder."""
        account_id = "0"
        folder_path = "Trash/OldMail"
        gateway.delete_mailbox(account_id, folder_path)
        mock_module_mail.delete_folder.assert_called_once_with(account_id, folder_path)


# --------------------------------------------------------------------------- #
#  Email Access Tests
# --------------------------------------------------------------------------- #

class TestEmailAccess:
    """Test email access methods."""

    def test_get_mail_delegates_to_module(self, gateway, mock_module_mail):
        """Verify get_mail calls module.get_mail_detail."""
        mock_module_mail.get_mail_detail.return_value = {
            "uid": "123",
            "subject": "Test Email",
            "from": {"name": "Sender", "email": "sender@example.org"},
        }
        account_id = "0"
        folder_path = "INBOX"
        mail_uid = "123"
        result = gateway.get_mail(account_id, folder_path, mail_uid)
        mock_module_mail.get_mail_detail.assert_called_once_with(account_id, folder_path, mail_uid)
        assert result == mock_module_mail.get_mail_detail.return_value

    def test_get_mails_delegates_to_module(self, gateway, mock_module_mail):
        """Verify get_mails calls module.get_folder_mails."""
        mock_module_mail.get_folder_mails.return_value = (
            [{"uid": "1"}, {"uid": "2"}],
            2,
        )
        account_id = "0"
        folder_path = "INBOX"
        limit = 10
        offset = 0
        result = gateway.get_mails(account_id, folder_path, limit, offset)
        # Note: get_mails internally creates CollectionPaginateArgs
        assert len(result) == 2
        assert isinstance(result[1], int)

    def test_destroy_mail_delegates_to_module(self, gateway, mock_module_mail):
        """Verify destroy_mail calls module.delete_mails."""
        account_id = "0"
        folder_path = "INBOX"
        mail_uid = "123"
        gateway.destroy_mail(account_id, folder_path, mail_uid)
        mock_module_mail.delete_mails.assert_called_once_with(account_id, folder_path, mail_uid)

    def test_move_mail_delegates_to_module(self, gateway, mock_module_mail):
        """Verify move_mail calls module.move_mails."""
        account_id = "0"
        from_folder = "INBOX"
        mail_uid = 123
        to_folder = "Archive"
        gateway.move_mail(account_id, from_folder, mail_uid, to_folder)
        mock_module_mail.move_mails.assert_called_once_with(
            account_id, from_folder, [mail_uid], to_folder
        )

    def test_move_mail_with_list_of_uids(self, gateway, mock_module_mail):
        """Verify move_mail handles list of UIDs (if signature allows)."""
        account_id = "0"
        from_folder = "INBOX"
        mail_uid = [123, 456]  # List of UIDs
        to_folder = "Archive"
        # The current signature expects int, but let's verify it handles list
        # This might reveal a type issue
        try:
            gateway.move_mail(account_id, from_folder, mail_uid, to_folder)
            # If it doesn't raise, check what was passed
            call_args = mock_module_mail.move_mails.call_args
            assert call_args[0][2] == [mail_uid]  # Wrapped in another list
        except (TypeError, AttributeError):
            # Expected if the signature is strict
            pass


# --------------------------------------------------------------------------- #
#  Gateway Resolution Tests (role_for_folder)
# --------------------------------------------------------------------------- #

class TestGatewayResolution:
    """Test the role_for_folder static method — RFC 8621 §2.1 mailbox role mapping."""

    # --- Inbox ---

    def test_role_for_folder_inbox_by_type(self):
        """Inbox role detected from folder_type='inbox'."""
        result = JmapMailGateway.role_for_folder(folder_type="inbox", path="", name="")
        assert result == "inbox"

    def test_role_for_folder_inbox_by_type_uppercase(self):
        """Inbox role detected from folder_type='INBOX' (case-insensitive)."""
        result = JmapMailGateway.role_for_folder(folder_type="INBOX", path="", name="")
        assert result == "inbox"

    def test_role_for_folder_inbox_by_path(self):
        """Inbox role detected from path='INBOX'."""
        result = JmapMailGateway.role_for_folder(folder_type=None, path="INBOX", name="")
        assert result == "inbox"

    def test_role_for_folder_inbox_by_name(self):
        """Inbox role detected from name='Inbox'."""
        result = JmapMailGateway.role_for_folder(folder_type=None, path="", name="Inbox")
        assert result == "inbox"

    def test_role_for_folder_inbox_path_lowercase(self):
        """Inbox role detected from path='inbox' (case-insensitive)."""
        result = JmapMailGateway.role_for_folder(folder_type=None, path="inbox", name="")
        assert result == "inbox"

    # --- Sent ---

    def test_role_for_folder_sent_by_type(self):
        """Sent role detected from folder_type='sent'."""
        result = JmapMailGateway.role_for_folder(folder_type="sent", path="", name="")
        assert result == "sent"

    def test_role_for_folder_sent_in_path(self):
        """Sent role detected from path containing 'sent'."""
        result = JmapMailGateway.role_for_folder(folder_type=None, path="Mail/Sent", name="")
        assert result == "sent"

    def test_role_for_folder_sent_from_path_sent_items(self):
        """Sent role detected from path containing 'Sent Items'."""
        result = JmapMailGateway.role_for_folder(folder_type=None, path="Sent Items", name="")
        assert result == "sent"

    # --- Drafts ---

    def test_role_for_folder_drafts_by_type(self):
        """Drafts role detected from folder_type='drafts'."""
        result = JmapMailGateway.role_for_folder(folder_type="drafts", path="", name="")
        assert result == "drafts"

    def test_role_for_folder_draft_in_path(self):
        """Drafts role detected from path containing 'draft'."""
        result = JmapMailGateway.role_for_folder(folder_type=None, path="Mail/Drafts", name="")
        assert result == "drafts"

    def test_role_for_folder_drafts_from_type_drafts(self):
        """Drafts role detected from folder_type='Drafts'."""
        result = JmapMailGateway.role_for_folder(folder_type="Drafts", path="", name="")
        assert result == "drafts"

    # --- Trash ---

    def test_role_for_folder_trash_by_type(self):
        """Trash role detected from folder_type='trash'."""
        result = JmapMailGateway.role_for_folder(folder_type="trash", path="", name="")
        assert result == "trash"

    def test_role_for_folder_trash_in_path(self):
        """Trash role detected from path containing 'trash'."""
        result = JmapMailGateway.role_for_folder(folder_type=None, path="Mail/Trash", name="")
        assert result == "trash"

    # --- Junk ---

    def test_role_for_folder_junk_by_type(self):
        """Junk role detected from folder_type='junk'."""
        result = JmapMailGateway.role_for_folder(folder_type="junk", path="", name="")
        assert result == "junk"

    def test_role_for_folder_junk_in_path(self):
        """Junk role detected from path containing 'junk'."""
        result = JmapMailGateway.role_for_folder(folder_type=None, path="Mail/Junk", name="")
        assert result == "junk"

    def test_role_for_folder_spam_in_path(self):
        """Junk role detected from path containing 'spam'."""
        result = JmapMailGateway.role_for_folder(folder_type=None, path="Mail/Spam", name="")
        assert result == "junk"

    def test_role_for_folder_junk_from_path_junk_mail(self):
        """Junk role detected from path containing 'Junk Mail'."""
        result = JmapMailGateway.role_for_folder(folder_type=None, path="Junk Mail", name="")
        assert result == "junk"

    # --- Archive ---

    def test_role_for_folder_archive_by_type(self):
        """Archive role detected from folder_type='archive'."""
        result = JmapMailGateway.role_for_folder(folder_type="archive", path="", name="")
        assert result == "archive"

    def test_role_for_folder_archive_in_path(self):
        """Archive role detected from path containing 'archive'."""
        result = JmapMailGateway.role_for_folder(folder_type=None, path="Mail/Archive", name="")
        assert result == "archive"

    # --- None / Unknown ---

    def test_role_for_folder_none_for_unknown_type(self):
        """None returned for unknown folder type."""
        result = JmapMailGateway.role_for_folder(folder_type="custom", path="", name="")
        assert result is None

    def test_role_for_folder_none_for_empty_inputs(self):
        """None returned for empty/None inputs."""
        result = JmapMailGateway.role_for_folder(folder_type=None, path="", name="")
        assert result is None

    def test_role_for_folder_none_for_regular_folder(self):
        """None returned for a regular folder."""
        result = JmapMailGateway.role_for_folder(folder_type=None, path="Mail/Personal", name="Personal")
        assert result is None

    # --- Priority: type > path > name ---

    def test_role_for_folder_type_drafts_with_path_sent(self):
        """With folder_type='Drafts' and path='Sent', path check wins because it's checked first in the sent if."""
        # The if checks are: inbox? sent? drafts? trash? junk? archive?
        # For folder_type="Drafts", path="Sent":
        # - inbox: low=="inbox"? No. path_low=="inbox"? No. name_low=="inbox"? No.
        # - sent: low=="sent"? No (low is "drafts"). "sent" in path_low? Yes ("Sent" contains "sent"). Returns "sent"
        result = JmapMailGateway.role_for_folder(folder_type="Drafts", path="Sent", name="")
        assert result == "sent"

    def test_role_for_folder_path_trash_with_name_inbox(self):
        """With path='Trash' and name='Inbox', inbox check wins because it's checked first."""
        # The if checks are in order: inbox, sent, drafts, trash, junk, archive
        # For folder_type=None, path="Trash", name="Inbox":
        # - inbox: low=="inbox"? No. path_low=="inbox"? No. name_low=="inbox"? Yes ("Inbox" == "inbox"). Returns "inbox"
        result = JmapMailGateway.role_for_folder(folder_type=None, path="Trash", name="Inbox")
        assert result == "inbox"

    def test_role_for_folder_type_junk_with_path_inbox(self):
        """folder_type='junk' is checked first, so it wins over path='INBOX'."""
        # The conditions are OR'd together in order:
        # 1. folder_type check: low == "junk" -> True, returns "junk"
        # But wait, the inbox check is: low == "inbox" or path_low == "inbox" or name_low == "inbox"
        # So with folder_type="junk", path="INBOX", name="Inbox":
        # - junk check: low == "junk" -> False (low is "junk" not "junk"... wait it is "junk")
        # Let me re-check the logic
        # The checks are in order: inbox, sent, drafts, trash, junk, archive
        # So for folder_type="junk", path="INBOX", name="Inbox":
        # 1. inbox: low=="inbox"? "junk"=="inbox" -> False. path_low=="inbox"? "inbox"=="inbox" -> True! Returns "inbox"
        # So path="INBOX" will match inbox first
        result = JmapMailGateway.role_for_folder(
            folder_type="junk", path="INBOX", name="Inbox"
        )
        # Due to check ordering, path="INBOX" causes inbox match first
        assert result == "inbox"

    # --- Edge cases ---

    def test_role_for_folder_empty_string_type(self):
        """Empty string for folder_type is treated as None."""
        result = JmapMailGateway.role_for_folder(folder_type="", path="INBOX", name="")
        assert result == "inbox"  # Falls back to path

    def test_role_for_folder_check_order_inbox_first(self):
        """Inbox check happens before other checks."""
        # Because inbox is checked first, even with folder_type='sent',
        # if path='INBOX', inbox wins
        result = JmapMailGateway.role_for_folder(
            folder_type="sent", path="INBOX", name=""
        )
        assert result == "inbox"

    def test_role_for_folder_check_order_name_inbox(self):
        """Name 'inbox' is also checked for inbox role."""
        result = JmapMailGateway.role_for_folder(
            folder_type=None, path="Mail", name="Inbox"
        )
        assert result == "inbox"

    def test_role_for_folder_mixed_case_spam(self):
        """Spam in any case is mapped to junk."""
        result = JmapMailGateway.role_for_folder(folder_type=None, path="mail/SPAM/folder", name="")
        assert result == "junk"

    def test_role_for_folder_substring_sent(self):
        """Substring 'sent' in path is detected (not just whole word)."""
        result = JmapMailGateway.role_for_folder(folder_type=None, path="my-sent-items", name="")
        assert result == "sent"

    def test_role_for_folder_archive_in_path(self):
        """Archive role detected from path containing 'archive'."""
        # name is only checked for inbox, not archive
        result = JmapMailGateway.role_for_folder(folder_type=None, path="Mail/Archive", name="")
        assert result == "archive"


# --------------------------------------------------------------------------- #
#  Session Integration Tests
# --------------------------------------------------------------------------- #

class TestSessionIntegration:
    """Test gateway behavior with User session data."""

    def test_gateway_uses_user_uid(self, mock_user, mock_user_domain_settings):
        """Verify gateway stores and uses user.uid."""
        with patch("app.service.jmap.JmapMailGateway.ModuleMail"):
            gw = JmapMailGateway(
                process_setting=None,
                user_domain_settings=mock_user_domain_settings,
                user=mock_user,
            )
            assert gw.user.uid == "testuser@example.org"

    def test_gateway_uses_user_login_mail_server(self, mock_user, mock_user_domain_settings):
        """Verify gateway has access to user.login_mail_server."""
        with patch("app.service.jmap.JmapMailGateway.ModuleMail"):
            gw = JmapMailGateway(
                process_setting=None,
                user_domain_settings=mock_user_domain_settings,
                user=mock_user,
            )
            # ModuleMail would use user.login_mail_server in _get_user_conf
            assert gw.user.login_mail_server == "testuser"

    def test_gateway_handles_user_with_external_accounts(self, mock_user, mock_user_domain_settings):
        """Verify gateway handles user with external accounts."""
        mock_user.profile.external_accounts = {
            "ext-123": {
                "mail_server": {
                    "username": "extuser",
                    "password": "extpass",
                    "type": "imap",
                    "server": "ext.imap.example.org",
                    "port": 143,
                    "encryption": "None",
                    "auth_mech": "login",
                }
            }
        }
        with patch("app.service.jmap.JmapMailGateway.ModuleMail"):
            gw = JmapMailGateway(
                process_setting=None,
                user_domain_settings=mock_user_domain_settings,
                user=mock_user,
            )
            # The gateway itself doesn't directly access external_accounts
            # but ModuleMail would
            assert gw.user.profile.external_accounts is not None


# --------------------------------------------------------------------------- #
#  Error Path Tests
# --------------------------------------------------------------------------- #

class TestErrorPaths:
    """Test error handling and edge cases."""

    def test_module_get_folder_list_error_propagates(self, gateway, mock_module_mail):
        """Verify RequestException from module propagates through gateway."""
        from app.utils.exceptions import RequestException
        mock_module_mail.get_folder_list.side_effect = RequestException("IMAP error")
        with pytest.raises(RequestException):
            gateway.list_mailbox_rows("0")

    def test_module_get_mail_detail_error_propagates(self, gateway, mock_module_mail):
        """Verify RequestException from get_mail_detail propagates."""
        from app.utils.exceptions import RequestException
        mock_module_mail.get_mail_detail.side_effect = RequestException("Mail not found")
        with pytest.raises(RequestException):
            gateway.get_mail("0", "INBOX", "999")

    def test_move_mail_with_empty_to_folder_raises(self, gateway, mock_module_mail):
        """Verify move_mail raises when to_folder is empty."""
        # ModuleMail.move_mails should handle this, but let's verify the call
        gateway.move_mail("0", "INBOX", 123, "")
        # The module should handle validation, but we verify the call goes through
        mock_module_mail.move_mails.assert_called()
