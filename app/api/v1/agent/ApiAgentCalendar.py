"""Agent facade — calendar actions.

Events CRUD with one-call invitations, freebusy, appointment slots and
attendance responses — thin delegation to InterfaceApiCalendarCalendar.
"""
import json

from flask import g, request
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from marshmallow import Schema, fields, validate

from app.service import sogo_cache
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response, ApiBaseResponse
from app.utils.logger.logger import logger_api

from . import agent_blueprint, calendar_interface, register_action, require_scope

blp = agent_blueprint("Agent Calendar", "/agent/calendar", "Agent calendar actions")

_SLOT_PREFIX: str = "appt_slot:"
_BOOKING_PREFIX: str = "appt_booking:"


# ── Schemas (OpenAPI contract) ─────────────────────────────────────────────

class AgentEventCreateSchema(Schema):
    """Create payload: title/start/end + attendees; unknown fields pass through."""

    class Meta:
        unknown = "include"

    title = fields.String(required=True, metadata={"description": "Event title/summary"})
    start = fields.Raw(required=True, metadata={"description": "Start datetime (ISO 8601)"})
    end = fields.Raw(required=True, metadata={"description": "End datetime (ISO 8601)"})
    attendees = fields.List(fields.Raw(), load_default=list,
                            metadata={"description": "Attendee list; invitations dispatched in the same call"})
    calendar_key = fields.String(load_default=None, allow_none=True,
                                 metadata={"description": "Target calendar; default = first personal calendar"})


class AgentEventPatchSchema(Schema):
    """Partial update; attendee changes trigger invitations."""

    class Meta:
        unknown = "include"


class AgentInvitationRespondSchema(Schema):
    status = fields.String(required=True, validate=validate.OneOf(["accepted", "tentative", "declined"]))


class AgentSlotBookSchema(Schema):
    date = fields.String(required=True, metadata={"description": "Slot date (ISO 8601)"})
    time = fields.String(required=True, metadata={"description": "Slot time (HH:MM)"})


class AgentCalendarEnvelopeSchema(ApiBaseResponse):
    data = fields.Dict(required=False, allow_none=True)


def _events_query_args() -> dict:
    """Map agent query params (from/to) to the calendar event query args."""
    from app.api.v1.calendar.schemas.event import CalendarEventQueryArgsSchema
    raw = {
        "start_date_time": request.args.get("from") or None,
        "end_date_time": request.args.get("to") or None,
        "search": request.args.get("search") or None,
    }
    return CalendarEventQueryArgsSchema().load(raw)


def _default_calendar_key(interface) -> str | None:
    """First personal calendar key of the user (for create without calendar_key)."""
    response, status = interface.get_all_calendars()
    if status >= 400:
        return None
    calendars = (response.get("data") or {}).get("calendars") or response.get("data") or []
    if isinstance(calendars, dict):
        calendars = list(calendars.values())
    for cal in calendars:
        if isinstance(cal, dict) and cal.get("key"):
            return cal["key"]
    return None


# ── Events ───────────────────────────────────────────────────────────────────

