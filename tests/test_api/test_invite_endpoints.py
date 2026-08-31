"""Acceptance-gate tests for the calendar invitation / attendee / RSVP endpoints (BACKEND-GAPS F1).

Covers the three "Expose Invitation Endpoints":

* ``POST  /api/user/v1/calendar/calendars/{key}/events/{event_key}/invite``   - send invitations
* ``GET   /api/user/v1/calendar/calendars/{key}/events/{event_key}/attendees`` - list attendees
* ``PUT   /api/user/v1/calendar/calendars/{key}/events/{event_key}/attendees/{attendee_id}``
                                                                              - update RSVP status

All tests run WITHOUT a live stack. DB-backed config resolution is stubbed exactly
like ``tests/test_api/test_jmap_protocol.py``; the calendar API interface is replaced
by a controllable fake; SMTP delivery is spied on (never touches the network).
"""
from __future__ import annotations

import os

# Set required environment variables for ProcessSetting (mirrors the rest of the suite).
os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from marshmallow import ValidationError

from app import create_app
from app.utils import constants as cs

CAL = "/api/user/v1"
INVITE = f"{CAL}/calendars/cal-1/events/evt-1/invite"
ATTENDEES = f"{CAL}/calendars/cal-1/events/evt-1/attendees"

_UTC = timezone.utc


# --------------------------------------------------------------------------- #
# Domain test data (built with the REAL serializer so the handler round-trips
# exactly the payloads the calendar stack produces in production).
# --------------------------------------------------------------------------- #

def _organizer(email="alice@example.org", name="Alice Stone"):
    from app.module.calendar.model.CalOrganizer import CalOrganizer
    return CalOrganizer(email=email, name=name)


def _attendee(email, status="needs-action", name=None):
    from app.module.calendar.model.CalAttendee import CalAttendee
    from app.module.calendar.model.enums.AttendeeStatus import AttendeeStatus
    return CalAttendee(email=email, name=name, status=AttendeeStatus(status))


def _serialized_event(organizer=None, attendees=None, **kwargs):
    """Serialize a synthetic CalEvent the way ``get_event`` would."""
    from app.module.calendar.model.CalEvent import CalEvent
    from app.module.calendar.model.enums.ComponentType import ComponentType
    from app.module.calendar.model.enums.EventStatus import EventStatus
    from app.module.calendar.model.enums.EventVisibility import EventVisibility
    from app.module.calendar.model.enums.ShowAs import ShowAs
    from app.module.calendar.serializer.CalEventSerializerDict import CalEventSerializerDict

    defaults = dict(
        key="evt-1",
        calendar_key="cal-1",
        uid="evt-1@example.org",
        title="Product planning",
        description="Bring the roadmap.",
        location="Room 4A",
        date_start=datetime(2026, 7, 1, 9, 0, tzinfo=_UTC),
        date_end=datetime(2026, 7, 1, 10, 0, tzinfo=_UTC),
        component_type=ComponentType.EVENT,
        status=EventStatus.CONFIRMED,
        visibility=EventVisibility.PUBLIC,
        show_as=ShowAs.BUSY,
        organizer=organizer,
        attendees=attendees or [],
    )
    defaults.update(kwargs)
    return CalEventSerializerDict().serialize(CalEvent(**defaults))


def _ok(envelope_data):
    """A successful ``get_event``-style return value."""
    return {"data": envelope_data, "error_code": "S000000", "error_msg": "No Error"}, 200


def _err(error_code, error_msg, status):
    return {"data": None, "error_code": error_code, "error_msg": error_msg}, status


# --------------------------------------------------------------------------- #
# App + auth fixture (no live DB/LDAP/Redis - see tests/test_api/test_jmap_protocol.py)
# --------------------------------------------------------------------------- #

