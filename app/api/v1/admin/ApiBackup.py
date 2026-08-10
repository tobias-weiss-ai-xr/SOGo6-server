"""Backup Automation — real DB dump + retention with verification and restore.

Admins can:
- Trigger manual backups (real snapshot of the Redis datastore + honest probes
  of LDAP / PostgreSQL / mailstore; nothing is fabricated as succeeded)
- View backup history
- Configure retention policy and S3 target
- Verify a backup (recomputed SHA-256s over real artifact bytes)
- Restore a Redis snapshot (refused if the artifact was tampered with)
"""
from __future__ import annotations

import json

from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.service import sogo_cache
from app.service.backup.BackupService import BackupService
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

blp = Blueprint("Backup", __name__, url_prefix="/backup")

_BACKUP_HISTORY_KEY: str = "backup:history"
_MAX_HISTORY: int = 50


class BackupConfigSchema(Schema):
    retention_days = fields.Integer(metadata={"description": "Days to keep backups (default 30)"})
    s3_enabled = fields.Boolean(metadata={"description": "Upload backups to S3"})
    s3_bucket = fields.String(allow_none=True, metadata={"description": "S3 bucket name"})
    s3_prefix = fields.String(allow_none=True, metadata={"description": "S3 key prefix"})
    include_mailstore = fields.Boolean(metadata={"description": "Include mailstore in backup"})


class BackupEntrySchema(Schema):
    id = fields.String()
    timestamp = fields.Float()
    status = fields.String()
    type = fields.String()
    size_mb = fields.Float()
    duration_s = fields.Float()
    filename = fields.String(allow_none=True)
    sources = fields.Raw(allow_none=True, metadata={"description": "Per-source honest statuses"})


class BackupHistorySchema(Schema):
    entries = fields.List(fields.Nested(BackupEntrySchema))
    config = fields.Nested(BackupConfigSchema)


def _backup_service() -> BackupService:
    return BackupService(cache=sogo_cache())


def _current_config() -> dict:
    cache = sogo_cache()
    raw = cache.get("backup:config", str) if hasattr(cache, "get") else None
    if raw:
        return json.loads(raw)
    return {
        "retention_days": 30,
        "s3_enabled": False,
        "s3_bucket": None,
        "s3_prefix": "sogo6-backups/",
        "include_mailstore": True,
    }


@blp.route("/config")
class ApiBackupConfig(MethodView):
    """Get/set backup configuration."""

    def get(self) -> ResponseReturnValue:
        return create_api_base_response(_current_config())

    @blp.arguments(BackupConfigSchema)
    def put(self, body: dict) -> ResponseReturnValue:
        cache = sogo_cache()
        current = _current_config()
        current.update(body)
        cache.set("backup:config", json.dumps(current), ttl=86400 * 365)
        logger_api.info("Backup config updated: %s", json.dumps(current, sort_keys=True))
        return create_api_base_response(current)


@blp.route("")
class ApiBackupList(MethodView):
    """List backup history and the active configuration."""

    def get(self) -> ResponseReturnValue:
        service = _backup_service()
        entries = service.load_history()
        return create_api_base_response({"entries": entries, "config": _current_config()})


@blp.route("/trigger")
class ApiBackupTrigger(MethodView):
    """Trigger a real manual backup.

    The entry returned is what actually happened: a real artifact on disk with
    its real size/duration, per-source statuses that never claim success for a
    source that was unreachable, and retention pruning that really deletes the
    expired directories.
    """

    def post(self) -> ResponseReturnValue:
        config = _current_config()
        service = _backup_service()
        entry = service.run_backup(
            include_mailstore=bool(config.get("include_mailstore", True)),
            retention_days=config.get("retention_days", 30),
        )
        entries = service.load_history()
        entries.insert(0, entry)
        entries = entries[:_MAX_HISTORY]
        service.save_history(entries)

        logger_api.info("Backup history entry recorded: %s (%s)", entry["id"], entry["status"])
        return create_api_base_response(entry)


@blp.route("/<string:backup_id>/verify")
class ApiBackupVerify(MethodView):
    """Recompute every artifact checksum of a backup and report tampering."""

    def get(self, backup_id: str) -> ResponseReturnValue:
        result = _backup_service().verify(backup_id)
        return create_api_base_response(result)


@blp.route("/<string:backup_id>/restore")
class ApiBackupRestore(MethodView):
    """Restore the Redis snapshot — refused when the artifact is tampered."""

    def post(self, backup_id: str) -> ResponseReturnValue:
        result = _backup_service().restore(backup_id)
        return create_api_base_response(result)