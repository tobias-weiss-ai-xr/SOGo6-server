"""Regression: GET /external-calendars must list ALL external subscription
types (ICS and CalDAV), not only plain-ICS ones.

Historical bug: ApiExternalCalendarList.get() hardcoded
``source_type="ics"``, silently hiding CalDAV rows (e.g. the calrs booking
mirror subscription) from the list endpoint. The interface's
``get_all_calendars()`` treats ``None`` as "no filter — return everything".
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask, g

from app.api.v1.calendar.ApiCalendar import blp as calendar_blp


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(calendar_blp)

    @app.before_request
    def _user_and_inter():
        g.user = SimpleNamespace(uid="u1", email="u1@example.com", is_admin=True)
        # ApiCalendar handlers read g.inter (the interface instance). The mock
        # is injected per-test via patch below; this just creates a placeholder.
        g.process_settings = {}
        g.user_domain_settings = {}

    return app


@pytest.fixture
def client(app):
    return app.test_client()


@patch("app.api.v1.calendar.ApiCalendar.InterfaceApiCalendarCalendar")
def test_external_calendars_lists_all_source_types(mock_inter_cls, app, client):
    """The list endpoint must request source_type=None (all types)."""
    mock_inter = mock_inter_cls.return_value

    ics_row = {
        "key": "k-ics",
        "name": "Public ICS",
        "source_type": "ics",
        "url": "https://example.com/test.ics",
        "sync_status": "idle",
    }
    caldav_row = {
        "key": "k-caldav",
        "name": "calrs (Public Calendar)",
        "source_type": "caldav",
        "url": "https://calendar.example/dav/booking/main/",
        "sync_status": "idle",
    }
    mock_inter.get_all_calendars.return_value = {
        "data": {"calendars": [ics_row, caldav_row], "total_count": 2},
        "error": None,
    }

    resp = client.get("/external-calendars")
    assert resp.status_code == 200
    body = resp.get_json()

    # The fix: the interface is called with NO source_type filter (None),
    # so CalDAV rows are no longer hidden.
    called_kwargs = mock_inter.get_all_calendars.call_args
    assert called_kwargs is not None
    kw = called_kwargs.kwargs
    if called_kwargs.args:
        kw["source_type"] = called_kwargs.args[0]
    assert kw.get("source_type") is None, (
        f"expected source_type=None (all types), got {kw.get('source_type')!r}"
    )

    data = body["data"]
    assert data["total_count"] == 2
    types = {c["source_type"] for c in data["calendars"]}
    assert types == {"ics", "caldav"}


@patch("app.api.v1.calendar.ApiCalendar.InterfaceApiCalendarCalendar")
def test_external_calendars_detail_get_by_key(mock_inter_cls, app, client):
    """Detail lookup still works for a CalDAV subscription."""
    mock_inter = mock_inter_cls.return_value
    mock_inter.get_calendar.return_value = {
        "data": {
            "key": "k-caldav",
            "name": "calrs (Public Calendar)",
            "source_type": "caldav",
        },
        "error": None,
    }

    resp = client.get("/external-calendars/k-caldav")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["source_type"] == "caldav"
    assert data["name"] == "calrs (Public Calendar)"
