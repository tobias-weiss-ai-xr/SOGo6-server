"""Job implementations for the job module.

Each job file decorated with @agent_job is auto-discovered and
registered with Celery at startup.
"""
from __future__ import annotations

from app.module.job.jobs import JobCleanupAttachments  # noqa: F401
from app.module.job.jobs import JobRequestCleanupAttachments  # noqa: F401

__all__ = ["JobCleanupAttachments", "JobRequestCleanupAttachments"]
