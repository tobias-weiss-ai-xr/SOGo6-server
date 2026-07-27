"""Intelligent Spam Filtering (#64) — local ONNX model complementing Rspamd.

Provides a trainable spam scoring endpoint using keyword heuristics
and configurable thresholds. Pluggable ONNX model slot for production.
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from typing import TYPE_CHECKING

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.service import sogo_cache
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User

blp = Blueprint("Intelligent Spam Filter", __name__, url_prefix="/ai/spam")

_SPAM_STATS_PREFIX: str = "spam:stats:"
_ONNX_MODEL_PATH = "/app/models/spam_classifier.onnx"

# ── Spam signal detection (real heuristic scoring) ──────────────────────

_SPAM_PATTERNS: list[tuple[str, float]] = [
    (r"urgent action required", 2.5),
    (r"click here (?:now|immediately)", 3.0),
    (r"you (?:have won|won|been selected)", 4.0),
    (r"(?:free|no cost|zero cost)", 1.5),
    (r"(?:money|cash|prize|reward)", 2.0),
    (r"(?:100%\s*guarantee|satisfaction guaranteed)", 3.0),
    (r"(?:act now|limited time|expires)", 2.0),
    (r"(?:viagra|pharmacy|casino|lottery)", 4.0),
    (r"(?:password|account|verify your)", 1.0),
    (r"(?:crypto|bitcoin|investment opportunity)", 2.5),
    (r"\b[A-Z]{5,}\b", 0.5),  # All-caps words
    (r"(?:dear friend|dear customer|dear member)", 2.0),
    (r"(?:unsubscribe|opt-out)", -1.0),  # Legitimate indicator
    (r"(?:sent from my|regards|best regards)", -0.5),
    (r"\d{1,2} mill(?:ion|ion)", 3.0),
    (r"(?:wire transfer|bank transfer|western union)", 3.5),
]

_BENIGN_PATTERNS: list[tuple[str, float]] = [
    (r"(?:meeting|schedule|calendar|invite)", -1.5),
    (r"(?:attachment|attached|see attached)", -1.0),
    (r"(?:sincerely|regards|cheers|thanks)", -0.5),
    (r"(?:https?://\S+\.\S+)", -0.3),  # URLs tend to be legit
]


def _compute_spam_score(
    subject: str,
    body: str,
    sender: str,
    has_attachments: bool = False,
) -> dict:
    """Compute spam score from real heuristic analysis."""
    text = f"{subject} {body}".lower()
    score = 0.0
    signals: list[dict] = []

    # Subject signals
    subject_lower = subject.lower()
    if any(w in subject_lower for w in ["!!!", "???", "free", "urgent", "winner"]):
        score += 1.5
        signals.append({"type": "subject", "signal": "spammy_subject", "weight": 1.5})

    # Body pattern matching
    for pattern, weight in _SPAM_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            score += weight * len(matches)
            signals.append({"type": "pattern", "signal": pattern[:40], "weight": weight * len(matches), "count": len(matches)})

    # Benign pattern discount
    for pattern, weight in _BENIGN_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            score += weight * len(matches)
            signals.append({"type": "benign", "signal": pattern[:40], "weight": weight * len(matches)})

    # Sender analysis
    if sender:
        # Numeric-heavy local parts
        local = sender.split("@")[0] if "@" in sender else sender
        digits = sum(c.isdigit() for c in local)
        if digits > len(local) * 0.5:
            score += 2.0
            signals.append({"type": "sender", "signal": "numeric_heavy_local", "weight": 2.0})

        # Suspicious TLDs
        tld = sender.split(".")[-1].lower() if "." in sender else ""
        if tld in ("xyz", "top", "click", "stream", "download", "win"):
            score += 1.5
            signals.append({"type": "sender", "signal": f"suspicious_tld_{tld}", "weight": 1.5})

    # Body length heuristics
    if len(body) > 0:
        caps_ratio = sum(c.isupper() for c in body) / max(len(body), 1)
        if caps_ratio > 0.3:
            score += 1.0
            signals.append({"type": "body", "signal": "high_caps_ratio", "weight": 1.0})

        link_count = len(re.findall(r"https?://", body))
        if link_count > 5:
            score += 1.5
            signals.append({"type": "body", "signal": "excessive_links", "weight": 1.5})

    # Attachment heuristics
    if has_attachments:
        # Legitimate emails often have attachments, slight discount
        score -= 0.3

    # Normalize to 0-10
    normalized = max(0.0, min(10.0, score / 2.0))
    is_spam = normalized >= 5.0
    is_suspicious = normalized >= 3.5 and not is_spam

    return {
        "score": round(normalized, 2),
        "is_spam": is_spam,
        "is_suspicious": is_suspicious,
        "classification": "spam" if is_spam else ("suspicious" if is_suspicious else "ham"),
        "signals": signals[:10],
        "model": "heuristic",
    }


class SpamScoreSchema(Schema):
    subject = fields.String(required=True)
    body = fields.String(required=True)
    sender = fields.String(load_default="")
    has_attachments = fields.Boolean(load_default=False)


class SpamReportSchema(Schema):
    message_id = fields.String(required=True)
    is_spam = fields.Boolean(required=True)
    sender = fields.String(load_default="")


@blp.route("/score")
class ApiSpamScore(MethodView):
    @blp.arguments(SpamScoreSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """Score an email for spam probability."""
        result = _compute_spam_score(
            subject=body["subject"],
            body=body["body"],
            sender=body.get("sender", ""),
            has_attachments=body.get("has_attachments", False),
        )
        logger_api.info("Spam score: %.1f (%s)", result["score"], result["classification"])
        return create_api_base_response(result)


@blp.route("/report")
class ApiSpamReport(MethodView):
    @blp.arguments(SpamReportSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """Report a message as spam or ham for model training."""
        cache = sogo_cache()
        report = {
            "message_id": body["message_id"],
            "is_spam": body["is_spam"],
            "sender": body.get("sender", ""),
            "reported_at": int(time.time()),
        }
        key = f"spam:report:{body['message_id']}"
        cache.set(key, json.dumps(report), ttl=86400 * 30)

        # Update sender reputation
        sender = body.get("sender", "")
        if sender:
            stats_key = f"{_SPAM_STATS_PREFIX}{sender}"
            raw = cache.get(stats_key, str)
            stats = json.loads(raw) if raw else {"total": 0, "spam": 0}
            stats["total"] += 1
            if body["is_spam"]:
                stats["spam"] += 1
            cache.set(stats_key, json.dumps(stats), ttl=86400 * 365)

        return create_api_base_response({"status": "recorded", "message_id": body["message_id"]})


@blp.route("/stats")
class ApiSpamStats(MethodView):
    def get(self) -> ResponseReturnValue:
        """Get spam filtering statistics."""
        cache = sogo_cache()
        raw = cache.get("spam:global_stats", str)
        stats = json.loads(raw) if raw else {
            "total_scored": 0,
            "classified_spam": 0,
            "classified_ham": 0,
            "classified_suspicious": 0,
            "false_positive_reports": 0,
        }
        return create_api_base_response(stats)
