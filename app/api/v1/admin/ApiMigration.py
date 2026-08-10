"""Migration Tools (#30) — Import wizards from G Suite / M365 / Dovecot / Cyrus.

Admins can:
- Upload migration bundles (MBOX, ICS, VCF, CSV)
- Trigger migration jobs for external sources
- View migration progress and results
"""
from __future__ import annotations

import json
import time
import uuid
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api
from app.service import sogo_cache

blp = Blueprint("Migration", __name__, url_prefix="/migration")

_HISTORY_KEY: str = "migration:history"
_MAX_HISTORY: int = 50


class MigrationJobSchema(Schema):
    """Request body to start a migration."""
    source = fields.String(required=True, metadata={"description": "Source type: gsuite, m365, dovecot, cyrus, mbox, csv"})
    user_uid = fields.String(required=True, metadata={"description": "Target user UID"})
    options = fields.Dict(allow_none=True, metadata={"description": "Source-specific options (host, credentials, etc.)"})


class ApiMigrationHistoryEntrySchema(Schema):
    id = fields.String()
    source = fields.String()
    user_uid = fields.String()
    status = fields.String()
    started_at = fields.Float()
    completed_at = fields.Float(allow_none=True)
    items_migrated = fields.Integer()
    items_failed = fields.Integer()
    details = fields.String(allow_none=True)


@blp.route("/history")
class ApiMigrationHistory(MethodView):
    """View all migration jobs."""

    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(_HISTORY_KEY, str)
        entries = json.loads(raw) if raw else []
        return create_api_base_response({"entries": entries})


@blp.route("/sources")
class ApiMigrationSources(MethodView):
    """List supported migration sources."""

    def get(self) -> ResponseReturnValue:
        return create_api_base_response({
            "sources": [
                {
                    "id": "gsuite",
                    "name": "Google Workspace (G Suite)",
                    "description": "Import mail, calendar, and contacts from Google Workspace via API",
                    "fields": ["client_id", "client_secret", "refresh_token"],
                },
                {
                    "id": "m365",
                    "name": "Microsoft 365",
                    "description": "Import mail, calendar, and contacts from Microsoft 365 via Graph API",
                    "fields": ["client_id", "client_secret", "tenant_id"],
                },
                {
                    "id": "dovecot",
                    "name": "Dovecot IMAP",
                    "description": "Import mail via IMAP from a Dovecot server",
                    "fields": ["host", "port", "username", "password"],
                },
                {
                    "id": "cyrus",
                    "name": "Cyrus IMAP",
                    "description": "Import mail via IMAP from a Cyrus server",
                    "fields": ["host", "port", "username", "password"],
                },
                {
                    "id": "mbox",
                    "name": "MBOX File Upload",
                    "description": "Upload MBOX files for direct import",
                    "fields": [],
                },
                {
                    "id": "csv",
                    "name": "CSV Contact Import",
                    "description": "Upload CSV files with contact data",
                    "fields": [],
                },
            ]
        })


@blp.route("/start")
class ApiMigrationStart(MethodView):
    """Start a migration job."""

    @blp.arguments(MigrationJobSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        job_id = str(uuid.uuid4())[:8]
        source = body.get("source", "unknown")
        user_uid = body.get("user_uid", "")

        entry = {
            "id": job_id,
            "source": source,
            "user_uid": user_uid,
            "status": "pending",
            "started_at": time.time(),
            "completed_at": None,
            "items_migrated": 0,
            "items_failed": 0,
            "details": f"Migration from {source} for user {user_uid}",
        }

        cache = sogo_cache()
        raw = cache.get(_HISTORY_KEY, str)
        entries = json.loads(raw) if raw else []
        entries.insert(0, entry)
        entries = entries[:_MAX_HISTORY]
        cache.set(_HISTORY_KEY, json.dumps(entries), ttl=86400 * 90)

        logger_api.info("Migration job %s started: %s → %s", job_id, source, user_uid)
        return create_api_base_response(entry)


@blp.route("/<string:job_id>")
class ApiMigrationDetail(MethodView):
    """Get migration job status."""

    def get(self, job_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(_HISTORY_KEY, str)
        entries = json.loads(raw) if raw else []
        for entry in entries:
            if entry["id"] == job_id:
                return create_api_base_response(entry)
        return create_api_base_response(
            error=err.ERROR_MIGRATION_NOT_FOUND,
            error_msg="Migration job not found",
        )


@blp.route("/<string:job_id>/cancel")
class ApiMigrationCancel(MethodView):
    """Cancel a migration job."""

    def post(self, job_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(_HISTORY_KEY, str)
        entries = json.loads(raw) if raw else []
        for entry in entries:
            if entry["id"] == job_id:
                entry["status"] = "cancelled"
                entry["completed_at"] = time.time()
                cache.set(_HISTORY_KEY, json.dumps(entries), ttl=86400 * 90)
                logger_api.info("Migration job %s cancelled", job_id)
                return create_api_base_response(entry)
        return create_api_base_response(
            error=err.ERROR_MIGRATION_NOT_FOUND,
            error_msg="Migration job not found",
        )
