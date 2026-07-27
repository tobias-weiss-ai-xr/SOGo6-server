"""Schedule Send — delivers an email at a future time.

Triggered when the user sets ``send_at`` on ``POST /mail/send``. The job is
enqueued with ``eta=send_at`` so Celery delivers it at (or soon after) that
timestamp.

The job payload mirrors the fields that ``InterfaceApiMailSend._execute_send``
needs: ``account_id``, ``mail_data``, ``extra_headers``, ``tmp_draft_key``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar

from app.agent.jobs.Job import Job, agent_job
from app.agent.jobs.JobRequest import JobRequest
from app.module.mail.ModuleMail import ModuleMail
from app.manager.mail.ClientImap import RequestException
from app.interface.mail.InterfaceApiMailSend import InterfaceApiMailSend
from app.config.settings.ProcessSetting import ProcessSetting
from app.config.settings.DomainSettings import MailSettingsObj
from app.auth.User import AnonymousUser
from app.utils.logger.logger import logger_agent
from app.utils import errors as err


class ScheduleSendRequest(JobRequest):
    """Request to deliver an email that was scheduled for later delivery.

    .. code: python

        req = ScheduleSendRequest(
            account_id="0",
            mail_data={...},
            extra_headers=None,
            tmp_draft_key=None,
        )
        agent.start(req)
    """
    name: ClassVar[str] = "schedule_send"
    max_try: ClassVar[int] = 3
    soft_timeout_seconds: ClassVar[int] = 120
    max_concurrent: ClassVar[int] = 0  # Allow multiple scheduled sends

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
    """Deliver a scheduled email by calling ``_execute_send``."""

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

        # Build minimal process/domain settings from the payload (set at enqueue time)
        # In production these would come from the user's session — for async delivery
        # we reconstruct them from stored context.
        process_settings = ProcessSetting()
        mail_settings = MailSettingsObj()

        # Create a lightweight interface that can execute the send
        # We reuse InterfaceApiMailSend._execute_send by setting up the
        # minimal required context.
        from flask import g
        from app.auth.User import User

        # Build anonymous user with the scheduling metadata
        user = AnonymousUser()
        user.uid = mail_data.get("from", "scheduled@localhost")
        user.login_mail_server = mail_data.get("from", "")

        # We need the mail module to call _execute_send
        module_mail = ModuleMail(
            process_settings=process_settings,
            mail_settings=mail_settings,
            user=user,
        )

        interface = InterfaceApiMailSend(
            process_settings=process_settings,
            user_domain={},
            user=user,
        )

        # Remove send_at before forwarding to _execute_send (it has already been consumed)
        mail_data.pop("send_at", None)

        result, status = interface._execute_send(
            account_id, mail_data, extra_headers, tmp_draft_key,
        )

        logger_agent.info(
            "ScheduleSendJob: delivery complete (account=%s, status=%s)",
            account_id, status,
        )
        return {"status": status, "result": result}
