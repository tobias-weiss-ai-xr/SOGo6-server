"""Shared test helpers for SOGo 6 Server unit tests.

Provides reusable fakes and mock interface subclasses so test files
don't duplicate fixture setup code.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.interface.mail.InterfaceApiMailSend import InterfaceApiMailSend


class FakeModuleMail:
    """Minimal fake for ModuleMail — satisfies the interface needed by send_mail().

    Records all calls for assertion and can be configured with side effects
    to test error paths.
    """

    def __init__(self):
        self.validate_tmp_draft_key_calls: list = []
        self.get_headers_from_tmp_draft_calls: list = []
        self.get_attachments_from_tmp_draft_calls: list = []
        self.delete_tmp_draft_calls: list = []

        self.validate_tmp_draft_key_side_effect: Exception | None = None
        self.get_headers_from_tmp_draft_result: dict = {}
        self.get_attachments_from_tmp_draft_result: list = []

    def validate_tmp_draft_key(self, key: str) -> None:
        self.validate_tmp_draft_key_calls.append(key)
        if self.validate_tmp_draft_key_side_effect:
            raise self.validate_tmp_draft_key_side_effect

    def get_headers_from_tmp_draft(self, key: str) -> dict:
        self.get_headers_from_tmp_draft_calls.append(key)
        return self.get_headers_from_tmp_draft_result

    def get_attachments_from_tmp_draft(self, account_id: str, key: str) -> list:
        self.get_attachments_from_tmp_draft_calls.append((account_id, key))
        return self.get_attachments_from_tmp_draft_result

    def delete_tmp_draft(self, key: str, account_id: str) -> None:
        self.delete_tmp_draft_calls.append((key, account_id))

    def save_mail_to_folder(self, account_id: str, message: dict, folder_type: str) -> None:
        pass


class InterfaceApiMailSendWithInjectedConf(InterfaceApiMailSend):
    """Subclass that allows injecting mocked dependencies for testing.

    Usage::

        iface = InterfaceApiMailSendWithInjectedConf(
            mail_module=FakeModuleMail(),
            outgoing_module=MagicMock(),
            user_profile=MagicMock(),
        )
        iface.user.uid = "testuser@example.org"
        result, status = iface.send_mail("0", mail_data)
    """

    def __init__(self, mail_module=None, outgoing_module=None, user_profile=None):
        self.mail_module = mail_module or MagicMock()
        self.mail_outgoing_module = outgoing_module or MagicMock()
        self.module_user_profile = user_profile or MagicMock()
        self._process = MagicMock()
        self.user = MagicMock()
        self.user.uid = "testuser@example.org"
        self.mail_settings = MagicMock()
        self.mail_settings.SOGO_D_SCHEDULE_SEND_MAX_DELAY_DAYS = 30


def make_mail_data(overrides: dict | None = None) -> dict:
    """Build a standard mail_data dict, optionally overriding fields.

    Example::

        make_mail_data({"send_at": "2026-08-01T14:00:00Z"})
    """
    data = {
        "from": "sender@example.org",
        "to": ["recipient@example.org"],
        "subject": "Test",
        "body": "Hello",
    }
    if overrides:
        data.update(overrides)
    return data


def make_mail_iface(
    mail_module=None,
    outgoing_module=None,
    user_profile=None,
    undo_seconds: int = 0,
) -> InterfaceApiMailSendWithInjectedConf:
    """Build a configured InterfaceApiMailSend with sensible defaults.

    The outgoing module returns success by default. Undo Send is disabled
    unless *undo_seconds* > 0.

    Example::

        iface = make_mail_iface(undo_seconds=5)
        result, status = iface.send_mail("0", make_mail_data())
    """
    outgoing = outgoing_module or MagicMock()
    if not hasattr(outgoing, 'send_mail') or outgoing.send_mail is None:
        outgoing = MagicMock()
    outgoing.send_mail.return_value = {"uid": "42"}

    profile = user_profile or MagicMock()
    profile.get_partial_user_preferences.return_value = {
        "USER_GENERAL": {"SOGO_U_UNDO_SEND_SECONDS": undo_seconds}
    }

    iface = InterfaceApiMailSendWithInjectedConf(
        mail_module=mail_module or FakeModuleMail(),
        outgoing_module=outgoing,
        user_profile=profile,
    )
    iface.user.uid = "testuser@example.org"
    return iface
