"""Undo Send — delivers a pending email after the Undo Send grace period.

Triggered when a user sends an email with Undo Send enabled
(``SOGO_U_UNDO_SEND_SECONDS > 0``): ``InterfaceApiMailSend.send_mail`` stores
the full send context in Redis under ``undo_send:{uid}:{pending_key}`` with a
TTL slightly longer than the grace period, and enqueues this job with
``eta = now + undo_seconds``.

At execution time the job re-reads the pending entry:

* if it is **gone** (the user cancelled via ``cancel_pending_send``, or the
  Redis TTL expired as a safety net) the job does nothing — the email was
  intentionally not sent;
* if it is **still present** the email is delivered through
  ``ModuleMailOutgoing`` (same code path as an immediate send), the Sent
  folder is updated and the tmp_draft is cleaned up, then the Redis entry is
  deleted so a retry (at-least-once delivery) never double-sends.

The user is rebuilt from the session data stored in the pending payload so the
outgoing module has the correct SMTP credentials / external accounts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar

from app.agent.jobs.Job import Job, agent_job
from app.agent.jobs.JobRequest import JobRequest
from app.config.settings.DomainSettings import MailSettings, MailSettingsObj
from app.config.settings.ProcessSetting import ProcessSetting
from app.utils.logger.logger import logger_agent

# Same prefix as InterfaceApiMailSend — infra invariant, keep in sync.
_PENDING_SEND_PREFIX: str = "undo_send:"


class UndoSendRequest(JobRequest):
    """Request to deliver a pending email once the Undo Send window elapsed.

    .. code:: python

        req = UndoSendRequest(user_uid="user@example.org", pending_key="…")
        agent.enqueue(req, user_uid=user_uid, eta=now + timedelta(seconds=undo_seconds))
    """
    name: ClassVar[str] = "undo_send"
    max_try: ClassVar[int] = 3
    soft_timeout_seconds: ClassVar[int] = 120
    max_concurrent: ClassVar[int] = 0  # Multiple pending sends may coexist

    def __init__(self, user_uid: str, pending_key: str):
        self.user_uid = user_uid
        self.pending_key = pending_key

    def payload(self) -> dict[str, Any]:
        return {
            "user_uid": self.user_uid,
            "pending_key": self.pending_key,
        }


@agent_job
class UndoSendJob(Job):
    """Deliver a pending email after the undo window expires (if not cancelled)."""

    request_class = UndoSendRequest

    def process(
        self, payload: dict[str, Any], *, user_uid: str | None, job_id: str,
    ) -> dict[str, Any]:
        pending_key: str = payload["pending_key"]
        owner_uid: str = payload.get("user_uid") or user_uid or ""
        redis_key: str = f"{_PENDING_SEND_PREFIX}{owner_uid}:{pending_key}"

        # Import lazily to avoid circular imports at module load.
        from app.service import sogo_cache
        from app.config.init_config import init_get_user_domain_settings
        from app.auth.User import User
        from app.module.mail.ModuleMail import ModuleMail
        from app.module.mail.ModuleMailOutgoing import ModuleMailOutgoing
        from app.module.user.ModuleUserProfile import ModuleUserProfile
        from app.utils import constants as cs

        cache = sogo_cache()
        raw: str | None = cache.get(redis_key, str)
        if raw is None:
            logger_agent.info(
                "UndoSendJob: pending send %s for %s no longer exists — cancelled or expired, skipping",
                pending_key, owner_uid,
            )
            return {"status": "skipped", "reason": "cancelled"}

        import json
        try:
            pending: dict = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger_agent.warning(
                "UndoSendJob: corrupt pending payload for %s, deleting entry", pending_key,
            )
            cache.delete(redis_key)
            return {"status": "skipped", "reason": "corrupt"}

        account_id: str = pending.get("account_id", "0")
        mail_data: dict = pending.get("mail_data", {})
        extra_headers: dict | None = pending.get("extra_headers")
        tmp_draft_key: str | None = pending.get("tmp_draft_key")
        user_session: dict = pending.get("user_session", {})
        login_mail_outgoing: str | None = pending.get("login_mail_outgoing")

        # Rebuild the user the same way an authenticated request would.
        user = User.init_from_user_session(user_session)
        user.login_mail_outgoing = login_mail_outgoing or user.mail

        process_settings = ProcessSetting()
        domain_settings = init_get_user_domain_settings(user)
        ModuleUserProfile(process_settings, domain_settings).get_user_profile(user)

        mail_settings = MailSettingsObj(domain_settings[MailSettings.subparent])

        logger_agent.info(
            "UndoSendJob: delivering pending mail (account=%s, subject=%s)",
            account_id, mail_data.get("subject", ""),
        )
        mail_data.pop("send_at", None)

        outgoing = ModuleMailOutgoing(user, mail_settings)
        try:
            message = outgoing.send_mail(account_id, mail_data, extra_headers=extra_headers)
        except Exception as exc:  # noqa: BLE001 — retried by the agent for transient errors
            logger_agent.error("UndoSendJob: delivery failed for %s: %s", pending_key, repr(exc))
            # Keep the Redis entry so a retry can pick it up again.
            raise

        # Mirror the immediate-send path: save to Sent and clean the tmp_draft.
        try:
            mail_module = ModuleMail(user, mail_settings, process_settings)
            mail_module.save_mail_to_folder(account_id, message, cs.MAIL_FOLDER_SENT)
            if tmp_draft_key is not None:
                mail_module.delete_tmp_draft(tmp_draft_key, account_id)
        except Exception as exc:  # noqa: BLE001 — best-effort bookkeeping
            logger_agent.warning("UndoSendJob: post-send bookkeeping failed for %s: %s", pending_key, repr(exc))

        # Delete the pending entry — a retry must not double-send.
        cache.delete(redis_key)

        logger_agent.info(
            "UndoSendJob: delivery complete (account=%s, uid=%s)",
            account_id, message.get("uid", "?"),
        )
        return {"status": "sent", "uid": message.get("uid", ""), "at": datetime.now(timezone.utc).isoformat()}
