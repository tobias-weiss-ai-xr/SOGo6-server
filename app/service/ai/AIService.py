"""AI Service — local model inference for SOGo 6 intelligence features.

Supports:
- Email summarization via extractive/abstractive summarization
- Email classification (newsletter, invoice, notification, personal)
- Draft assistance (reply suggestions, tone adjustment)
- Natural language to structured search query
- Anomaly detection in sending patterns

Uses a pluggable model backend — defaults to a rule-based fallback
so features work out of the box. Connect local ONNX/LLM models for
production use.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Callable

from app.service import sogo_cache
from app.utils.logger.logger import logger_api

# Cache prefix for AI results
_AI_CACHE_PREFIX: str = "ai:cache:"


class AIModelBackend:
    """Pluggable model backend. Replace with ONNX/LLM inference for production."""

    def __init__(self):
        self._loaded = False

    def load(self) -> bool:
        """Load the model. Returns True if successful."""
        self._loaded = True
        return True

    def is_loaded(self) -> bool:
        return self._loaded

    # ── Fallback implementations ──────────────────────────────────────────

    def summarize(self, text: str, max_sentences: int = 3) -> str:
        """Extractive summarization: return top N sentences."""
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        if len(sentences) <= max_sentences:
            return text
        # Score sentences by length + position (first sentences are more important)
        scored = []
        for i, s in enumerate(sentences):
            score = len(s.split()) * (1.0 / (i + 1))
            scored.append((score, s))
        scored.sort(reverse=True)
        top = [s for _, s in scored[:max_sentences]]
        # Re-sort by original position
        top.sort(key=lambda s: sentences.index(s) if s in sentences else 0)
        return " ".join(top)

    def classify(self, text: str, subject: str = "", sender: str = "") -> list[dict]:
        """Classify email into categories with confidence scores."""
        text_lower = (subject + " " + text).lower()
        rules = [
            ("newsletter", ["unsubscribe", "newsletter", "marketing", "promotions", "weekly digest", "monthly update"]),
            ("invoice", ["invoice", "receipt", "payment", "billing", "order confirmation", "your order"]),
            ("notification", ["notification", "alert", "reminder", "password reset", "verification code", "two-factor"]),
            ("social", ["friend request", "connection request", "invitation", "accepted your", "commented on"]),
            ("personal", ["dear", "regards", "best", "cheers", "thanks", "hello"]),
        ]
        results = []
        for label, keywords in rules:
            score = sum(1 for kw in keywords if kw in text_lower) / len(keywords)
            if score > 0:
                results.append({"label": label, "confidence": round(score, 2)})
        results.sort(key=lambda x: x["confidence"], reverse=True)
        if not results:
            results.append({"label": "other", "confidence": 1.0})
        return results

    def suggest_reply(self, email_text: str, tone: str = "professional") -> str:
        """Generate a reply suggestion based on the email content."""
        # Extract key points
        sentences = re.split(r'(?<=[.!?])\s+', email_text.strip())
        key_points = [s for s in sentences if any(w in s.lower() for w in ["question", "please", "could you", "can you", "need", "urgent"])]
        if not key_points and sentences:
            key_points = [sentences[-1]]  # Last sentence often contains the ask

        templates = {
            "professional": "Thank you for your message.\n\n{points}\n\nBest regards",
            "friendly": "Hey, thanks for reaching out!\n\n{points}\n\nCheers",
            "formal": "Dear Sir or Madam,\n\n{points}\n\nYours faithfully",
        }
        template = templates.get(tone, templates["professional"])
        points_text = "\n".join(f"- Regarding: {p}" for p in key_points[:3])
        return template.format(points=points_text) if points_text else template.format(points="I have received your message and will respond shortly.")

    def nl_to_search(self, query: str) -> dict:
        """Convert natural language to structured search query."""
        query_lower = query.lower()
        result = {"query": query, "filters": {}}

        # Date ranges
        date_patterns = [
            (r"from (\w+ \d+)", "date_from"),
            (r"until (\w+ \d+)", "date_to"),
            (r"before (\w+ \d+)", "date_to"),
            (r"after (\w+ \d+)", "date_from"),
            (r"in (march|april|may|june|july|august|september|october|november|december|january|february)", "date_range"),
        ]
        for pattern, key in date_patterns:
            m = re.search(pattern, query_lower)
            if m:
                result["filters"][key] = m.group(1)

        # Sender/recipient
        sender_m = re.search(r"from ([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})", query_lower)
        if sender_m:
            result["filters"]["from"] = sender_m.group(1)
        to_m = re.search(r"to ([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})", query_lower)
        if to_m:
            result["filters"]["to"] = to_m.group(1)

        # Amount (for invoices)
        amount_m = re.search(r"over (\d+)", query_lower)
        if amount_m:
            result["filters"]["amount_min"] = int(amount_m.group(1))

        # Labels
        if "invoice" in query_lower:
            result["filters"]["label"] = "invoice"
        elif "newsletter" in query_lower:
            result["filters"]["label"] = "newsletter"
        elif "attachment" in query_lower:
            result["filters"]["has_attachment"] = True

        return result

    def detect_anomaly(self, sending_pattern: dict) -> dict:
        """Detect unusual sending patterns."""
        flags = []
        is_anomaly = False

        # Check bulk sending
        if sending_pattern.get("recipient_count", 0) > 50:
            flags.append("bulk_send")
            is_anomaly = True

        # Check unusual hours (10 PM - 6 AM)
        hour = sending_pattern.get("hour", 12)
        if hour < 6 or hour > 22:
            flags.append("unusual_hours")
            is_anomaly = True

        # Check new recipients
        if sending_pattern.get("new_recipient_ratio", 0) > 0.8:
            flags.append("new_recipients")
            is_anomaly = True

        return {
            "is_anomaly": is_anomaly,
            "flags": flags,
            "score": len(flags) / 3.0,
        }

    def extract_contact_info(self, text: str) -> dict:
        """Extract contact information from email signature."""
        info = {}
        # Phone
        phone_m = re.search(r'(\+?\d[\d\s-]{7,}\d)', text)
        if phone_m:
            info["phone"] = phone_m.group(1).strip()
        # Title/position
        title_patterns = [
            r"(?:^|\n)\s*(Professor|Dr\.|CEO|CTO|VP|Director|Manager|Engineer|Consultant|President|Founder)",
            r"(?:^|\n)\s*(Senior|Lead|Head|Chief|Principal|Staff)\s+\w+",
        ]
        for p in title_patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                info["title"] = m.group(1).strip()
                break
        # Company
        company_m = re.search(r"(?:^|\n)\s*(?:\w+\s+){1,3}(?:Inc|Corp|LLC|Ltd|GmbH|AG|SA|BV|PLC)", text)
        if company_m:
            info["company"] = company_m.group(0).strip()
        # Location
        location_m = re.search(r"(?:^|\n)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s*[A-Z]{2})", text)
        if location_m:
            info["location"] = location_m.group(1).strip()
        return info

    def classify_attachment(self, filename: str, content_type: str) -> dict:
        """Classify attachment type and suggest actions."""
        name_lower = filename.lower()
        ext = filename.split(".")[-1].lower() if "." in filename else ""

        types = {
            "document": ["pdf", "doc", "docx", "odt", "rtf", "tex", "txt", "md"],
            "spreadsheet": ["xls", "xlsx", "csv", "ods", "numbers"],
            "presentation": ["ppt", "pptx", "odp", "key"],
            "image": ["jpg", "jpeg", "png", "gif", "bmp", "svg", "webp", "tiff"],
            "archive": ["zip", "tar", "gz", "bz2", "7z", "rar"],
            "calendar": ["ics", "ical", "icalendar"],
            "contact": ["vcf", "vcard"],
            "code": ["py", "js", "ts", "html", "css", "java", "cpp", "c", "go", "rs", "sh"],
        }

        detected_type = "unknown"
        for t, exts in types.items():
            if ext in exts:
                detected_type = t
                break

        suggestions = {
            "document": "Preview or save to Documents",
            "spreadsheet": "Open in spreadsheet viewer",
            "presentation": "Open in presentation viewer",
            "image": "Preview inline",
            "archive": "Download and extract",
            "calendar": "Import to calendar",
            "contact": "Add to contacts",
            "code": "View source",
            "unknown": "Download file",
        }

        return {
            "type": detected_type,
            "suggestion": suggestions.get(detected_type, "Download file"),
            "can_preview": detected_type in ("document", "image", "code", "calendar", "contact"),
        }


# Singleton
_model_backend: AIModelBackend | None = None


def get_model_backend() -> AIModelBackend:
    global _model_backend
    if _model_backend is None:
        _model_backend = AIModelBackend()
        _model_backend.load()
    return _model_backend


def cached_ai_result(cache_key: str, ttl: int = 3600) -> Callable:
    """Decorator: cache AI results in Redis."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            cache = sogo_cache()
            key = f"{_AI_CACHE_PREFIX}{cache_key}:{hashlib.md5(str(args).encode()).hexdigest()}"
            cached = cache.get(key, str)
            if cached:
                try:
                    return json.loads(cached)
                except Exception:
                    pass
            result = func(*args, **kwargs)
            cache.set(key, json.dumps(result), ttl=ttl)
            return result
        return wrapper
    return decorator
