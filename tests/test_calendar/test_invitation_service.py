"""Unit tests for InvitationService (ICS generation + MIME rendering).

Covered here (BACKEND-GAPS F1 · subsection 1 "Implement Invitation Email Generation"):
* ``InvitationService.generate_ics_event``  - RFC 5545 / iTIP REQUEST VCALENDAR generation.
* ``InvitationService.render_invitation_email`` - multipart/alternative MIME (plain + HTML + ICS).

Pure unit tests: no DB, SMTP, LDAP or Redis involved - the service is stateless by design.
ICS content is asserted via ``icalendar`` (the serializers fold ATTENDEE lines at 75 octets, so
raw substring checks on ``mailto:...`` addresses would be unreliable).
"""
from datetime import datetime, timezone

from icalendar import Calendar

from app.interface.calendar.InterfaceInvitationService import InvitationService
from app.module.calendar.imip.ImipMethod import ImipMethod
from app.module.calendar.imip.ImipMessage import ImipMessage
from app.module.calendar.imip.InvitationEmailBuilder import InvitationEmailBuilder
from app.module.calendar.imip.InvitationIcsBuilder import InvitationIcsBuilder
from app.module.calendar.model.CalAttendee import CalAttendee
from app.module.calendar.model.CalEvent import CalEvent
from app.module.calendar.model.CalOrganizer import CalOrganizer
from app.module.calendar.model.enums.AttendeeStatus import AttendeeStatus
from app.utils.exceptions import BugException

_UTC = timezone.utc


def _make_event(**kwargs) -> CalEvent:
    defaults = dict(
        uid="evt-invite-1@example.org",
        title="Product planning",
        date_start=datetime(2026, 7, 1, 9, 0, tzinfo=_UTC),
        date_end=datetime(2026, 7, 1, 10, 0, tzinfo=_UTC),
        location="Room 4A",
        description="Bring the roadmap.",
    )
    defaults.update(kwargs)
    return CalEvent(**defaults)


def _organizer(email="alice@example.org", name="Alice Stone"):
    return CalOrganizer(email=email, name=name)


def _attendee(email="bob@example.org", name="Bob Rivers", status=AttendeeStatus.NEEDS_ACTION):
    return CalAttendee(email=email, name=name, status=status)


# ----------------------------------------------------------- ICS-level helpers


def _parse_ics(ics: str) -> Calendar:
    return Calendar.from_ical(ics)


def _vevent_attendee_emails(calendar: Calendar) -> set[str]:
    """Return the set of mailto: ATTENDEE addresses from the first VEVENT."""
    for component in calendar.walk("VEVENT"):
        raw = component.get("ATTENDEE")
        if raw is None:
            return set()
        # icalendar returns a scalar for a single ATTENDEE, a list for several.
        addresses = raw if isinstance(raw, list) else [raw]
        return {str(address) for address in addresses}
    return set()


def _vevent_organizer_email(calendar: Calendar) -> str | None:
    for component in calendar.walk("VEVENT"):
        organizer = component.get("ORGANIZER")
        return str(organizer) if organizer is not None else None
    return None


# ============================================================== generate_ics_event


def test_generate_ics_event_returns_imip_request_vcalendar():
    event = _make_event(organizer=_organizer(), attendees=[_attendee()])
    ics = InvitationService.generate_ics_event(event)
    parsed = _parse_ics(ics)
    assert str(parsed.get("method")) == "REQUEST"
    assert _vevent_attendee_emails(parsed) == {"mailto:bob@example.org"}
    assert _vevent_organizer_email(parsed) == "mailto:alice@example.org"
    vevent = parsed.walk("VEVENT")[0]
    assert str(vevent.get("summary")) == "Product planning"
    assert str(vevent.get("uid")) == "evt-invite-1@example.org"


def test_generate_ics_event_uses_explicit_organizer_and_attendees():
    event = _make_event()  # no organizer / attendees embedded
    ics = InvitationService.generate_ics_event(
        event, organizer=_organizer("carol@example.org", "Carol"),
        attendees=[_attendee("dave@example.org", "Dave")],
    )
    parsed = _parse_ics(ics)
    assert _vevent_attendee_emails(parsed) == {"mailto:dave@example.org"}
    assert _vevent_organizer_email(parsed) == "mailto:carol@example.org"


def test_generate_ics_event_keeps_event_defaults_for_missing_args():
    event = _make_event(organizer=_organizer(), attendees=[_attendee()])
    ics = InvitationService.generate_ics_event(event)  # organizer/attendees come from event
    parsed = _parse_ics(ics)
    assert str(parsed.get("method")) == "REQUEST"
    assert _vevent_attendee_emails(parsed) == {"mailto:bob@example.org"}
    assert _vevent_organizer_email(parsed) == "mailto:alice@example.org"


def test_generate_ics_event_all_attendees_emitted():
    event = _make_event(
        organizer=_organizer(),
        attendees=[_attendee("a@x.org"), _attendee("b@x.org", name=None)],
    )
    ics = InvitationService.generate_ics_event(event)
    assert _vevent_attendee_emails(_parse_ics(ics)) == {"mailto:a@x.org", "mailto:b@x.org"}


