# pylint: disable=invalid-sequence-index
"""Unit tests for InterfaceApiMailSend — send_mail / Schedule Send / Undo Send."""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from tests.helpers import (
    make_mail_data,
    make_mail_iface,
)
from app.agent.jobs.ScheduleSendJob import ScheduleSendRequest


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSendMailScheduleSend:
    """Tests for send_mail with send_at (Schedule Send)."""

    def setup_method(self):
        self.iface = make_mail_iface(undo_seconds=0)
        self.outgoing = self.iface.mail_outgoing_module
        self.fake_mail = self.iface.mail_module

    # ── send_at in the future → scheduled ──────────────────────────────────

    @patch("app.interface.mail.InterfaceApiMailSend.sogo_agent")
    def test_send_mail_with_future_send_at_returns_scheduled(self, mock_client_agent):
        """send_at in the future → enqueue with eta → status: scheduled."""
        mock_agent = MagicMock()
        mock_agent.enqueue.return_value = "job-uuid-123"
        mock_client_agent.return_value = mock_agent

        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        result, status = self.iface.send_mail(
            "0", make_mail_data({"send_at": future})
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
            "0", make_mail_data({"send_at": past})
        )

        assert status == 200
        # Should fall through to immediate send
        self.outgoing.send_mail.assert_called_once()
        # send_at should be removed from mail_data (passed as second positional arg)
        sent_data = self.outgoing.send_mail.call_args[0][1]
        assert "send_at" not in sent_data

    # ── no send_at → immediate send (existing behaviour) ──────────────────

    def test_send_mail_without_send_at_sends_immediately(self):
        """No send_at → existing behaviour unchanged (immediate send)."""
        self.outgoing.send_mail.return_value = {"uid": "99"}
        result, status = self.iface.send_mail("0", make_mail_data())

        assert status == 200
        self.outgoing.send_mail.assert_called_once()

    # ── invalid send_at format ────────────────────────────────────────────

    def test_send_mail_with_invalid_send_at_format(self):
        """Malformed send_at → 400 error."""
        result, status = self.iface.send_mail(
            "0", make_mail_data({"send_at": "not-a-date"})
        )
        assert status == 400
        assert result["error_code"] == "S000396"

    # ── send_at stripped before forwarding to execute_send ────────────────

    def test_send_mail_strips_send_at_before_immediate_send(self):
        """send_at must be removed from mail_data before _execute_send."""
        self.outgoing.send_mail.return_value = {"uid": "7"}
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self.iface.send_mail("0", make_mail_data({"send_at": past}))

        sent_data = self.outgoing.send_mail.call_args[0][1]
        assert "send_at" not in sent_data

    # ── send_at beyond max delay ──────────────────────────────────

    @patch("app.interface.mail.InterfaceApiMailSend.sogo_agent")
    def test_send_mail_with_send_at_beyond_max_delay(self, mock_client_agent):
        """send_at >30 days from now → 400 max delay error."""
        mock_agent = MagicMock()
        mock_agent.enqueue.return_value = "job-uuid"
        mock_client_agent.return_value = mock_agent

        far_future = (datetime.now(timezone.utc) + timedelta(days=31)).isoformat()
        result, status = self.iface.send_mail(
            "0", make_mail_data({"send_at": far_future})
        )

        assert status == 400
        assert result["error_code"] == "S000489"
        assert "Exceeds Maximum Allowed Delay" in result["error_msg"]

    # ── send_at exactly at max delay boundary ──────────────────────

    @patch("app.interface.mail.InterfaceApiMailSend.sogo_agent")
    def test_send_mail_with_send_at_at_max_delay_boundary(self, mock_client_agent):
        """send_at exactly 30 days from now → accepted (boundary test)."""
        mock_agent = MagicMock()
        mock_agent.enqueue.return_value = "job-uuid-boundary"
        mock_client_agent.return_value = mock_agent

        boundary = (datetime.now(timezone.utc) + timedelta(days=29)).isoformat()
        result, status = self.iface.send_mail(
            "0", make_mail_data({"send_at": boundary})
        )

        assert status == 200
        assert result["data"]["status"] == "scheduled"


