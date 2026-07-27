"""Schedule Send — delivers an email at a future time.

Triggered when the user sets ``send_at`` on ``POST /mail/send``. The job is
enqueued with ``eta=send_at`` so Celery delivers it at (or soon after) that
timestamp.

The job payload stores every field that ``InterfaceApiMailSend.send_mail``
extracted before the scheduling decision: ``account_id``, ``mail_data``,
``extra_headers``, ``tmp_draft_key``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar

from app.agent.jobs.Job import Job, agent_job
from app.agent.jobs.JobRequest import JobRequest
from app.config.settings.DomainSettings import MailSettingsObj
from app.config.settings.ProcessSetting import ProcessSetting
from app.module.mail.ModuleMailOutgoing import ModuleMailOutgoing
from app.utils.logger.logger import logger_agent


class ScheduleSendRequest(JobRequest):
    """Request to deliver an email that was scheduled for later delivery.

    .. code:: python

        req = ScheduleSendRequest(
            account_id="0",
            mail_data={...},
            extra_headers=None,
            tmp_draft_key=None,
        )
        agent.enqueue(req, eta=send_at_dt)
    """
    name: ClassVar[str] = "schedule_send"
    max_try: ClassVar[int] = 3
    soft_timeout_seconds: ClassVar[int] = 120
    max_concurrent: ClassVar[int] = 0  # Allow multiple concurrent scheduled sends

    account_id: str
    mail_data: dict
    extra_headers: dict | None
    tmp_draft_key: str | None

    def payload(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "mail_data": self.mail_data,
            "extra_headers": self.extra_headers,
            "tmp_draft_key": self.tmp_draft_key,
        }


@agent_job
class ScheduleSendJob(Job):
    """Deliver a scheduled email by calling the outgoing mail module directly."""

    request_class = ScheduleSendRequest

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        account_id: str = payload["account_id"]
        mail_data: dict = payload["mail_data"]
        extra_headers: dict | None = payload.get("extra_headers")
        tmp_draft_key: str | None = payload.get("tmp_draft_key")

        logger_agent.info(
            "ScheduleSendJob: delivering scheduled mail (account=%s, subject=%s)",
            account_id, mail_data.get("subject", ""),
        )

        # Ensure send_at is stripped (should already be removed by the caller)
        mail_data.pop("send_at", None)

        # Build minimal process & mail settings for sending
        process_settings = ProcessSetting()
        mail_settings = MailSettingsObj()

        outgoing = ModuleMailOutgoing(
            process_settings=process_settings,
            mail_settings=mail_settings,
        )
        message = outgoing.send_mail(account_id, mail_data, extra_headers=extra_headers)

        logger_agent.info(
            "ScheduleSendJob: delivery complete (account=%s, uid=%s)",
            account_id, message.get("uid", "?"),
        )
        return {"status": "sent", "uid": message.get("uid", "")}
