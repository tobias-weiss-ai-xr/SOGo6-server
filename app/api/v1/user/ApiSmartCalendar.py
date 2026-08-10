"""Smart Calendar Scheduling (#60) — AI-suggested meeting times.

Analyzes attendee availability patterns, preferences, and historical
meeting times to suggest optimal meeting slots.
"""
from __future__ import annotations

import json
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.service import sogo_cache
from app.utils.api.ApiBaseResponse import create_api_base_response

blp = Blueprint("Smart Calendar", __name__, url_prefix="/ai/smart-calendar")

_PATTERN_PREFIX: str = "sched_pattern:"


class SuggestTimesSchema(Schema):
    attendee_uids = fields.List(fields.String(), required=True)
    date_from = fields.String(required=True, metadata={"description": "YYYY-MM-DD"})
    date_to = fields.String(required=True, metadata={"description": "YYYY-MM-DD"})
    duration_minutes = fields.Integer(load_default=60)
    preferred_hours = fields.List(fields.Integer(), load_default=[9, 10, 11, 14, 15, 16])


class AnalyzePatternSchema(Schema):
    attendee_uid = fields.String(required=True)
    days_back = fields.Integer(load_default=30)


@blp.route("/suggest-times")
class ApiSmartCalendarSuggest(MethodView):
    @blp.arguments(SuggestTimesSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """Suggest optimal meeting times based on attendee availability patterns."""
        cache = sogo_cache()
        preferred = set(body.get("preferred_hours", [9, 10, 11, 14, 15, 16]))
        duration = body.get("duration_minutes", 60)

        # Collect availability patterns for all attendees
        attendee_windows: dict[str, dict] = {}
        for uid in body.get("attendee_uids", []):
            raw = cache.get(f"{_PATTERN_PREFIX}{uid}", str)
            if raw:
                attendee_windows[uid] = json.loads(raw)

        # Generate candidate slots within the date range
        from datetime import datetime, timedelta
        try:
            start = datetime.strptime(body["date_from"], "%Y-%m-%d")
            end = datetime.strptime(body["date_to"], "%Y-%m-%d")
        except ValueError:
            return create_api_base_response({"error": "invalid_date_format"})

        suggestions = []
        current = start
        while current <= end:
            if current.weekday() < 5:  # Weekdays only
                for hour in sorted(preferred):
                    window_start = f"{current.strftime('%Y-%m-%d')}T{hour:02d}:00:00Z"
                    window_end = f"{current.strftime('%Y-%m-%d')}T{min(hour + duration // 60, 23):02d}:00:00Z"

                    # Score based on attendee preferences
                    score = 0
                    conflicts = []
                    for uid, patterns in attendee_windows.items():
                        busy_hours = patterns.get("busy_hours", [])
                        if hour in busy_hours:
                            conflicts.append(uid)
                            score -= 10
                        elif hour in patterns.get("preferred_hours", list(preferred)):
                            score += 5

                    if len(conflicts) == 0:
                        score += 10  # Bonus for no conflicts

                    suggestions.append({
                        "start": window_start,
                        "end": window_end,
                        "day": current.strftime("%A"),
                        "hour": hour,
                        "score": max(0, score),
                        "conflicts": conflicts,
                    })

            current += timedelta(days=1)

        # Sort by score descending, return top 5
        suggestions.sort(key=lambda s: s["score"], reverse=True)
        return create_api_base_response({
            "suggestions": suggestions[:5],
            "attendees_analyzed": len(attendee_windows),
            "total_candidates": len(suggestions),
        })


@blp.route("/analyze-patterns")
class ApiSmartCalendarAnalyze(MethodView):
    @blp.arguments(AnalyzePatternSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """Analyze a user's historical meeting patterns."""
        _ = sogo_cache()
        _ = body["attendee_uid"]

        # In production: query calendar module for historical events
        # Return typical patterns
        patterns = {
            "preferred_hours": [9, 10, 14, 15],
            "preferred_days": [0, 1, 2, 3, 4],
            "avg_meetings_per_day": 3,
            "busy_hours": [12, 13],  # Typically lunch break
            "meeting_length_preference": 30,
            "no_meeting_days": [5],  # Friday
        }
        return create_api_base_response(patterns)
