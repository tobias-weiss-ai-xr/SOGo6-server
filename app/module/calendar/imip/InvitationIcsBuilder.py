"""Builds the iCalendar payload of an outgoing invitation (RFC 5545 / iTIP REQUEST).

This is the ICS-generation half of the invitation workflow: given a ``CalEvent`` (plus the
organizer/attendees, which callers may pass explicitly rather than embedding in the event), it
produces the ``text/calendar`` document with ``METHOD:REQUEST`` that gets attached to the
invitation email.

It sits beside ``ImipBuilder`` (which builds the full ``ImipMessage`` envelope) and reuses the
same ``CalEventSerializerIcal`` pipeline so all RFC 5545 reverse-mapping / line-folding rules
stay in the *Ical serializer; this class only handles invitation-specific normalisation and
input validation.
"""
from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from app.module.calendar.serializer.CalEventSerializerIcal import CalEventSerializerIcal
from app.utils.exceptions import BugException

if TYPE_CHECKING:
    from app.module.calendar.model.CalAttendee import CalAttendee
    from app.module.calendar.model.CalEvent import CalEvent
    from app.module.calendar.model.CalOrganizer import CalOrganizer


class InvitationIcsBuilder:
    """Generates the iCalendar (METHOD:REQUEST) payload for an event invitation."""

    _serializer: CalEventSerializerIcal = CalEventSerializerIcal()

    @staticmethod
    def normalize_event(
        event: CalEvent,
        organizer: CalOrganizer | None = None,
        attendees: list[CalAttendee] | None = None,
    ) -> CalEvent:
        """Return a copy of ``event`` with the explicit organizer/attendees applied.

        Lets callers supply the organizer and attendee list as arguments instead of embedding
        them in the event object (as the manager layer does when the invitee list is assembled
        per-notification). When an argument is ``None`` the value already carried by the event
        is kept.

        :raises BugException: if no organizer can be resolved - an iTIP REQUEST without an
            ORGANIZER is invalid (RFC 5546 §3.2.3), so a caller asking for one is a bug.
        :raises BugException: if the resolved attendee list is empty - there is nobody to invite.
        """
        resolved_organizer: CalOrganizer | None = organizer if organizer is not None else event.organizer
        if resolved_organizer is None:
            raise BugException(
                "Cannot build an invitation without an organizer "
                "(iTIP REQUEST requires an ORGANIZER property)"
            )
        resolved_attendees: list[CalAttendee] = (
            attendees if attendees is not None else event.attendees
        )
        if not resolved_attendees:
            raise BugException(
                "Cannot build an invitation without attendees "
                "(iTIP REQUEST requires at least one ATTENDEE property)"
            )
        return dataclasses.replace(
            event, organizer=resolved_organizer, attendees=list(resolved_attendees),
        )

    @staticmethod
    def build_ics(
        event: CalEvent,
        organizer: CalOrganizer | None = None,
        attendees: list[CalAttendee] | None = None,
    ) -> str:
        """Generate the iCalendar invitation string (RFC 5545, iTIP METHOD:REQUEST).

        :param event: the event to invite people to (dates, location, description, ...).
        :param organizer: the inviting party; ``None`` to keep ``event.organizer``.
        :param attendees: the invited parties; ``None`` to keep ``event.attendees``.
        :return: the folded, CRLF-terminated VCALENDAR text with a ``METHOD:REQUEST`` property.
        :rtype: str
        """
        normalized: CalEvent = InvitationIcsBuilder.normalize_event(event, organizer, attendees)
        return InvitationIcsBuilder._serializer.build_imip(normalized, "REQUEST")
