"""Appointment Slots (#47) — publish bookable time slots (Calendly-style).

Users define available time blocks, generate a booking link, and
external participants can book a slot without needing a SOGo account.
"""
from __future__ import annotations

import json
import secrets
import time
from typing import TYPE_CHECKING

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate

from app.service import sogo_cache
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User

blp = Blueprint("Appointment Slots", __name__, url_prefix="/appointment-slots")

_SLOT_PREFIX: str = "appt_slot:"
_BOOKING_PREFIX: str = "appt_booking:"


class SlotConfigSchema(Schema):
    duration_minutes = fields.Integer(required=True, validate=validate.Range(min=15, max=240))
    start_time = fields.String(required=True, metadata={"description": "HH:MM format, e.g. 09:00"})
    end_time = fields.String(required=True, metadata={"description": "HH:MM format, e.g. 17:00"})
    days_of_week = fields.List(fields.Integer(validate=validate.Range(min=0, max=6)), required=True, metadata={"description": "0=Sunday, 6=Saturday"})
    buffer_minutes = fields.Integer(load_default=0)
    max_bookings_per_day = fields.Integer(load_default=1)


class SlotCreateSchema(SlotConfigSchema):
    title = fields.String(required=True)
    description = fields.String(load_default="")


@blp.route("")
class ApiSlotListCreate(MethodView):
    def get(self) -> ResponseReturnValue:
        user: User = g.user
        cache = sogo_cache()
        raw = cache.get(f"{_SLOT_PREFIX}index:{user.uid}", list)
        index = raw if isinstance(raw, list) else []
        slots = []
        for sid in index:
            raw_slot = cache.get(f"{_SLOT_PREFIX}{sid}", str)
            if raw_slot:
                try:
                    slots.append(json.loads(raw_slot))
                except Exception:
                    continue
        return create_api_base_response({"slots"})

    @blp.arguments(SlotCreateSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        user: User = g.user
        cache = sogo_cache()
        slot_id = secrets.token_hex(10)
        token = secrets.token_hex(20)
        slot = {
            "id": slot_id,
            "user_uid": user.uid,
            "title": body["title"],
            "description": body.get("description", ""),
            "duration_minutes": body["duration_minutes"],
            "start_time": body["start_time"],
            "end_time": body["end_time"],
            "days_of_week": body["days_of_week"],
            "buffer_minutes": body.get("buffer_minutes", 0),
            "max_bookings_per_day": body.get("max_bookings_per_day", 1),
            "token": token,
            "created_at": int(time.time()),
            "enabled": True,
        }
        cache.set(f"{_SLOT_PREFIX}{slot_id}", json.dumps(slot), ttl=86400 * 365)
        idx = list(cache.get(f"{_SLOT_PREFIX}index:{user.uid}", list) or [])
        idx.append(slot_id)
        cache.set(f"{_SLOT_PREFIX}index:{user.uid}", idx, ttl=86400 * 365)

        booking_url = f"/book/{slot_id}?token={token}"
        logger_api.info("Appointment slot created: %s by %s", slot_id[:8], user.uid)
        return create_api_base_response({**slot, "booking_url": booking_url}, code=201)


class BookingCreateSchema(Schema):
    name = fields.String(required=True)
    email = fields.String(required=True)
    date = fields.String(required=True, metadata={"description": "YYYY-MM-DD"})
    time = fields.String(required=True, metadata={"description": "HH:MM"})


@blp.route("/<string:slot_id>/book")
class ApiSlotBook(MethodView):
    """Book an appointment slot (public, no auth required)."""
    @blp.arguments(BookingCreateSchema)
    def post(self, body: dict, slot_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_SLOT_PREFIX}{slot_id}", str)
        if not raw:
            return create_api_base_response(None, err.ERROR_NOT_FOUND)
        slot = json.loads(raw)
        if not slot.get("enabled"):
            return create_api_base_response(None, err.ERROR_SLOT_DISABLED)

        booking_id = secrets.token_hex(12)
        booking = {
            "id": booking_id,
            "slot_id": slot_id,
            "name": body["name"],
            "email": body["email"],
            "date": body["date"],
            "time": body["time"],
            "created_at": int(time.time()),
        }
        cache.set(f"{_BOOKING_PREFIX}{booking_id}", json.dumps(booking), ttl=86400 * 30)
        logger_api.info("Appointment booked: slot=%s by %s", slot_id[:8], body["email"])
        return create_api_base_response(booking, code=201)


@blp.route("/bookings")
class ApiSlotBookings(MethodView):
    """List bookings for the current user's slots."""
    def get(self) -> ResponseReturnValue:
        user: User = g.user
        cache = sogo_cache()
        raw = cache.get(f"{_SLOT_PREFIX}index:{user.uid}", list)
        index = raw if isinstance(raw, list) else []
        bookings = []
        for sid in index:
            raw_slot = cache.get(f"{_SLOT_PREFIX}{sid}", str)
            if raw_slot:
                # Find bookings for this slot
                all_raw = cache.get(f"{_BOOKING_PREFIX}index:{sid}", list)
                all_b = all_raw if isinstance(all_raw, list) else []
                for bid in all_b:
                    raw_b = cache.get(f"{_BOOKING_PREFIX}{bid}", str)
                    if raw_b:
                        try:
                            bookings.append(json.loads(raw_b))
                        except Exception:
                            continue
        return create_api_base_response({"bookings": bookings})
