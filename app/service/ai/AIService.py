"""AI Service — local model inference for SOGo 6 intelligence features.

Supports:
- Email summarization via extractive/abstractive summarization
- Email classification (newsletter, invoice, notification, personal)
- Draft assistance (reply suggestions, tone adjustment)
- Natural language to structured search query
- Anomaly detection in sending patterns

Uses a pluggable model backend — defaults to a rule-based fallback
so features work out of the box. Set SOGO_AI_OLLAMA_URL to use a local
Ollama server for real LLM-powered features.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Callable

import requests

from app.service import sogo_cache
from app.utils.logger.logger import logger_api

# Cache prefix for AI results
_AI_CACHE_PREFIX: str = "ai:cache:"

# Ollama configuration (env-driven, hot-reloadable)
_OLLAMA_URL: str | None = None
_OLLAMA_MODEL: str = "qwen2.5:1.5b"


def _get_ollama_config() -> tuple[str | None, str]:
    """Read Ollama config from env. Cached at module level but re-reads if env changes."""
    global _OLLAMA_URL, _OLLAMA_MODEL
    url = os.getenv("SOGO_AI_OLLAMA_URL", "")
    model = os.getenv("SOGO_AI_OLLAMA_MODEL", "qwen2.5:1.5b")
    if url:
        _OLLAMA_URL = url.rstrip("/")
    else:
        _OLLAMA_URL = None
    _OLLAMA_MODEL = model
    return _OLLAMA_URL, _OLLAMA_MODEL


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
        _ = filename.lower()
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


class OllamaBackend(AIModelBackend):
    """LLM-powered backend using a local Ollama server.

    Falls back to the rule-based parent for methods that don't benefit
    from LLM (classify_attachment, detect_anomaly, nl_to_search) or
    when the Ollama server is unreachable.
    """

    def __init__(self, url: str, model: str):
        super().__init__()
        self._url = url.rstrip("/")
        self._model = model
        self._timeout = int(os.getenv("SOGO_AI_OLLAMA_TIMEOUT", "30"))

    def load(self) -> bool:
        """Check Ollama server is reachable."""
        try:
            resp = requests.get(f"{self._url}/api/tags", timeout=5)
            self._loaded = resp.status_code == 200
        except Exception:
            self._loaded = False
        if self._loaded:
            logger_api.info("Ollama backend loaded: %s (model: %s)", self._url, self._model)
        else:
            logger_api.warning("Ollama backend unavailable at %s — falling back to rules", self._url)
        return self._loaded

    def _chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        """Call Ollama /api/chat and return the assistant content."""
        try:
            resp = requests.post(
                f"{self._url}/api/chat",
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "options": {"temperature": temperature},
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"].strip()
        except Exception as exc:
            logger_api.warning("Ollama chat failed: %s — falling back to rules", exc)
            return ""

    # ── LLM-powered overrides ─────────────────────────────────────────────

    def summarize(self, text: str, max_sentences: int = 3) -> str:
        system = (
            "You are an email summarizer. Summarize the following email "
            f"in {max_sentences} sentences. Reply with only the summary, no preamble."
        )
        result = self._chat(system, text[:8000])
        return result if result else super().summarize(text, max_sentences)

    def classify(self, text: str, subject: str = "", sender: str = "") -> list[dict]:
        system = (
            "You are an email classifier. Classify the email into one or more "
            "of: newsletter, invoice, notification, social, personal, other. "
            'Reply as JSON: [{"label": "...", "confidence": 0.0-1.0}, ...]. '
            "No preamble."
        )
        payload = f"Subject: {subject}\nFrom: {sender}\nBody: {text[:4000]}"
        result = self._chat(system, payload)
        if result:
            try:
                parsed = json.loads(result)
                if isinstance(parsed, list) and parsed:
                    return parsed
            except json.JSONDecodeError:
                pass
        return super().classify(text, subject, sender)

    def suggest_reply(self, email_text: str, tone: str = "professional") -> str:
        system = (
            f"You are an email assistant. Write a {tone} reply to the email below. "
            "Reply with only the email body, no subject line, no preamble."
        )
        result = self._chat(system, email_text[:8000], temperature=0.5)
        return result if result else super().suggest_reply(email_text, tone)

    def extract_contact_info(self, text: str) -> dict:
        system = (
            "You are a contact information extractor. Extract phone, title, "
            "company, and location from the text below. "
            'Reply as JSON: {"phone": "...", "title": "...", '
            '"company": "...", "location": "..."}. Missing fields = null. No preamble.'
        )
        result = self._chat(system, text[:4000])
        if result:
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        return super().extract_contact_info(text)


# Singleton
_model_backend: AIModelBackend | None = None


def get_model_backend() -> AIModelBackend:
    """Return the AI model backend.

    If SOGO_AI_OLLAMA_URL is set and the server is reachable, returns
    an OllamaBackend (LLM-powered). Otherwise returns the rule-based
    AIModelBackend fallback.
    """
    global _model_backend
    if _model_backend is None:
        url, model = _get_ollama_config()
        if url:
            backend = OllamaBackend(url, model)
            if backend.load():
                _model_backend = backend
            else:
                _model_backend = AIModelBackend()
                _model_backend.load()
        else:
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
                    pass  # best-effort: keep fallback/default value on failure
            result = func(*args, **kwargs)
            cache.set(key, json.dumps(result), ttl=ttl)
            return result
        return wrapper
    return decorator
