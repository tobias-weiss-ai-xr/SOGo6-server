# pylint: disable=invalid-sequence-index
"""Unit tests for InterfaceApiMailSend — send_mail / Schedule Send / Undo Send."""

from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import patch, MagicMock

from app.interface.mail.InterfaceApiMailSend import InterfaceApiMailSend
from app.utils.exceptions import RequestException
from app.utils import errors as err
from app.agent.jobs.ScheduleSendJob import ScheduleSendRequest


class InterfaceApiMailSendWithInjectedConf(InterfaceApiMailSend):
    """Subclass that allows injecting mocked dependencies for testing."""

    def __init__(self, mail_module=None, outgoing_module=None, user_profile=None):
        self.mail_module = mail_module or MagicMock()
        self.mail_outgoing_module = outgoing_module or MagicMock()
        self.module_user_profile = user_profile or MagicMock()
        self._process = MagicMock()
        self.user = MagicMock()
        self.user.uid = "testuser@example.org"


class FakeModuleMail:
    """Fake ModuleMail for testing send_mail flows."""

    def __init__(self):
        self.validate_tmp_draft_key_calls = []
        self.get_headers_from_tmp_draft_calls = []
        self.get_attachments_from_tmp_draft_calls = []
        self.delete_tmp_draft_calls = []

        self.validate_tmp_draft_key_side_effect = None
        self.get_headers_from_tmp_draft_result = {}
        self.get_attachments_from_tmp_draft_result = []

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


# ─────────────────────────────────────────────────────────────────────────────
# Helper to build the mail_data dict that send_mail receives from the schema
# ─────────────────────────────────────────────────────────────────────────────

def _mail_data(overrides: dict | None = None) -> dict[str, Any]:
    data = {
        "from": "sender@example.org",
        "to": ["recipient@example.org"],
        "subject": "Test",
        "body": "Hello",
    }
    if overrides:
        data.update(overrides)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSendMailScheduleSend:
    """Tests for send_mail with send_at (Schedule Send)."""

    def setup_method(self):
        self.fake_mail = FakeModuleMail()
        self.outgoing = MagicMock()
        self.profile = MagicMock()
        # Default: undo send disabled (0 seconds)
        self.profile.get_partial_user_preferences.return_value = {
            "user_general": {"SOGO_U_UNDO_SEND_SECONDS": 0}
        }
        self.iface = InterfaceApiMailSendWithInjectedConf(
            mail_module=self.fake_mail,
            outgoing_module=self.outgoing,
            user_profile=self.profile,
        )
        self.iface.user.uid = "testuser@example.org"

    # ── send_at in the future → scheduled ──────────────────────────────────

    @patch("app.interface.mail.InterfaceApiMailSend.ClientAgent")
    def test_send_mail_with_future_send_at_returns_scheduled(self, mock_client_agent):
        """send_at in the future → enqueue with eta → status: scheduled."""
        mock_agent = MagicMock()
        mock_agent.enqueue.return_value = "job-uuid-123"
        mock_client_agent.return_value = mock_agent

        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        result, status = self.iface.send_mail(
            "0", _mail_data({"send_at": future})
        )

        assert status == 200
        assert result["data"]["status"] == "scheduled"
        assert result["data"]["scheduled_at"] == future
        assert result["data"]["job_id"] == "job-uuid-123"
        mock_agent.enqueue.assert_called_once()
        call_kwargs = mock_agent.enqueue.call_args[1]
        assert "eta" in call_kwargs
        assert isinstance(call_kwargs["eta"], datetime)

    # ── send_at in the past → immediate send ───────────────────────────────

    def test_send_mail_with_past_send_at_sends_immediately(self):
        """send_at in the past → send immediately (no scheduling)."""
        self.outgoing.send_mail.return_value = {"uid": "42"}
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        result, status = self.iface.send_mail(
            "0", _mail_data({"send_at": past})
        )

        assert status == 200
        # Should fall through to immediate send
        self.outgoing.send_mail.assert_called_once()
        # send_at should be removed from mail_data before sending
        sent_data = self.outgoing.send_mail.call_args[1]["mail_data"]
        assert "send_at" not in sent_data

    # ── no send_at → immediate send (existing behaviour) ──────────────────

    def test_send_mail_without_send_at_sends_immediately(self):
        """No send_at → existing behaviour unchanged (immediate send)."""
        self.outgoing.send_mail.return_value = {"uid": "99"}
        result, status = self.iface.send_mail("0", _mail_data())

        assert status == 200
        self.outgoing.send_mail.assert_called_once()

    # ── invalid send_at format ────────────────────────────────────────────

    def test_send_mail_with_invalid_send_at_format(self):
        """Malformed send_at → 400 error."""
        result, status = self.iface.send_mail(
            "0", _mail_data({"send_at": "not-a-date"})
        )
        assert status == 400
        assert result["error_code"] == err.ERROR_MAIL_SCHEDULE_INVALID_DATE.code_num

    # ── send_at stripped before forwarding to execute_send ────────────────

    def test_send_mail_strips_send_at_before_immediate_send(self):
        """send_at must be removed from mail_data before _execute_send."""
        self.outgoing.send_mail.return_value = {"uid": "7"}
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self.iface.send_mail("0", _mail_data({"send_at": past}))

        sent_data = self.outgoing.send_mail.call_args[1]["mail_data"]
        assert "send_at" not in sent_data


