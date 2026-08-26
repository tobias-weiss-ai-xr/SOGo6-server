"""Approval Workflows (#50) — email-based approval chains.

Define multi-step approval workflows: submit, approve, reject, comment.
Tracks state machine: pending → approved/rejected → completed.
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

blp = Blueprint("Approval Workflows", __name__, url_prefix="/approvals")

_PREFIX: str = "approval:"


class ApprovalCreateSchema(Schema):
    title = fields.String(required=True)
    description = fields.String(load_default="")
    category = fields.String(load_default="general", metadata={"description": "purchase_order, announcement, leave_request, general"})
    steps = fields.List(fields.Dict(keys=fields.String(), values=fields.String()), required=True, metadata={"description": "List of {approver_email: role}"})


class ApprovalActionSchema(Schema):
    action = fields.String(required=True, validate=validate.OneOf(["approve", "reject", "comment"]))
    comment = fields.String(load_default="")


@blp.route("")
class ApiApprovalListCreate(MethodView):
    def get(self) -> ResponseReturnValue:
        """List approvals involving the current user."""
        user: User = getattr(g, "user", None)
        if user is None:
            return create_api_base_response({"approvals": []})
        cache = sogo_cache()
        index = list(cache.get(f"{_PREFIX}index:{user.uid}", list) or [])
        approvals = []
        seen = set()
        for aid in index:
            if aid in seen:
                continue
            seen.add(aid)
            raw = cache.get(f"{_PREFIX}{aid}", str)
            if raw:
                try:
                    approvals.append(json.loads(raw))
                except Exception:
                    continue
        approvals.sort(key=lambda a: a.get("created_at", 0), reverse=True)
        return create_api_base_response({"approvals": approvals})

    @blp.arguments(ApprovalCreateSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """Create a new approval workflow."""
        user: User = getattr(g, "user", None)
        if user is None:
            return create_api_base_response(None, "User context not available")
        cache = sogo_cache()
        approval_id = secrets.token_hex(12)
        steps = body["steps"]
        approval = {
            "id": approval_id,
            "title": body["title"],
            "description": body.get("description", ""),
            "category": body.get("category", "general"),
            "created_by": user.uid,
            "created_at": int(time.time()),
            "steps": steps,
            "current_step": 0,
            "status": "pending",
            "history": [],
        }
        cache.set(f"{_PREFIX}{approval_id}", json.dumps(approval), ttl=86400 * 90)
        for email in steps:
            idx = list(cache.get(f"{_PREFIX}index:{email}", list) or [])
            idx.append(approval_id)
            cache.set(f"{_PREFIX}index:{email}", idx, ttl=86400 * 90)
        logger_api.info("Approval workflow created: %s by %s", approval_id[:8], user.uid)
        return create_api_base_response(approval, code=201)


@blp.route("/<string:approval_id>/action")
class ApiApprovalAction(MethodView):
    """Approve, reject, or comment on a workflow step."""

    @blp.arguments(ApprovalActionSchema)
    def post(self, body: dict, approval_id: str) -> ResponseReturnValue:
        user: User = g.user
        cache = sogo_cache()
        raw = cache.get(f"{_PREFIX}{approval_id}", str)
        if not raw:
            return create_api_base_response(None, err.ERROR_NOT_FOUND)

        approval = json.loads(raw)
        if approval["status"] not in ("pending", "in_review"):
            return create_api_base_response(None, err.ERROR_BAD_REQUEST, error_msg="Workflow already completed")

        action = body["action"]
        comment = body.get("comment", "")

        approval["history"].append({
            "actor": user.uid,
            "action": action,
            "comment": comment,
            "at": int(time.time()),
        })

        if action == "approve":
            approval["current_step"] += 1
            if approval["current_step"] >= len(approval["steps"]):
                approval["status"] = "approved"
            else:
                approval["status"] = "in_review"
        elif action == "reject":
            approval["status"] = "rejected"

        cache.set(f"{_PREFIX}{approval_id}", json.dumps(approval), ttl=86400 * 90)
        return create_api_base_response(approval)
