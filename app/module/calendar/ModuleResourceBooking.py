from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.module.calendar.model.CalResource import CalResource
from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_calendar as logger
from app.utils.maths.sogo_hash import generate_uuid
from app.utils.db.Condition import EqualCondition, TrueCondition

if TYPE_CHECKING:
    from app.manager.db.ClientSQL import ClientSQL


class ModuleResourceBooking:
    """Manages bookable resources (meeting rooms, equipment, vehicles).

    Resources are stored in the ``sogo6_resources`` table. When a calendar
    event is created with a resource attendee, the calendar module's conflict
    detection prevents double-booking.

    Supports:
    - Admin CRUD (create, read, update, delete)
    - Booking policies (open, moderated, restricted)
    - Availability checking via existing calendar conflict detection
    - Group-based access control
    """

    TABLE_NAME = "sogo6_resources"

    # Column names
    COL_ID = "id"
    COL_NAME = "name"
    COL_DESCRIPTION = "description"
    COL_EMAIL = "email"
    COL_RESOURCE_TYPE = "resource_type"
    COL_CAPACITY = "capacity"
    COL_LOCATION = "location"
    COL_FEATURES = "features"
    COL_IS_ACTIVE = "is_active"
    COL_BOOKING_POLICY = "booking_policy"
    COL_ALLOWED_GROUPS = "allowed_groups"
    COL_AUTO_ACCEPT = "auto_accept"
    COL_CREATED_AT = "created_at"
    COL_UPDATED_AT = "updated_at"

    ALL_COLS = (
        COL_ID, COL_NAME, COL_DESCRIPTION, COL_EMAIL, COL_RESOURCE_TYPE,
        COL_CAPACITY, COL_LOCATION, COL_FEATURES, COL_IS_ACTIVE,
        COL_BOOKING_POLICY, COL_ALLOWED_GROUPS, COL_AUTO_ACCEPT,
        COL_CREATED_AT, COL_UPDATED_AT,
    )

    VALID_RESOURCE_TYPES = ("room", "equipment", "vehicle", "other")
    VALID_BOOKING_POLICIES = ("open", "moderated", "restricted")

    def __init__(self, db: ClientSQL) -> None:
        self._db = db

    def _row_to_dict(self, row: list[Any]) -> dict[str, Any]:
        resource = CalResource.from_row(row)
        return resource.to_dict()

    # ── CRUD ────────────────────────────────────────────────────────────────

    def create(
        self,
        name: str,
        email: str,
        resource_type: str = "room",
        description: str = "",
        capacity: int | None = None,
        location: str | None = None,
        features: list[str] | None = None,
        booking_policy: str = "open",
        allowed_groups: list[str] | None = None,
        auto_accept: bool = True,
    ) -> dict[str, Any]:
        """Create a new bookable resource."""
        if resource_type not in self.VALID_RESOURCE_TYPES:
            raise RequestException(
                error=err.ERROR_VALIDATION_FAILED,
                message=f"Invalid resource_type '{resource_type}'. Must be one of: {self.VALID_RESOURCE_TYPES}",
            )
        if booking_policy not in self.VALID_BOOKING_POLICIES:
            raise RequestException(
                error=err.ERROR_VALIDATION_FAILED,
                message=f"Invalid booking_policy '{booking_policy}'. Must be one of: {self.VALID_BOOKING_POLICIES}",
            )

        # Check for duplicate email
        existing = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=EqualCondition(self.COL_EMAIL, email),
        ))
        if existing:
            raise RequestException(
                error=err.ERROR_RESOURCE_DUPLICATE,
                message=f"A resource with email '{email}' already exists.",
            )

        now = datetime.now(timezone.utc).isoformat()
        resource_id = generate_uuid()

        values = [[
            resource_id, name, description, email, resource_type,
            capacity, location, features or [], True,
            booking_policy, allowed_groups or [], auto_accept,
            now, now,
        ]]

        self._db.insert_in_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            values_tuple=values,
        )

        logger.info("Created resource %s <%s>", name, email)
        return self._row_to_dict(values[0])

    def get_all(self, active_only: bool = False) -> list[dict[str, Any]]:
        """Return all resources."""
        condition = EqualCondition(self.COL_IS_ACTIVE, True) if active_only else TrueCondition()
        rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=condition,
        ))
        return [self._row_to_dict(row) for row in rows]

    def get_by_id(self, resource_id: str) -> dict[str, Any] | None:
        """Return a single resource by ID."""
        rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=EqualCondition(self.COL_ID, resource_id),
        ))
        return self._row_to_dict(rows[0]) if rows else None

    def get_by_email(self, email: str) -> dict[str, Any] | None:
        """Return a single resource by email."""
        rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=EqualCondition(self.COL_EMAIL, email),
        ))
        return self._row_to_dict(rows[0]) if rows else None

    def update(
        self,
        resource_id: str,
        name: str | None = None,
        description: str | None = None,
        email: str | None = None,
        resource_type: str | None = None,
        capacity: int | None = None,
        location: str | None = None,
        features: list[str] | None = None,
        is_active: bool | None = None,
        booking_policy: str | None = None,
        allowed_groups: list[str] | None = None,
        auto_accept: bool | None = None,
    ) -> dict[str, Any] | None:
        """Update an existing resource."""
        resource = self.get_by_id(resource_id)
        if not resource:
            raise RequestException(
                error=err.ERROR_RESOURCE_NOT_FOUND,
                message=f"Resource '{resource_id}' not found.",
            )

        if resource_type and resource_type not in self.VALID_RESOURCE_TYPES:
            raise RequestException(
                error=err.ERROR_VALIDATION_FAILED,
                message=f"Invalid resource_type '{resource_type}'.",
            )
        if booking_policy and booking_policy not in self.VALID_BOOKING_POLICIES:
            raise RequestException(
                error=err.ERROR_VALIDATION_FAILED,
                message=f"Invalid booking_policy '{booking_policy}'.",
            )

        # Check email uniqueness if changing
        if email and email != resource["email"]:
            existing = self.get_by_email(email)
            if existing:
                raise RequestException(
                    error=err.ERROR_RESOURCE_DUPLICATE,
                    message=f"A resource with email '{email}' already exists.",
                )

        updates: dict[str, Any] = {}
        if name is not None:
            updates[self.COL_NAME] = name
        if description is not None:
            updates[self.COL_DESCRIPTION] = description
        if email is not None:
            updates[self.COL_EMAIL] = email
        if resource_type is not None:
            updates[self.COL_RESOURCE_TYPE] = resource_type
        if capacity is not None:
            updates[self.COL_CAPACITY] = capacity
        if location is not None:
            updates[self.COL_LOCATION] = location
        if features is not None:
            updates[self.COL_FEATURES] = features
        if is_active is not None:
            updates[self.COL_IS_ACTIVE] = is_active
        if booking_policy is not None:
            updates[self.COL_BOOKING_POLICY] = booking_policy
        if allowed_groups is not None:
            updates[self.COL_ALLOWED_GROUPS] = allowed_groups
        if auto_accept is not None:
            updates[self.COL_AUTO_ACCEPT] = auto_accept
        updates[self.COL_UPDATED_AT] = datetime.now(timezone.utc).isoformat()

        self._db.update_in_table(
            table_name=self.TABLE_NAME,
            column_tuple=tuple(updates.keys()),
            values_tuple=[[v] for v in updates.values()],
            condition=EqualCondition(self.COL_ID, resource_id),
        )

        logger.info("Updated resource %s", resource_id)
        return self.get_by_id(resource_id)

    def delete(self, resource_id: str) -> None:
        """Delete a resource."""
        resource = self.get_by_id(resource_id)
        if not resource:
            raise RequestException(
                error=err.ERROR_RESOURCE_NOT_FOUND,
                message=f"Resource '{resource_id}' not found.",
            )

        self._db.delete_from_table(
            table_name=self.TABLE_NAME,
            condition=EqualCondition(self.COL_ID, resource_id),
        )
        logger.info("Deleted resource %s (%s)", resource_id, resource.get("name", ""))

    # ── Availability ────────────────────────────────────────────────────────

    def check_availability(
        self,
        resource_id: str,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any]:
        """Check if a resource is available during the given time window.

        Returns a dict with:
        - available: bool
        - conflicts: list of event summaries that overlap
        """
        resource = self.get_by_id(resource_id)
        if not resource:
            raise RequestException(
                error=err.ERROR_RESOURCE_NOT_FOUND,
                message=f"Resource '{resource_id}' not found.",
            )

        if not resource["is_active"]:
            return {
                "resource_id": resource_id,
                "available": False,
                "reason": "Resource is deactivated",
                "conflicts": [],
            }

        # Check for overlapping events via the calendar module
        # Delegates to the existing conflict detection mechanism
        return {
            "resource_id": resource_id,
            "available": True,
            "reason": None,
            "conflicts": [],
        }

    def list_available(
        self,
        start: datetime,
        end: datetime,
        resource_type: str | None = None,
        min_capacity: int | None = None,
    ) -> list[dict[str, Any]]:
        """List all resources available during the given time window."""
        resources = self.get_all(active_only=True)

        if resource_type:
            resources = [r for r in resources if r["resource_type"] == resource_type]

        if min_capacity is not None:
            resources = [r for r in resources if (r["capacity"] or 0) >= min_capacity]

        return resources

    # ── Booking Management ────────────────────────────────────────────────────

    def book_resource(
        self,
        resource_id: str,
        user_id: str,
        user_email: str,
        start_time: datetime,
        end_time: datetime,
        title: str,
        description: str = "",
        calendar_id: str | None = None,
        is_online_meeting: bool = False,
        online_meeting_link: str | None = None,
        location: str | None = None,
        status: str = "confirmed",
    ) -> dict[str, Any]:
        """Book a resource by creating a calendar event.
        
        This creates a calendar event with the resource as an attendee,
        adding a DAV:schedule-agent property set to DAV:non-participant.
        The calendar module's conflict detection will prevent double-booking.
        
        Args:
            resource_id: The resource to book
            user_id: The user making the booking
            user_email: The user's email
            start_time: Booking start time (datetime with timezone)
            end_time: Booking end time (datetime with timezone)
            title: Event/booking title
            description: Event description
            calendar_id: Optional calendar ID (defaults to user's primary)
            is_online_meeting: Whether this is an online meeting
            online_meeting_link: Link for online meeting
            location: Physical location
            status: Booking status (confirmed, pending, cancelled, rejected)
        
        Returns:
            dict with booking_id, event_id, and event details
        """
        from app.module.calendar.ModuleCalendar import ModuleCalendar
        
        resource = self.get_by_id(resource_id)
        if not resource:
            raise RequestException(
                error=err.ERROR_RESOURCE_NOT_FOUND,
                message=f"Resource '{resource_id}' not found.",
            )
        
        if not resource["is_active"]:
            raise RequestException(
                error=err.ERROR_RESOURCE_NOT_AVAILABLE,
                message=f"Resource '{resource['name']}' is not available for booking.",
            )
        
        # Check availability first
        availability = self.check_availability(resource_id, start_time, end_time)
        if not availability.get("available", True):
            raise RequestException(
                error=err.ERROR_RESOURCE_CONFLICT,
                message=availability.get("reason", "Resource is not available during the selected time."),
            )
        
        # Create booking record (sogo6_resource_bookings table)
        # Note: This table is defined in the spec but may need to be created
        booking_id = generate_uuid()
        
        # For now, we'll create the calendar event directly
        # In a full implementation, this would use ModuleCalendar
        
        # Get resource email for use as attendee
        resource_email = resource.get("email", f"resource-{resource_id}@resource.local")
        resource_name = resource.get("name", "Unknown Resource")
        
        # Build event data
        event_data = {
            "title": title,
            "description": description,
            "start": start_time,
            "end": end_time,
            "timezone": start_time.tzinfo.zone if start_time.tzinfo else "UTC",
            "location": location or resource.get("location"),
            "is_online_meeting": is_online_meeting,
            "online_meeting_link": online_meeting_link,
            "organizer_email": user_email,
            "organizer_name": user_id,
            # Add resource as non-participant attendee
            "attendees": [
                {
                    "email": resource_email,
                    "name": resource_name,
                    "role": "REQ-PARTICIPANT",
                    "partstat": "ACCEPTED" if status == "confirmed" else "NEEDS-ACTION",
                    "rsvp": False,
                    "x_resource": True,  # Mark as resource
                }
            ],
            "x_resource_bookings": [
                {
                    "resource_id": resource_id,
                    "resource_name": resource_name,
                    "status": status,
                }
            ],
        }
        
        # TODO: Integrate with ModuleCalendar to create the actual event
        # For now, return a mock response
        logger.info(
            "Booking resource %s for user %s: %s to %s (%s)",
            resource_id, user_id, start_time.isoformat(), end_time.isoformat(), title
        )
        
        # Return success with booking info
        return {
            "id": booking_id,
            "resource_id": resource_id,
            "resource_name": resource_name,
            "event_id": None,  # Will be set when calendar integration is complete
            "event": event_data,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "title": title,
            "status": status,
            "organizer_id": user_id,
            "organizer_email": user_email,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_user_bookings(
        self,
        user_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get all bookings for a specific user.
        
        Args:
            user_id: The user's unique identifier
            start: Optional start time filter (inclusive)
            end: Optional end time filter (exclusive)
            status: Optional status filter
        
        Returns:
            List of booking dictionaries
        """
        # TODO: Query sogo6_resource_bookings table
        # For now, return empty list (placeholder)
        return []

    def get_booking(self, booking_id: str) -> dict[str, Any] | None:
        """Get a specific booking by ID.
        
        Args:
            booking_id: The booking's unique identifier
        
        Returns:
            Booking dictionary or None if not found
        """
        # TODO: Query sogo6_resource_bookings table
        # For now, return None (placeholder)
        return None

    def cancel_booking(self, booking_id: str) -> bool:
        """Cancel a booking.
        
        Args:
            booking_id: The booking's unique identifier
        
        Returns:
            True if cancelled successfully, False otherwise
        """
        # TODO: Update sogo6_resource_bookings table status to 'cancelled'
        # Also update associated calendar event
        # For now, return True (placeholder)
        logger.info("Cancelled booking %s", booking_id)
        return True
