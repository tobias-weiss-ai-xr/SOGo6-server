"""
Locale-aware iMIP / reminder email strings for the calendar module.

Replaces hard-coded English subject prefixes and body labels with
translations sourced from the recipient's language preference.

The user's language is read from ``SOGO_U_LANGUAGE`` (user setting) or
falls back to ``en``.  When a translation key is missing for a locale the
English value is used as fallback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.auth.User import User

# ── Translation tables ──────────────────────────────────────────────────────

_IMIP_SUBJECTS: dict[str, dict[str, str]] = {
    "en": {
        "request": "Invitation",
        "reply": "Re",
        "cancel": "Cancelled",
    },
    "de": {
        "request": "Einladung",
        "reply": "Antwort",
        "cancel": "Abgesagt",
    },
    "fr": {
        "request": "Invitation",
        "reply": "Réponse",
        "cancel": "Annulé",
    },
    "es": {
        "request": "Invitación",
        "reply": "Respuesta",
        "cancel": "Cancelado",
    },
    "zh": {
        "request": "邀请",
        "reply": "回复",
        "cancel": "已取消",
    },
}

_REMINDER_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "prefix": "Reminder",
        "when": "When",
        "where": "Where",
        "default_title": "Event",
    },
    "de": {
        "prefix": "Erinnerung",
        "when": "Wann",
        "where": "Wo",
        "default_title": "Termin",
    },
    "fr": {
        "prefix": "Rappel",
        "when": "Quand",
        "where": "Où",
        "default_title": "Événement",
    },
    "es": {
        "prefix": "Recordatorio",
        "when": "Cuándo",
        "where": "Dónde",
        "default_title": "Evento",
    },
    "zh": {
        "prefix": "提醒",
        "when": "时间",
        "where": "地点",
        "default_title": "事件",
    },
}

# ── Public helpers ──────────────────────────────────────────────────────────


def _locale_for(user: User | None) -> str:
    """Return the user's language code (ISO 639-1), defaulting to ``en``."""
    if user is None:
        return "en"
    try:
        lang = getattr(user, "language", None) or getattr(user, "SOGO_U_LANGUAGE", None)
        if lang and lang in _IMIP_SUBJECTS:
            return lang
    except Exception:
        pass
    return "en"


def imip_subject_prefix(method: str, user: User | None = None) -> str:
    """Return the iMIP Subject prefix for *method* (request/reply/cancel) in the user's locale."""
    locale = _locale_for(user)
    table = _IMIP_SUBJECTS.get(locale, _IMIP_SUBJECTS["en"])
    return table.get(method, _IMIP_SUBJECTS["en"].get(method, method.title()))


def reminder_subject_prefix(user: User | None = None) -> str:
    """Return the reminder email subject prefix in the user's locale."""
    locale = _locale_for(user)
    table = _REMINDER_LABELS.get(locale, _REMINDER_LABELS["en"])
    return table["prefix"]


def reminder_label_when(user: User | None = None) -> str:
    locale = _locale_for(user)
    table = _REMINDER_LABELS.get(locale, _REMINDER_LABELS["en"])
    return table["when"]


def reminder_label_where(user: User | None = None) -> str:
    locale = _locale_for(user)
    table = _REMINDER_LABELS.get(locale, _REMINDER_LABELS["en"])
    return table["where"]


def reminder_default_title(user: User | None = None) -> str:
    locale = _locale_for(user)
    table = _REMINDER_LABELS.get(locale, _REMINDER_LABELS["en"])
    return table["default_title"]
