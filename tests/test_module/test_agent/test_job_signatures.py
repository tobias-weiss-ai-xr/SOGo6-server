"""
Contract tests for agent job handlers.

Regression context (2026-08-30): ScheduleSendJob.process kept an outdated
signature ``(self, payload)`` while the base class and the agent runtime call
``process(payload, user_uid=..., job_id=...)`` — every scheduled send failed
with ``TypeError ... unexpected keyword argument 'user_uid'`` after 3 retries,
silently dropping the email. These tests pin the contract so signature drift
fails in CI instead of in production.
"""
import inspect

import pytest

from app.agent.jobs.Job import Job


def _all_job_classes() -> list[type[Job]]:
    """Collect every @agent_job-registered class."""
    from app.agent.jobs.Job import collected_agent_class_jobs

    return collected_agent_class_jobs()


def test_every_job_process_signature_matches_base_class():
    assert _all_job_classes(), "no agent jobs collected — collector broken?"
    base_params = list(inspect.signature(Job.process).parameters)
    for cls in _all_job_classes():
        params = list(inspect.signature(cls.process).parameters)
        missing = set(base_params) - set(params)
        assert not missing, (
            f"{cls.__name__}.process is missing parameters {sorted(missing)} — "
            f"the agent calls process(payload, user_uid=..., job_id=...) and "
            f"would raise TypeError at runtime"
        )


def test_schedule_send_job_accepts_runtime_kwargs():
    from app.agent.jobs.ScheduleSendJob import ScheduleSendJob

    sig = inspect.signature(ScheduleSendJob.process)
    call = sig.bind(self=None, payload={})  # positional self+payload must bind
    call.apply_defaults()
    assert "user_uid" in call.arguments
    assert "job_id" in call.arguments


def test_snooze_job_accepts_runtime_kwargs():
    from app.agent.jobs.SnoozeJob import SnoozeJob

    sig = inspect.signature(SnoozeJob.process)
    call = sig.bind(self=None, payload={})
    call.apply_defaults()
    assert "user_uid" in call.arguments
    assert "job_id" in call.arguments


def test_schedule_send_request_payload_carries_user_context():
    from app.agent.jobs.ScheduleSendJob import ScheduleSendRequest

    req = ScheduleSendRequest(
        account_id="0",
        mail_data={"subject": "x"},
        extra_headers=None,
        tmp_draft_key=None,
        user_session={"uid": "user@example.org"},
        login_mail_outgoing="user@example.org",
    )
    payload = req.payload()
    # regression: without the user session the worker cannot rebuild the user
    # and ModuleMailOutgoing(user, ...) would receive process settings instead
    assert payload["user_session"] == {"uid": "user@example.org"}
    assert payload["login_mail_outgoing"] == "user@example.org"
