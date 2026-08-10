from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Invite lifecycle statuses
INVITE_STATUS_PENDING: str = "pending"
INVITE_STATUS_ACCEPTED: str = "accepted"
INVITE_STATUS_REJECTED: str = "rejected"
INVITE_STATUS_CANCELLED: str = "cancelled"

VALID_INVITE_STATUSES: frozenset[str] = frozenset(
    {INVITE_STATUS_PENDING, INVITE_STATUS_ACCEPTED, INVITE_STATUS_REJECTED, INVITE_STATUS_CANCELLED}
)


@dataclass
class CalendarInvite:
    """A membership invitation to a team calendar."""

    id: str = ""
    calendar_key: str = ""
    user_uid: str = ""
    invited_by: str = ""
    status: str = INVITE_STATUS_PENDING
    share_level: str = "view_all"
    created_at: datetime | None = None
    updated_at: datetime | None = None