class TestSendMailUndoSend:
    """Tests for Undo Send (existing behaviour preserved)."""

    def setup_method(self):
        self.iface = make_mail_iface(undo_seconds=5)
        self.outgoing = self.iface.mail_outgoing_module
        self.fake_mail = self.iface.mail_module

    @patch("app.interface.mail.InterfaceApiMailSend.sogo_cache")
    @patch("app.interface.mail.InterfaceApiMailSend.sogo_agent")
    def test_undo_send_enabled_returns_pending(self, mock_client_agent, mock_cache):
        """Undo Send enabled → status: pending + delivery job enqueued."""
        mock_redis = MagicMock()
        mock_cache.return_value = mock_redis
        mock_client_agent.return_value.enqueue.return_value = "job-uuid"

        result, status = self.iface.send_mail("0", make_mail_data())

        assert status == 200
        assert result["data"]["status"] == "pending"
        assert "pending_key" in result["data"]
        mock_redis.set.assert_called_once()
        # A delivery job must be enqueued with an eta in the future.
        mock_client_agent.return_value.enqueue.assert_called_once()
        enqueue_kwargs = mock_client_agent.return_value.enqueue.call_args[1]
        assert "eta" in enqueue_kwargs
        assert enqueue_kwargs["eta"] > datetime.now(timezone.utc)
        assert enqueue_kwargs["user_uid"] == "testuser@example.org"

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
        assert result["error_code"] == "S000392"


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

    @staticmethod
    def _job_patches(outgoing):
        """Patch set for ScheduleSendJob.process: the worker rebuilds the user
        from payload['user_session'] with no request context (see UndoSendJob
        tests for the same pattern)."""
        from contextlib import ExitStack
        stack = ExitStack()
        # ModuleMailOutgoing is bound at import time in ScheduleSendJob — patch
        # the job module's binding, not the source module.
        stack.enter_context(patch("app.agent.jobs.ScheduleSendJob.ModuleMailOutgoing", return_value=outgoing))
        stack.enter_context(patch("app.config.init_config.init_get_user_domain_settings",
                                  return_value={"MAIL_SETTINGS": {}}))
        stack.enter_context(patch("app.module.user.ModuleUserProfile.ModuleUserProfile"))
        stack.enter_context(patch("app.config.settings.DomainSettings.MailSettingsObj"))
        return stack

    @staticmethod
    def _job_payload(mail_data: dict, extra_headers=None) -> dict:
        return {
            "account_id": "0",
            "mail_data": mail_data,
            "extra_headers": extra_headers,
            "tmp_draft_key": None,
            # Mirrors User.get_user_session(): all five keys are required by
            # User.init_from_user_session in the worker.
            "user_session": {"uid": "testuser@example.org", "password": "", "domain": "example.org",
                             "email": "testuser@example.org", "source_id": "example.org"},
            "login_mail_outgoing": None,
        }

    def test_schedule_send_job_process_calls_execute_send(self):
        """ScheduleSendJob.process() calls outgoing.send_mail with correct data."""
        from app.agent.jobs.ScheduleSendJob import ScheduleSendJob

        mock_outgoing = MagicMock()
        mock_outgoing.send_mail.return_value = {"uid": "sent-42"}

        job = ScheduleSendJob()
        with self._job_patches(mock_outgoing):
            result = job.process(self._job_payload(
                {"from": "a@b.com", "to": ["c@d.com"], "subject": "Test", "body": "Hello"}))

        assert result["status"] == "sent"
        assert result["uid"] == "sent-42"
        mock_outgoing.send_mail.assert_called_once()
        sent_data = mock_outgoing.send_mail.call_args[0][1]
        assert "send_at" not in sent_data

    def test_schedule_send_job_process_strips_send_at(self):
        """ScheduleSendJob.process() strips send_at from mail_data if present."""
        from app.agent.jobs.ScheduleSendJob import ScheduleSendJob

        mock_outgoing = MagicMock()
        mock_outgoing.send_mail.return_value = {"uid": "sent-99"}

        job = ScheduleSendJob()
        payload = self._job_payload({
            "from": "a@b.com",
            "to": ["c@d.com"],
            "subject": "Test",
            "body": "Hello",
            "send_at": "2026-08-01T14:00:00Z",  # should be stripped
        })
        with self._job_patches(mock_outgoing):
            result = job.process(payload)

        assert result["status"] == "sent"
        sent_data = mock_outgoing.send_mail.call_args[0][1]
        assert "send_at" not in sent_data, "send_at leaked through to outgoing.send_mail"

    def test_schedule_send_job_process_with_extra_headers(self):
        """ScheduleSendJob.process() forwards extra_headers to outgoing.send_mail."""
        from app.agent.jobs.ScheduleSendJob import ScheduleSendJob

        mock_outgoing = MagicMock()
        mock_outgoing.send_mail.return_value = {"uid": "sent-77"}

        job = ScheduleSendJob()
        payload = self._job_payload(
            {"from": "a@b.com", "to": ["c@d.com"], "subject": "Test", "body": "Hello"},
            extra_headers={"References": "<msgid@example>"},
        )
        with self._job_patches(mock_outgoing):
            result = job.process(payload)

        assert result["status"] == "sent"
        mock_outgoing.send_mail.assert_called_once()
        call_kwargs = mock_outgoing.send_mail.call_args[1]
        assert call_kwargs.get("extra_headers") == {"References": "<msgid@example>"}
