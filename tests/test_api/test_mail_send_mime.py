# pylint: disable=invalid-sequence-index
"""Unit tests for the mailer's ``send_mime_message`` (F1 Email Delivery Integration).

``send_mime_message(recipient, subject, mime_msg)`` delivers a fully-formed MIME
message verbatim through the configured outgoing SMTP client (Stalwart by default).
Unlike ``send_mail`` it never rebuilds the body from a field dict, which is what
iMIP invitations (``text/calendar; method=REQUEST``) require.

Tests run WITHOUT a live stack: the SMTP delivery path (``send_raw_message`` →
``ClientSmtp``) is mocked, mirroring the rest of the suite.
"""
from __future__ import annotations

# ``app.config.settings.ProcessSetting`` instantiates a pydantic model at import
# time and requires these three env vars (no defaults). CI sets them via secrets;
# we seed harmless dev values here so this file also runs on a bare checkout.
import os

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

from email.message import EmailMessage, Message  # noqa: E402
from email import message_from_bytes  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402

from app.module.mail.ModuleMailOutgoing import ModuleMailOutgoing  # noqa: E402
from app.interface.mail.InterfaceApiMailSend import InterfaceApiMailSend  # noqa: E402
from app.utils.exceptions import RequestException  # noqa: E402
from tests.helpers import make_mail_iface  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# ModuleMailOutgoing.send_mime_message
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def outgoing() -> ModuleMailOutgoing:
    """ModuleMailOutgoing with a stubbed ``send_raw_message`` (no real SMTP)."""
    user = MagicMock()
    user.login_mail_outgoing = "organizer@example.org"
    module = ModuleMailOutgoing(user, MagicMock())
    module.send_raw_message = MagicMock()
    return module


class TestModuleSendMimeMessage:
    """Core delivery semantics of ModuleMailOutgoing.send_mime_message."""

    def test_sends_an_upstream_built_message_verbatim(self, outgoing):
        """An EmailMessage built upstream (e.g. iMIP invitation) is delivered as-is."""
        msg = EmailMessage()
        msg["From"] = "organizer@example.org"
        msg.set_content(
            "BEGIN:VCALENDAR", subtype="calendar",
            params={"method": "REQUEST", "component": "VEVENT"},
        )

        sent = outgoing.send_mime_message(
            "attendee@example.org", "Invitation: Planning", msg,
        )

        assert sent is msg
        outgoing.send_raw_message.assert_called_once_with("0", msg)
        assert msg["To"] == "attendee@example.org"

    def test_real_smtp_delivery_path_lives_in_send_raw_message(self, outgoing):
        """send_mime_message delegates to the Stalwart SMTP client via send_raw_message."""
        with patch.object(
            outgoing, "_open_client_for",
            return_value=MagicMock(send_mail=MagicMock()),
        ) as mock_open:
            imip = EmailMessage()
            imip["From"] = "organizer@example.org"
            imip.set_content(
                "BEGIN:VCALENDAR", subtype="calendar",
                params={"method": "REQUEST", "component": "VEVENT"},
            )
            # Replace send_raw_message with the real implementation so the full
            # chain -> ClientOutgoing.send_mail is exercised.
            real = ModuleMailOutgoing.send_raw_message
            outgoing.send_raw_message = real.__get__(outgoing, ModuleMailOutgoing)

            sent = outgoing.send_mime_message("a@example.org", "Invite", imip)

            client = mock_open.return_value
            client.send_mail.assert_called_once_with(sent)

    def test_fills_missing_to_subject_and_from(self, outgoing):
        """Missing To/Subject/From headers are filled from the arguments."""
        msg = EmailMessage()
        msg.set_content("Hello")

        outgoing.send_mime_message(["a@example.org", "b@example.org"], "Hello Re", msg)

        assert msg["To"] == "a@example.org, b@example.org"
        assert msg["Subject"] == "Hello Re"
        assert msg["From"] == "organizer@example.org"

    def test_existing_headers_are_kept(self, outgoing):
        """Existing To/Subject/From headers are not overwritten (except Date)."""
        msg = EmailMessage()
        msg["From"] = "custom@example.org"
        msg["To"] = "existing@example.org"
        msg["Subject"] = "Existing subject"
        msg.set_content("Hello")

        outgoing.send_mime_message("arg@example.org", "Argument subject", msg)

        assert msg["From"] == "custom@example.org"
        assert msg["To"] == "existing@example.org"
        assert msg["Subject"] == "Existing subject"

    def test_explicit_from_addr_wins(self, outgoing):
        """An explicit from_addr replaces the message From header (no duplicate)."""
        msg = EmailMessage()
        msg["From"] = "old@example.org"
        msg.set_content("Hello")

        outgoing.send_mime_message("a@example.org", "S", msg, from_addr="master@example.org")

        assert msg["From"] == "master@example.org"

    def test_accepts_raw_mime_string(self, outgoing):
        """A raw MIME string payload is parsed and delivered."""
        raw = (
            "From: organizer@example.org\r\n"
            "To: attendee@example.org\r\n"
            "Subject: Raw Invite\r\n"
            "MIME-Version: 1.0\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "Hello"
        )
        sent = outgoing.send_mime_message("attendee@example.org", "Unused", raw)

        assert isinstance(sent, Message)
        assert sent["From"] == "organizer@example.org"
        assert sent["Subject"] == "Raw Invite"
        assert "To" in sent
        outgoing.send_raw_message.assert_called_once()

    def test_accepts_raw_mime_bytes(self, outgoing):
        """A raw MIME bytes payload is parsed and delivered (Date is re-stamped)."""
        raw = (
            b"From: organizer@example.org\r\n"
            b"To: attendee@example.org\r\n"
            b"Subject: Bytes Invite\r\n"
            b"MIME-Version: 1.0\r\n"
            b"Content-Type: text/plain\r\n"
            b"\r\n"
            b"Hello"
        )
        sent = outgoing.send_mime_message("attendee@example.org", "Unused", raw)

        assert isinstance(sent, Message)
        parsed = message_from_bytes(raw)
        assert sent["From"] == parsed["From"]
        assert sent["To"] == parsed["To"]
        assert sent["Subject"] == parsed["Subject"]
        # send_mime_message always stamps a fresh Date on delivery.
        assert "Date" in sent

    def test_accepts_lazy_callable(self, outgoing):
        """A zero-argument callable is invoked to build the message lazily."""
        built: list = []

        def build() -> EmailMessage:
            msg = EmailMessage()
            msg.set_content("Lazy")
            built.append(msg)
            return msg

        sent = outgoing.send_mime_message("a@example.org", "Lazy subject", build)

        assert len(built) == 1
        assert sent is built[0]
        assert sent["Subject"] == "Lazy subject"

    def test_adds_message_id_and_date(self, outgoing):
        """A unique Message-ID and a fresh Date are always present."""
        msg = EmailMessage()
        msg.set_content("Hello")

        outgoing.send_mime_message("a@example.org", "S", msg)

        assert msg["Message-ID"]
        assert msg["Date"]

    def test_default_account_is_main(self, outgoing):
        """With no account_id the main account (DEFAULT_IDENTITY_KEY_VALUE) is used."""
        outgoing.send_mime_message("a@example.org", "S", EmailMessage())
        outgoing.send_raw_message.assert_called_once_with("0", outgoing.send_raw_message.call_args.args[1])

    def test_custom_account_is_passed_through(self, outgoing):
        """An explicit account_id is handed to the low-level send."""
        outgoing.send_mime_message("a@example.org", "S", EmailMessage(), account_id="shared-abc")
        outgoing.send_raw_message.assert_called_once_with("shared-abc", outgoing.send_raw_message.call_args.args[1])

    def test_propagates_request_exception(self, outgoing):
        """A delivery failure surfaces as RequestException (mapped by the caller)."""
        from app.utils import errors as err

        outgoing.send_raw_message.side_effect = RequestException(
            err.ERROR_SMTP_RECIPIENTS_REFUSED.m, err.ERROR_SMTP_RECIPIENTS_REFUSED,
        )
        with pytest.raises(RequestException):
            outgoing.send_mime_message("a@example.org", "S", EmailMessage())


