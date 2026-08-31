"""Attachment cleanup job implementation.

This job runs hourly to clean up expired temporary attachment files and
orphaned Redis metadata keys.
"""
from __future__ import annotations

from typing import Any, ClassVar

from app.agent.jobs.Job import Job, agent_job
from app.agent.jobs.JobRequest import JobRequest
from app.service import sogo_cache
from app.utils.logger.logger import logger_agent

from .JobRequestCleanupAttachments import JobRequestCleanupAttachments


@agent_job
class JobCleanupAttachments(Job):
    """Job that cleans up expired temporary attachment files and orphaned Redis keys.
    
    This is a system-level job (user_uid=None) that runs periodically via Celery Beat.
    It performs:
    1. Deletion of temporary attachment files older than 24 hours
    2. Removal of Redis keys for attachments that no longer exist on disk
    
    The job is idempotent and safe to run concurrently (though max_concurrent=1
    prevents overlap by design).
    """

    request_class = JobRequestCleanupAttachments

    def process(
        self, payload: dict[str, Any], *, user_uid: str | None = None, job_id: str = "",
    ) -> dict[str, Any]:
        """Execute the attachment cleanup job.
        
        :param payload: Job payload (empty dict for this job).
        :type payload: dict[str, Any]
        :param user_uid: Owner of the job. Should be None for system jobs.
        :type user_uid: str | None
        :param job_id: Celery job ID for logging.
        :type job_id: str
        :return: Dictionary with cleanup statistics.
        :rtype: dict[str, Any]
        """
        logger_agent.info(
            "JobCleanupAttachments: starting cleanup job (job_id=%s, user_uid=%s)",
            job_id, user_uid,
        )
        
        # Get Redis client
        cache_client = sogo_cache()
        
        # Create cleanup interface
        from app.interface.job.InterfaceJobCleanup import InterfaceJobCleanup
        cleanup_interface = InterfaceJobCleanup(cache_client)
        
        # Run cleanup
        result = cleanup_interface.cleanup_all()
        
        logger_agent.info(
            "JobCleanupAttachments: completed with %d files deleted, %d keys deleted, %d errors",
            result.get("files_deleted", 0),
            result.get("keys_deleted", 0),
            len(result.get("errors", [])),
        )
        
        return result
