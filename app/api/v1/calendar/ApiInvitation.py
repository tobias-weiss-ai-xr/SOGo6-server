"""Calendar invitation / attendee / RSVP API endpoints (BACKEND-GAPS F1, subsection 2).

Implements the three failing "Expose Invitation Endpoints":

* ``POST  /api/user/v1/calendar/calendars/<key>/events/<event_key>/invite``
    - validate the event exists, load its attendees, deliver one iTIP REQUEST
      email per attendee (RFC 6047);
* ``GET   /api/user/v1/calendar/calendars/<key>/events/<event_key>/attendees``
    - list the event's attendees (RFC 5545 ATTENDEE properties);
* ``PUT   /api/user/v1/calendar/calendars/<key>/events/<event_key>/attendees/<attendee_id>``
    - update one attendee's RSVP status (PARTSTAT), the attendee being
      identified by its email address.

Layering: the routes stay thin and reuse the existing calendar stack - the api
interface (``InterfaceApiCalendarCalendar``) serves and persists the (serialized)
event, the domain deserializer/serializer round-trip it, ``ImipBuilder`` produces
the RFC 6047 payload and the outgoing mail module (``ModuleMailOutgoing``)
delivers it - the exact components the calendar interface uses for the
create/update/delete iMIP announcements.
"""
from __future__ import annotations

import dataclasses
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from flask import g
from flask.typing import ResponseReturnValue
from flask.views import MethodView
from flask_smorest import Blueprint

from app.config.settings.DomainSettings import MailSettings, MailSettingsObj
from app.interface.calendar.InterfaceApiCalendarCalendar import InterfaceApiCalendarCalendar
from app.module.calendar.imip.ImipBuilder import ImipBuilder
from app.module.calendar.imip.ImipEmailBuilder import ImipEmailBuilder
from app.module.calendar.serializer.CalEventDeserializerDict import CalEventDeserializerDict
from app.module.mail.ModuleMailOutgoing import ModuleMailOutgoing
from app.utils import constants as cs
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.errors import (
    ERROR_CALENDAR_EVENT_NOT_FOUND,
    ERROR_CALENDAR_JSON_PARSE_FAILED,
    ERROR_CALENDAR_NOT_ORGANIZER,
    ERROR_NOT_FOUND,
    ERROR_SMTP_CONNECTION_FAILED,
)
from app.utils.logger.logger import logger_api
from .schemas.event import CalendarEventResponseSchema
from .schemas.invitation import (
    AttendeeListResponseSchema,
    InviteResponseSchema,
    RsvpUpdateSchema,
)

if TYPE_CHECKING:
    from app.module.calendar.imip.ImipMessage import ImipMessage
    from app.module.calendar.model.CalEvent import CalEvent

blp = Blueprint("Invitation", __name__, url_prefix="")


@blp.before_request
def init_invitation_config() -> None:  # pylint: disable=missing-function-docstring
    g.inter = InterfaceApiCalendarCalendar(
        process_setting=g.process_settings,
        user_domain_settings=g.user_domain_settings,
        user=g.user,
    )


def _outgoing_mailer() -> ModuleMailOutgoing:
    """Build the outgoing mail client from the current user's domain settings.

    Mirrors ``InterfaceApiCalendarCalendar._mail_outgoing``. The mail settings
    block is optional in unit tests (empty dict yields class-level defaults, so
    no live SMTP/LDAP/DB is ever touched at construction time).
    """
    domain_settings: dict[str, Any] = getattr(g, "user_domain_settings", None) or {}
    mail_settings: dict[str, Any] = domain_settings.get(MailSettings.subparent) or {}
    return ModuleMailOutgoing(g.user, MailSettingsObj(mail_settings))