@pytest.fixture()
def client(monkeypatch):
    """An authenticated test client for the USER (basic) API in the SOGo_OK state."""
    from app.auth.User import User

    app = create_app(cs.SOGO_OK)
    app.config["TESTING"] = True

    class FakeAuthUser:
        def __init__(self, *args, **kwargs):  # noqa: D401
            pass

        def check_user_and_fill_info(self, user):
            return True, user

    monkeypatch.setattr("app.init_get_system_and_default_domain_settings", lambda: ({}, {}))
    monkeypatch.setattr("app.init_get_user_domain_settings", lambda user: {})
    monkeypatch.setattr("app.InterfaceAuthUser", FakeAuthUser)
    monkeypatch.setattr("app.VoucherUserService.__init__", lambda self, ps: None)
    monkeypatch.setattr(
        "app.VoucherUserService.generate_user_from_voucher",
        staticmethod(lambda token: User("testuser@example.org", cn="Test User", domain="example.org")),
    )
    test_client = app.test_client()
    test_client.environ_base["HTTP_AUTHORIZATION"] = "Bearer test-token"
    return test_client


@pytest.fixture()
def fake_interface(monkeypatch):
    """Replace the calendar API interface the Invitation blueprint builds per request."""
    inter = MagicMock()
    monkeypatch.setattr(
        "app.api.v1.calendar.ApiInvitation.InterfaceApiCalendarCalendar", lambda **kwargs: inter
    )
    return inter


@pytest.fixture()
def mail_spy(monkeypatch):
    """Record every raw MIME message handed to the outgoing mail module."""
    sent: list[tuple[str, object]] = []
    from app.module.mail.ModuleMailOutgoing import ModuleMailOutgoing

    def fake_send(self, account_id, message):
        sent.append((account_id, message))

    monkeypatch.setattr(ModuleMailOutgoing, "send_raw_message", fake_send)
    return sent


# --------------------------------------------------------------------------- #
# Route registration (pure app build - no requests, no stack)
# --------------------------------------------------------------------------- #

def test_invitation_blueprint_registered():
    from app.api.v1.calendar.ApiInvitation import blp
    assert blp.name == "Invitation"
    assert blp.url_prefix == ""


def test_three_f1_routes_registered():
    """The three contract routes must be live on the /api/user/v1/calendar tree."""
    app = create_app(cs.SOGO_OK)
    found = []
    for rule in app.url_map.iter_rules():
        path = rule.rule or ""
        if path.startswith(CAL) and ("/invite" in path or "/attendees" in path):
            found.append((path, frozenset(m for m in rule.methods if m not in {"HEAD", "OPTIONS"})))

    assert (f"{CAL}/calendars/<string:key>/events/<string:event_key>/invite", frozenset({"POST"})) in found
    assert (f"{CAL}/calendars/<string:key>/events/<string:event_key>/attendees", frozenset({"GET"})) in found
    assert (
        f"{CAL}/calendars/<string:key>/events/<string:event_key>/attendees/<string:attendee_id>",
        frozenset({"PUT"}),
    ) in found


# --------------------------------------------------------------------------- #
# Request-body schema validation
# --------------------------------------------------------------------------- #

def test_rsvp_schema_accepts_every_partstat_literal():
    from app.api.v1.calendar.schemas.invitation import RsvpUpdateSchema
    for status in ("needs-action", "accepted", "declined", "tentative", "delegated"):
        assert RsvpUpdateSchema().load({"status": status})["status"] == status


def test_rsvp_schema_rejects_unknown_status():
    from app.api.v1.calendar.schemas.invitation import RsvpUpdateSchema
    with pytest.raises(ValidationError):
        RsvpUpdateSchema().load({"status": "maybe"})


# --------------------------------------------------------------------------- #
# GET .../events/{event_key}/attendees
# --------------------------------------------------------------------------- #

def test_get_attendees_lists_event_attendees(client, fake_interface):
    event = _serialized_event(
        organizer=_organizer(),
        attendees=[_attendee("bob@example.org", status="accepted"), _attendee("carol@example.org")],
    )
    fake_interface.get_event.return_value = _ok(event)

    resp = client.get(ATTENDEES)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["error_code"] == "S000000"
    data = body["data"]
    assert data["total_count"] == 2
    assert {a["email"] for a in data["attendees"]} == {"bob@example.org", "carol@example.org"}
    status_by_email = {a["email"]: a["status"] for a in data["attendees"]}
    assert status_by_email["bob@example.org"] == "accepted"
    assert status_by_email["carol@example.org"] == "needs-action"


