import pytest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from app.service.jmap.JmapMailGateway import JmapMailGateway
from app.auth.User import User

@pytest.fixture
def mock_user():
    return SimpleNamespace(uid="u1", email="u1@example.com")

@pytest.fixture
def mock_settings():
    return {"mail": {"some": "setting"}}

@pytest.fixture
def gateway(mock_user, mock_settings):
    # Patch ModuleMail to avoid real IMAP connections
    with patch("app.service.jmap.JmapMailGateway.ModuleMail") as mock_mod:
        gateway = JmapMailGateway(None, mock_settings, mock_user)
        # Make the mock_mod instance available to the gateway
        gateway.module = mock_mod.return_value
        yield gateway

def test_list_mailbox_rows(gateway):
    gateway.module.get_folder_list.return_value = [{"name": "INBOX", "count": 10}]
    res = gateway.list_mailbox_rows("acc1")
    assert res == [{"name": "INBOX", "count": 10}]
    gateway.module.get_folder_list.assert_called_once_with("acc1")

def test_create_mailbox(gateway):
    gateway.module.create_folder.return_value = {"name": "NewFolder", "path": "NewFolder"}
    res = gateway.create_mailbox("acc1", "NewFolder", "parent")
    assert res == {"name": "NewFolder", "path": "NewFolder"}
    gateway.module.create_folder.assert_called_once_with("acc1", "NewFolder", "parent")

def test_delete_mailbox(gateway):
    gateway.delete_mailbox("acc1", "folder/path")
    gateway.module.delete_folder.assert_called_once_with("acc1", "folder/path")

def test_get_mail(gateway):
    gateway.module.get_mail_detail.return_value = {"uid": "123", "subject": "hi"}
    res = gateway.get_mail("acc1", "INBOX", "123")
    assert res == {"uid": "123", "subject": "hi"}
    gateway.module.get_mail_detail.assert_called_once_with("acc1", "INBOX", "123")

def test_get_mails(gateway):
    gateway.module.get_folder_mails.return_value = ([{"uid": "1"}], 1)
    res, count = gateway.get_mails("acc1", "INBOX", limit=10, offset=20)
    assert res == [{"uid": "1"}]
    assert count == 1
    # Page = 20 // 10 + 1 = 3
    # Verify the call to ModuleMail.get_folder_mails was made with correct arguments
    args, _ = gateway.module.get_folder_mails.call_args
    assert args[0] == "acc1"
    assert args[1] == "INBOX"
    assert args[2].page == 3
    assert args[2].page_size == 10

def test_get_mails_limit_zero(gateway):
    # Test max(limit, 1)
    gateway.module.get_folder_mails.return_value = ([], 0)
    gateway.get_mails("acc1", "INBOX", limit=0)
    args, _ = gateway.module.get_folder_mails.call_args
    assert args[2].page_size == 1

def test_destroy_mail(gateway):
    gateway.destroy_mail("acc1", "INBOX", "123")
    gateway.module.delete_mails.assert_called_once_with("acc1", "INBOX", "123")

def test_move_mail(gateway):
    gateway.move_mail("acc1", "INBOX", 123, "Archive")
    gateway.module.move_mails.assert_called_once_with("acc1", "INBOX", [123], "Archive")

@pytest.mark.parametrize("folder_type, path, name, expected", [
    ("INBOX", "any", "any", "inbox"),
    (None, "INBOX", "any", "inbox"),
    ("any", "any", "INBOX", "inbox"),
    ("SENT", "any", "any", "sent"),
    ("any", "Sent Messages", "any", "sent"),
    ("DRAFTS", "any", "any", "drafts"),
    ("any", "Drafts", "any", "drafts"),
    ("TRASH", "any", "any", "trash"),
    ("any", "Trash", "any", "trash"),
    ("JUNK", "any", "any", "junk"),
    ("any", "Junk", "any", "junk"),
    ("any", "Spam", "any", "junk"),
    ("ARCHIVE", "any", "any", "archive"),
    ("any", "Archive", "any", "archive"),
    ("UNKNOWN", "UNKNOWN", "UNKNOWN", None),
    (None, "UNKNOWN", "UNKNOWN", None),
])
def test_role_for_folder(folder_type, path, name, expected):
    assert JmapMailGateway.role_for_folder(folder_type, path, name) == expected
