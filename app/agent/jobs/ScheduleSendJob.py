"""Schedule Send — delivers an email at a future time.

Triggered when the user sets ``send_at`` on ``POST /mail/send``. The job is
enqueued with ``eta=send_at`` so Celery delivers it at (or soon after) that
timestamp.

The job payload stores every field that ``InterfaceApiMailSend.send_mail``
extracted before the scheduling decision: ``account_id``, ``mail_data``,
``extra_headers``, ``tmp_draft_key``.
"""
from __future__ import annotations

from typing import Any, ClassVar

from app.agent.jobs.Job import Job, agent_job
from app.agent.jobs.JobRequest import JobRequest
from app.config.settings.DomainSettings import MailSettings, MailSettingsObj
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

    def __init__(self, account_id: str, mail_data: dict, extra_headers: dict | None,
                 tmp_draft_key: str | None, user_session: dict | None = None,
                 login_mail_outgoing: str | None = None):
        self.account_id = account_id
        self.mail_data = mail_data
        self.extra_headers = extra_headers
        self.tmp_draft_key = tmp_draft_key
        # Needed by the worker to rebuild the user (no request context there)
        self.user_session = user_session or {}
        self.login_mail_outgoing = login_mail_outgoing

    def payload(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "mail_data": self.mail_data,
            "extra_headers": self.extra_headers,
            "tmp_draft_key": self.tmp_draft_key,
            "user_session": self.user_session,
            "login_mail_outgoing": self.login_mail_outgoing,
        }


@agent_job
class ScheduleSendJob(Job):
    """Deliver a scheduled email by calling the outgoing mail module directly."""

    request_class = ScheduleSendRequest

    def process(
        self, payload: dict[str, Any], *, user_uid: str | None = None, job_id: str = "",
    ) -> dict[str, Any]:
        account_id: str = payload["account_id"]
        mail_data: dict = payload["mail_data"]
        extra_headers: dict | None = payload.get("extra_headers")
        _ = payload.get("tmp_draft_key")

        logger_agent.info(
            "ScheduleSendJob: delivering scheduled mail (account=%s, subject=%s)",
            account_id, mail_data.get("subject", ""),
        )

        # Ensure send_at is stripped (should already be removed by the caller)
        mail_data.pop("send_at", None)

        # Rebuild the user the same way an authenticated request would — the
        # agent worker has no request context (see UndoSendJob).
        from app.auth.User import User
        from app.config.init_config import init_get_user_domain_settings
        from app.module.user.ModuleUserProfile import ModuleUserProfile

        user = User.init_from_user_session(payload.get("user_session") or {})
        if payload.get("login_mail_outgoing"):
            user.login_mail_outgoing = payload["login_mail_outgoing"]

        process_settings = ProcessSetting()
        domain_settings = init_get_user_domain_settings(user)
        ModuleUserProfile(process_settings, domain_settings).get_user_profile(user)
        mail_settings = MailSettingsObj(domain_settings[MailSettings.subparent])

        outgoing = ModuleMailOutgoing(user, mail_settings)
        message = outgoing.send_mail(account_id, mail_data, extra_headers=extra_headers)

        logger_agent.info(
            "ScheduleSendJob: delivery complete (account=%s, uid=%s)",
            account_id, message.get("uid", "?"),
        )
        return {"status": "sent", "uid": message.get("uid", "")}
