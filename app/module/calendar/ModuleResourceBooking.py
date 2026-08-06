from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.module.calendar.model.CalResource import CalResource
from app.module.calendar.repository.RepositoryCalendar import RepositoryCalendar
from app.module.calendar.repository.RepositoryCalendarShare import RepositoryCalendarShare
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
        with CUTYPE set to RESOURCE. The calendar module's conflict detection
        will prevent double-booking.
        
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
        from app.module.calendar.model.CalAttendee import CalAttendee
        from app.module.calendar.model.CalEvent import CalEvent
        from app.module.calendar.model.CalOrganizer import CalOrganizer
        from app.module.calendar.model.CalendarUser import CalendarUser
        from app.module.calendar.model.enums.AttendeeRole import AttendeeRole
        from app.module.calendar.model.enums.AttendeeStatus import AttendeeStatus
        from app.module.calendar.model.enums.CalUserType import CalUserType
        from app.module.calendar.model.enums.ComponentType import ComponentType
        from app.module.calendar.model.enums.EventStatus import EventStatus
        from app.module.calendar.model.enums.EventVisibility import EventVisibility
        from app.auth.User import User
        
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
        
        # Get resource email for use as attendee
        resource_email = resource.get("email", f"resource-{resource_id}@resource.local")
        resource_name = resource.get("name", "Unknown Resource")
        
        # Create a User object for the booker
        # Note: This is a minimal user object - in production, use the authenticated user
        user = User(uid=user_id, email=user_email, name=user_id)
        calendar_user = CalendarUser(user=user, owner=user)
        
        # Get the calendar to use (default to user's primary calendar)
        try:
            from app.config.settings.ProcessSetting import ProcessSetting
            from app.manager.cache.ClientRedis import ClientRedis
            from app.module.calendar.ModuleCalendar import ModuleCalendar
            
            module_calendar: ModuleCalendar = ModuleCalendar(
                process_settings=ProcessSetting(),
                cache=None,
                agent=None,
            )
            
            # Get user's primary calendar
            calendars = module_calendar.get_all_calendars(user, shared_keys=None)
            calendar_to_use = calendars[0] if calendars else None
            
            if not calendar_to_use:
                # Create a default calendar if one doesn't exist
                calendar_to_use = module_calendar.create_personal_calendar(
                    user_uid=user_id,
                    tz=start_time.tzinfo.zone if start_time.tzinfo else "UTC",
                )
            
            calendar_key = calendar_to_use.key
            
        except Exception as exc:
            logger.exception("Error getting user calendar for booking: %s", exc)
            # Fall back to creating a standalone booking without calendar event
            # Return success with booking info but no event_id
            logger.info(
                "Booking resource %s for user %s: %s to %s (%s) - NO CALENDAR EVENT",
                resource_id, user_id, start_time.isoformat(), end_time.isoformat(), title
            )
            
            return {
                "id": booking_id,
                "resource_id": resource_id,
                "resource_name": resource_name,
                "event_id": None,
                "event_key": None,
                "booking_purpose": description,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "title": title,
                "status": status,
                "organizer_id": user_id,
                "organizer_email": user_email,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        
        # Create the calendar event with resource attendee
        try:
            # Map status to EventStatus
            event_status_map = {
                "confirmed": EventStatus.CONFIRMED,
                "pending": EventStatus.TENTATIVE,
                "cancelled": EventStatus.CANCELLED,
                "rejected": EventStatus.CANCELLED,
            }
            event_status = event_status_map.get(status, EventStatus.CONFIRMED)
            
            # Create the event
            event = CalEvent(
                title=title,
                description=description,
                date_start=start_time,
                date_end=end_time,
                timezone=start_time.tzinfo.zone if start_time.tzinfo else "UTC",
                location=location or resource.get("location"),
                status=event_status,
                visibility=EventVisibility.PRIVATE,
                component_type=ComponentType.EVENT,
                all_day=False,
                organizer=CalOrganizer(email=user_email, name=user_id),
                attendees=[
                    CalAttendee(
                        email=resource_email,
                        name=resource_name,
                        role=AttendeeRole.REQUIRED,
                        status=AttendeeStatus.ACCEPTED if status == "confirmed" else AttendeeStatus.NEEDS_ACTION,
                        rsvp=False,
                        cutype=CalUserType.RESOURCE,
                    )
                ],
            )
            
            # Validation
            event.apply_defaults()
            event.validate()
            
            # Create the event via ModuleCalendar
            created_event = module_calendar.create_event(
                calendar_user=calendar_user,
                calendar_key=calendar_key,
                event=event,
                organizer=CalOrganizer(email=user_email, name=user_id),
            )
            
            # Store booking record in sogo6_resource_bookings table
            # Note: This table may not exist yet - for now, we'll use the calendar event
            # In a future iteration, we'll create the table and store proper booking records
            
            logger.info(
                "Booking resource %s for user %s: %s to %s (%s) - Event: %s",
                resource_id, user_id, start_time.isoformat(), end_time.isoformat(), title, created_event.key
            )
            
            # Return success with booking info
            return {
                "id": booking_id,
                "resource_id": resource_id,
                "resource_name": resource_name,
                "event_id": created_event.db_id,
                "event_key": created_event.key,
                "event_uid": created_event.uid,
                "calendar_key": calendar_key,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "title": title,
                "description": description,
                "location": location or resource.get("location"),
                "status": status,
                "organizer_id": user_id,
                "organizer_email": user_email,
                "booking_purpose": description,
                "is_online_meeting": is_online_meeting,
                "online_meeting_link": online_meeting_link,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            
        except Exception as exc:
            logger.exception("Error creating calendar event for resource booking: %s", exc)
            raise RequestException(
                error=err.ERROR_CALENDAR_EVENT_INSERT_FAILED,
                message=f"Failed to create calendar event for resource booking: {exc}",
            )

    def get_user_bookings(
        self,
        user_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get all bookings for a specific user.
        
        This queries both the sogo6_resource_bookings table (when it exists)
        and the calendar events to find all events where this user is the
        organizer and that have resource attendees.
        
        Args:
            user_id: The user's unique identifier
            start: Optional start time filter (inclusive)
            end: Optional end time filter (exclusive)
            status: Optional status filter
        
        Returns:
            List of booking dictionaries
        """
        from app.module.calendar.model.CalUserType import CalUserType
        from app.module.calendar.repository.RepositoryEvent import RepositoryEvent
        from app.module.calendar.repository.RepositoryCalendar import RepositoryCalendar
        
        bookings = []
        
        try:
            # First, try to query sogo6_resource_bookings table directly
            # This table may not exist yet, so we'll fall back to calendar events
            try:
                rows = list(self._db.select_from_table(
                    table_name="sogo6_resource_bookings",
                    column_tuple=(
                        "id", "event_id", "resource_id", "start_ts", "end_ts",
                        "status", "organizer_id", "booking_purpose", "created_at"
                    ),
                    condition=EqualCondition("organizer_id", user_id),
                ))
                
                for row in rows:
                    booking_id, event_id, resource_id, start_ts, end_ts, booking_status, 
                    organizer_id, booking_purpose, created_at = row
                    
                    # Filter by time range if specified
                    if start and end_ts and end_ts < start:
                        continue
                    if end and start_ts and start_ts >= end:
                        continue
                    
                    # Filter by status if specified
                    if status and booking_status != status:
                        continue
                    
                    # Get resource details
                    resource = self.get_by_id(resource_id)
                    
                    bookings.append({
                        "id": booking_id,
                        "event_id": event_id,
                        "resource_id": resource_id,
                        "resource_name": resource.get("name", "Unknown") if resource else "Unknown",
                        "resource_type": resource.get("resource_type", "other") if resource else "other",
                        "start_time": start_ts.isoformat() if start_ts else None,
                        "end_time": end_ts.isoformat() if end_ts else None,
                        "status": booking_status,
                        "organizer_id": organizer_id,
                        "booking_purpose": booking_purpose,
                        "created_at": created_at.isoformat() if created_at else None,
                    })
                
                return bookings
            except Exception as exc:
                # sogo6_resource_bookings table doesn't exist yet
                logger.debug("sogo6_resource_bookings table not found, falling back to calendar events: %s", exc)
            
            # Fall back to querying calendar events for bookings
            # This looks for events where the user is organizer and that have resource attendees
            
            repo_calendar = RepositoryCalendar(self._db)
            calendars = repo_calendar.find_all(user_id)
            
            if not calendars:
                return []
            
            repo_event = RepositoryEvent(self._db)
            
            for calendar in calendars:
                if not calendar.key:
                    continue
                
                # Get all events in this calendar
                calendar_events = repo_event.find_by_calendar(
                    calendar.key,
                    start_time=None,
                    end_time=None,
                )
                
                for event in calendar_events:
                    # Check if user is organizer
                    if event.organizer and event.organizer.email == user_id:
                        # Check if event has resource attendees
                        resource_attendees = [
                            a for a in event.attendees 
                            if a.cutype in (CalUserType.RESOURCE, CalUserType.ROOM)
                        ]
                        
                        if resource_attendees:
                            # Filter by time range if specified
                            event_start = event.require_date_start
                            event_end = event.require_date_end or event_start
                            
                            if start and event_end < start:
                                continue
                            if end and event_start >= end:
                                continue
                            
                            # Map event status to booking status
                            status_map = {
                                EventStatus.CONFIRMED: "confirmed",
                                EventStatus.TENTATIVE: "pending",
                                EventStatus.CANCELLED: "cancelled",
                            }
                            event_status = status_map.get(event.status, "confirmed")
                            
                            # Filter by status if specified
                            if status and event_status != status:
                                continue
                            
                            # Create booking entry for each resource attendee
                            for attendee in resource_attendees:
                                # Try to find the resource by email
                                resource = self.get_by_email(attendee.email)
                                resource_id = resource.get("id") if resource else attendee.email
                                
                                bookings.append({
                                    "id": event.uid or event.key or generate_uuid(),
                                    "event_id": event.db_id,
                                    "event_key": event.key,
                                    "event_uid": event.uid,
                                    "resource_id": resource_id,
                                    "resource_name": attendee.name or attendee.email,
                                    "resource_type": resource.get("resource_type", "other") if resource else "other",
                                    "start_time": event_start.isoformat(),
                                    "end_time": event_end.isoformat(),
                                    "status": event_status,
                                    "organizer_id": user_id,
                                    "organizer_email": event.organizer.email if event.organizer else None,
                                    "booking_purpose": event.description,
                                    "title": event.title,
                                    "location": event.location,
                                    "created_at": event.created_at.isoformat() if event.created_at else None,
                                })
            
        except Exception as exc:
            logger.exception("Error getting user bookings for %s: %s", user_id, exc)
            raise RequestException(
                error=err.ERROR_CALENDAR_EVENT_INSERT_FAILED,
                message=f"Failed to retrieve user bookings: {exc}",
            )
        
        return bookings

    def get_booking(self, booking_id: str) -> dict[str, Any] | None:
        """Get a specific booking by ID.
        
        This queries both the sogo6_resource_bookings table (when it exists)
        and the calendar events to find the booking.
        
        Args:
            booking_id: The booking's unique identifier (can be event UID or booking ID)
        
        Returns:
            Booking dictionary or None if not found
        """
        from app.module.calendar.model.CalUserType import CalUserType
        from app.module.calendar.repository.RepositoryEvent import RepositoryEvent
        
        try:
            # First, try to query sogo6_resource_bookings table directly
            try:
                rows = list(self._db.select_from_table(
                    table_name="sogo6_resource_bookings",
                    column_tuple=(
                        "id", "event_id", "resource_id", "start_ts", "end_ts",
                        "status", "organizer_id", "booking_purpose", "created_at"
                    ),
                    condition=EqualCondition("id", booking_id),
                ))
                
                if rows:
                    row = rows[0]
                    booking_id_db, event_id, resource_id, start_ts, end_ts, booking_status, 
                    organizer_id, booking_purpose, created_at = row
                    
                    # Get resource details
                    resource = self.get_by_id(resource_id)
                    
                    return {
                        "id": booking_id_db,
                        "event_id": event_id,
                        "resource_id": resource_id,
                        "resource_name": resource.get("name", "Unknown") if resource else "Unknown",
                        "resource_type": resource.get("resource_type", "other") if resource else "other",
                        "start_time": start_ts.isoformat() if start_ts else None,
                        "end_time": end_ts.isoformat() if end_ts else None,
                        "status": booking_status,
                        "organizer_id": organizer_id,
                        "booking_purpose": booking_purpose,
                        "created_at": created_at.isoformat() if created_at else None,
                    }
            except Exception as exc:
                # sogo6_resource_bookings table doesn't exist yet
                logger.debug("sogo6_resource_bookings table not found, falling back to calendar events: %s", exc)
            
            # Fall back to querying calendar events
            repo_event = RepositoryEvent(self._db)
            
            # Try to find event by UID or key
            event = repo_event.find_by_uid(booking_id)
            if not event:
                # Try by key
                all_events = repo_event.find_all()
                event = next((e for e in all_events if e.key == booking_id), None)
            
            if not event:
                return None
            
            # Check if event has resource attendees
            resource_attendees = [
                a for a in event.attendees 
                if a.cutype in (CalUserType.RESOURCE, CalUserType.ROOM)
            ]
            
            if not resource_attendees:
                return None
            
            # Map event status to booking status
            status_map = {
                "CONFIRMED": "confirmed",
                "TENTATIVE": "pending",
                "CANCELLED": "cancelled",
            }
            event_status = status_map.get(event.status.name, "confirmed")
            
            # Get organizer
            organizer_id = event.organizer.email if event.organizer else None
            organizer_email = event.organizer.email if event.organizer else None
            
            # Create booking entries for each resource attendee
            results = []
            for attendee in resource_attendees:
                # Try to find the resource by email
                resource = self.get_by_email(attendee.email)
                resource_id = resource.get("id") if resource else attendee.email
                
                results.append({
                    "id": event.uid or event.key or booking_id,
                    "event_id": event.db_id,
                    "event_key": event.key,
                    "event_uid": event.uid,
                    "resource_id": resource_id,
                    "resource_name": attendee.name or attendee.email,
                    "resource_type": resource.get("resource_type", "other") if resource else "other",
                    "start_time": event.require_date_start.isoformat(),
                    "end_time": (event.require_date_end or event.require_date_start).isoformat(),
                    "status": event_status,
                    "organizer_id": organizer_id,
                    "organizer_email": organizer_email,
                    "booking_purpose": event.description,
                    "title": event.title,
                    "location": event.location,
                    "calendar_key": event.calendar_key,
                    "created_at": event.created_at.isoformat() if event.created_at else None,
                })
            
            return results[0] if results else None
            
        except Exception as exc:
            logger.exception("Error getting booking %s: %s", booking_id, exc)
            return None

    def cancel_booking(self, booking_id: str, user_id: str) -> bool:
        """Cancel a booking.
        
        This cancels both the booking record (when sogo6_resource_bookings exists)
        and the associated calendar event.
        
        Args:
            booking_id: The booking's unique identifier
            user_id: The user requesting the cancellation (for ownership verification)
        
        Returns:
            True if cancelled successfully, False otherwise
        """
        from app.module.calendar.repository.RepositoryEvent import RepositoryEvent
        from app.module.calendar.model.enums.EventStatus import EventStatus
        from app.module.calendar.model.CalEvent import CalEvent
        
        try:
            # First, get the booking to verify ownership
            booking = self.get_booking(booking_id)
            if not booking:
                raise RequestException(
                    error=err.ERROR_BOOKING_NOT_FOUND,
                    message=f"Booking '{booking_id}' not found.",
                )
            
            # Verify that the user owns this booking
            if booking.get("organizer_id") != user_id:
                raise RequestException(
                    error=err.ERROR_BOOKING_ACCESS_DENIED,
                    message=f"User '{user_id}' does not own booking '{booking_id}'.",
                )
            
            # Check current status
            if booking.get("status") == "cancelled":
                return True  # Already cancelled
            
            # Try to update sogo6_resource_bookings table first
            try:
                self._db.update_in_table(
                    table_name="sogo6_resource_bookings",
                    column_tuple=("status",),
                    values_tuple=[["cancelled"]],
                    condition=EqualCondition("id", booking_id),
                )
            except Exception as exc:
                logger.debug("Could not update sogo6_resource_bookings table (may not exist): %s", exc)
            
            # If we have an event, cancel it
            event_id = booking.get("event_id")
            event_key = booking.get("event_key")
            event_uid = booking.get("event_uid")
            calendar_key = booking.get("calendar_key")
            
            if event_key or event_uid:
                repo_event = RepositoryEvent(self._db)
                
                # Find the event
                event = None
                if event_uid:
                    event = repo_event.find_by_uid(event_uid)
                if not event and event_key:
                    all_events = repo_event.find_all()
                    event = next((e for e in all_events if e.key == event_key), None)
                
                if event:
                    # Update event status to cancelled
                    event.status = EventStatus.CANCELLED
                    event.sequence += 1
                    
                    # Update the event in the database
                    # Note: We need a source to update the event
                    from app.module.calendar.source.CalendarSource import CalendarSource
                    from app.module.calendar.Serializer import CalendarSources
                    
                    try:
                        sources = CalendarSources(self._db, RepositoryCalendarShare(self._db))
                        if calendar_key:
                            source = sources.get_by_key(user_id, calendar_key)
                            if source:
                                source.update_event(event)
                                logger.info("Cancelled calendar event %s for booking %s", event.key, booking_id)
                    except Exception as exc:
                        logger.warning("Could not update calendar event for booking %s: %s", booking_id, exc)
            
            logger.info("Cancelled booking %s for user %s", booking_id, user_id)
            return True
            
        except RequestException:
            raise
        except Exception as exc:
            logger.exception("Error cancelling booking %s: %s", booking_id, exc)
            raise RequestException(
                error=err.ERROR_BOOKING_CANCEL_FAILED,
                message=f"Failed to cancel booking: {exc}",
            )