@blp.route("/events")
class AgentCalendarEvents(MethodView):
    """List events across calendars in a time range, or create one."""

    def get(self) -> ResponseReturnValue:
        """Events between ?from= and ?to= (ISO 8601 UTC), recurrence expanded."""
        guard = require_scope("calendar:read")
        if guard is not None:
            return guard

        calendar_key = request.args.get("calendar_key")
        response, status = calendar_interface().get_events(calendar_key, _events_query_args())
        return response, status

    @blp.arguments(AgentEventCreateSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """Create an event with attendees (invitations dispatched) in one call."""
        guard = require_scope("calendar:write")
        if guard is not None:
            return guard

        interface = calendar_interface()
        calendar_key = body.pop("calendar_key", None)
        if not calendar_key:
            calendar_key = _default_calendar_key(interface)
            if not calendar_key:
                return create_api_base_response(None, err.ERROR_NOT_FOUND)
        logger_api.info("Agent event create: user=%s calendar=%s attendees=%d",
                        g.user.uid, calendar_key, len(body.get("attendees") or []))
        return interface.create_event(calendar_key, body)


@blp.route("/events/<string:event_key>")
class AgentCalendarEventDetail(MethodView):
    """Fetch, patch or delete a single event."""

    def get(self, event_key: str) -> ResponseReturnValue:
        guard = require_scope("calendar:read")
        if guard is not None:
            return guard
        return calendar_interface().get_event(event_key)

    @blp.arguments(AgentEventPatchSchema)
    def patch(self, body: dict, event_key: str) -> ResponseReturnValue:
        """Partial update (title, time, attendees, …) — invitations dispatched."""
        guard = require_scope("calendar:write")
        if guard is not None:
            return guard
        logger_api.info("Agent event patch: user=%s event=%s fields=%s",
                        g.user.uid, event_key, sorted(body.keys()))
        return calendar_interface().patch_event(event_key, body)

    def delete(self, event_key: str) -> ResponseReturnValue:
        guard = require_scope("calendar:write")
        if guard is not None:
            return guard
        from app.api.v1.calendar.schemas.event import CalendarEventDeleteArgsSchema
        args = CalendarEventDeleteArgsSchema().load(request.args)
        return calendar_interface().delete_event(event_key, recurrence_id=args.get("recurrence_id"))


# ── Freebusy ─────────────────────────────────────────────────────────────────

@blp.route("/freebusy")
class AgentCalendarFreebusy(MethodView):
    """Free/busy periods for target users."""

    def get(self) -> ResponseReturnValue:
        """?uids=user1,user2&from=...&to=... — same contract as UI freebusy."""
        guard = require_scope("calendar:read")
        if guard is not None:
            return guard

        uids_raw = request.args.get("uids", "")
        target_uids = [u.strip() for u in uids_raw.split(",") if u.strip()]
        if not target_uids or not request.args.get("from") or not request.args.get("to"):
            return create_api_base_response(None, err.ERROR_VALIDATION_FAILED)
        body = {
            "target_uids": target_uids,
            "start": request.args.get("from"),
            "end": request.args.get("to"),
        }
        return calendar_interface().get_freebusy(body)


# ── Appointment slots ────────────────────────────────────────────────────────

@blp.route("/slots")
class AgentCalendarSlots(MethodView):
    """List appointment slots (booking pages)."""

    def get(self) -> ResponseReturnValue:
        guard = require_scope("calendar:read")
        if guard is not None:
            return guard
        cache = sogo_cache()
        raw = cache.get(f"{_SLOT_PREFIX}index:{g.user.uid}", list)
        index = raw if isinstance(raw, list) else []
        slots = []
        for sid in index:
            raw_slot = cache.get(f"{_SLOT_PREFIX}{sid}", str)
            if raw_slot:
                try:
                    slots.append(json.loads(raw_slot))
                except Exception:
                    continue
        return create_api_base_response({"slots": slots})


@blp.route("/slots/<string:slot_id>/book")
class AgentCalendarSlotBook(MethodView):
    """Book an appointment slot as the current user."""

    @blp.arguments(AgentSlotBookSchema)
    def post(self, body: dict, slot_id: str) -> ResponseReturnValue:
        guard = require_scope("calendar:write")
        if guard is not None:
            return guard
        cache = sogo_cache()
        raw = cache.get(f"{_SLOT_PREFIX}{slot_id}", str)
        if not raw:
            return create_api_base_response(None, err.ERROR_NOT_FOUND)
        slot = json.loads(raw)
        booking_contact = {
            "name": g.user.cn or g.user.uid,
            "email": g.user.mail or g.user.uid,
            "date": body["date"],
            "time": body["time"],
        }
        import secrets
        import time as _time
        booking_id = secrets.token_hex(12)
        booking = {
            "id": booking_id, "slot_id": slot_id,
            "name": booking_contact["name"], "email": booking_contact["email"],
            "date": booking_contact["date"], "time": booking_contact["time"],
            "created_at": int(_time.time()),
        }
        cache.set(f"{_BOOKING_PREFIX}{booking_id}", json.dumps(booking), ttl=86400 * 30)
        index_key = f"{_BOOKING_PREFIX}index:{slot_id}"
        raw_index = cache.get(index_key, list)
        index = raw_index if isinstance(raw_index, list) else []
        index.append(booking_id)
        cache.set(index_key, index, ttl=86400 * 365)
        return create_api_base_response({"booking_id": booking_id})


# ── Invitations ──────────────────────────────────────────────────────────────

@blp.route("/invitations/<string:event_key>/respond")
class AgentCalendarInvitationRespond(MethodView):
    """Respond to an event invitation (accept/tentative/decline)."""

    @blp.arguments(AgentInvitationRespondSchema)
    def post(self, body: dict, event_key: str) -> ResponseReturnValue:
        """Body: {status: accepted|declined|tentative}."""
        guard = require_scope("calendar:write")
        if guard is not None:
            return guard
        logger_api.info("Agent invitation respond: user=%s event=%s status=%s",
                        g.user.uid, event_key, body.get("status"))
        return calendar_interface().set_attendance_status(event_key, body)


# ── Registry ─────────────────────────────────────────────────────────────────

register_action("calendar.events.list", "GET", "/api/user/v1/agent/calendar/events",
                "List events in a time range (?from&to, recurrence expanded)", "calendar:read")
register_action("calendar.events.get", "GET", "/api/user/v1/agent/calendar/events/{key}",
                "Get one event", "calendar:read")
register_action("calendar.events.create", "POST", "/api/user/v1/agent/calendar/events",
                "Create event with attendees (invitations dispatched) in one call", "calendar:write")
register_action("calendar.events.update", "PATCH", "/api/user/v1/agent/calendar/events/{key}",
                "Partial event update (invitations dispatched on attendee change)", "calendar:write")
register_action("calendar.events.delete", "DELETE", "/api/user/v1/agent/calendar/events/{key}",
                "Delete an event (or one occurrence via ?recurrence_id)", "calendar:write")
register_action("calendar.freebusy", "GET", "/api/user/v1/agent/calendar/freebusy",
                "Free/busy periods (?uids=&from=&to=)", "calendar:read")
register_action("calendar.slots.list", "GET", "/api/user/v1/agent/calendar/slots",
                "List appointment slots", "calendar:read")
register_action("calendar.slots.book", "POST", "/api/user/v1/agent/calendar/slots/{slot_id}/book",
                "Book an appointment slot as the current user", "calendar:write")
register_action("calendar.invitations.respond", "POST", "/api/user/v1/agent/calendar/invitations/{event_key}/respond",
                "Respond to an event invitation (accepted/tentative/declined)", "calendar:write")
