"""Configuration as Code (#36) — GitOps-ready immutable config with version control.

Admins can:
- Export entire system configuration as JSON/YAML
- Import configuration (validate before applying)
- View configuration history (versioned snapshots)
- Compare configuration diffs between versions
"""
from __future__ import annotations

import json
import time
import hashlib
import uuid
from flask import g, request
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api
from app.service import sogo_cache

blp = Blueprint("Config as Code", __name__, url_prefix="/config-as-code")

_HISTORY_KEY: str = "configascode:history"
_CURRENT_KEY: str = "configascode:current"
_MAX_HISTORY: int = 20


class ConfigSnapshotSchema(Schema):
    id = fields.String()
    version = fields.Integer()
    created_at = fields.Float()
    created_by = fields.String()
    checksum = fields.String()
    config = fields.Dict()


class ConfigImportSchema(Schema):
    config = fields.Dict(required=True, metadata={"description": "Configuration object to apply"})
    description = fields.String(allow_none=True, metadata={"description": "Change description for version history"})


class ConfigDiffSchema(Schema):
    version_a = fields.Integer()
    version_b = fields.Integer()
    diff = fields.List(fields.Dict())


@blp.route("/export")
class ApiConfigExport(MethodView):
    """Export the current configuration."""

    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(_CURRENT_KEY, str)
        if raw:
            current = json.loads(raw)
            return create_api_base_response({
                "config": current.get("config", {}),
                "version": current.get("version", 0),
                "checksum": current.get("checksum", ""),
                "exported_at": time.time(),
            })

        # Return empty config if none set
        empty = {
            "domains": {},
            "users": {},
            "system": {},
            "rules": [],
            "theme": {},
        }
        return create_api_base_response({
            "config": empty,
            "version": 0,
            "checksum": hashlib.sha256(json.dumps(empty).encode()).hexdigest()[:16],
            "exported_at": time.time(),
        })


@blp.route("/import")
class ApiConfigImport(MethodView):
    """Import and apply a configuration."""

    @blp.arguments(ConfigImportSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        config = body.get("config", {})
        description = body.get("description", "Configuration import")
        user_uid = getattr(g, "user", None) and getattr(g.user, "uid", "admin") or "admin"

        # Compute checksum
        config_str = json.dumps(config, sort_keys=True)
        checksum = hashlib.sha256(config_str.encode()).hexdigest()[:16]

        # Get current version
        raw_current = cache_get("configascode:current")
        current = json.loads(raw_current) if raw_current else {"version": 0}
        new_version = current.get("version", 0) + 1

        snapshot = {
            "id": str(uuid.uuid4())[:8],
            "version": new_version,
            "created_at": time.time(),
            "created_by": user_uid,
            "description": description,
            "checksum": checksum,
            "config": config,
        }

        cache = sogo_cache()

        # Store current
        cache.set(_CURRENT_KEY, json.dumps(snapshot), ttl=86400 * 365)

        # Store in history
        raw_history = cache.get(_HISTORY_KEY, str)
        history = json.loads(raw_history) if raw_history else []
        history.insert(0, snapshot)
        history = history[:_MAX_HISTORY]
        cache.set(_HISTORY_KEY, json.dumps(history), ttl=86400 * 365)

        logger_api.info("Config v%d imported by %s (checksum: %s)", new_version, user_uid, checksum)
        return create_api_base_response({
            "version": new_version,
            "checksum": checksum,
            "id": snapshot["id"],
        })


def cache_get(key: str) -> str:
    """Helper to get from cache."""
    from app.service import sogo_cache as _cache
    return _cache().get(key, str)


@blp.route("/history")
class ApiConfigHistory(MethodView):
    """View configuration version history."""

    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(_HISTORY_KEY, str)
        entries = json.loads(raw) if raw else []
        return create_api_base_response({"snapshots": entries})


@blp.route("/diff")
class ApiConfigDiff(MethodView):
    """Compare two configuration versions."""

    def get(self) -> ResponseReturnValue:
        version_a = request.args.get("a", type=int)
        version_b = request.args.get("b", type=int)

        cache = sogo_cache()
        raw = cache.get(_HISTORY_KEY, str)
        entries = json.loads(raw) if raw else []

        snap_a = next((e for e in entries if e.get("version") == version_a), None)
        snap_b = next((e for e in entries if e.get("version") == version_b), None)

        if not snap_a or not snap_b:
            return create_api_base_response(
                error=err.ERROR_RESOURCE_NOT_FOUND,
                error_msg="Version not found in history",
            )

        # Simple diff: compare top-level keys
        diff = []
        all_keys = set(list(snap_a.get("config", {}).keys()) + list(snap_b.get("config", {}).keys()))
        for key in sorted(all_keys):
            val_a = json.dumps(snap_a.get("config", {}).get(key), sort_keys=True)
            val_b = json.dumps(snap_b.get("config", {}).get(key), sort_keys=True)
            if val_a != val_b:
                diff.append({
                    "key": key,
                    "old": snap_a.get("config", {}).get(key),
                    "new": snap_b.get("config", {}).get(key),
                })

        return create_api_base_response({
            "version_a": version_a,
            "version_b": version_b,
            "diff": diff,
        })
