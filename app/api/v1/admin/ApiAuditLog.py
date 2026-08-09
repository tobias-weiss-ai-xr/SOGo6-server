"""Audit Log — tamper-evident, SIEM-exportable.

Every entry is a link in a SHA-256 hash chain:

  * each entry carries a monotonic ``seq`` (Redis INCR), the ``prev_seq`` and
    ``prev_hash`` of the entry written just before it, and its own ``hash``
    over the canonical entry fields (including ``prev_hash``);
  * mutating or deleting a retained entry breaks the chain — ``/verify``
    recomputes every link and reports exactly which sequence broke;
  * retention trimming is honest: entries beyond ``_MAX_ENTRIES`` are removed
    with ``ZREMRANGEBYRANK`` (oldest first, real removal — the previous
    implementation called ``zset_remove`` with score strings, which never
    removed anything) and the verify endpoint reports the trimmed boundary
    rather than flagging it as tampering.

SIEM export: ``/audit-log/export?format=cef|jsonl`` emits CEF or NDJSON lines
(oldest first) with proper field escaping.
"""
from __future__ import annotations

import hashlib
import json
import time
from flask import request
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.service import sogo_cache
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

blp = Blueprint("Audit Log", __name__, url_prefix="/audit-log")

_AUDIT_ZSET: str = "audit_log"
_AUDIT_SEQ_KEY: str = "audit_log_seq"
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


def _canonical(entry: dict) -> str:
    """Canonical JSON of every hashed field, in a fixed key order."""
    return json.dumps(
        {
            "timestamp": entry.get("timestamp"),
            "action": entry.get("action"),
            "actor": entry.get("actor"),
            "target": entry.get("target"),
            "detail": entry.get("detail"),
            "ip": entry.get("ip"),
            "seq": entry.get("seq"),
            "prev_seq": entry.get("prev_seq"),
            "prev_hash": entry.get("prev_hash"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _entry_hash(entry: dict) -> str:
    """SHA-256 of the canonical entry (its own hash does not feed the input)."""
    return hashlib.sha256(_canonical(entry).encode()).hexdigest()


def audit(action: str, actor: str = "", target: str = "", detail: str = "", ip: str = "") -> None:
    """Append an entry to the tamper-evident audit log."""
    cache = sogo_cache()
    seq = cache.incr(_AUDIT_SEQ_KEY)

    newest = cache.zset_revrange(_AUDIT_ZSET, 0, 0)
    prev_seq = 0
    prev_hash = ""
    if newest:
        try:
            prev_entry = json.loads(newest[0])
            prev_seq = int(prev_entry.get("seq", 0))
            prev_hash = str(prev_entry.get("hash", ""))
        except Exception:  # pragma: no cover - corrupt member is reported by /verify
            prev_seq = 0
            prev_hash = ""

    entry = {
        "timestamp": int(time.time()),
        "action": action,
        "actor": actor,
        "target": target,
        "detail": detail,
        "ip": ip,
        "seq": seq,
        "prev_seq": prev_seq,
        "prev_hash": prev_hash,
    }
    entry["hash"] = _entry_hash(entry)

    cache.zset_add(_AUDIT_ZSET, json.dumps(entry, sort_keys=True), float(seq))

    total = cache.zset_count(_AUDIT_ZSET)
    if total > _MAX_ENTRIES:
        # Real retention: drop the lowest-scoring (oldest) members.
        cache.zset_trim(_AUDIT_ZSET, _MAX_ENTRIES)

    logger_api.debug("Audit seq=%d: %s by %s", seq, action, actor)


def _all_entries() -> list[dict]:
    """Return every retained audit entry, oldest first."""
    cache = sogo_cache()
    raw = cache.zset_revrange(_AUDIT_ZSET, 0, -1)
    out = []
    for member in raw:
        try:
            out.append(json.loads(member))
        except Exception:
            continue
    out.sort(key=lambda e: int(e.get("seq", 0)))
    return out


def verify_chain() -> dict:
    """Recompute the hash chain and report integrity honestly.

    Returns ``{"chain_valid": bool, "entries": int, "trimmed": bool,
    "broken": [{"seq": int, "reason": str}]}``.  A ``trimmed`` head boundary
    (an oldest retained entry whose predecessor was dropped by retention) is
    information, not a tamper flag.
    """
    entries = _all_entries()
    if not entries:
        return {"chain_valid": True, "entries": 0, "trimmed": False, "broken": []}

    by_seq = {int(e.get("seq", 0)): e for e in entries}
    seqs = sorted(by_seq)
    broken: list[dict] = []

    for seq in seqs:
        entry = by_seq[seq]
        recomputed = _entry_hash(entry)
        if recomputed != str(entry.get("hash", "")):
            broken.append({"seq": seq, "reason": "stored hash does not match content"})

    for i in range(1, len(seqs)):
        prev_entry = by_seq[seqs[i - 1]]
        cur_entry = by_seq[seqs[i]]
        if int(cur_entry.get("prev_seq", 0)) != int(prev_entry.get("seq", 0)):
            broken.append({"seq": seqs[i], "reason": "sequence link skip"})
        elif str(cur_entry.get("prev_hash", "")) != str(prev_entry.get("hash", "")):
            broken.append({"seq": seqs[i], "reason": "previous-entry hash mismatch"})

    # head boundary: the oldest retained entry's predecessor was trimmed away
    oldest = by_seq[seqs[0]]
    trimmed = int(oldest.get("prev_seq", 0)) != 0 and int(oldest.get("prev_seq", 0)) not in by_seq
    # zero-length chain where seq 1 was never written looks like trimming; the
    # empty prev fields on seq 1 are the honest anchor of a fresh log
    if int(oldest.get("prev_seq", 0)) == 0:
        trimmed = False

    return {
        "chain_valid": not broken,
        "entries": len(entries),
        "trimmed": trimmed,
        "broken": broken,
    }


def _cef_escape(value: str) -> str:
    """CEF escaping: backslash, pipe, and '=' are replaced per the spec."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("=", "\\=")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def _to_cef(entry: dict) -> str:
    action = _cef_escape(entry.get("action", "audit"))
    actor = _cef_escape(entry.get("actor", "unknown"))
    detail = _cef_escape(entry.get("detail", ""))
    target = _cef_escape(entry.get("target", ""))
    ip = _cef_escape(entry.get("ip", ""))
    ts = int(entry.get("timestamp", 0))
    return (
        f"CEF:0|SOGo|SOGo Server|6.0.0-alpha1|audit|{action}|5|"
        f"rt={ts} src={ip} suser={actor} msg={detail} "
        f"cs1Label=target cs1={target} cs2Label=seq cs2={entry.get('seq', '')}"
    )


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


@blp.route("/verify")
class ApiAuditLogVerify(MethodView):
    """Chain-integrity verification (tamper detection)."""

    def get(self) -> ResponseReturnValue:
        return create_api_base_response(data=verify_chain())


@blp.route("/export")
class ApiAuditLogExport(MethodView):
    """SIEM export in CEF or NDJSON format (oldest first)."""

    def get(self) -> ResponseReturnValue:
        from flask import Response

        fmt = (request.args.get("format", "cef") or "").lower()
        entries = _all_entries()
        if fmt == "jsonl":
            body = "\n".join(json.dumps(e, sort_keys=True, separators=(",", ":")) for e in entries)
            content_type = "application/x-ndjson"
        else:
            body = "\n".join(_to_cef(e) for e in entries)
            content_type = "text/plain"
        return Response(body + ("\n" if body else ""), content_type=content_type)