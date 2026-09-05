import pytest
import json
import dataclasses
from flask import Flask, g
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from datetime import datetime

from app.api.v1.calendar.ApiInvitation import blp as invitation_blp
from app.api.v1.calendar.ApiTeamCalendar import blp as team_blp
from app.api.v1.user.ApiSmartCalendar import blp as smart_blp
from app.module.calendar.imip.ImipProcessor import ImipProcessor
from app.module.calendar.imip.ImipMethod import ImipMethod
from app.module.calendar.imip.ImipMessage import ImipMessage
from app.module.calendar.model.CalEvent import CalEvent
from app.module.calendar.model.CalAttendee import CalAttendee
from app.utils.exceptions import RequestException
from app.utils.errors import (
    ERROR_CALENDAR_EVENT_NOT_FOUND,
    ERROR_CALENDAR_NOT_ORGANIZER,
    ERROR_SMTP_CONNECTION_FAILED,
    ERROR_NOT_FOUND,
    ERROR_CALENDAR_ICS_PARSE_FAILED,
    ERROR_CALENDAR_IMIP_INVALID_REQUEST,
    ERROR_CALENDAR_IMIP_SENDER_MISMATCH,
    ERROR_CALENDAR_NOT_SUPPORTED,
    ERROR_CALENDAR_EVENT_INSERT_FAILED,
)

class FakeCache:
    def __init__(self): self._d = {}
    def get(self, key, as_type=None): 
        return self._d.get(key)
    def set(self, key, value, ttl=None): self._d[key] = value
    def delete(self, key): return self._d.pop(key, None) is not None
    def __contains__(self, key): return key in self._d

CACHE = FakeCache()

@pytest.fixture(autouse=True)
def _cache_mock(monkeypatch):
    monkeypatch.setattr("app.api.v1.user.ApiSmartCalendar.sogo_cache", lambda: CACHE)
    yield
    CACHE._d = {}

@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(invitation_blp)
    app.register_blueprint(team_blp)
    app.register_blueprint(smart_blp)

    @app.before_request
    def _user():
        g.user = SimpleNamespace(uid="u1", email="u1@example.com", is_admin=True)
        g.process_settings = {}
        g.user_domain_settings = {}

    return app

@pytest.fixture
def client(app): return app.test_client()

def check_error(res_json, error_obj):
    """Helper to check if the response contains the expected error object's code.
    Error objects (class E) use .c for the code.
    """
    return res_json.get("error_code") == error_obj.c

# --- ApiInvitation Tests ---

def test_api_invitation_post_success(client):
    with patch("app.api.v1.calendar.ApiInvitation.InterfaceApiCalendarCalendar") as mock_inter_cls, \
         patch("app.api.v1.calendar.ApiInvitation.ModuleMailOutgoing") as mock_mailer_cls, \
         patch("app.api.v1.calendar.ApiInvitation.ImipBuilder") as mock_builder:
        
        mock_inter = mock_inter_cls.return_value
        mock_event = MagicMock(spec=CalEvent)
        mock_event.organizer = "u1@example.com"
        mock_event.attendees = [{"email": "a1@example.com"}, {"email": "a2@example.com"}]
        mock_event.uid = "ev1"
        mock_event.title = "Meeting"
        mock_event.description = None
        mock_event.location = None
        mock_event.url = None
        mock_event.sequence = 1
        mock_event.priority = None
        mock_inter.get_event.return_value = ({"data": {"event": "data"}}, 200)
        
        with patch("app.api.v1.calendar.ApiInvitation.CalEventDeserializerDict") as mock_deser_cls:
            mock_deser_cls.return_value.deserialize.return_value = mock_event
            mock_imip = ImipMessage(
                method=ImipMethod.REQUEST, 
                event=mock_event, 
                to_emails=["a1@example.com", "a2@example.com"],
                from_email="u1@example.com"
            )
            mock_builder.build_request.return_value = mock_imip
            resp = client.post("/calendars/c1/events/e1/invite")
            assert resp.status_code == 200
            assert "invited" in resp.get_json()["data"]

