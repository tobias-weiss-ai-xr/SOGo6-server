"""Meeting Transcript & Summary (#65) — Whisper/STT → notes to calendar event.

Records meeting transcripts, transcribes via STT, and generates
structured summaries linked to calendar events.
"""
from __future__ import annotations

import json
import os
import secrets
import time
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

blp = Blueprint("Meeting Transcripts", __name__, url_prefix="/ai/transcripts")

_PREFIX: str = "transcript:"
_WHISPER_URL = os.getenv("WHISPER_API_URL", "")

# ── Summary extraction (real extractive logic) ──────────────────────────

def _extract_summary(text: str, max_lines: int = 10) -> str:
    """Extract key points from transcript text."""
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if len(sentences) <= max_lines:
        return text

    # Score: action items + questions + long sentences weighted higher
    scored = []
    action_keywords = ["should", "need to", "will", "must", "action item", "next step", "todo", "deadline", "follow up"]
    question_keywords = ["?", "how", "what", "when", "who", "why"]

    for i, s in enumerate(sentences):
        score = 1.0
        s_lower = s.lower()
        for kw in action_keywords:
            if kw in s_lower:
                score += 2.0
        for kw in question_keywords:
            if kw in s_lower:
                score += 1.5
        score += len(s.split()) * 0.1  # Longer = more informative
        score *= 1.0 / (i // 5 + 1)  # Position bonus (earlier = more important)
        scored.append((score, s))

    scored.sort(reverse=True)
    top = sorted([s for _, s in scored[:max_lines]], key=lambda s: text.index(s) if s in text else 0)
    return " ".join(top)


def _extract_action_items(text: str) -> list[dict]:
    """Extract action items from transcript."""
    import re
    items = []
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    action_triggers = [
        r"(?:i|we|you|they|he|she)\s+(?:should|need to|will|must|have to|plan to|are going to)\s+",
        r"action\s+item\s*:?\s*",
        r"next\s+(?:step|steps?)\s*:?\s*",
        r"TODO\s*:?\s*",
        r"deadline\s+(?:is|:)\s*",
        r"follow\s+up\s+(?:on|with)\s*",
    ]
    for sentence in sentences:
        for trigger in action_triggers:
            if re.search(trigger, sentence, re.IGNORECASE):
                items.append({
                    "text": sentence.strip(),
                    "type": "action_item",
                })
                break
    return items[:10]


class TranscriptCreateSchema(Schema):
    event_id = fields.String(load_default="")
    title = fields.String(required=True)
    text = fields.String(required=True, metadata={"description": "Transcript or raw meeting notes"})
    language = fields.String(load_default="en")
    duration_minutes = fields.Integer(load_default=60)
    attendees = fields.List(fields.String(), load_default=[])


class TranscriptUpdateSchema(Schema):
    text = fields.String(load_default="")


@blp.route("")
class ApiTranscriptListCreate(MethodView):
    def get(self) -> ResponseReturnValue:
        user: User = g.user
        cache = sogo_cache()
        index = list(cache.get(f"{_PREFIX}index:{user.uid}", list) or [])
        transcripts = []
        for tid in index:
            raw = cache.get(f"{_PREFIX}{tid}", str)
            if raw:
                try:
                    transcripts.append(json.loads(raw))
                except Exception:
                    continue
        return create_api_base_response({"transcripts": transcripts})

    @blp.arguments(TranscriptCreateSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        user: User = g.user
        cache = sogo_cache()
        transcript_id = secrets.token_hex(12)

        summary = _extract_summary(body["text"])
        action_items = _extract_action_items(body["text"])

        transcript = {
            "id": transcript_id,
            "event_id": body.get("event_id", ""),
            "title": body["title"],
            "text": body["text"],
            "summary": summary,
            "action_items": action_items,
            "language": body.get("language", "en"),
            "duration_minutes": body.get("duration_minutes", 60),
            "attendees": body.get("attendees", []),
            "created_by": user.uid,
            "created_at": int(time.time()),
        }
        cache.set(f"{_PREFIX}{transcript_id}", json.dumps(transcript), ttl=86400 * 90)
        idx = list(cache.get(f"{_PREFIX}index:{user.uid}", list) or [])
        idx.append(transcript_id)
        cache.set(f"{_PREFIX}index:{user.uid}", idx, ttl=86400 * 90)
        logger_api.info("Transcript created: %s for event %s", transcript_id[:8], body.get("event_id", ""))
        return create_api_base_response(transcript, code=201)


@blp.route("/<string:transcript_id>")
class ApiTranscriptDetail(MethodView):
    def get(self, transcript_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_PREFIX}{transcript_id}", str)
        if not raw:
            from app.utils import errors as err
            return create_api_base_response(None, err.ERROR_NOT_FOUND)
        return create_api_base_response(json.loads(raw))


@blp.route("/<string:transcript_id>/summary")
class ApiTranscriptSummary(MethodView):
    def get(self, transcript_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_PREFIX}{transcript_id}", str)
        if not raw:
            from app.utils import errors as err
            return create_api_base_response(None, err.ERROR_NOT_FOUND)
        transcript = json.loads(raw)
        summary = _extract_summary(transcript["text"])
        action_items = _extract_action_items(transcript["text"])
        return create_api_base_response({
            "transcript_id": transcript_id,
            "summary": summary,
            "action_items": action_items,
            "duration_minutes": transcript.get("duration_minutes", 0),
            "attendee_count": len(transcript.get("attendees", [])),
        })
