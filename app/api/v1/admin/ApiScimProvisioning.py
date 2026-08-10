"""SCIM Provisioning (#66) — enterprise identity lifecycle against the real LDAP store.

SCIM 2.0-compatible user provisioning endpoints for Azure AD, Okta, and
other identity providers.  Users are created/read/updated/deleted in the
configured OpenLDAP directory via the ScimIdentityGateway (wrapping
ModuleAdminUser) — never only in Redis.

Redis is kept as a small sidecar for the fields the directory schema does not
carry (``externalId``, ``groups``, and the ``active`` flag mirrored onto the
real ``shadowExpire`` LDAP attribute). Authentication is the bearer token in
``SCIM_BEARER_TOKEN`` (no open fallback); these routes declare
``public_access`` so the admin-JWT middleware lets SCIM's own token gate
authorize them.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import time

from flask import g, request, Response
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.service import sogo_cache
from app.service.scim.ScimIdentityGateway import ScimIdentityGateway, record_values
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api

blp = Blueprint("SCIM Provisioning", __name__, url_prefix="/scim/v2")

_SCIM_META_PFX: str = "scim_meta:"


def _verify_scim_token() -> bool:
    """Verify the SCIM bearer token from the incoming request.

    The ``SCIM_BEARER_TOKEN`` environment variable **must** be set to a
    non-empty value for SCIM requests to succeed.  When it is unset or empty,
    all requests are rejected — there is no "open" fallback.
    """
    configured_token = os.environ.get("SCIM_BEARER_TOKEN", "")
    if not configured_token:
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


def _gateway() -> ScimIdentityGateway | None:
    """Build the identity gateway when process settings are available."""
    ps = getattr(g, "process_settings", None)
    if ps is None:
        return None
    return ScimIdentityGateway(ps)


# ---------------------------------------------------------------------------- #
# meta sidecar (Redis): externalId/groups/active-flag do not exist in the LDAP
# schema used here.  The LDAP record is authoritative for identity; the sidecar
# only augments it.
# ---------------------------------------------------------------------------- #

def _read_meta(user_id: str) -> dict:
    raw = sogo_cache().get(f"{_SCIM_META_PFX}{user_id}", str)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _write_meta(user_id: str, meta: dict) -> None:
    sogo_cache().set(f"{_SCIM_META_PFX}{user_id}", json.dumps(meta), ttl=86400 * 365)


def _delete_meta(user_id: str) -> None:
    sogo_cache().delete(f"{_SCIM_META_PFX}{user_id}")


def _primary_email(emails) -> str:
    for e in emails or []:
        if e.get("primary") and e.get("value"):
            return e["value"]
    for e in emails or []:
        if e.get("value"):
            return e["value"]
    return ""


def _to_scim_user(record: dict, meta: dict | None = None) -> dict:
    """Map an LDAP record + meta sidecar to a SCIM 2.0 User object."""
    meta = meta or {}
    uid = record_values(record, "uid")
    cn = record_values(record, "cn") or uid
    given = record_values(record, "givenName")
    sn = record_values(record, "sn")
    mail = record_values(record, "mail")
    shadow_expire = record_values(record, "shadowExpire")
    if shadow_expire and shadow_expire not in ("0", ""):
        active = False
    else:
        active = bool(meta.get("active", True))

    emails = [{"value": mail, "primary": True}] if mail else []
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "id": uid,
        "userName": uid,
        "displayName": cn or uid,
        "name": {"givenName": given, "familyName": sn},
        "emails": emails,
        "active": active,
        "externalId": meta.get("externalId", ""),
        "groups": meta.get("groups", []),
        "meta": {
            "resourceType": "User",
            "created": meta.get("created", ""),
            "lastModified": meta.get("lastModified", ""),
            "location": f"/scim/v2/Users/{uid}",
        },
    }


# ---------------------------------------------------------------------------- #
# /Users
# ---------------------------------------------------------------------------- #

@blp.route("/Users")
class ScimUsers(MethodView):
    public_access = True

    def get(self) -> ResponseReturnValue:
        """List users from the real directory."""
        if not _verify_scim_token():
            return _scim_error(401, "invalid_token", "Unauthorized")
        gateway = _gateway()
        if gateway is None:
            return _scim_error(500, "serverFailure", "Identity source is not configured")

        try:
            start = max(int(request.args.get("startIndex", 1) or 1), 1)
            count = max(int(request.args.get("count", 10) or 10), 0)
            count = min(count, 1000)
            total, records = gateway.list_users(
                query=request.args.get("filter", "") or None,
                page=1,
                per_page=max(count, 1),
            )
        except (RequestException, ValueError) as exc:
            return _scim_error(500, "serverFailure", str(exc))

        slice_end = start - 1 + max(count, 1)
        resources = [_to_scim_user(r, _read_meta(record_values(r, "uid"))) for r in records[start - 1:slice_end]]
        return Response(
            json.dumps({
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ListResponse"],
                "totalResults": total,
                "startIndex": start,
                "itemsPerPage": len(resources),
                "Resources": resources,
            }),
            content_type="application/scim+json",
        )

    def post(self) -> ResponseReturnValue:
        """Create a real LDAP user (uniqueness-checked) + meta sidecar."""
        if not _verify_scim_token():
            return _scim_error(401, "invalid_token", "Unauthorized")
        gateway = _gateway()
        if gateway is None:
            return _scim_error(500, "serverFailure", "Identity source is not configured")

        body = request.get_json(force=True) or {}
        uid = body.get("userName", "")
        if not uid:
            return _scim_error(400, "invalidSyntax", "userName is required")

        try:
            gateway.get_user(uid)
            return _scim_error(409, "uniqueness", f"User '{uid}' already exists")
        except RequestException:
            pass  # not present — good to create

        name = body.get("name", {}) or {}
        try:
            gateway.create_user({
                "uid": uid,
                "cn": body.get("displayName") or uid,
                "sn": name.get("familyName") or uid,
                "givenName": name.get("givenName") or body.get("displayName") or uid,
                "mail": _primary_email(body.get("emails")) or uid,
                "password": secrets.token_urlsafe(18),
            })
        except RequestException as exc:
            return _scim_error(500, "serverFailure", str(exc))

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        meta = {
            "externalId": body.get("externalId", ""),
            "groups": body.get("groups", []),
            "active": bool(body.get("active", True)),
            "created": now,
            "lastModified": now,
        }
        _write_meta(uid, meta)

        try:
            record = gateway.get_user(uid)
        except RequestException:
            record = {}
        logger_api.info("SCIM user provisioned in LDAP: %s (active=%s)", uid, meta["active"])
        return Response(
            json.dumps(_to_scim_user(record, meta)),
            status=201,
            content_type="application/scim+json",
        )


@blp.route("/Users/<path:user_id>")
class ScimUserResource(MethodView):
    public_access = True

    def get(self, user_id: str) -> ResponseReturnValue:
        if not _verify_scim_token():
            return _scim_error(401, "invalid_token", "Unauthorized")
        gateway = _gateway()
        if gateway is None:
            return _scim_error(500, "serverFailure", "Identity source is not configured")
        try:
            record = gateway.get_user(user_id)
        except RequestException:
            return _scim_error(404, "noSuchResource", "User not found")
        return Response(
            json.dumps(_to_scim_user(record, _read_meta(user_id))),
            content_type="application/scim+json",
        )

    def patch(self, user_id: str) -> ResponseReturnValue:
        """Apply SCIM PatchOp operations to the real LDAP entry."""
        if not _verify_scim_token():
            return _scim_error(401, "invalid_token", "Unauthorized")
        gateway = _gateway()
        if gateway is None:
            return _scim_error(500, "serverFailure", "Identity source is not configured")
        try:
            gateway.get_user(user_id)
        except RequestException:
            return _scim_error(404, "noSuchResource", "User not found")

        body = request.get_json(force=True) or {}
        meta = _read_meta(user_id)
        ldap_mods: dict = {}
        for op in body.get("Operations", []):
            path = (op.get("path") or "").strip()
            value = op.get("value")
            if path == "active":
                flag = bool(value)
                ldap_mods["shadowExpire"] = "1" if not flag else None
                meta["active"] = flag
            elif path == "displayName":
                if value:
                    ldap_mods["cn"] = value
            elif path == "name.givenName":
                if value:
                    ldap_mods["givenName"] = value
            elif path == "name.familyName":
                if value:
                    ldap_mods["sn"] = value
            elif path == "emails":
                if isinstance(value, list):
                    ldap_mods["mail"] = _primary_email(value)
                elif isinstance(value, dict):
                    ldap_mods["mail"] = value.get("value", "")
            elif path == "externalId":
                meta["externalId"] = value if isinstance(value, str) else ""
            elif path == "groups":
                meta["groups"] = value if isinstance(value, list) else []

        try:
            if ldap_mods:
                gateway.update_user(user_id, ldap_mods)
        except RequestException as exc:
            return _scim_error(500, "serverFailure", str(exc))

        meta["lastModified"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_meta(user_id, meta)
        try:
            record = gateway.get_user(user_id)
        except RequestException:
            record = {}
        logger_api.info("SCIM user patched in LDAP: %s", user_id)
        return Response(
            json.dumps(_to_scim_user(record, meta)),
            content_type="application/scim+json",
        )

    def delete(self, user_id: str) -> ResponseReturnValue:
        """Deprovision: remove the LDAP entry and its meta sidecar."""
        if not _verify_scim_token():
            return _scim_error(401, "invalid_token", "Unauthorized")
        gateway = _gateway()
        if gateway is None:
            return _scim_error(500, "serverFailure", "Identity source is not configured")
        try:
            gateway.delete_user(user_id)
        except RequestException:
            return _scim_error(404, "noSuchResource", "User not found")
        _delete_meta(user_id)
        logger_api.info("SCIM user deprovisioned from LDAP: %s", user_id)
        return Response(status=204)