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
    "it": {
        "request": "Invito",
        "reply": "Risposta",
        "cancel": "Annullato",
    },
    "pt": {
        "request": "Convite",
        "reply": "Resposta",
        "cancel": "Cancelado",
    },
    "nl": {
        "request": "Uitnodiging",
        "reply": "Antwoord",
        "cancel": "Geannuleerd",
    },
    "pl": {
        "request": "Zaproszenie",
        "reply": "Odpowiedź",
        "cancel": "Anulowano",
    },
    "ru": {
        "request": "Приглашение",
        "reply": "Ответ",
        "cancel": "Отменено",
    },
    "sv": {
        "request": "Inbjudan",
        "reply": "Svar",
        "cancel": "Avbokad",
    },
    "da": {
        "request": "Invitation",
        "reply": "Svar",
        "cancel": "Aflyst",
    },
    "fi": {
        "request": "Kutsu",
        "reply": "Vastaus",
        "cancel": "Peruttu",
    },
    "nb": {
        "request": "Invitasjon",
        "reply": "Svar",
        "cancel": "Avlyst",
    },
    "cs": {
        "request": "Pozvánka",
        "reply": "Odpověď",
        "cancel": "Zrušeno",
    },
    "el": {
        "request": "Πρόσκληση",
        "reply": "Απάντηση",
        "cancel": "Ακυρώθηκε",
    },
    "tr": {
        "request": "Davetiye",
        "reply": "Yanıt",
        "cancel": "İptal Edildi",
    },
    "hu": {
        "request": "Meghívó",
        "reply": "Válasz",
        "cancel": "Lemondva",
    },
    "ro": {
        "request": "Invitație",
        "reply": "Răspuns",
        "cancel": "Anulat",
    },
    "ja": {
        "request": "招待",
        "reply": "返信",
        "cancel": "キャンセル",
    },
    "hi": {
        "request": "निमंत्रण",
        "reply": "उत्तर",
        "cancel": "रद्द किया गया",
    },
    "ar": {
        "request": "دعوة",
        "reply": "رد",
        "cancel": "ملغي",
    },
    "ko": {
        "request": "초대",
        "reply": "답장",
        "cancel": "취소됨",
    },
    "th": {
        "request": "คำเชิญ",
        "reply": "ตอบกลับ",
        "cancel": "ยกเลิก",
    },
    "vi": {
        "request": "Lời mời",
        "reply": "Trả lời",
        "cancel": "Đã hủy",
    },
    "id": {
        "request": "Undangan",
        "reply": "Balasan",
        "cancel": "Dibatalkan",
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
    "it": {
        "prefix": "Promemoria",
        "when": "Quando",
        "where": "Dove",
        "default_title": "Evento",
    },
    "pt": {
        "prefix": "Lembrete",
        "when": "Quando",
        "where": "Onde",
        "default_title": "Evento",
    },
    "nl": {
        "prefix": "Herinnering",
        "when": "Wanneer",
        "where": "Waar",
        "default_title": "Gebeurtenis",
    },
    "pl": {
        "prefix": "Przypomnienie",
        "when": "Kiedy",
        "where": "Gdzie",
        "default_title": "Wydarzenie",
    },
    "ru": {
        "prefix": "Напоминание",
        "when": "Когда",
        "where": "Где",
        "default_title": "Событие",
    },
    "sv": {
        "prefix": "Påminnelse",
        "when": "När",
        "where": "Var",
        "default_title": "Händelse",
    },
    "da": {
        "prefix": "Påmindelse",
        "when": "Hvornår",
        "where": "Hvor",
        "default_title": "Begivenhed",
    },
    "fi": {
        "prefix": "Muistutus",
        "when": "Milloin",
        "where": "Missä",
        "default_title": "Tapahtuma",
    },
    "nb": {
        "prefix": "Påminnelse",
        "when": "Når",
        "where": "Hvor",
        "default_title": "Hendelse",
    },
    "cs": {
        "prefix": "Připomínka",
        "when": "Kdy",
        "where": "Kde",
        "default_title": "Událost",
    },
    "el": {
        "prefix": "Υπενθύμιση",
        "when": "Πότε",
        "where": "Πού",
        "default_title": "Εκδήλωση",
    },
    "tr": {
        "prefix": "Hatırlatıcı",
        "when": "Ne Zaman",
        "where": "Nerede",
        "default_title": "Etkinlik",
    },
    "hu": {
        "prefix": "Emlékeztető",
        "when": "Mikor",
        "where": "Hol",
        "default_title": "Esemény",
    },
    "ro": {
        "prefix": "Memento",
        "when": "Când",
        "where": "Unde",
        "default_title": "Eveniment",
    },
    "ja": {
        "prefix": "リマインダー",
        "when": "日時",
        "where": "場所",
        "default_title": "イベント",
    },
    "hi": {
        "prefix": "अनुस्मारक",
        "when": "कब",
        "where": "कहाँ",
        "default_title": "ईवेंट",
    },
    "ar": {
        "prefix": "تذكير",
        "when": "متى",
        "where": "أين",
        "default_title": "حدث",
    },
    "ko": {
        "prefix": "알림",
        "when": "언제",
        "where": "어디서",
        "default_title": "이벤트",
    },
    "th": {
        "prefix": "การแจ้งเตือน",
        "when": "เมื่อไหร่",
        "where": "ที่ไหน",
        "default_title": "กิจกรรม",
    },
    "vi": {
        "prefix": "Nhắc nhở",
        "when": "Khi nào",
        "where": "Ở đâu",
        "default_title": "Sự kiện",
    },
    "id": {
        "prefix": "Pengingat",
        "when": "Kapan",
        "where": "Di mana",
        "default_title": "Acara",
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
