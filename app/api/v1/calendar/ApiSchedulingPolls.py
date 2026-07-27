"""Scheduling Polls (#46) — "When are you free?" polls.

Users create a poll with proposed time slots, invite participants
(internal and external), and collect responses.
"""
from __future__ import annotations

import json
import secrets
import time
from typing import TYPE_CHECKING, Any

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

blp = Blueprint("Scheduling Polls", __name__, url_prefix="/polls")

_POLL_PREFIX: str = "poll:"


class TimeSlotSchema(Schema):
    start = fields.String(required=True, metadata={"description": "ISO 8601 start time"})
    end = fields.String(required=True, metadata={"description": "ISO 8601 end time"})


class PollCreateSchema(Schema):
    title = fields.String(required=True)
    description = fields.String(load_default="")
    time_slots = fields.List(fields.Nested(TimeSlotSchema), required=True, validate=validate.Length(min=1))
    participants = fields.List(fields.String(), required=True, metadata={"description": "Email addresses of participants"})
    expires_at = fields.Integer(load_default=None, allow_none=True, metadata={"description": "Unix timestamp when poll closes"})


class PollResponseSchema(Schema):
    participant = fields.String()
    available_slots = fields.List(fields.String(), metadata={"description": "List of time slot indices that work"})


@blp.route("")
class ApiPollListCreate(MethodView):
    def get(self) -> ResponseReturnValue:
        """List polls created by or involving the current user."""
        user: User = g.user
        cache = sogo_cache()
        raw = cache.get(f"{_POLL_PREFIX}index:{user.uid}", list)
        index = raw if isinstance(raw, list) else []
        polls = []
        for pid in index:
            raw_poll = cache.get(f"{_POLL_PREFIX}{pid}", str)
            if raw_poll:
                try:
                    polls.append(json.loads(raw_poll))
                except Exception:
                    pass
        return create_api_base_response({"polls": polls})

    @blp.arguments(PollCreateSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """Create a new scheduling poll."""
        user: User = g.user
        cache = sogo_cache()
        poll_id = secrets.token_hex(12)
        token = secrets.token_hex(24)
        poll = {
            "id": poll_id,
            "title": body["title"],
            "description": body.get("description", ""),
            "time_slots": body["time_slots"],
            "participants": body["participants"],
            "created_by": user.uid,
            "created_at": int(time.time()),
            "expires_at": body.get("expires_at"),
            "token": token,
            "responses": [],
            "status": "open",
        }
        cache.set(f"{_POLL_PREFIX}{poll_id}", json.dumps(poll), ttl=86400 * 30)

        # Add to creator's index
        idx = list(cache.get(f"{_POLL_PREFIX}index:{user.uid}", list) or [])
        idx.append(poll_id)
        cache.set(f"{_POLL_PREFIX}index:{user.uid}", idx, ttl=86400 * 30)

        logger_api.info("Scheduling poll created: %s by %s", poll_id[:8], user.uid)
        return create_api_base_response(poll, code=201)


@blp.route("/<string:poll_id>/respond")
class ApiPollRespond(MethodView):
    """Respond to a scheduling poll."""

    @blp.arguments(PollResponseSchema)
    def post(self, body: dict, poll_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_POLL_PREFIX}{poll_id}", str)
        if not raw:
            return create_api_base_response(None, err.ERROR_NOT_FOUND)
        poll = json.loads(raw)
        if poll.get("status") != "open":
            return create_api_base_response(None, err.ERROR_POLL_CLOSED)
        if body["participant"] not in poll["participants"]:
            return create_api_base_response(None, err.ERROR_POLL_PARTICIPANT_NOT_FOUND)

        # Remove previous response from this participant
        poll["responses"] = [r for r in poll["responses"] if r.get("participant") != body["participant"]]
        poll["responses"].append({
            "participant": body["participant"],
            "available_slots": body["available_slots"],
            "responded_at": int(time.time()),
        })
        cache.set(f"{_POLL_PREFIX}{poll_id}", json.dumps(poll), ttl=86400 * 30)
        return create_api_base_response({"status": "recorded"})


@blp.route("/<string:poll_id>/results")
class ApiPollResults(MethodView):
    """Get poll results."""
    def get(self, poll_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_POLL_PREFIX}{poll_id}", str)
        if not raw:
            return create_api_base_response(None, err.ERROR_NOT_FOUND)
        poll = json.loads(raw)
        # Find best time slot
        slot_counts = {}
        for r in poll.get("responses", []):
            for slot_idx in r.get("available_slots", []):
                slot_counts[slot_idx] = slot_counts.get(slot_idx, 0) + 1
        best_slot = max(slot_counts, key=slot_counts.get) if slot_counts else None
        return create_api_base_response({
            "poll": poll,
            "response_count": len(poll.get("responses", [])),
            "participant_count": len(poll.get("participants", [])),
            "best_slot": best_slot,
            "slot_counts": slot_counts,
        })