def test_generate_ics_event_without_organizer_raises():
    event = _make_event(attendees=[_attendee()])
    try:
        InvitationService.generate_ics_event(event)
    except BugException:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected BugException for missing organizer")


def test_generate_ics_event_without_attendees_raises():
    event = _make_event(organizer=_organizer())
    try:
        InvitationService.generate_ics_event(event)
    except BugException:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected BugException for missing attendees")


def test_ics_builder_normalize_event_returns_copy_not_mutation():
    event = _make_event(organizer=_organizer(), attendees=[_attendee()])
    normalized = InvitationIcsBuilder.normalize_event(
        event, organizer=_organizer("zoe@example.org"), attendees=[_attendee("zed@example.org")],
    )
    # The original event must not be mutated by the normalize step.
    assert event.organizer.email == "alice@example.org"
    assert normalized.organizer.email == "zoe@example.org"
    assert normalized.attendees[0].email == "zed@example.org"


# ============================================================== render_invitation_email


def test_render_invitation_email_headers():
    event = _make_event(organizer=_organizer(), attendees=[_attendee()])
    email = InvitationService.render_invitation_email("bob@example.org", event)
    assert email["From"] == "alice@example.org"
    assert email["To"] == "bob@example.org"
    assert email["Subject"] == "Invitation: Product planning"


def test_render_invitation_email_is_multipart_alternative_with_three_parts():
    event = _make_event(organizer=_organizer(), attendees=[_attendee()])
    email = InvitationService.render_invitation_email("bob@example.org", event)
    assert email.is_multipart()
    assert email.get_content_type() == "multipart/alternative"
    payloads = email.get_payload()
    assert [part.get_content_type() for part in payloads] == [
        "text/plain", "text/html", "text/calendar",
    ]


def test_render_invitation_email_plain_body_summary():
    event = _make_event(organizer=_organizer(), attendees=[_attendee()])
    email = InvitationService.render_invitation_email("bob@example.org", event)
    plain = next(p for p in email.get_payload() if p.get_content_type() == "text/plain").get_content()
    assert "Invitation: Product planning" in plain
    assert "Organizer: Alice Stone <alice@example.org>" in plain
    assert "Room 4A" in plain
    assert "Bring the roadmap." in plain
    assert "Bob Rivers <bob@example.org>" in plain


def test_render_invitation_email_html_body_escapes_content():
    event = _make_event(
        organizer=_organizer(),
        attendees=[_attendee()],
        description="<script>alert('x')</script> party",
    )
    email = InvitationService.render_invitation_email("bob@example.org", event)
    html_part = next(p for p in email.get_payload() if p.get_content_type() == "text/html")
    html_body = html_part.get_content()
    assert "<script>" not in html_body
    assert "&lt;script&gt;" in html_body
    assert "<h2>" in html_body


def test_render_invitation_email_calendar_part_is_request_ics():
    event = _make_event(organizer=_organizer(), attendees=[_attendee()])
    email = InvitationService.render_invitation_email("bob@example.org", event)
    cal_part = next(p for p in email.get_payload() if p.get_content_type() == "text/calendar")
    assert cal_part.get_param("method") == "REQUEST"
    assert cal_part.get_param("component") == "VEVENT"
    parsed = _parse_ics(cal_part.get_content())
    assert str(parsed.get("method")) == "REQUEST"
    assert _vevent_attendee_emails(parsed) == {"mailto:bob@example.org"}
    assert _vevent_organizer_email(parsed) == "mailto:alice@example.org"


def test_render_invitation_email_with_explicit_organizer_attendees():
    event = _make_event()
    email = InvitationService.render_invitation_email(
        "carol@example.org", event,
        organizer=_organizer("carol@example.org", "Carol"),
        attendees=[_attendee("dave@example.org", "Dave")],
    )
    assert email["From"] == "carol@example.org"
    assert email["To"] == "carol@example.org"
    cal = next(p for p in email.get_payload() if p.get_content_type() == "text/calendar").get_content()
    parsed = _parse_ics(cal)
    assert _vevent_organizer_email(parsed) == "mailto:carol@example.org"
    assert _vevent_attendee_emails(parsed) == {"mailto:dave@example.org"}


def test_render_invitation_email_requires_organizer():
    event = _make_event(attendees=[_attendee()])
    try:
        InvitationService.render_invitation_email("bob@example.org", event)
    except BugException:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected BugException for missing organizer")


# ============================================================== ImipMessage compatibility


def test_rendered_email_accepts_an_imip_message_directly():
    """InvitationEmailBuilder stays useful at the ImipMessage level (same input as ImipEmailBuilder)."""
    event = _make_event(organizer=_organizer(), attendees=[_attendee()])
    message = ImipMessage(
        method=ImipMethod.REQUEST, event=event,
        from_email="alice@example.org",
        to_emails=["bob@example.org"],
        ical_content=InvitationIcsBuilder.build_ics(event),
    )
    email = InvitationEmailBuilder.build_email(message)
    assert email["Subject"] == "Invitation: Product planning"
    assert email.is_multipart()
    assert email.get_content_type() == "multipart/alternative"