@blp.route("/calendars/<string:key>/events/<string:event_key>/invite")
class ApiEventInvite(MethodView):
    """Send (or re-send) the calendar invitation to every attendee of an event."""

    @blp.response(200, InviteResponseSchema)
    def post(self, key: str, event_key: str) -> ResponseReturnValue:
        """Validate the event, build the iTIP REQUEST and deliver one email per attendee.

        Delivery is best-effort per recipient (iTIP requires one copy per attendee and a
        single unreachable address must not sink the batch), matching the calendar
        interface's ``_send_imip``. When every delivery fails the endpoint answers 503
        (service temporarily unavailable) so the client can retry; partial success is
        reported honestly in ``data.invited``.
        """
        logger_api.debug("POST /calendars/%s/events/%s/invite user=%s", key, event_key, g.user.uid)
        interface: InterfaceApiCalendarCalendar = g.inter
        envelope, status = interface.get_event(event_key)
        if status != HTTPStatus.OK:
            return envelope, status
        try:
            event: CalEvent = CalEventDeserializerDict().deserialize(envelope.get("data") or {})
        except (ValueError, KeyError, TypeError):
            logger_api.exception("Failed to deserialize event %s for invitation", event_key)
            return create_api_base_response(None, ERROR_CALENDAR_JSON_PARSE_FAILED)
        if event.organizer is None:
            return create_api_base_response(None, ERROR_CALENDAR_NOT_ORGANIZER)
        if not event.attendees:
            return create_api_base_response(None, ERROR_CALENDAR_EVENT_NOT_FOUND)
        imip: ImipMessage | None = ImipBuilder.build_request(event)
        if imip is None:
            return create_api_base_response(None, ERROR_CALENDAR_EVENT_NOT_FOUND)

        invited: list[str] = []
        mailer: ModuleMailOutgoing = _outgoing_mailer()
        for recipient in imip.to_emails:
            try:
                single: ImipMessage = dataclasses.replace(imip, to_emails=[recipient])
                mailer.send_raw_message(
                    cs.DEFAULT_IDENTITY_KEY_VALUE, ImipEmailBuilder.build_email(single)
                )
                invited.append(recipient)
            except Exception:  # pylint: disable=broad-exception-caught
                logger_api.exception(
                    "iMIP REQUEST send failed for event %s to %s", imip.event.uid, recipient,
                )
        if not invited:
            return create_api_base_response(None, ERROR_SMTP_CONNECTION_FAILED)
        return create_api_base_response({
            "event_key": event_key,
            "invited": invited,
            "total_attendees": len(event.attendees),
        })


@blp.route("/calendars/<string:key>/events/<string:event_key>/attendees")
class ApiEventAttendees(MethodView):
    """List the attendees of a calendar event."""

    @blp.response(200, AttendeeListResponseSchema)
    def get(self, key: str, event_key: str) -> ResponseReturnValue:
        """Return the event attendees (RFC 5545 ATTENDEE properties)."""
        logger_api.debug("GET /calendars/%s/events/%s/attendees user=%s", key, event_key, g.user.uid)
        interface: InterfaceApiCalendarCalendar = g.inter
        envelope, status = interface.get_event(event_key)
        if status != HTTPStatus.OK:
            return envelope, status
        attendees: list[dict[str, Any]] = (envelope.get("data") or {}).get("attendees") or []
        return create_api_base_response({
            "attendees": attendees,
            "total_count": len(attendees),
        })


@blp.route("/calendars/<string:key>/events/<string:event_key>/attendees/<string:attendee_id>")
class ApiEventAttendeeDetail(MethodView):
    """Manage a single attendee of a calendar event (RSVP tracking)."""

    @blp.arguments(RsvpUpdateSchema)
    @blp.response(200, CalendarEventResponseSchema)
    def put(self, body: dict, key: str, event_key: str, attendee_id: str) -> ResponseReturnValue:
        """Update the RSVP status (PARTSTAT) of one attendee, identified by email.

        The updated attendee list is persisted through the calendar interface
        (``patch_event``): the module re-validates access, stores the row and - for
        the organizer - re-announces the change to the attendees (iMIP REQUEST).
        """
        logger_api.debug(
            "PUT /calendars/%s/events/%s/attendees/%s user=%s status=%s",
            key, event_key, attendee_id, g.user.uid, body.get("status"),
        )
        interface: InterfaceApiCalendarCalendar = g.inter
        envelope, status = interface.get_event(event_key)
        if status != HTTPStatus.OK:
            return envelope, status
        attendees: list[dict[str, Any]] = (envelope.get("data") or {}).get("attendees") or []
        target: str = attendee_id.lower()
        emails = {(a.get("email") or "").lower() for a in attendees if isinstance(a, dict)}
        if target not in emails:
            return create_api_base_response(None, ERROR_NOT_FOUND)
        updated = [
            dict(a, status=body["status"]) if (a.get("email") or "").lower() == target else a
            for a in attendees
        ]
        return interface.patch_event(event_key, {"attendees": updated})