def test_api_invitation_post_not_organizer(client):
    with patch("app.api.v1.calendar.ApiInvitation.InterfaceApiCalendarCalendar") as mock_inter_cls, \
         patch("app.api.v1.calendar.ApiInvitation.ImipBuilder") as mock_builder:
        mock_inter = mock_inter_cls.return_value
        mock_event = MagicMock(spec=CalEvent)
        mock_event.organizer = None # Trigger ERROR_CALENDAR_NOT_ORGANIZER
        mock_event.attendees = [{"email": "a1@example.com"}]
        mock_inter.get_event.return_value = ({"data": {"event": "data"}}, 200)
        
        with patch("app.api.v1.calendar.ApiInvitation.CalEventDeserializerDict") as mock_deser_cls:
            mock_deser_cls.return_value.deserialize.return_value = mock_event
            mock_builder.build_request.return_value = None
            resp = client.post("/calendars/c1/events/e1/invite")
            assert resp.status_code == 403
            assert check_error(resp.get_json(), ERROR_CALENDAR_NOT_ORGANIZER)

def test_api_invitation_post_no_attendees(client):
    with patch("app.api.v1.calendar.ApiInvitation.InterfaceApiCalendarCalendar") as mock_inter_cls:
        mock_inter = mock_inter_cls.return_value
        mock_event = MagicMock(spec=CalEvent)
        mock_event.organizer = "u1@example.com"
        mock_event.attendees = []
        mock_inter.get_event.return_value = ({"data": {"event": "data"}}, 200)
        
        with patch("app.api.v1.calendar.ApiInvitation.CalEventDeserializerDict") as mock_deser_cls:
            mock_deser_cls.return_value.deserialize.return_value = mock_event
            resp = client.post("/calendars/c1/events/e1/invite")
            assert resp.status_code == 404
            assert check_error(resp.get_json(), ERROR_CALENDAR_EVENT_NOT_FOUND)

def test_api_invitation_post_mail_fail(client):
    with patch("app.api.v1.calendar.ApiInvitation.InterfaceApiCalendarCalendar") as mock_inter_cls, \
         patch("app.api.v1.calendar.ApiInvitation.ModuleMailOutgoing") as mock_mailer_cls, \
         patch("app.api.v1.calendar.ApiInvitation.ImipBuilder") as mock_builder:
        
        mock_inter = mock_inter_cls.return_value
        mock_event = MagicMock(spec=CalEvent)
        mock_event.organizer = "u1@example.com"
        mock_event.attendees = [{"email": "a1@example.com"}]
        mock_inter.get_event.return_value = ({"data": {"event": "data"}}, 200)
        
        with patch("app.api.v1.calendar.ApiInvitation.CalEventDeserializerDict") as mock_deser_cls:
            mock_deser_cls.return_value.deserialize.return_value = mock_event
            mock_imip = ImipMessage(
                method=ImipMethod.REQUEST, 
                event=mock_event, 
                to_emails=["a1@example.com"],
                from_email="u1@example.com"
            )
            mock_builder.build_request.return_value = mock_imip
            mock_mailer = mock_mailer_cls.return_value
            mock_mailer.send_raw_message.side_effect = Exception("SMTP fail")
            resp = client.post("/calendars/c1/events/e1/invite")
            assert resp.status_code == 503
            assert check_error(resp.get_json(), ERROR_SMTP_CONNECTION_FAILED)

def test_api_invitation_get_attendees(client):
    with patch("app.api.v1.calendar.ApiInvitation.InterfaceApiCalendarCalendar") as mock_inter_cls:
        mock_inter = mock_inter_cls.return_value
        mock_inter.get_event.return_value = ({"data": {"attendees": [{"email": "a1@example.com"}]}}, 200)
        resp = client.get("/calendars/c1/events/e1/attendees")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["total_count"] == 1

def test_api_invitation_put_attendee_success(client):
    with patch("app.api.v1.calendar.ApiInvitation.InterfaceApiCalendarCalendar") as mock_inter_cls:
        mock_inter = mock_inter_cls.return_value
        mock_inter.get_event.return_value = ({"data": {"attendees": [{"email": "a1@example.com", "status": "needs-action"}]}}, 200)
        mock_inter.patch_event.return_value = ({"data": {"status": "accepted"}}, 200)
        resp = client.put("/calendars/c1/events/e1/attendees/a1@example.com", json={"status": "accepted"})
        assert resp.status_code == 200

