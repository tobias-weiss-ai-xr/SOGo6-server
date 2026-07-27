"""Agent job modules — each file decorated with @agent_job is auto-discovered.

Importing a module here causes its @agent_job decorator to fire and register
the class in _AGENT_JOB_CLASSES so that Agent.register_all_job_handlers picks
it up at boot.
"""
from app.agent.jobs import JobCanceller  # noqa: F401
from app.agent.jobs import JobRecovery  # noqa: F401
from app.agent.jobs import ScheduleSendJob  # noqa: F401
