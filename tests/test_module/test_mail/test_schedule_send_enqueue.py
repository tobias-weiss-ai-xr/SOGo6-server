"""
Regression: scheduled send must enqueue its agent job WITH an owner.

Bug (2026-08-30): ``InterfaceApiMailSend.send_mail`` enqueued
``ScheduleSendRequest`` without ``user_uid``, so the persisted JobState had
``user_uid=None``. Consequences:
  - ``GET /jobs/<id>`` answered 403 S000801 "Job Does Not Belong To Current
    User" for the very user who scheduled the send (polling broken for
    clients), and
  - the job never appeared in the user's job list.

The Undo Send path already passed ``user_uid=self.user.uid`` — this pins the
same contract for the scheduled path.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.interface.mail.InterfaceApiMailSend import InterfaceApiMailSend


class _DummyUser:
    uid = "user@example.org"
    mail = "user@example.org"
    login_mail_outgoing = "user@example.org"

    def get_user_session(self):
        return {"uid": self.uid}


def _future_iso() -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()


@pytest.fixture()
def interface() -> InterfaceApiMailSend:
    inter = InterfaceApiMailSend.__new__(InterfaceApiMailSend)
    inter.user = _DummyUser()
    return inter


def test_scheduled_send_enqueues_job_with_owner(interface):
    """The scheduled branch must pass user_uid so the job is owned by the caller."""
    agent = MagicMock()
    agent.enqueue.return_value = "job-1"
    with patch("app.interface.mail.InterfaceApiMailSend.sogo_agent", return_value=agent), \
         patch("app.interface.mail.InterfaceApiMailSend.create_api_base_response") as resp:
        resp.side_effect = lambda data, code=200: (data, code)
        data, _ = interface.send_mail("0", {
            "from": "user@example.org",
            "to": ["other@example.org"],
            "subject": "later",
            "body": "hi",
            "send_at": _future_iso(),
        })
    assert data == {"status": "scheduled", "job_id": "job-1", "scheduled_at": data["scheduled_at"]}
    _, kwargs = agent.enqueue.call_args
    assert kwargs.get("user_uid") == "user@example.org", (
        "schedule_send must be enqueued with user_uid — without it the "
        "JobState has no owner and GET /jobs/<id> returns 403 S000801"
    )
