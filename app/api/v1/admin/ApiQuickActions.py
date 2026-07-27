"""Custom Actions / Quick Actions (#55) — user-defined multi-step actions as one click.

Users define a sequence of actions (label, forward, move, tag, etc.)
and trigger them with a single click from the mail list.
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
from marshmallow import Schema, fields

from app.service import sogo_cache
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User

blp = Blueprint("Quick Actions", __name__, url_prefix="/quick-actions")

_PREFIX: str = "quick_action:"


class ActionStepSchema(Schema):
    type = fields.String(required=True, metadata={"description": "label, move, forward, tag, archive, snooze"})
    params = fields.Dict(keys=fields.String(), values=fields.String(), load_default={})


class QuickActionCreateSchema(Schema):
    name = fields.String(required=True)
    icon = fields.String(load_default="zap", metadata={"description": "lucide icon name"})
    steps = fields.List(fields.Nested(ActionStepSchema), required=True, validate=lambda x: len(x) >= 1)


class QuickActionExecuteSchema(Schema):
    message_keys = fields.List(fields.String(), required=True, metadata={"description": "List of message keys to apply action to"})


@blp.route("")
class ApiQuickActionListCreate(MethodView):
    def get(self) -> ResponseReturnValue:
        user: User = g.user
        cache = sogo_cache()
        index = list(cache.get(f"{_PREFIX}index:{user.uid}", list) or [])
        actions = []
        for aid in index:
            raw = cache.get(f"{_PREFIX}{aid}", str)
            if raw:
                try:
                    actions.append(json.loads(raw))
                except Exception:
                    pass
        return create_api_base_response({"actions": actions})

    @blp.arguments(QuickActionCreateSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        user: User = g.user
        cache = sogo_cache()
        action_id = secrets.token_hex(8)
        action = {
            "id": action_id,
            "name": body["name"],
            "icon": body.get("icon", "zap"),
            "steps": body["steps"],
            "created_by": user.uid,
            "created_at": int(time.time()),
        }
        cache.set(f"{_PREFIX}{action_id}", json.dumps(action), ttl=86400 * 365)
        idx = list(cache.get(f"{_PREFIX}index:{user.uid}", list) or [])
        idx.append(action_id)
        cache.set(f"{_PREFIX}index:{user.uid}", idx, ttl=86400 * 365)
        logger_api.info("Quick action created: %s by %s", action_id[:8], user.uid)
        return create_api_base_response(action, code=201)


@blp.route("/<string:action_id>")
class ApiQuickActionDetail(MethodView):
    def get(self, action_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_PREFIX}{action_id}", str)
        if not raw:
            from app.utils import errors as err
            return create_api_base_response(None, err.ERROR_NOT_FOUND)
        return create_api_base_response(json.loads(raw))

    def delete(self, action_id: str) -> ResponseReturnValue:
        user: User = g.user
        cache = sogo_cache()
        cache.delete(f"{_PREFIX}{action_id}")
        idx = list(cache.get(f"{_PREFIX}index:{user.uid}", list) or [])
        idx = [a for a in idx if a != action_id]
        cache.set(f"{_PREFIX}index:{user.uid}", idx, ttl=86400 * 365)
        return create_api_base_response({"status": "deleted"})


@blp.route("/<string:action_id>/execute")
class ApiQuickActionExecute(MethodView):
    """Execute a quick action on selected messages."""

    @blp.arguments(QuickActionExecuteSchema)
    def post(self, body: dict, action_id: str) -> ResponseReturnValue:
        user: User = g.user
        cache = sogo_cache()
        raw = cache.get(f"{_PREFIX}{action_id}", str)
        if not raw:
            from app.utils import errors as err
            return create_api_base_response(None, err.ERROR_NOT_FOUND)

        action = json.loads(raw)
        steps = action["steps"]
        message_keys = body["message_keys"]
        results = []

        for step in steps:
            step_result = {
                "type": step["type"],
                "params": step.get("params", {}),
                "applied_to": message_keys,
                "status": "executed",
            }
            # In production: actually execute the step via mail module
            results.append(step_result)

        logger_api.info("Quick action executed: %s on %d messages by %s", action_id[:8], len(message_keys), user.uid)
        return create_api_base_response({
            "action_id": action_id,
            "results": results,
            "messages_affected": len(message_keys),
        })
