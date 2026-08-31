"""Renders an outgoing invitation email with a human-friendly body + machine-readable ICS.

This is the MIME-rendering half of the invitation workflow. ``ImipEmailBuilder`` produces the
minimal RFC 6047 wire message (a bare ``text/calendar`` payload) for programmatic delivery; this
builder instead produces a reader-facing ``multipart/alternative`` message with:

* a ``text/plain`` summary of the invitation,
* a ``text/html`` version of the same summary,
* the ``text/calendar; method=...`` part carrying the iTIP payload so calendar-aware clients can
  act on the invitation (add/update/remove the event, reply, ...).

Headers follow the same conventions as ``ImipEmailBuilder``; only the body is enriched.
"""
from __future__ import annotations

import html
from email.message import EmailMessage
from typing import TYPE_CHECKING

from app.module.calendar.CalendarConst import (
    IMIP_SUBJECT_PREFIX_CANCEL,
    IMIP_SUBJECT_PREFIX_REPLY,
    IMIP_SUBJECT_PREFIX_REQUEST,
)
from app.module.calendar.imip.ImipMethod import ImipMethod
from app.utils.datetime.DateTimeUtils import fmt_dt

if TYPE_CHECKING:
    from app.module.calendar.imip.ImipMessage import ImipMessage

# Subject prefix per method - the human-facing hint, the machine part is the text/calendar body.
_SUBJECT_PREFIX: dict[ImipMethod, str] = {
    ImipMethod.REQUEST: IMIP_SUBJECT_PREFIX_REQUEST,
    ImipMethod.REPLY: IMIP_SUBJECT_PREFIX_REPLY,
    ImipMethod.CANCEL: IMIP_SUBJECT_PREFIX_CANCEL,
}


class InvitationEmailBuilder:
    """Builds a multipart/alternative (text/plain + text/html + text/calendar) invitation email."""

    @staticmethod
    def build_email(message: ImipMessage) -> EmailMessage:
        """Wrap an iMIP message in a reader-friendly email ready for the outgoing mail client.

        :param message: the iMIP message to deliver (method, ical_content, from/to, event).
        :return: the email to hand to the outgoing mail client.
        """
        event = message.event
        title: str = event.title or event.uid or "Untitled"
        prefix: str = _SUBJECT_PREFIX.get(message.method, IMIP_SUBJECT_PREFIX_REQUEST)

        organizer_line: str = InvitationEmailBuilder._organizer_line(event)
        when_line: str = InvitationEmailBuilder._when_line(event)
        where_line: str = event.location or ""

        plain_body: str = InvitationEmailBuilder._render_plain(
            title, organizer_line, when_line, where_line, event, prefix,
        )
        html_body: str = InvitationEmailBuilder._render_html(
            title, organizer_line, when_line, where_line, event, prefix,
        )

        email_message: EmailMessage = EmailMessage()
        email_message["From"] = message.from_email
        email_message["To"] = ", ".join(message.to_emails)
        email_message["Subject"] = f"{prefix}: {title}"
        email_message.set_content(plain_body)
        email_message.add_alternative(html_body, subtype="html")
        email_message.add_alternative(
            message.ical_content,
            subtype="calendar",
            params={"method": message.method.value, "component": "VEVENT"},
        )
        return email_message

    @staticmethod
    def _organizer_line(event) -> str:  # pragma: no cover - trivial formatting helper
        """Return a human-readable "Organizer: ..." line for the plain/HTML body."""
        organizer = event.organizer
        if organizer is None:
            return ""
        if organizer.name:
            return f"{organizer.name} <{organizer.email}>"
        return organizer.email

    @staticmethod
    def _when_line(event) -> str:  # pragma: no cover - trivial formatting helper
        """Render the event's start/end as a single "When:" line, or '' when unknown."""
        if event.date_start is None:
            return ""
        if event.date_end is not None and event.date_end != event.date_start:
            return f"{fmt_dt(event.date_start)} - {fmt_dt(event.date_end)}"
        return fmt_dt(event.date_start)

    @staticmethod
    def _attendee_lines(event) -> list[str]:
        """Return one bullet per attendee ("" when none are attached to the event)."""
        return [
            f"- {attendee.name} <{attendee.email}>" if attendee.name else f"- {attendee.email}"
            for attendee in event.attendees
        ]

    @staticmethod
    def _render_plain(
        title: str, organizer_line: str, when_line: str, where_line: str, event, prefix: str,
    ) -> str:
        """Render the text/plain alternative of the invitation body."""
        lines: list[str] = [f"{prefix}: {title}", ""]
        if organizer_line:
            lines.append(f"Organizer: {organizer_line}")
        if when_line:
            lines.append(f"When: {when_line}")
        if where_line:
            lines.append(f"Where: {where_line}")
        if event.description:
            lines.extend(["", event.description])
        attendee_lines: list[str] = InvitationEmailBuilder._attendee_lines(event)
        if attendee_lines:
            lines.extend(["", "Attendees:", *attendee_lines])
        return "\n".join(lines)

    @staticmethod
    def _render_html(
        title: str, organizer_line: str, when_line: str, where_line: str, event, prefix: str,
    ) -> str:
        """Render the text/html alternative of the invitation body (escaped, minimal markup)."""
        esc = html.escape
        parts: list[str] = [
            "<html><body>",
            f"<h2>{esc(f'{prefix}: {title}')}</h2>",
        ]
        if organizer_line:
            parts.append(f"<p><strong>Organizer:</strong> {esc(organizer_line)}</p>")
        if when_line:
            parts.append(f"<p><strong>When:</strong> {esc(when_line)}</p>")
        if where_line:
            parts.append(f"<p><strong>Where:</strong> {esc(where_line)}</p>")
        if event.description:
            parts.append(f"<p>{esc(event.description)}</p>")
        attendee_lines: list[str] = InvitationEmailBuilder._attendee_lines(event)
        if attendee_lines:
            parts.append("<p><strong>Attendees:</strong></p><ul>")
            for attendee in attendee_lines:
                parts.append(f"<li>{esc(attendee)}</li>")
            parts.append("</ul>")
        parts.append("</body></html>")
        return "\n".join(parts)
