"""Email-based Helpdesk / Ticketing (#51) — auto-create tickets from emails.

Tickets with assignment, SLA tracking, priority, status, and response history.
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

blp = Blueprint("Helpdesk / Ticketing", __name__, url_prefix="/tickets")

_PREFIX: str = "ticket:"


class TicketCreateSchema(Schema):
    subject = fields.String(required=True)
    description = fields.String(required=True)
    priority = fields.String(load_default="medium", validate=validate.OneOf(["low", "medium", "high", "urgent"]))
    requester_email = fields.String(load_default="")
    assignee_email = fields.String(load_default="")
    sla_hours = fields.Integer(load_default=48, metadata={"description": "SLA response time in hours"})


class TicketUpdateSchema(Schema):
    status = fields.String(validate=validate.OneOf(["open", "in_progress", "waiting", "resolved", "closed"]))
    priority = fields.String(validate=validate.OneOf(["low", "medium", "high", "urgent"]))
    assignee_email = fields.String()
    comment = fields.String(load_default="")


class TicketResponseSchema(Schema):
    body = fields.String(required=True)
    is_internal = fields.Boolean(load_default=False)


@blp.route("")
class ApiTicketListCreate(MethodView):
    def get(self) -> ResponseReturnValue:
        """List all tickets."""
        cache = sogo_cache()
        index = list(cache.get(f"{_PREFIX}index", list) or [])
        tickets = []
        for tid in index:
            raw = cache.get(f"{_PREFIX}{tid}", str)
            if raw:
                try:
                    tickets.append(json.loads(raw))
                except Exception:
                    continue
        tickets.sort(key=lambda t: t.get("created_at", 0), reverse=True)
        return create_api_base_response({"tickets": tickets})

    @blp.arguments(TicketCreateSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """Create a new ticket."""
        user: User = g.user
        cache = sogo_cache()
        ticket_id = f"TKT-{secrets.token_hex(4).upper()}"
        sla_deadline = int(time.time()) + body.get("sla_hours", 48) * 3600
        ticket = {
            "id": ticket_id,
            "subject": body["subject"],
            "description": body["description"],
            "priority": body.get("priority", "medium"),
            "requester_email": body.get("requester_email", user.uid),
            "assignee_email": body.get("assignee_email", ""),
            "status": "open",
            "created_by": user.uid,
            "created_at": int(time.time()),
            "sla_deadline": sla_deadline,
            "responses": [],
        }
        cache.set(f"{_PREFIX}{ticket_id}", json.dumps(ticket), ttl=86400 * 365)
        idx = list(cache.get(f"{_PREFIX}index", list) or [])
        idx.append(ticket_id)
        cache.set(f"{_PREFIX}index", idx, ttl=86400 * 365)
        logger_api.info("Ticket created: %s by %s", ticket_id, user.uid)
        return create_api_base_response(ticket, code=201)


@blp.route("/<string:ticket_id>")
class ApiTicketDetail(MethodView):
    def get(self, ticket_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_PREFIX}{ticket_id}", str)
        if not raw:
            return create_api_base_response(None, err.ERROR_NOT_FOUND)
        return create_api_base_response(json.loads(raw))

    @blp.arguments(TicketUpdateSchema)
    def patch(self, body: dict, ticket_id: str) -> ResponseReturnValue:
        user: User = g.user
        cache = sogo_cache()
        raw = cache.get(f"{_PREFIX}{ticket_id}", str)
        if not raw:
            return create_api_base_response(None, err.ERROR_NOT_FOUND)
        ticket = json.loads(raw)
        if "status" in body:
            ticket["status"] = body["status"]
        if "priority" in body:
            ticket["priority"] = body["priority"]
        if "assignee_email" in body:
            ticket["assignee_email"] = body["assignee_email"]
        if body.get("comment"):
            ticket["responses"].append({
                "author": user.uid,
                "body": body["comment"],
                "is_internal": False,
                "at": int(time.time()),
            })
        ticket["updated_at"] = int(time.time())
        cache.set(f"{_PREFIX}{ticket_id}", json.dumps(ticket), ttl=86400 * 365)
        return create_api_base_response(ticket)


@blp.route("/<string:ticket_id>/respond")
class ApiTicketRespond(MethodView):
    @blp.arguments(TicketResponseSchema)
    def post(self, body: dict, ticket_id: str) -> ResponseReturnValue:
        user: User = g.user
        cache = sogo_cache()
        raw = cache.get(f"{_PREFIX}{ticket_id}", str)
        if not raw:
            return create_api_base_response(None, err.ERROR_NOT_FOUND)
        ticket = json.loads(raw)
        ticket["responses"].append({
            "author": user.uid,
            "body": body["body"],
            "is_internal": body.get("is_internal", False),
            "at": int(time.time()),
        })
        cache.set(f"{_PREFIX}{ticket_id}", json.dumps(ticket), ttl=86400 * 365)
        return create_api_base_response({"status": "response_recorded"})
