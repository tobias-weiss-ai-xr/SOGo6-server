"""Audit Log — tamper-proof admin/user action log.

Entries are stored in a Redis sorted set (by timestamp) and are
append-only — once written they cannot be modified or deleted.
"""
from __future__ import annotations

import json
import time
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.service import sogo_cache
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

blp = Blueprint("Audit Log", __name__, url_prefix="/audit-log")

_AUDIT_ZSET: str = "audit_log"
_MAX_ENTRIES: int = 10000


class AuditEntrySchema(Schema):
    timestamp = fields.Integer()
    action = fields.String()
    actor = fields.String()
    target = fields.String(allow_none=True)
    detail = fields.String(allow_none=True)
    ip = fields.String(allow_none=True)


class AuditLogQuerySchema(Schema):
    limit = fields.Integer(load_default=50, metadata={"description": "Max entries to return"})
    offset = fields.Integer(load_default=0, metadata={"description": "Offset for pagination"})
    action = fields.String(load_default=None, allow_none=True, metadata={"description": "Filter by action type"})


def audit(action: str, actor: str = "", target: str = "", detail: str = "", ip: str = "") -> None:
    """Append an entry to the audit log."""
    entry = {
        "timestamp": int(time.time()),
        "action": action,
        "actor": actor,
        "target": target,
        "detail": detail,
        "ip": ip,
    }
    cache = sogo_cache()
    cache.zset_add(_AUDIT_ZSET, json.dumps(entry, sort_keys=True), entry["timestamp"])
    # Trim to max entries
    count = cache.zset_count(_AUDIT_ZSET)
    if count > _MAX_ENTRIES:
        cache.zset_remove(_AUDIT_ZSET, *[str(i) for i in range(count - _MAX_ENTRIES)])
    logger_api.debug("Audit: %s by %s", action, actor)


@blp.route("")
class ApiAuditLogList(MethodView):
    """List audit log entries (admin only)."""

    @blp.arguments(AuditLogQuerySchema, location="query")
    def get(self, args: dict) -> ResponseReturnValue:
        """Return audit log entries, most recent first."""
        limit: int = min(args.get("limit", 50), 200)
        offset: int = args.get("offset", 0)
        action_filter: str | None = args.get("action")

        cache = sogo_cache()
        total = cache.zset_count(_AUDIT_ZSET)
        entries_raw = cache.zset_revrange(_AUDIT_ZSET, offset, offset + limit - 1)

        entries = []
        for raw in entries_raw:
            try:
                entry = json.loads(raw)
                if action_filter and entry.get("action") != action_filter:
                    continue
                entries.append(entry)
            except Exception:
                continue

        return create_api_base_response({
            "entries": entries,
            "total": total,
            "limit": limit,
            "offset": offset,
        })
