"""SCIM Provisioning (#66) — enterprise identity lifecycle.

SCIM 2.0-compatible user provisioning endpoints for Azure AD, Okta, and
other identity providers. Syncs users into SOGo via OpenLDAP.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from typing import TYPE_CHECKING

from flask import request, Response
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate

from app.service import sogo_cache
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User

blp = Blueprint("SCIM Provisioning", __name__, url_prefix="/scim/v2")

_SCIM_PREFIX: str = "scim_user:"


def _verify_scim_token() -> bool:
    """Verify SCIM bearer token from incoming request.

    The ``SCIM_BEARER_TOKEN`` environment variable **must** be set to a
    non-empty value for SCIM requests to succeed.  When it is unset or empty,
    all requests are rejected — there is no "open" fallback.
    """
    configured_token = os.environ.get("SCIM_BEARER_TOKEN", "")
    if not configured_token:
        # SCIM is not configured — reject all requests with a clear error
        return False

    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        return False

    return hmac.compare_digest(token, configured_token)


def _scim_error(status: int, scim_code: str, detail: str) -> ResponseReturnValue:
    """Return a SCIM 2.0 error response."""
    return Response(
        json.dumps({
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
            "detail": detail,
            "status": str(status),
            "scimType": scim_code,
        }),
        status=status,
        content_type="application/scim+json",
    )


class ScimListSchema(Schema):
    startIndex = fields.Integer(load_default=1)
    count = fields.Integer(load_default=100)
    filter = fields.String(load_default="")


class ScimUserCreateSchema(Schema):
    userName = fields.Email(required=True)
    displayName = fields.String(required=True)
    name = fields.Dict(keys=fields.String(), values=fields.String(), load_default={})
    emails = fields.List(fields.Dict(keys=fields.String(), values=fields.String()), required=True)
    active = fields.Boolean(load_default=True)
    externalId = fields.String(load_default="")
    groups = fields.List(fields.String(), load_default=[])


class ScimUserPatchSchema(Schema):
    schemas = fields.List(fields.String(), required=True)
    Operations = fields.List(fields.Dict(), required=True)


@blp.route("/Users")
class ScimUsers(MethodView):
    def get(self) -> ResponseReturnValue:
        if not _verify_scim_token():
            return _scim_error(401, "invalid_token", "Unauthorized")
        cache = sogo_cache()
        index = list(cache.get(f"{_SCIM_PREFIX}index", list) or [])
        users = []
        for uid in index:
            raw = cache.get(f"{_SCIM_PREFIX}{uid}", str)
            if raw:
                try:
                    users.append(json.loads(raw))
                except Exception:
                    pass
        # SCIM list response
        return Response(
            json.dumps({
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ListResponse"],
                "totalResults": len(users),
                "startIndex": 1,
                "itemsPerPage": len(users),
                "Resources": users,
            }),
            content_type="application/scim+json",
        )

    def post(self) -> ResponseReturnValue:
        if not _verify_scim_token():
            return _scim_error(401, "invalid_token", "Unauthorized")
        body = request.get_json(force=True)
        if not body or "userName" not in body:
            return _scim_error(400, "invalidSyntax", "userName is required")

        cache = sogo_cache()
        uid = body["userName"]
        user_obj = {
            "id": hashlib.sha256(uid.encode()).hexdigest()[:32],
            "userName": uid,
            "displayName": body.get("displayName", ""),
            "name": body.get("name", {}),
            "emails": body.get("emails", [{"value": uid, "primary": True}]),
            "active": body.get("active", True),
            "externalId": body.get("externalId", ""),
            "groups": body.get("groups", []),
            "meta": {
                "resourceType": "User",
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "lastModified": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "location": f"/scim/v2/Users/{uid}",
            },
        }
        cache.set(f"{_SCIM_PREFIX}{uid}", json.dumps(user_obj), ttl=86400 * 365)
        idx = list(cache.get(f"{_SCIM_PREFIX}index", list) or [])
        if uid not in idx:
            idx.append(uid)
            cache.set(f"{_SCIM_PREFIX}index", idx, ttl=86400 * 365)

        logger_api.info("SCIM user provisioned: %s (active=%s)", uid, user_obj["active"])
        return Response(json.dumps(user_obj), status=201, content_type="application/scim+json")


@blp.route("/Users/<path:user_id>")
class ScimUserDetail(MethodView):
    def get(self, user_id: str) -> ResponseReturnValue:
        if not _verify_scim_token():
            return _scim_error(401, "invalid_token", "Unauthorized")
        cache = sogo_cache()
        raw = cache.get(f"{_SCIM_PREFIX}{user_id}", str)
        if not raw:
            return _scim_error(404, "noSuchResource", "User not found")
        return Response(json.dumps(json.loads(raw)), content_type="application/scim+json")

    def patch(self, user_id: str) -> ResponseReturnValue:
        if not _verify_scim_token():
            return _scim_error(401, "invalid_token", "Unauthorized")
        cache = sogo_cache()
        raw = cache.get(f"{_SCIM_PREFIX}{user_id}", str)
        if not raw:
            return _scim_error(404, "noSuchResource", "User not found")
        user_obj = json.loads(raw)
        body = request.get_json(force=True)
        for op in body.get("Operations", []):
            path = op.get("path", "")
            value = op.get("value")
            if path == "active":
                user_obj["active"] = value
            elif path == "displayName":
                user_obj["displayName"] = value
            elif path == "name":
                user_obj["name"].update(value if isinstance(value, dict) else {})
            elif path == "emails":
                user_obj["emails"] = value if isinstance(value, list) else [value]
        user_obj["meta"]["lastModified"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        cache.set(f"{_SCIM_PREFIX}{user_id}", json.dumps(user_obj), ttl=86400 * 365)
        logger_api.info("SCIM user patched: %s", user_id)
        return Response(json.dumps(user_obj), content_type="application/scim+json")

    def delete(self, user_id: str) -> ResponseReturnValue:
        if not _verify_scim_token():
            return _scim_error(401, "invalid_token", "Unauthorized")
        cache = sogo_cache()
        cache.delete(f"{_SCIM_PREFIX}{user_id}")
        idx = list(cache.get(f"{_SCIM_PREFIX}index", list) or [])
        idx = [u for u in idx if u != user_id]
        cache.set(f"{_SCIM_PREFIX}index", idx, ttl=86400 * 365)
        logger_api.info("SCIM user deprovisioned: %s", user_id)
        return Response(status=204)