def test_api_invitation_put_attendee_not_found(client):
    with patch("app.api.v1.calendar.ApiInvitation.InterfaceApiCalendarCalendar") as mock_inter_cls:
        mock_inter = mock_inter_cls.return_value
        mock_inter.get_event.return_value = ({"data": {"attendees": [{"email": "a1@example.com"}]}}, 200)
        resp = client.put("/calendars/c1/events/e1/attendees/unknown@example.com", json={"status": "accepted"})
        assert resp.status_code == 404
        assert check_error(resp.get_json(), ERROR_NOT_FOUND)

# --- ApiTeamCalendar Tests ---

def test_api_team_calendar_crud(client):
    with patch("app.api.v1.calendar.ApiTeamCalendar.InterfaceApiTeamCalendar") as mock_inter_cls:
        mock_inter = mock_inter_cls.return_value
        mock_inter.list_team_calendars.return_value = ({"data": []}, 200)
        assert client.get("/calendars/teams").status_code == 200
        mock_inter.create_team_calendar.return_value = ({"data": {}}, 201)
        assert client.post("/calendars/teams", json={"name": "Test"}).status_code == 201
        mock_inter.get_team_calendar.return_value = ({"data": {}}, 200)
        assert client.get("/calendars/teams/t1").status_code == 200
        mock_inter.update_team_calendar.return_value = ({"data": {}}, 200)
        assert client.patch("/calendars/teams/t1", json={"name": "New"}).status_code == 200
        mock_inter.delete_team_calendar.return_value = ({"data": {}}, 200)
        assert client.delete("/calendars/teams/t1").status_code == 200

def test_api_team_calendar_members(client):
    with patch("app.api.v1.calendar.ApiTeamCalendar.InterfaceApiTeamCalendar") as mock_inter_cls:
        mock_inter = mock_inter_cls.return_value
        mock_inter.list_members.return_value = ({"data": []}, 200)
        assert client.get("/calendars/teams/t1/members").status_code == 200
        mock_inter.add_member.return_value = ({"data": {}}, 201)
        assert client.post("/calendars/teams/t1/members", json={"user_uid": "u2", "share_level": "view_all"}).status_code == 201
        mock_inter.update_member.return_value = ({"data": {}}, 200)
        assert client.patch("/calendars/teams/t1/members/u1", json={"share_level": "modify"}).status_code == 200
        mock_inter.remove_member.return_value = ({"data": {}}, 200)
        assert client.delete("/calendars/teams/t1/members/u1").status_code == 200

def test_api_team_calendar_invites(client):
    with patch("app.api.v1.calendar.ApiTeamCalendar.InterfaceApiTeamCalendar") as mock_inter_cls:
        mock_inter = mock_inter_cls.return_value
        mock_inter.invite_user.return_value = ({"data": {}}, 201)
        assert client.post("/calendars/teams/t1/invites", json={"user_uid": "u2", "share_level": "view_all"}).status_code == 201
        mock_inter.list_invites.return_value = ({"data": []}, 200)
        assert client.get("/calendars/teams/invites").status_code == 200
        mock_inter.get_invite.return_value = ({"data": {}}, 200)
        assert client.get("/calendars/teams/invites/i1").status_code == 200
        mock_inter.cancel_invite.return_value = ({"data": {}}, 200)
        assert client.delete("/calendars/teams/invites/i1").status_code == 200
        mock_inter.accept_invite.return_value = ({"data": {}}, 200)
        assert client.post("/calendars/teams/invites/i1/accept").status_code == 200
        mock_inter.reject_invite.return_value = ({"data": {}}, 200)
        assert client.post("/calendars/teams/invites/i1/reject").status_code == 200

# --- ApiSmartCalendar Tests ---

