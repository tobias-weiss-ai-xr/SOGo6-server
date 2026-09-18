"""Fixtures for property-based tests.

Uses the shared helpers from ``tests.helpers`` so contract tests
don't duplicate mail-interface mock setup code.
"""

from unittest.mock import patch, MagicMock

import pytest

from tests.helpers import make_mail_iface


@pytest.fixture
def mail_iface():
    """Provide a mocked InterfaceApiMailSend for property-based fuzzing.

    The outgoing module returns a success by default so we can test
    envelope conformance regardless of mail content. The Celery agent
    is mocked to accept schedule-send jobs.
    """
    iface = make_mail_iface(undo_seconds=0)

    # InterfaceApiMailSend calls sogo_agent() (module-imported) for the
    # schedule/undo paths — NOT a ClientAgent attribute (stale patch target;
    # the class lives in app.manager.agent and is only referenced there).
    with patch("app.interface.mail.InterfaceApiMailSend.sogo_agent") as mock_agent_fn:
        mock_agent = MagicMock()
        mock_agent.enqueue.return_value = "job-uuid-fuzz"
        mock_agent_fn.return_value = mock_agent
        yield iface
