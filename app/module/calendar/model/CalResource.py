from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CalResource:
    """Represents a bookable resource (meeting room, equipment, vehicle, etc.).

    Resources can be invited as attendees to calendar events using
    CUTYPE=RESOURCE or CUTYPE=ROOM. The calendar module's conflict
    detection ensures no double-booking.
    """

    id: str | None = None
    name: str = ""
    description: str = ""
    email: str = ""
    resource_type: str = "room"  # room, equipment, vehicle, other
    capacity: int | None = None
    location: str | None = None
    features: list[str] = field(default_factory=list)  # e.g. ["projector", "video_conferencing", "whiteboard"]
    is_active: bool = True
    booking_policy: str = "open"  # open, moderated, restricted
    allowed_groups: list[str] = field(default_factory=list)  # LDAP groups that can book (empty = all)
    auto_accept: bool = True  # auto-accept booking or require approval
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "email": self.email,
            "resource_type": self.resource_type,
            "capacity": self.capacity,
            "location": self.location,
            "features": self.features,
            "is_active": self.is_active,
            "booking_policy": self.booking_policy,
            "allowed_groups": self.allowed_groups,
            "auto_accept": self.auto_accept,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: list[Any]) -> CalResource:
        """Construct from a database row."""
        return cls(
            id=row[0],
            name=row[1],
            description=row[2],
            email=row[3],
            resource_type=row[4],
            capacity=row[5],
            location=row[6],
            features=row[7] or [],
            is_active=row[8] if len(row) > 8 else True,
            booking_policy=row[9] if len(row) > 9 else "open",
            allowed_groups=row[10] if len(row) > 10 else [],
            auto_accept=row[11] if len(row) > 11 else True,
            created_at=row[12] if len(row) > 12 else None,
            updated_at=row[13] if len(row) > 13 else None,
        )