def test_api_smart_calendar_suggest(client):
    CACHE.set("sched_pattern:u2", json.dumps({"busy_hours": [10], "preferred_hours": [9]}))
    payload = {
        "attendee_uids": ["u2"],
        "date_from": "2023-10-01",
        "date_to": "2023-10-02",
        "duration_minutes": 60,
        "preferred_hours": [9, 10]
    }
    resp = client.post("/ai/smart-calendar/suggest-times", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert "suggestions" in data
    for s in data["suggestions"]:
        if s["hour"] == 10:
            assert "u2" in s["conflicts"]

def test_api_smart_calendar_suggest_invalid_date(client):
    payload = {"attendee_uids": ["u2"], "date_from": "invalid", "date_to": "2023-10-02"}
    resp = client.post("/ai/smart-calendar/suggest-times", json=payload)
    assert resp.get_json()["data"]["error"] == "invalid_date_format"

def test_api_smart_calendar_analyze(client):
    resp = client.post("/ai/smart-calendar/analyze-patterns", json={"attendee_uid": "u1"})
    assert resp.status_code == 200
    assert "preferred_hours" in resp.get_json()["data"]

# --- ImipProcessor Tests ---

def test_imip_processor_process_reply():
    mock_sources = MagicMock()
    mock_owner = SimpleNamespace(uid="u1")
    processor = ImipProcessor(mock_sources)
    with patch("app.module.calendar.imip.ImipProcessor.ImipParser.parse_calendar") as mock_parse:
        mock_msg = MagicMock(spec=ImipMessage)
        mock_msg.method = ImipMethod.REPLY
        mock_msg.event = MagicMock()
        mock_msg.event.require_uid = "ev1"
        mock_msg.event.attendees = [MagicMock(email="a1@example.com", status="accepted")]
        mock_parse.return_value = mock_msg
        mock_source = MagicMock()
        mock_source.is_writable.return_value = True
        mock_event = MagicMock(spec=CalEvent)
        mock_sources.find_by_uid.return_value = (mock_source, mock_event)
        processor.process_reply(mock_owner, b"ical", "a1@example.com")
        mock_event.set_attendance.assert_called_with("a1@example.com", "accepted")
        mock_source.update_event_or_fail.assert_called()

def test_imip_processor_process_request_new_event():
    mock_sources = MagicMock()
    mock_owner = SimpleNamespace(uid="u1")
    processor = ImipProcessor(mock_sources)
    with patch("app.module.calendar.imip.ImipProcessor.ImipParser.parse_calendar") as mock_parse:
        organizer = MagicMock()
        organizer.email = "org@example.com"
        mock_event = CalEvent(uid="ev1", organizer=organizer, attendees=[], reminders=[])
        mock_msg = ImipMessage(method=ImipMethod.REQUEST, event=mock_event, to_emails=["u1@example.com"], from_email="org@example.com")
        mock_parse.return_value = mock_msg
        mock_sources.find_by_uid.return_value = None
        mock_source = MagicMock()
        mock_sources.get_default.return_value = mock_source
        processor.process_request(mock_owner, b"ical", "org@example.com")
        mock_source.insert_event.assert_called()

def test_imip_processor_process_request_existing_stale():
    mock_sources = MagicMock()
    mock_owner = SimpleNamespace(uid="u1")
    processor = ImipProcessor(mock_sources)
    with patch("app.module.calendar.imip.ImipProcessor.ImipParser.parse_calendar") as mock_parse:
        mock_msg = MagicMock(spec=ImipMessage)
        mock_msg.method = ImipMethod.REQUEST
        mock_msg.event = MagicMock()
        mock_msg.event.require_uid = "ev1"
        mock_msg.event.sequence = 1
        mock_parse.return_value = mock_msg
        mock_source = MagicMock()
        mock_source.is_writable.return_value = True
        mock_event = MagicMock(spec=CalEvent)
        mock_event.sequence = 2 
        mock_event.is_organized_by.return_value = True
        mock_sources.find_by_uid.return_value = (mock_source, mock_event)
        result = processor.process_request(mock_owner, b"ical", "org@example.com")
        assert result == mock_event
        mock_source.update_event_or_fail.assert_not_called()

def test_imip_processor_process_request_sender_mismatch():
    mock_sources = MagicMock()
    mock_owner = SimpleNamespace(uid="u1")
    processor = ImipProcessor(mock_sources)
    with patch("app.module.calendar.imip.ImipProcessor.ImipParser.parse_calendar") as mock_parse:
        mock_msg = MagicMock(spec=ImipMessage)
        mock_msg.method = ImipMethod.REQUEST
        mock_msg.event = MagicMock()
        mock_msg.event.require_uid = "ev1"
        mock_parse.return_value = mock_msg
        mock_source = MagicMock()
        mock_source.is_writable.return_value = True
        mock_event = MagicMock(spec=CalEvent)
        mock_event.is_organized_by.return_value = False
        mock_sources.find_by_uid.return_value = (mock_source, mock_event)
        with pytest.raises(RequestException) as excinfo:
            processor.process_request(mock_owner, b"ical", "attacker@example.com")
        assert excinfo.value.error == ERROR_CALENDAR_IMIP_SENDER_MISMATCH

def test_imip_processor_process_cancel_partial():
    mock_sources = MagicMock()
    mock_owner = SimpleNamespace(uid="u1")
    processor = ImipProcessor(mock_sources)
    with patch("app.module.calendar.imip.ImipProcessor.ImipParser.parse_calendar") as mock_parse:
        mock_msg = MagicMock(spec=ImipMessage)
        mock_msg.method = ImipMethod.CANCEL
        mock_msg.event = MagicMock()
        mock_msg.event.require_uid = "ev1"
        mock_msg.event.recurrence_id = "2023-10-01T10:00:00Z"
        mock_parse.return_value = mock_msg
        mock_source = MagicMock()
        mock_source.is_writable.return_value = True
        mock_event = MagicMock(spec=CalEvent)
        mock_event.is_organized_by.return_value = True
        mock_event.recurrence_exceptions = []
        mock_sources.find_by_uid.return_value = (mock_source, mock_event)
        processor.process_cancel(mock_owner, b"ical", "org@example.com")
        assert "2023-10-01T10:00:00Z" in mock_event.recurrence_exceptions
        mock_source.update_event.assert_called_with(mock_event)

def test_imip_processor_process_cancel_full():
    mock_sources = MagicMock()
    mock_owner = SimpleNamespace(uid="u1")
    processor = ImipProcessor(mock_sources)
    with patch("app.module.calendar.imip.ImipProcessor.ImipParser.parse_calendar") as mock_parse:
        mock_msg = MagicMock(spec=ImipMessage)
        mock_msg.method = ImipMethod.CANCEL
        mock_msg.event = MagicMock()
        mock_msg.event.require_uid = "ev1"
        mock_msg.event.recurrence_id = None
        mock_parse.return_value = mock_msg
        mock_source = MagicMock()
        mock_source.is_writable.return_value = True
        mock_event = MagicMock(spec=CalEvent)
        mock_event.is_organized_by.return_value = True
        mock_sources.find_by_uid.return_value = (mock_source, mock_event)
        processor.process_cancel(mock_owner, b"ical", "org@example.com")
        mock_source.delete_event.assert_called()

def test_imip_processor_parse_validation_errors():
    processor = ImipProcessor(MagicMock())
    with patch("app.module.calendar.imip.ImipProcessor.ImipParser.parse_calendar") as mock_parse:
        mock_msg = MagicMock(spec=ImipMessage)
        mock_msg.method = ImipMethod.REPLY
        mock_parse.return_value = mock_msg
        with pytest.raises(RequestException) as excinfo:
            processor._parse_and_validate(b"ical", ImipMethod.REQUEST)
        assert excinfo.value.error == ERROR_CALENDAR_IMIP_INVALID_REQUEST
    with patch("app.module.calendar.imip.ImipProcessor.ImipParser.parse_calendar") as mock_parse:
        mock_parse.side_effect = Exception("Boom")
        with pytest.raises(RequestException) as excinfo:
            processor._parse_and_validate(b"ical", ImipMethod.REQUEST)
        assert excinfo.value.error == ERROR_CALENDAR_ICS_PARSE_FAILED
