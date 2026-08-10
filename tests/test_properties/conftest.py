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

    with patch("app.interface.mail.InterfaceApiMailSend.ClientAgent") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.enqueue.return_value = "job-uuid-fuzz"
        mock_agent_cls.return_value = mock_agent
        yield iface
