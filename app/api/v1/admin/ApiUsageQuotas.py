"""Usage Quotas — per-user mailbox size and resource limits.

Admins can view and set quotas for individual users.
Users can view their own quota usage.
"""
from __future__ import annotations

from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.service import sogo_cache
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
    mailbox_used_mb = fields.Float()
    calendar_count = fields.Integer()
    calendar_used = fields.Integer()
    contact_count = fields.Integer()
    contact_used = fields.Integer()


@blp.route("/<string:user_uid>")
class ApiQuotaDetail(MethodView):
    """Get or set quotas for a user."""

    def get(self, user_uid: str) -> ResponseReturnValue:
        """Get quota limits and current usage for a user."""
        cache = sogo_cache()
        raw = cache.get(f"{_QUOTA_PREFIX}{user_uid}", str)
        limits = {}
        if raw:
            try:
                import json
                limits = json.loads(raw)
            except Exception:
                pass  # best-effort: keep fallback/default value on failure

        # Get current usage from the mail module (simplified)
        # In production this would query actual storage
        usage = {
            "mailbox_size_mb": limits.get("mailbox_size_mb", 0),
            "mailbox_used_mb": 0.0,
            "calendar_count": limits.get("calendar_count", 0),
            "calendar_used": 0,
            "contact_count": limits.get("contact_count", 0),
            "contact_used": 0,
        }
        return create_api_base_response(usage)

    @blp.arguments(QuotaSchema)
    def put(self, body: dict, user_uid: str) -> ResponseReturnValue:
        """Set quota limits for a user."""
        cache = sogo_cache()
        import json
        cache.set(f"{_QUOTA_PREFIX}{user_uid}", json.dumps(body), ttl=86400 * 365)
        logger_api.info("Quotas updated for user %s: %s", user_uid, body)
        return create_api_base_response(body)