# ─────────────────────────────────────────────────────────────────────────────
# InterfaceApiMailSend.send_mime_message (service facade)
# ─────────────────────────────────────────────────────────────────────────────

class TestInterfaceSendMimeMessage:
    """Facade maps the module result to an API response and errors to HTTP errors."""

    def setup_method(self):
        self.iface = make_mail_iface()
        self.iface.user.uid = "organizer@example.org"

    def test_returns_sent_status_with_headers(self):
        """Successful delivery returns data with status 'sent' and header echo."""
        from app.utils import errors as err

        sent_msg = EmailMessage()
        sent_msg["To"] = "attendee@example.org"
        sent_msg["Subject"] = "Invitation: Planning"
        self.iface.mail_outgoing_module.send_mime_message.return_value = sent_msg

        result, status = self.iface.send_mime_message(
            "attendee@example.org", "Invitation: Planning", sent_msg,
        )

        assert status == 200
        assert result["data"]["status"] == "sent"
        assert result["data"]["to"] == "attendee@example.org"
        assert result["data"]["subject"] == "Invitation: Planning"
        assert result["error_code"] == err.ERROR_NO_ERROR.c  # "S000000"

    def test_forwards_arguments_to_module(self):
        """recipient/subject/mime_msg/account_id/from_addr reach the module."""
        self.iface.mail_outgoing_module.send_mime_message.return_value = EmailMessage()

        self.iface.send_mime_message(
            ["a@example.org"], "S", "raw mime", account_id="0", from_addr="noreply@example.org",
        )

        self.iface.mail_outgoing_module.send_mime_message.assert_called_once_with(
            ["a@example.org"], "S", "raw mime", account_id="0", from_addr="noreply@example.org",
        )

    def test_error_maps_to_request_exception_error(self):
        """A RequestException from the module becomes an error API response."""
        from app.utils import errors as err

        self.iface.mail_outgoing_module.send_mime_message.side_effect = RequestException(
            err.ERROR_SMTP_RECIPIENTS_REFUSED.m, err.ERROR_SMTP_RECIPIENTS_REFUSED,
        )

        result, status = self.iface.send_mime_message("a@example.org", "S", EmailMessage())

        assert result["data"] is None
        assert result["error_code"] == err.ERROR_SMTP_RECIPIENTS_REFUSED.c
        assert status == err.ERROR_SMTP_RECIPIENTS_REFUSED.h  # 400


def test_interface_exposes_send_mime_message():
    """The mail interface facade exposes send_mime_message (API layer contract)."""
    from app.interface.mail.InterfaceApiMailSend import InterfaceApiMailSend

    assert hasattr(InterfaceApiMailSend, "send_mime_message")
    assert callable(InterfaceApiMailSend.send_mime_message)
