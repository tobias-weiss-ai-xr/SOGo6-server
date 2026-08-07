"""Workflow Builder (#54) — low-code rule engine.

Define workflows: "If email from X and subject Y → forward, create event, notify".
Uses JSON-based rule definitions stored in Redis.
"""
from __future__ import annotations

import json
import secrets
import time
from typing import TYPE_CHECKING

from flask import g, request
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.service import sogo_cache
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User

blp = Blueprint("Workflow Builder", __name__, url_prefix="/workflows")

_PREFIX: str = "workflow:"


class WorkflowCreateSchema(Schema):
    name = fields.String(required=True)
    description = fields.String(load_default="")
    trigger_type = fields.String(required=True, metadata={"description": "email_received, calendar_event, user_created"})
    conditions = fields.List(fields.Dict(keys=fields.String()), required=True, metadata={"description": "List of {field, operator, value}"})
    actions = fields.List(fields.Dict(keys=fields.String()), required=True, metadata={"description": "List of {type, params}"})
    enabled = fields.Boolean(load_default=True)


class WorkflowToggleSchema(Schema):
    enabled = fields.Boolean(required=True)


@blp.route("")
class ApiWorkflowListCreate(MethodView):
    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        index = list(cache.get(f"{_PREFIX}index", list) or [])
        workflows = []
        for wid in index:
            raw = cache.get(f"{_PREFIX}{wid}", str)
            if raw:
                try:
                    workflows.append(json.loads(raw))
                except Exception:
                    continue
        return create_api_base_response({"workflows": workflows})

    @blp.arguments(WorkflowCreateSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        user: User = g.user
        cache = sogo_cache()
        wf_id = secrets.token_hex(10)
        workflow = {
            "id": wf_id,
            "name": body["name"],
            "description": body.get("description", ""),
            "trigger_type": body["trigger_type"],
            "conditions": body["conditions"],
            "actions": body["actions"],
            "enabled": body.get("enabled", True),
            "created_by": user.uid,
            "created_at": int(time.time()),
            "last_triggered": None,
            "trigger_count": 0,
        }
        cache.set(f"{_PREFIX}{wf_id}", json.dumps(workflow), ttl=86400 * 365)
        idx = list(cache.get(f"{_PREFIX}index", list) or [])
        idx.append(wf_id)
        cache.set(f"{_PREFIX}index", idx, ttl=86400 * 365)
        logger_api.info("Workflow created: %s by %s", wf_id[:8], user.uid)
        return create_api_base_response(workflow, code=201)


@blp.route("/<string:workflow_id>")
class ApiWorkflowDetail(MethodView):
    def get(self, workflow_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_PREFIX}{workflow_id}", str)
        if not raw:
            from app.utils import errors as err
            return create_api_base_response(None, err.ERROR_NOT_FOUND)
        return create_api_base_response(json.loads(raw))

    @blp.arguments(WorkflowToggleSchema)
    def patch(self, body: dict, workflow_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_PREFIX}{workflow_id}", str)
        if not raw:
            from app.utils import errors as err
            return create_api_base_response(None, err.ERROR_NOT_FOUND)
        wf = json.loads(raw)
        wf["enabled"] = body["enabled"]
        cache.set(f"{_PREFIX}{workflow_id}", json.dumps(wf), ttl=86400 * 365)
        return create_api_base_response(wf)

    def delete(self, workflow_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_PREFIX}{workflow_id}", str)
        if not raw:
            from app.utils import errors as err
            return create_api_base_response(None, err.ERROR_NOT_FOUND)
        cache.delete(f"{_PREFIX}{workflow_id}")
        idx = list(cache.get(f"{_PREFIX}index", list) or [])
        idx = [w for w in idx if w != workflow_id]
        cache.set(f"{_PREFIX}index", idx, ttl=86400 * 365)
        return create_api_base_response({"status": "deleted"})


@blp.route("/<string:workflow_id>/test")
class ApiWorkflowTest(MethodView):
    """Dry-run a workflow against test data."""
    def post(self, workflow_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_PREFIX}{workflow_id}", str)
        if not raw:
            from app.utils import errors as err
            return create_api_base_response(None, err.ERROR_NOT_FOUND)
        wf = json.loads(raw)
        test_data = request.get_json(force=True) if hasattr(request, 'get_json') else {}
        matched = True
        for cond in wf.get("conditions", []):
            field = cond.get("field", "")
            op = cond.get("operator", "equals")
            val = cond.get("value", "")
            actual = test_data.get(field, "")
            if op == "equals" and actual != val:
                matched = False
            elif op == "contains" and val not in actual:
                matched = False
            elif op == "starts_with" and not actual.startswith(val):
                matched = False
        return create_api_base_response({
            "workflow_id": workflow_id,
            "matched": matched,
            "actions": wf["actions"] if matched else [],
            "would_execute": matched,
        })
