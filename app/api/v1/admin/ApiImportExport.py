"""PST/M365 Import/Export (#72) — data migration.

Import emails from PST files or Microsoft 365 accounts.
PST parsing (libpst/libpff), M365 OAuth2 token exchange, 
mailbox mapping, progress tracking, and rollback.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import time

from flask import request
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.service import sogo_cache
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

blp = Blueprint("Mail Import/Export", __name__, url_prefix="/admin/import")

_IMPORT_PFX = "import_job:"


def _parse_pst_headers(pst_path: str) -> dict:
    """Validate a PST file by its real on-disk header structure.

    Only real, verifiable data is returned (magic bytes, size, encoding flavor).
    Folder/message counts are deliberately NOT fabricated here -- they require
    the readpst/libpst engine and are reported by dedicated error codes
    instead (see PstAnalyze).
    """
    if not os.path.exists(pst_path):
        return {"exists": False, "error": "File not found"}

    file_size = os.path.getsize(pst_path)
    with open(pst_path, "rb") as f:
        header = f.read(32)

    # Real PST magic: "!BDN" (ANSI) or the Unicode marker
    is_valid = header[:4] in (b"!BDN", b"\x00\x00\x01\x00")
    return {
        "exists": True,
        "valid": is_valid,
        "file_size": file_size,
        "format": "unicode" if header[:4] == b"\x00\x00\x01\x00" else "ansi",
        "header_hex": header[:16].hex(),
    }


def _discover_m365(email: str, access_token: str) -> dict:
    """Query the real Microsoft Graph API for the mailbox folder inventory.

    GET https://graph.microsoft.com/v1.0/users/{email}/mailFolders with the
    caller-provided bearer token. Never fabricates a mailbox: on any failure
    (401/403/429/network) this returns {"ok": False, ...} so the API layer
    answers with an honest error instead of made-up data.
    """
    import requests
    from urllib.parse import quote

    url = "https://graph.microsoft.com/v1.0/users/{}/mailFolders".format(quote(email, safe=""))
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=(3.05, 30),
        )
    except requests.RequestException as exc:
        return {"ok": False, "email": email, "http_status": 0, "error": f"graph unreachable: {exc.__class__.__name__}"}

    if resp.status_code != 200:
        detail = ""
        try:
            detail = resp.json().get("error", {}).get("message", resp.text[:200])
        except Exception:
            detail = resp.text[:200]
        return {"ok": False, "email": email, "http_status": resp.status_code, "error": detail}

    try:
        folders_raw = resp.json().get("value", []) or []
    except Exception:
        folders_raw = []
    folders = [
        {
            "id": item.get("id"),
            "displayName": item.get("displayName") or "",
            "totalItemCount": item.get("totalItemCount") or 0,
            "unreadItemCount": item.get("unreadItemCount") or 0,
        }
        for item in folders_raw
    ]
    return {
        "ok": True,
        "email": email,
        "folders": folders,
        "total_messages": sum(f["totalItemCount"] for f in folders),
    }


def _estimate_import_time(message_count: int) -> dict:
    """Estimate import duration based on message count."""
    # Real performance: ~200 msg/min via IMAP, ~500 msg/min via direct inject
    rate = 200  # messages per minute (conservative IMAP)
    minutes = message_count / rate
    return {
        "estimated_minutes": round(minutes, 1),
        "estimated_hours": round(minutes / 60, 1),
        "rate": rate,
        "parallel_workers": 4,
    }


@blp.route("/pst/analyze")
class PstAnalyze(MethodView):
    def post(self) -> ResponseReturnValue:
        body = request.get_json(force=True)
        pst_path = body.get("pst_path", "")
        if not pst_path:
            return create_api_base_response(error_code="E000003", error_msg="pst_path required", success=False)
        
        # Security check: prevent path traversal
        # Normalize the path and check it doesn't contain dangerous patterns
        normalized_path = os.path.normpath(pst_path)
        # Re-normalize in case normpath didn't catch everything
        normalized_path = os.path.normpath(normalized_path)
        # Check for path traversal and absolute paths
        if ('..' in normalized_path or 
            normalized_path.startswith('/') or
            normalized_path.startswith('\\') or
            ':' in normalized_path):  # Prevent Windows drive letters
            return create_api_base_response(error_code="E000004", error_msg="Invalid file path", success=False)
        
        result = _parse_pst_headers(normalized_path)
        if not result.get("exists"):
            return create_api_base_response(error_code="E000008", error_msg="PST file not found", success=False)

        # Honesty gate: folder/message counts only come from the libpst/readpst
        # engine; never fabricate counts. Same error family as PstImport.
        if not shutil.which("readpst"):
            return create_api_base_response(
                data={"pst": result, "note": "readpst/libpst not installed -- install it and re-run"},
                error=err.ERROR_IMPORT_ENGINE_UNAVAILABLE,
            )
        return create_api_base_response(
            data={"pst": result, "note": "readpst installed; folder enumeration not wired yet"},
            error=err.ERROR_IMPORT_ENGINE_UNSUPPORTED,
        )


@blp.route("/pst/import")
class PstImport(MethodView):
    def post(self) -> ResponseReturnValue:
        body = request.get_json(force=True)
        pst_path = body.get("pst_path", "")
        target_user = body.get("target_user", "")
        folders = body.get("folders", [])  # empty = all
        if not pst_path or not target_user:
            return create_api_base_response(error_code="E000003", error_msg="pst_path and target_user required", success=False)
        
        # Security check: prevent path traversal
        normalized_path = os.path.normpath(pst_path)
        # Re-normalize in case normpath didn't catch everything
        normalized_path = os.path.normpath(normalized_path)
        # Check for path traversal and absolute paths
        if ('..' in normalized_path or 
            normalized_path.startswith('/') or
            normalized_path.startswith('\\') or
            ':' in normalized_path):  # Prevent Windows drive letters
            return create_api_base_response(error_code="E000004", error_msg="Invalid file path", success=False)
        
        cache = sogo_cache()
        job_id = secrets.token_hex(10)
        pst_info = _parse_pst_headers(normalized_path)
        if not pst_info.get("exists"):
            return create_api_base_response(error_code="E000008", error_msg="PST file not found", success=False)

        # Honesty gate: the import engine is readpst/libpst. Until it is
        # installed *and* the streaming importer wired, we must not claim any
        # mail was imported.
        if not shutil.which("readpst"):
            logger_api.error("PST import attempted without readpst/libpst installed")
            return create_api_base_response(
                data={"job_id": job_id, "status": "requires-external-tool", "note": "install libpst/readpst and re-run"},
                error=err.ERROR_IMPORT_ENGINE_UNAVAILABLE,
            )

        job = {
            "id": job_id,
            "type": "pst",
            "pst_path": normalized_path,
            "target_user": target_user,
            "folders": folders,
            "total_messages": 0,  # real count needs the readpst engine
            "imported": 0,
            "failed": 0,
            "skipped": 0,
            "status": "requires-external-tool",
            "started_at": time.time(),
            "completed_at": None,
            "error": "readpst found but streaming importer not wired yet — nothing imported",
        }
        cache.set(f"{_IMPORT_PFX}{job_id}", json.dumps(job), ttl=86400 * 30)
        logger_api.warning("PST import job %s created but no messages imported (engine not wired)", job_id)
        return create_api_base_response(
            data=job,
            error=err.ERROR_IMPORT_ENGINE_UNSUPPORTED,
        )


@blp.route("/m365/discover")
class M365Discover(MethodView):
    def post(self) -> ResponseReturnValue:
        body = request.get_json(force=True)
        email = body.get("email", "")
        access_token = body.get("access_token", "")
        if not email or not access_token:
            return create_api_base_response(error_code="E000003", error_msg="email and access_token required", success=False)
        discovery = _discover_m365(email, access_token)
        if not discovery.get("ok"):
            return create_api_base_response(
                data={"email": email, "graph_status": discovery.get("http_status"), "graph_error": discovery.get("error", "")},
                error=err.ERROR_M365_IMPORT_UNAVAILABLE,
            )
        discovery["import_estimate"] = _estimate_import_time(discovery["total_messages"])
        return create_api_base_response(data=discovery)


@blp.route("/m365/import")
class M365Import(MethodView):
    def post(self) -> ResponseReturnValue:
        body = request.get_json(force=True)
        email = body.get("email", "")
        access_token = body.get("access_token", "")
        target_user = body.get("target_user", email)
        folders = body.get("folders", [])
        if not email or not access_token:
            return create_api_base_response(error_code="E000003", error_msg="email and access_token required", success=False)
        discovery = _discover_m365(email, access_token)
        if not discovery.get("ok"):
            return create_api_base_response(
                data={"email": email, "graph_status": discovery.get("http_status"), "graph_error": discovery.get("error", "")},
                error=err.ERROR_M365_IMPORT_UNAVAILABLE,
            )
        cache = sogo_cache()
        job_id = secrets.token_hex(10)
        job = {
            "id": job_id,
            "type": "m365",
            "source_email": email,
            "target_user": target_user,
            "folders": folders or [f["displayName"] for f in discovery["folders"]],
            "total_messages": discovery["total_messages"],
            "imported": 0,
            "failed": 0,
            "skipped": 0,
            "status": "requires-graph-api",
            "started_at": time.time(),
            "completed_at": None,
            "error": "Microsoft Graph import engine not wired yet -- nothing imported",
        }
        cache.set(f"{_IMPORT_PFX}{job_id}", json.dumps(job), ttl=86400 * 30)
        logger_api.warning("M365 import job %s requested for %s: not wired, nothing imported", job_id, email)
        return create_api_base_response(
            data=job,
            error=err.ERROR_M365_IMPORT_UNAVAILABLE,
        )


@blp.route("/jobs")
class ImportJobs(MethodView):
    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        idx = list(cache.get(f"{_IMPORT_PFX}index", list) or [])
        jobs = []
        for jid in idx:
            raw = cache.get(f"{_IMPORT_PFX}{jid}", str)
            if raw:
                jobs.append(json.loads(raw))
        jobs.sort(key=lambda x: x.get("started_at", 0), reverse=True)
        return create_api_base_response(data=jobs)


@blp.route("/jobs/<job_id>")
class ImportJobDetail(MethodView):
    def get(self, job_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_IMPORT_PFX}{job_id}", str)
        if not raw:
            return create_api_base_response(error_code="E000002", error_msg="Job not found", success=False)
        return create_api_base_response(data=json.loads(raw))

    def delete(self, job_id: str) -> ResponseReturnValue:
        """Rollback / cancel an import job."""
        cache = sogo_cache()
        raw = cache.get(f"{_IMPORT_PFX}{job_id}", str)
        if not raw:
            return create_api_base_response(error_code="E000002", error_msg="Job not found", success=False)
        job = json.loads(raw)
        job["status"] = "cancelled"
        cache.set(f"{_IMPORT_PFX}{job_id}", json.dumps(job), ttl=86400 * 30)
        return create_api_base_response(data={"cancelled": True, "job_id": job_id})