def test_get_attendees_event_without_attendees_is_empty_list(client, fake_interface):
    event = _serialized_event(organizer=_organizer(), attendees=[])
    fake_interface.get_event.return_value = _ok(event)

    resp = client.get(ATTENDEES)
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["total_count"] == 0
    assert data["attendees"] == []


def test_get_attendees_propagates_event_not_found(client, fake_interface):
    fake_interface.get_event.return_value = _err("S000605", "Calendar Event Not Found", 404)

    resp = client.get(ATTENDEES)
    assert resp.status_code == 404
    assert resp.get_json()["error_code"] == "S000605"


# --------------------------------------------------------------------------- #
# POST .../events/{event_key}/invite
# --------------------------------------------------------------------------- #

def test_invite_sends_one_imip_request_per_attendee(client, fake_interface, mail_spy):
    event = _serialized_event(
        organizer=_organizer(),
        attendees=[_attendee("bob@example.org"), _attendee("carol@example.org")],
    )
    fake_interface.get_event.return_value = _ok(event)

    resp = client.post(INVITE, json={})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["error_code"] == "S000000"
    assert body["data"]["event_key"] == "evt-1"
    assert body["data"]["total_attendees"] == 2
    assert set(body["data"]["invited"]) == {"bob@example.org", "carol@example.org"}

    # iTIP delivers one copy per recipient: exactly two raw MIME messages.
    assert len(mail_spy) == 2
    recipients = sorted(message["To"] for _account_id, message in mail_spy)
    assert recipients == ["bob@example.org", "carol@example.org"]
    assert all(account_id == cs.DEFAULT_IDENTITY_KEY_VALUE for account_id, _message in mail_spy)
    # each delivered message is a text/calendar body carrying the iTIP method (RFC 6047)
    for _account_id, message in mail_spy:
        assert message.get_content_type() == "text/calendar"
        assert message.get_param("method") == "REQUEST"


def test_invite_requires_organizer(client, fake_interface, mail_spy):
    event = _serialized_event(organizer=None, attendees=[_attendee("bob@example.org")])
    fake_interface.get_event.return_value = _ok(event)

    resp = client.post(INVITE, json={})
    assert resp.status_code == 403
    assert resp.get_json()["error_code"] == "S000618"
    assert mail_spy == []


def test_invite_event_without_attendees_is_not_found(client, fake_interface, mail_spy):
    event = _serialized_event(organizer=_organizer(), attendees=[])
    fake_interface.get_event.return_value = _ok(event)

    resp = client.post(INVITE, json={})
    assert resp.status_code == 404
    assert resp.get_json()["error_code"] == "S000605"
    assert mail_spy == []


def test_invite_propagates_event_not_found(client, fake_interface, mail_spy):
    fake_interface.get_event.return_value = _err("S000605", "Calendar Event Not Found", 404)

    resp = client.post(INVITE, json={})
    assert resp.status_code == 404
    assert resp.get_json()["error_code"] == "S000605"
    assert mail_spy == []


def test_invite_returns_503_when_every_delivery_fails(client, fake_interface, monkeypatch):
    event = _serialized_event(
        organizer=_organizer(), attendees=[_attendee("bob@example.org"), _attendee("carol@example.org")]
    )
    fake_interface.get_event.return_value = _ok(event)

    from app.module.mail.ModuleMailOutgoing import ModuleMailOutgoing

    def boom(self, account_id, message):
        raise OSError("SMTP temporarily down")

    monkeypatch.setattr(ModuleMailOutgoing, "send_raw_message", boom)

    resp = client.post(INVITE, json={})
    assert resp.status_code == 503
    assert resp.get_json()["error_code"] == "S001400"


