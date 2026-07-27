from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class CardContactSyncMeta:
    """Lightweight sync metadata for a persisted contact, used by the CardDAV sync engine.

    Carries only the fields needed for change detection (uid, rev/updated_at) and the
    key for database operations (key). No full contact deserialization.
    """

    # Opaque public key (maps to CardContact.key)
    key: str | None = None
    # vCard UID
    uid: str | None = None
    # Server-side last-updated timestamp
    updated_at: datetime | None = None
    # vCard REV value (from contact_data JSON)
    rev: Any = None
