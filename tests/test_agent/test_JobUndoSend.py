"""Unit tests for the UndoSendJob Agent job (delivers pending emails after the undo window)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.agent.jobs.UndoSendJob import UndoSendJob, UndoSendRequest

_JOB_MODULE = "app.agent.jobs.UndoSendJob"


def test_request_metadata():
    assert UndoSendJob.request_class is UndoSendRequest
    assert UndoSendRequest.name == "undo_send"
    assert UndoSendRequest.max_try == 3
    assert UndoSendRequest.max_concurrent == 0


def test_request_payload_roundtrip():
    req = UndoSendRequest(user_uid="user@example.org", pending_key="abc123")
    payload = req.payload()
    assert payload == {"user_uid": "user@example.org", "pending_key": "abc123"}
    rehydrated = UndoSendRequest(**payload)
    assert rehydrated.user_uid == "user@example.org"
    assert rehydrated.pending_key == "abc123"


def _pending_payload(**overrides) -> str:
    base = {
        "account_id": "0",
        "mail_data": {"from": "a@example.org", "to": ["b@example.org"], "subject": "Hi", "body": "Hello"},
        "extra_headers": None,
        "tmp_draft_key": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "user_session": {
            "uid": "user@example.org",
            "password": "secret",
            "domain": "example.org",
            "mail": "user@example.org",
            "source_id": "ldap",
        },
        "login_mail_outgoing": "user@example.org",
    }
    base.update(overrides)
    return json.dumps(base)


def _process(pending_key="abc123", user_uid="user@example.org") -> dict:
    return UndoSendJob().process(
        {"user_uid": user_uid, "pending_key": pending_key},
        user_uid=user_uid,
        job_id="j-1",
    )


class TestUndoSendJobProcess:
    def test_delivers_pending_mail_and_cleans_redis(self):
        """Pending entry present → mail sent, Sent folder updated, entry deleted."""
        cache = MagicMock()
        cache.get.return_value = _pending_payload()
        outgoing = MagicMock()
        outgoing.send_mail.return_value = {"uid": "42"}
        mail_module = MagicMock()
        user = MagicMock()

        with patch("app.service.sogo_cache", return_value=cache), \
             patch("app.config.init_config.init_get_user_domain_settings", return_value={"MAIL_SETTINGS": {}}) as get_dom, \
             patch("app.auth.User.User.init_from_user_session", return_value=user) as init_user, \
             patch("app.module.user.ModuleUserProfile.ModuleUserProfile") as profile_cls, \
             patch("app.config.settings.DomainSettings.MailSettingsObj") as mail_settings_cls, \
             patch("app.module.mail.ModuleMailOutgoing.ModuleMailOutgoing", return_value=outgoing) as outgoing_cls, \
             patch("app.module.mail.ModuleMail.ModuleMail", return_value=mail_module):
            result = _process()

        assert result["status"] == "sent"
        assert result["uid"] == "42"
        init_user.assert_called_once()
        assert user.login_mail_outgoing == "user@example.org"
        get_dom.assert_called_once_with(user)
        profile_cls().get_user_profile.assert_called_once_with(user)
        outgoing.send_mail.assert_called_once()
        mail_module.save_mail_to_folder.assert_called_once()
        cache.delete.assert_called_once_with("undo_send:user@example.org:abc123")

    def test_skips_when_cancelled(self):
        """Pending entry gone (user cancelled) → no-op."""
        cache = MagicMock()
        cache.get.return_value = None

        with patch("app.service.sogo_cache", return_value=cache), \
             patch("app.module.mail.ModuleMailOutgoing.ModuleMailOutgoing") as outgoing_cls:
            result = _process()

        assert result["status"] == "skipped"
        outgoing_cls.assert_not_called()
        cache.delete.assert_not_called()

    def test_skips_and_cleans_corrupt_payload(self):
        """Corrupt pending payload → entry deleted, no send."""
        cache = MagicMock()
        cache.get.return_value = "{not-json"

        with patch("app.service.sogo_cache", return_value=cache), \
             patch("app.module.mail.ModuleMailOutgoing.ModuleMailOutgoing") as outgoing_cls:
            result = _process()

        assert result["status"] == "skipped"
        outgoing_cls.assert_not_called()
        cache.delete.assert_called_once_with("undo_send:user@example.org:abc123")

    def test_keeps_entry_on_delivery_failure_for_retry(self):
        """Delivery raises → entry kept so the agent retry can pick it up."""
        cache = MagicMock()
        cache.get.return_value = _pending_payload()
        outgoing = MagicMock()
        outgoing.send_mail.side_effect = RuntimeError("smtp down")

        with patch("app.service.sogo_cache", return_value=cache), \
             patch("app.auth.User.User.init_from_user_session", return_value=MagicMock()), \
             patch("app.config.init_config.init_get_user_domain_settings", return_value={"MAIL_SETTINGS": {}}), \
             patch("app.module.user.ModuleUserProfile.ModuleUserProfile"), \
             patch("app.config.settings.DomainSettings.MailSettingsObj"), \
             patch("app.module.mail.ModuleMailOutgoing.ModuleMailOutgoing", return_value=outgoing), \
             pytest.raises(RuntimeError):
            _process()

        cache.delete.assert_not_called()