def test_invite_partial_delivery_is_reported_honestly(client, fake_interface, monkeypatch):
    event = _serialized_event(
        organizer=_organizer(), attendees=[_attendee("bob@example.org"), _attendee("carol@example.org")]
    )
    fake_interface.get_event.return_value = _ok(event)

    from app.module.mail.ModuleMailOutgoing import ModuleMailOutgoing

    def flaky(self, account_id, message):
        if message["To"] == "bob@example.org":
            raise OSError("SMTP down for bob")
        sent.append(account_id)

    sent = []
    monkeypatch.setattr(ModuleMailOutgoing, "send_raw_message", flaky)

    resp = client.post(INVITE, json={})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["invited"] == ["carol@example.org"]
    assert resp.get_json()["data"]["total_attendees"] == 2


# --------------------------------------------------------------------------- #
# PUT .../events/{event_key}/attendees/{attendee_id}  (RSVP)
# --------------------------------------------------------------------------- #

def test_put_rsvp_updates_attendee_status(client, fake_interface):
    event = _serialized_event(
        organizer=_organizer(), attendees=[_attendee("bob@example.org", status="needs-action")]
    )
    updated_event = _serialized_event(
        organizer=_organizer(), attendees=[_attendee("bob@example.org", status="accepted")]
    )
    fake_interface.get_event.return_value = _ok(event)
    fake_interface.patch_event.return_value = _ok(updated_event)

    resp = client.put(f"{ATTENDEES}/bob@example.org", json={"status": "accepted"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["attendees"][0]["email"] == "bob@example.org"
    assert body["data"]["attendees"][0]["status"] == "accepted"

    # The interface received the minimal attendee patch (other fields untouched).
    assert fake_interface.patch_event.call_count == 1
    _event_key, patch_body = fake_interface.patch_event.call_args.args
    assert _event_key == "evt-1"
    assert patch_body["attendees"][0]["email"] == "bob@example.org"
    assert patch_body["attendees"][0]["status"] == "accepted"


def test_put_rsvp_is_idempotent_for_unchanged_partstat(client, fake_interface):
    event = _serialized_event(
        organizer=_organizer(), attendees=[_attendee("bob@example.org", status="declined")]
    )
    fake_interface.get_event.return_value = _ok(event)
    fake_interface.patch_event.return_value = _ok(event)

    resp = client.put(f"{ATTENDEES}/bob@example.org", json={"status": "declined"})
    assert resp.status_code == 200
    assert fake_interface.patch_event.call_count == 1


def test_put_rsvp_unknown_attendee_returns_404(client, fake_interface):
    event = _serialized_event(
        organizer=_organizer(), attendees=[_attendee("bob@example.org", status="needs-action")]
    )
    fake_interface.get_event.return_value = _ok(event)

    resp = client.put(f"{ATTENDEES}/nobody@example.org", json={"status": "accepted"})
    assert resp.status_code == 404
    assert resp.get_json()["error_code"] == "S000003"
    fake_interface.patch_event.assert_not_called()


def test_put_rsvp_email_match_is_case_insensitive(client, fake_interface):
    event = _serialized_event(
        organizer=_organizer(), attendees=[_attendee("Bob@Example.Org", status="needs-action")]
    )
    updated_event = _serialized_event(
        organizer=_organizer(), attendees=[_attendee("Bob@Example.Org", status="tentative")]
    )
    fake_interface.get_event.return_value = _ok(event)
    fake_interface.patch_event.return_value = _ok(updated_event)

    resp = client.put(f"{ATTENDEES}/bob@example.org", json={"status": "tentative"})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["attendees"][0]["status"] == "tentative"


def test_put_rsvp_propagates_event_not_found(client, fake_interface):
    fake_interface.get_event.return_value = _err("S000605", "Calendar Event Not Found", 404)

    resp = client.put(f"{ATTENDEES}/bob@example.org", json={"status": "accepted"})
    assert resp.status_code == 404
    assert resp.get_json()["error_code"] == "S000605"
    fake_interface.patch_event.assert_not_called()


def test_put_rsvp_invalid_status_is_rejected_before_lookup(client, fake_interface):
    fake_interface.get_event.return_value = _err("S000605", "Calendar Event Not Found", 404)

    resp = client.put(f"{ATTENDEES}/bob@example.org", json={"status": "maybe"})
    assert resp.status_code == 422
    fake_interface.get_event.assert_not_called()
    fake_interface.patch_event.assert_not_called()
