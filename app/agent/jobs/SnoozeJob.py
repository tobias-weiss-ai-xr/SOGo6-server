"""Snooze Job — restores snoozed emails when their snooze_until time arrives.

Periodically checks the ``sogo6_snoozed`` table for records whose
``snooze_until <= now``. For each due record, the mail is conceptually
restored (in this implementation, the snooze record is removed and the
caller is expected to handle IMAP folder movement).

In a production deployment, this job would be triggered by Celery Beat
on a short interval (e.g., every 60 seconds).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar

from app.agent.jobs.Job import Job, agent_job
from app.agent.jobs.JobRequest import JobRequest
from app.utils.logger.logger import logger_agent


class SnoozeCheckRequest(JobRequest):
    """Periodic check for due snooze records.

    No payload needed — the job queries the DB directly.
    """
    name: ClassVar[str] = "snooze_check"
    max_try: ClassVar[int] = 3
    soft_timeout_seconds: ClassVar[int] = 60
    max_concurrent: ClassVar[int] = 1  # Only one snooze processor at a time


@agent_job
class SnoozeJob(Job):
    """Process due snooze records.

    Finds all snooze entries whose ``snooze_until`` has passed and
    removes them from the database. The IMAP folder restoration is
    handled by the UI client (which polls the snooze list and performs
    the IMAP COPY operation when a snooze disappears).
    """
    request_class = SnoozeCheckRequest

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Check and process due snooze records."""
        now = datetime.now(timezone.utc)

        # Import lazily to avoid circular dependencies at module load
        from app.config.settings.ProcessSetting import process_config
        from app.utils.module.importManager import import_and_instantiate_manager
        from app.module.mail.ModuleSnooze import ModuleSnooze

        db = import_and_instantiate_manager(
            module_path="app.manager.db",
            module_and_class_name=f"Client{process_config.SOGO_P_DB_TYPE}",
            module_args=process_config.get_db_settings(),
        )
        db.connect()

        module = ModuleSnooze(db)
        due = module.list_due(now)

        processed = 0
        for record in due:
            try:
                module.remove_record(record["id"])
                logger_agent.info(
                    "SnoozeJob: restored mail %s for user %s (was due at %s)",
                    record["mail_uid"],
                    record["user_uid"],
                    record["snooze_until"],
                )
                processed += 1
            except Exception as exc:
                logger_agent.error(
                    "SnoozeJob: failed to restore mail %s for user %s: %s",
                    record["mail_uid"],
                    record["user_uid"],
                    exc,
                )

        if processed > 0:
            logger_agent.info("SnoozeJob: processed %d due snooze(s)", processed)

        return {"processed": processed, "checked_at": now.isoformat()}