class TestSendMailUndoSend:
    """Tests for Undo Send (existing behaviour preserved)."""

    def setup_method(self):
        self.fake_mail = FakeModuleMail()
        self.outgoing = MagicMock()
        self.profile = MagicMock()
        # Enable undo send (5 seconds)
        self.profile.get_partial_user_preferences.return_value = {
            "user_general": {"SOGO_U_UNDO_SEND_SECONDS": 5}
        }
        self.iface = InterfaceApiMailSendWithInjectedConf(
            mail_module=self.fake_mail,
            outgoing_module=self.outgoing,
            user_profile=self.profile,
        )
        self.iface.user.uid = "testuser@example.org"

    @patch("app.interface.mail.InterfaceApiMailSend.sogo_cache")
    def test_undo_send_enabled_returns_pending(self, mock_cache):
        """Undo Send enabled → status: pending."""
        mock_redis = MagicMock()
        mock_cache.return_value = mock_redis

        result, status = self.iface.send_mail("0", _mail_data())

        assert status == 200
        assert result["data"]["status"] == "pending"
        assert "pending_key" in result["data"]
        mock_redis.set.assert_called_once()

    @patch("app.interface.mail.InterfaceApiMailSend.sogo_cache")
    def test_undo_send_cancel_returns_cancelled(self, mock_cache):
        """Cancel pending send → status: cancelled."""
        mock_redis = MagicMock()
        mock_cache.return_value = mock_redis
        mock_redis.get.return_value = (
            '{"account_id": "0", "mail_data": {}, "created_at": "'
            + datetime.now(timezone.utc).isoformat()
            + '"}'
        )

        result, status = self.iface.cancel_pending_send("0", "test-key")

        assert status == 200
        assert result["data"]["status"] == "cancelled"
        mock_redis.delete.assert_called_once()

    @patch("app.interface.mail.InterfaceApiMailSend.sogo_cache")
    def test_undo_send_cancel_not_found(self, mock_cache):
        """Cancel non-existent pending send → 404."""
        mock_redis = MagicMock()
        mock_cache.return_value = mock_redis
        mock_redis.get.return_value = None

        result, status = self.iface.cancel_pending_send("0", "missing-key")

        assert status == 404
        assert result["error_code"] == err.ERROR_MAIL_UNDO_SEND_NOT_FOUND.code_num


class TestScheduleSendJob:
    """Tests for ScheduleSendJob worker."""

    def test_schedule_send_request_payload(self):
        """ScheduleSendRequest.payload() returns expected dict."""
        req = ScheduleSendRequest(
            account_id="0",
            mail_data={"subject": "Test", "from": "a@b.com"},
            extra_headers=None,
            tmp_draft_key=None,
        )
        payload = req.payload()
        assert payload["account_id"] == "0"
        assert payload["mail_data"]["subject"] == "Test"
        assert "send_at" not in payload["mail_data"]

    def test_schedule_send_request_name(self):
        """ScheduleSendRequest.name matches the registered job name."""
        assert ScheduleSendRequest.name == "schedule_send"
