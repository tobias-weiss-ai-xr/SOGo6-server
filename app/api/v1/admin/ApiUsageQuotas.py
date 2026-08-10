"""Usage Quotas — per-user mailbox size and resource limits with REAL usage.

Admins can view and set quotas for individual users. Usage is always what
actually happened (calendar/contact counts from the real storage modules, IMAP
mailbox size from the real mail client) — the previous implementation returned
hardcoded ``0.0``/``0`` usage with a comment *"In production this would query
actual storage"*. When a source is unreachable or unconfigured that is reported
with an honest status and ``used: null``, never a fabricated zero. Over-quota
flags are computed from real usage vs the recorded limits.
"""
from __future__ import annotations

import json

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.service import sogo_cache
from app.service.quota.QuotaUsageService import QuotaUsageService
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

blp = Blueprint("Usage Quotas", __name__, url_prefix="/quotas")

_QUOTA_PREFIX: str = "quota:"


class QuotaSchema(Schema):
    mailbox_size_mb = fields.Integer(metadata={"description": "Max mailbox size in MB (0 = unlimited)"})
    calendar_count = fields.Integer(metadata={"description": "Max number of calendars (0 = unlimited)"})
    contact_count = fields.Integer(metadata={"description": "Max number of contacts (0 = unlimited)"})


class QuotaUsageSchema(Schema):
    mailbox_size_mb = fields.Integer()
    mailbox_used_mb = fields.Float(allow_none=True)
    calendar_count = fields.Integer()
    calendar_used = fields.Integer(allow_none=True)
    contact_count = fields.Integer()
    contact_used = fields.Integer(allow_none=True)


def _usage_service(user_uid: str, limits: dict) -> QuotaUsageService:
    """Build the real usage service (seam for tests: inject probes)."""
    ps = getattr(g, "process_settings", None)
    return QuotaUsageService(user_uid, limits, process_settings=ps)


def _sanitize_limits(body: dict) -> dict:
    """Clamp limits to sane non-negative integers (0 = unlimited)."""
    cleaned: dict = {}
    for key in ("mailbox_size_mb", "calendar_count", "contact_count"):
        if key in body and body[key] is not None:
            cleaned[key] = max(0, int(body[key]))
    return cleaned


@blp.route("/<string:user_uid>")
class ApiQuotaDetail(MethodView):
    """Get or set quotas for a user."""

    def get(self, user_uid: str) -> ResponseReturnValue:
        """Get quota limits and the REAL current usage for a user.

        ``used`` values are null — not zero — when a source is unreachable or
        unconfigured; ``sources`` carries the honest per-source status and error.
        ``over_limits`` only lists limits that are exceeded by *known* usage.
        """
        cache = sogo_cache()
        raw = cache.get(f"{_QUOTA_PREFIX}{user_uid}", str)
        limits: dict = {}
        if raw:
            try:
                limits = json.loads(raw)
            except Exception:  # pylint: disable=broad-except — corrupt record = defaults
                limits = {}

        report = _usage_service(user_uid, limits).usage()
        return create_api_base_response({
            "limits": limits,
            "usage": report["used"],
            "sources": report["sources"],
            "over_quota": report["over_quota"],
            "over_limits": report["over_limits"],
        })

    @blp.arguments(QuotaSchema)
    def put(self, body: dict, user_uid: str) -> ResponseReturnValue:
        """Set quota limits for a user (negative values clamped to 0 = unlimited)."""
        limits = _sanitize_limits(body)
        cache = sogo_cache()
        cache.set(f"{_QUOTA_PREFIX}{user_uid}", json.dumps(limits), ttl=86400 * 365)
        logger_api.info("Quotas updated for user %s: %s", user_uid, limits)
        return create_api_base_response(limits)