"""Invitation e-mail workflow facade for the calendar module (ICS generation + MIME rendering).

Exposes the two pure building blocks of the "invite to event" flow (BACKEND-GAPS F1, subsection 1):

* ``generate_ics_event`` -> the RFC 5545 ``text/calendar`` invitation (iTIP ``METHOD:REQUEST``),
* ``render_invitation_email`` -> the reader-friendly ``multipart/alternative`` MIME message that
  carries that ICS so the recipient's mail client can accept/decline (RFC 6047).

Like ``InterfaceAgentCalendar`` this facade is not route-bound: it performs no Flask/HTTP work and
needs no live stack (no DB, SMTP or LDAP), so it can run inside a request handler, an agent task or
a unit test alike. Delivery (SMTP) is deliberately out of scope - that belongs to the outgoing mail
client and depends on the domain's SMPT settings.
"""
from __future__ import annotations

from email.message import EmailMessage
from typing import TYPE_CHECKING

from app.module.calendar.imip.ImipMessage import ImipMessage
from app.module.calendar.imip.ImipMethod import ImipMethod
from app.module.calendar.imip.InvitationEmailBuilder import InvitationEmailBuilder
from app.module.calendar.imip.InvitationIcsBuilder import InvitationIcsBuilder

if TYPE_CHECKING:
    from app.module.calendar.model.CalAttendee import CalAttendee
    from app.module.calendar.model.CalEvent import CalEvent
    from app.module.calendar.model.CalOrganizer import CalOrganizer


class InvitationService:
    """Service facade for calendar invitation e-mail generation (ICS + MIME)."""

    #: Method used for the outgoing invitation payload - a fresh invite is always an iTIP REQUEST.
    _METHOD: ImipMethod = ImipMethod.REQUEST

    @staticmethod
    def generate_ics_event(
        event: CalEvent,
        organizer: CalOrganizer | None = None,
        attendees: list[CalAttendee] | None = None,
    ) -> str:
        """Generate the iCalendar invitation string for an event (RFC 5545, METHOD:REQUEST).

        :param event: the event being scheduled.
        :param organizer: the inviting party; defaults to ``event.organizer``.
        :param attendees: the invited parties; defaults to ``event.attendees``.
        :return: the VCALENDAR text (CRLF, 75-octet folded) carrying the ``METHOD:REQUEST``,
            ``ORGANIZER`` and one ``ATTENDEE`` per invited party.
        :rtype: str
        """
        return InvitationIcsBuilder.build_ics(event, organizer, attendees)

    @staticmethod
    def render_invitation_email(
        recipient: str,
        event: CalEvent,
        organizer: CalOrganizer | None = None,
        attendees: list[CalAttendee] | None = None,
    ) -> EmailMessage:
        """Render the MIME invitation email for one recipient (plain + HTML + ICS).

        Produces a ``multipart/alternative`` message: a human-readable ``text/plain`` and
        ``text/html`` summary plus the ``text/calendar; method=REQUEST`` payload so calendar-aware
        clients can add the event and reply. Headers carry the organizer as ``From`` and the target
        recipient as ``To``.

        :param recipient: the e-mail address this invitation is addressed to.
        :param event: the event being scheduled.
        :param organizer: the inviting party; defaults to ``event.organizer``.
        :param attendees: the invited parties; defaults to ``event.attendees``.
        :return: the ``EmailMessage`` ready for the outgoing mail client.
        """
        normalized: CalEvent = InvitationIcsBuilder.normalize_event(event, organizer, attendees)
        message: ImipMessage = ImipMessage(
            method=InvitationService._METHOD,
            event=normalized,
            from_email=normalized.organizer.email,  # type: ignore[union-attr]  # normalized => set
            to_emails=[recipient],
            ical_content=InvitationIcsBuilder.build_ics(normalized),
        )
        return InvitationEmailBuilder.build_email(message)
