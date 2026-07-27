"""Fixtures for property-based tests.

Provides fake/mocked interface instances so hypothesis tests can run
without a live stack.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.interface.mail.InterfaceApiMailSend import InterfaceApiMailSend


class FakeModuleMail:
    """Minimal fake for ModuleMail — enough to satisfy send_mail()."""

    def __init__(self):
        self.validate_tmp_draft_key_calls = []
        self.get_headers_from_tmp_draft_calls = []
        self.get_attachments_from_tmp_draft_calls = []
        self.delete_tmp_draft_calls = []

    def validate_tmp_draft_key(self, key: str) -> None:
        self.validate_tmp_draft_key_calls.append(key)

    def get_headers_from_tmp_draft(self, key: str) -> dict:
        self.get_headers_from_tmp_draft_calls.append(key)
        return {}

    def get_attachments_from_tmp_draft(self, account_id: str, key: str) -> list:
        self.get_attachments_from_tmp_draft_calls.append((account_id, key))
        return []

    def delete_tmp_draft(self, key: str, account_id: str) -> None:
        self.delete_tmp_draft_calls.append((key, account_id))

    def save_mail_to_folder(self, account_id: str, message: dict, folder_type: str) -> None:
        pass


class InterfaceApiMailSendWithInjectedConf(InterfaceApiMailSend):
    """Subclass that allows injecting mocked dependencies for testing."""

    def __init__(self, mail_module=None, outgoing_module=None, user_profile=None):
        self.mail_module = mail_module or MagicMock()
        self.mail_outgoing_module = outgoing_module or MagicMock()
        self.module_user_profile = user_profile or MagicMock()
        self._process = MagicMock()
        self.user = MagicMock()
        self.user.uid = "testuser@example.org"


@pytest.fixture
def mail_iface():
    """Provide a mocked InterfaceApiMailSend for property-based fuzzing.

    The outgoing module returns a success by default so we can test
    envelope conformance regardless of mail content.
    """
    fake_mail = FakeModuleMail()
    outgoing = MagicMock()
    outgoing.send_mail.return_value = {"uid": "42"}

    profile = MagicMock()
    profile.get_partial_user_preferences.return_value = {
        "user_general": {"SOGO_U_UNDO_SEND_SECONDS": 0}
    }

    iface = InterfaceApiMailSendWithInjectedConf(
        mail_module=fake_mail,
        outgoing_module=outgoing,
        user_profile=profile,
    )
    iface.user.uid = "testuser@example.org"

    with patch("app.interface.mail.InterfaceApiMailSend.ClientAgent") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.enqueue.return_value = "job-uuid-fuzz"
        mock_agent_cls.return_value = mock_agent
        yield iface
