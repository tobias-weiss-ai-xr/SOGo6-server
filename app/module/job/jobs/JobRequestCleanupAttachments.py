"""Request for the attachment cleanup job.

This defines the job request that will be enqueued for periodic cleanup
 of expired temporary attachment files.
"""
from __future__ import annotations

from typing import Any, ClassVar

from app.agent.jobs.JobRequest import JobRequest


class JobRequestCleanupAttachments(JobRequest):
    """Request to clean up expired temporary attachments.
    
    This is a system job (no user context) that runs periodically via Celery Beat.
    It cleans up:
    1. Temporary attachment files older than 24 hours
    2. Orphaned Redis keys for attachments that no longer exist on disk
    
    The job runs every hour as configured by the cron expression.
    
    Example usage:
        from app.service import sogo_agent
        from app.module.job.jobs.JobRequestCleanupAttachments import JobRequestCleanupAttachments
        
        # Manual triggering (rarely needed)
        req = JobRequestCleanupAttachments()
        job_id = sogo_agent().enqueue(req)
    """

    name: ClassVar[str] = "cleanup_attachments"
    max_try: ClassVar[int] = 1
    soft_timeout_seconds: ClassVar[int] = 300  # 5 minutes
    max_concurrent: ClassVar[int] = 1  # Only one cleanup at a time
    cron: ClassVar[str | None] = "0 * * * *"  # Every hour at minute 0
    resume: ClassVar[bool] = False  # Don't resume failed cleanups
    retry_for: ClassVar[tuple[type[Exception], ...]] = ()  # No retries for cleanup

    def __init__(self) -> None:
        """Initialize the cleanup request. No parameters needed."""
        pass

    def payload(self) -> dict[str, Any]:
        """Return the payload for the cleanup job.
        
        :return: Empty dict as no specific data is needed.
        :rtype: dict[str, Any]
        """
        return {}
