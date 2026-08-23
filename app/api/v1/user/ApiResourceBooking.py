"""
User-Facing Resource Booking API

This module provides user-facing endpoints for browsing, checking availability,
and booking resources. It complements the admin API in app.api.v1.admin.ApiResourceBooking.

Endpoints:
- GET /user/v1/resources - List available resources with filters
- GET /user/v1/resources/{id} - Get resource details
- GET /user/v1/resources/available - List resources available during time range
- POST /user/v1/resources/{id}/check-availability - Check specific resource availability
- POST /user/v1/resources/{id}/book - Book a resource (creates calendar event)
- GET /user/v1/resources/my-bookings - List user's bookings
- DELETE /user/v1/resources/my-bookings/{booking_id} - Cancel a booking
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from flask import g
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from marshmallow import Schema, fields, validate
from pytz import UTC

from app.module.calendar.ModuleResourceBooking import ModuleResourceBooking
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import RequestException

blp = Blueprint(
    "User Resource Booking",
    __name__,
    url_prefix="/resources",
    description="User-facing resource booking API for browsing and booking shared resources",
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class ResourceTypeEnum:
    """Resource type enumeration."""
    ROOM = "room"
    EQUIPMENT = "equipment"
    VEHICLE = "vehicle"
    OTHER = "other"


class BookingPolicyEnum:
    """Booking policy enumeration."""
    OPEN = "open"
    MODERATED = "moderated"
    RESTRICTED = "restricted"


class BookingStatusEnum:
    """Booking status enumeration."""
    CONFIRMED = "confirmed"
    PENDING = "pending"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class ResourceListQuerySchema(Schema):
    """Query parameters for listing resources."""
    resource_type = fields.String(
        load_default=None,
        validate=validate.OneOf(["room", "equipment", "vehicle", "other"]),
        metadata={"description": "Filter by resource type"},
    )
    location = fields.String(
        load_default=None,
        metadata={"description": "Filter by location (substring match)"},
    )
    capacity_min = fields.Integer(
        load_default=None,
        validate=validate.Range(min=1),
        metadata={"description": "Minimum capacity"},
    )
    capacity_max = fields.Integer(
        load_default=None,
        validate=validate.Range(min=1),
        metadata={"description": "Maximum capacity"},
    )
    search = fields.String(
        load_default=None,
        metadata={"description": "Search in name and description"},
    )
    feature = fields.String(
        load_default=None,
        metadata={"description": "Filter by feature (can be repeated)"},
    )
    is_available = fields.Boolean(
        load_default=None,
        metadata={"description": "Filter by current availability"},
    )
    limit = fields.Integer(
        load_default=50,
        validate=validate.Range(min=1, max=500),
        metadata={"description": "Maximum number of results"},
    )
    offset = fields.Integer(
        load_default=0,
        validate=validate.Range(min=0),
        metadata={"description": "Pagination offset"},
    )


class ResourceSchema(Schema):
    """Resource response schema."""
    id = fields.String(required=True)
    name = fields.String(required=True)
    description = fields.String()
    email = fields.Email()
    resource_type = fields.String(required=True)
    capacity = fields.Integer()
    location = fields.String()
    features = fields.List(fields.String())
    is_active = fields.Boolean(required=True)
    booking_policy = fields.String(required=True)
    auto_accept = fields.Boolean(required=True)
    created_at = fields.DateTime()
    updated_at = fields.DateTime()
    is_favorite = fields.Boolean(required=True)


class DetailedResourceSchema(ResourceSchema):
    """Detailed resource response schema with availability info."""
    allowed_groups = fields.List(fields.String())


class TimeRangeSchema(Schema):
    """Time range request schema."""
    start_time = fields.DateTime(
        required=True,
        format="iso",
        metadata={"example": "2025-08-25T10:00:00Z"},
    )
    end_time = fields.DateTime(
        required=True,
        format="iso",
        metadata={"example": "2025-08-25T12:00:00Z"},
    )
    timezone = fields.String(
        load_default="UTC",
        metadata={"description": "IANA timezone identifier"},
    )


class AvailabilityCheckSchema(TimeRangeSchema):
    """Availability check request schema."""


class AvailabilityResponseSchema(Schema):
    """Availability check response schema."""
    available = fields.Boolean(required=True)
    conflicts = fields.List(fields.Dict(), load_default=[])


class BookResourceSchema(TimeRangeSchema):
    """Book resource request schema."""
    title = fields.String(
        required=True,
        validate=validate.Length(min=1, max=255),
        metadata={"example": "Team Meeting"},
    )
    description = fields.String(
        load_default="",
        metadata={"description": "Event description"},
    )
    calendar_id = fields.String(
        load_default=None,
        metadata={"description": "Calendar to create event in (defaults to primary)"},
    )
    is_online_meeting = fields.Boolean(
        load_default=False,
        metadata={"description": "Whether this is an online meeting"},
    )
    online_meeting_link = fields.String(
        load_default=None,
        metadata={"description": "Online meeting link (Teams, Zoom, etc.)"},
    )
    location = fields.String(
        load_default=None,
        metadata={"description": "Event location"},
    )


class BookingSchema(Schema):
    """Booking response schema."""
    id = fields.String(required=True)
    resource_id = fields.String(required=True)
    resource_name = fields.String(required=True)
    event_id = fields.String()
    start_time = fields.DateTime(required=True)
    end_time = fields.DateTime(required=True)
    title = fields.String(required=True)
    status = fields.String(required=True)
    organizer_id = fields.String(required=True)
    organizer_name = fields.String()
    created_at = fields.DateTime(required=True)


class BookingListSchema(Schema):
    """Booking list response schema."""
    bookings = fields.List(fields.Nested(BookingSchema))
    total_count = fields.Integer(required=True)


class BookingCreateResponseSchema(Schema):
    """Booking creation response schema."""
    booking_id = fields.String(required=True)
    event_id = fields.String()
    calendar_event = fields.Dict()
    message = fields.String(required=True)


class ErrorSchema(Schema):
    """Error response schema."""
    error = fields.String(required=True)
    message = fields.String()
    details = fields.Dict()


# ── Helper Functions ────────────────────────────────────────────────────────


def _get_module() -> ModuleResourceBooking:
    """Get or create the ResourceBooking module instance."""
    if not hasattr(g, "_resource_booking_module"):
        from app.utils.module.importManager import import_and_instantiate_manager

        process = g.process_settings
        db = import_and_instantiate_manager(
            module_path="app.manager.db",
            module_and_class_name=f"Client{process.SOGO_P_DB_TYPE}",
            module_args=process.get_db_settings(),
        )
        g._resource_booking_module = ModuleResourceBooking(db)
    return g._resource_booking_module


def _get_user_id() -> str:
    """Get the current authenticated user's ID."""
    user = getattr(g, "user", None)
    uid = getattr(user, "uid", "") if user else ""
    if not uid or getattr(user, "anonymous", False):
        abort(401, message="Authentication required")
    return uid


def _get_user_groups() -> list[str]:
    """Get the current user's groups (ACLs granted to the user)."""
    user = getattr(g, "user", None)
    if user is None:
        return []
    return getattr(user, "acl_given", None) or []


def _get_user_email() -> Optional[str]:
    """Get the current user's primary email."""
    user = getattr(g, "user", None)
    if user is None:
        return None
    return getattr(user, "mail", None) or None


def _can_access_resource(resource: dict, user_groups: list[str]) -> bool:
    """Check if user has access to a resource based on allowed_groups."""
    # If resource has no allowed_groups restriction, everyone can access
    allowed_groups = resource.get("allowed_groups", [])
    if not allowed_groups:
        return True
    
    # Check if user is in any of the allowed groups
    for user_group in user_groups:
        if user_group in allowed_groups:
            return True
    
    # If user has admin privileges, they can access any resource
    if "admin" in user_groups or g.get("is_admin", False):
        return True
    
    return False


def _parse_datetime(dt_str: str, timezone: str = "UTC") -> datetime:
    """Parse datetime string with timezone support."""
    if isinstance(dt_str, datetime):
        return dt_str
    
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    
    # Convert to specified timezone
    if timezone and timezone.upper() != "UTC":
        from zoneinfo import ZoneInfo
        try:
            target_tz = ZoneInfo(timezone)
            dt = dt.astimezone(target_tz)
        except Exception:
            pass  # best-effort: keep fallback/default value on failure
    
    return dt


# ── Endpoints ─────────────────────────────────────────────────────────────────

@blp.route("")
class ApiResourceList(MethodView):
    """List available resources with optional filters."""

    @blp.arguments(ResourceListQuerySchema, location="query")
    @blp.response(200, ResourceSchema(many=True))
    def get(self, query: dict) -> dict[str, Any]:
        """List resources that the user has access to."""
        module = _get_module()
        user_id = _get_user_id()
        user_groups = _get_user_groups()
        
        # Get all resources
        resources = module.get_all()
        
        # Filter resources
        filtered_resources = []
        for resource in resources:
            # Check access
            if not _can_access_resource(resource, user_groups):
                continue
            
            # Check if active
            if not resource.get("is_active", True):
                continue
            
            # Apply filters
            if query.get("resource_type") and resource.get("resource_type") != query["resource_type"]:
                continue
            
            if query.get("location") and query["location"] not in resource.get("location", ""):
                continue
            
            if query.get("capacity_min") and (not resource.get("capacity") or resource["capacity"] < query["capacity_min"]):
                continue
            
            if query.get("capacity_max") and resource.get("capacity") and resource["capacity"] > query["capacity_max"]:
                continue
            
            if query.get("search"):
                search_term = query["search"].lower()
                name = resource.get("name", "").lower()
                description = resource.get("description", "").lower()
                if search_term not in name and search_term not in description:
                    continue
            
            if query.get("feature"):
                features = resource.get("features", [])
                if query["feature"] not in features:
                    continue
            
            filtered_resources.append(resource)
        
        # Mark favorites for the current user
        favorite_ids = set(module.list_favorite_resource_ids(user_id))
        for resource in filtered_resources:
            resource["is_favorite"] = resource.get("id") in favorite_ids
        
        # Apply pagination
        limit = query.get("limit", 50)
        offset = query.get("offset", 0)
        paginated = filtered_resources[offset:offset + limit]
        
        return create_api_base_response({
            "resources": paginated,
            "total_count": len(filtered_resources),
            "limit": limit,
            "offset": offset,
        })


@blp.route("/favorites")
class ApiResourceFavorites(MethodView):
    """List the current user's favorite resources."""

    @blp.response(200, ResourceSchema(many=True))
    def get(self) -> dict[str, Any]:
        """Return resources the current user has favorited."""
        module = _get_module()
        user_id = _get_user_id()
        favorite_ids = module.list_favorite_resource_ids(user_id)
        resources = []
        for resource_id in favorite_ids:
            resource = module.get_by_id(resource_id)
            if resource and resource.get("is_active", True):
                resource["is_favorite"] = True
                resources.append(resource)
        return create_api_base_response({"resources": resources, "total_count": len(resources)})


@blp.route("/<string:resource_id>/favorite")
class ApiResourceFavoriteToggle(MethodView):
    """Add or remove a favorite for the current user."""

    @blp.response(200)
    def post(self, resource_id: str) -> dict[str, Any]:
        """Mark a resource as favorite."""
        module = _get_module()
        user_id = _get_user_id()
        resource = module.get_by_id(resource_id)
        if not resource:
            return create_api_base_response(None, err.ERROR_RESOURCE_NOT_FOUND)
        return create_api_base_response(module.add_favorite(user_id, resource_id))

    @blp.response(200)
    def delete(self, resource_id: str) -> dict[str, Any]:
        """Remove a resource from favorites."""
        module = _get_module()
        user_id = _get_user_id()
        resource = module.get_by_id(resource_id)
        if not resource:
            return create_api_base_response(None, err.ERROR_RESOURCE_NOT_FOUND)
        return create_api_base_response(module.remove_favorite(user_id, resource_id))


@blp.route("/<string:resource_id>")
class ApiResourceDetail(MethodView):
    """Get detailed information about a specific resource."""

    @blp.response(200, DetailedResourceSchema)
    def get(self, resource_id: str) -> dict[str, Any]:
        """Get details for a specific resource."""
        module = _get_module()
        user_id = _get_user_id()
        user_groups = _get_user_groups()
        
        resource = module.get_by_id(resource_id)
        if not resource:
            return create_api_base_response(None, err.ERROR_RESOURCE_NOT_FOUND)
        
        # Check access
        if not _can_access_resource(resource, user_groups):
            return create_api_base_response(None, err.ERROR_RESOURCE_ACCESS_DENIED)
        
        resource["is_favorite"] = module.is_favorite(user_id, resource_id)
        
        return create_api_base_response(resource)


@blp.route("/available")
class ApiAvailableResources(MethodView):
    """List resources available during a specific time range."""

    @blp.arguments(TimeRangeSchema, location="query")
    @blp.response(200, ResourceSchema(many=True))
    def get(self, time_range: dict) -> dict[str, Any]:
        """List resources that are available during the specified time range."""
        module = _get_module()
        user_groups = _get_user_groups()
        
        start_time = _parse_datetime(time_range["start_time"], time_range.get("timezone", "UTC"))
        end_time = _parse_datetime(time_range["end_time"], time_range.get("timezone", "UTC"))
        
        # Get all accessible resources
        resources = module.get_all()
        available_resources = []
        
        for resource in resources:
            if not _can_access_resource(resource, user_groups):
                continue
            
            if not resource.get("is_active", True):
                continue
            
            # Check availability
            is_available, conflicts = module.check_availability(
                resource["id"],
                start_time,
                end_time,
            )
            
            if is_available:
                resource["is_available"] = True
                resource["next_available"] = None
            else:
                resource["is_available"] = False
                # Find next available time (simplified)
                resource["next_available"] = end_time.isoformat()
            
            available_resources.append(resource)
        
        # Mark favorites for the current user
        favorite_ids = set(module.list_favorite_resource_ids(_get_user_id()))
        for resource in available_resources:
            resource["is_favorite"] = resource.get("id") in favorite_ids
        
        return create_api_base_response({
            "resources": available_resources,
            "total_count": len(available_resources),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        })


@blp.route("/<string:resource_id>/check-availability")
class ApiResourceAvailabilityCheck(MethodView):
    """Check if a specific resource is available during a time range."""

    @blp.arguments(AvailabilityCheckSchema)
    @blp.response(200, AvailabilityResponseSchema)
    def post(self, data: dict, resource_id: str) -> dict[str, Any]:
        """Check availability of a specific resource."""
        module = _get_module()
        user_groups = _get_user_groups()
        
        # Get resource
        resource = module.get_by_id(resource_id)
        if not resource:
            return create_api_base_response(None, err.ERROR_RESOURCE_NOT_FOUND)
        
        # Check access
        if not _can_access_resource(resource, user_groups):
            return create_api_base_response(None, err.ERROR_RESOURCE_ACCESS_DENIED)
        
        # Parse times
        start_time = _parse_datetime(data["start_time"], data.get("timezone", "UTC"))
        end_time = _parse_datetime(data["end_time"], data.get("timezone", "UTC"))
        
        # Check availability
        is_available, conflicts = module.check_availability(
            resource_id,
            start_time,
            end_time,
        )
        
        return create_api_base_response({
            "available": is_available,
            "resource_id": resource_id,
            "resource_name": resource.get("name"),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "conflicts": conflicts,
        })


@blp.route("/<string:resource_id>/book")
class ApiResourceBook(MethodView):
    """Book a resource by creating a calendar event."""

    @blp.arguments(BookResourceSchema)
    @blp.response(201, BookingCreateResponseSchema)
    def post(self, data: dict, resource_id: str) -> dict[str, Any]:
        """Create a booking by creating a calendar event with the resource."""
        module = _get_module()
        user_id = _get_user_id()
        user_groups = _get_user_groups()
        user_email = _get_user_email()
        
        # Get resource
        resource = module.get_by_id(resource_id)
        if not resource:
            return create_api_base_response(None, err.ERROR_RESOURCE_NOT_FOUND)
        
        # Check access
        if not _can_access_resource(resource, user_groups):
            return create_api_base_response(None, err.ERROR_RESOURCE_ACCESS_DENIED)
        
        if not resource.get("is_active", True):
            return create_api_base_response(None, err.ERROR_RESOURCE_NOT_AVAILABLE)
        
        # Parse times
        start_time = _parse_datetime(data["start_time"], data.get("timezone", "UTC"))
        end_time = _parse_datetime(data["end_time"], data.get("timezone", "UTC"))
        
        # Check availability first
        is_available, conflicts = module.check_availability(
            resource_id,
            start_time,
            end_time,
        )
        
        if not is_available:
            return create_api_base_response(None, err.ERROR_RESOURCE_CONFLICT, message="Resource not available during the selected time")
        
        # Check booking policy
        booking_policy = resource.get("booking_policy", "open")
        if booking_policy == "restricted":
            # For restricted, check explicit permissions (simplified)
            pass
        elif booking_policy == "moderated":
            # For moderated, create pending booking (not yet implemented)
            status = "pending"
        else:
            # Open - auto-accept
            status = "confirmed"
        
        try:
            # Book the resource (this will create a calendar event)
            booking = module.book_resource(
                resource_id=resource_id,
                user_id=user_id,
                user_email=user_email,
                start_time=start_time,
                end_time=end_time,
                title=data["title"],
                description=data.get("description", ""),
                calendar_id=data.get("calendar_id"),
                is_online_meeting=data.get("is_online_meeting", False),
                online_meeting_link=data.get("online_meeting_link"),
                location=data.get("location"),
                status=status,
            )
            
            return create_api_base_response({
                "booking_id": booking["id"],
                "event_id": booking.get("event_id"),
                "calendar_event": booking.get("event"),
                "message": f"Resource '{resource['name']}' booked successfully",
            }, code=201)
            
        except RequestException as ex:
            return create_api_base_response(None, ex.error, error_msg=str(ex))
        except Exception as ex:
            return create_api_base_response(None, err.ERROR_UNKOWN, error_msg=str(ex))


@blp.route("/my-bookings")
class ApiMyBookings(MethodView):
    """List the current user's resource bookings."""

    @blp.response(200, BookingListSchema)
    def get(self) -> dict[str, Any]:
        """Get all bookings for the current user."""
        module = _get_module()
        user_id = _get_user_id()
        
        try:
            bookings = module.get_user_bookings(user_id)
            return create_api_base_response({
                "bookings": bookings,
                "total_count": len(bookings),
            })
        except Exception as ex:
            return create_api_base_response(None, err.ERROR_UNKOWN, error_msg=str(ex))


@blp.route("/my-bookings/<string:booking_id>")
class ApiMyBookingDetail(MethodView):
    """Get details or cancel a specific booking."""

    @blp.response(200, BookingSchema)
    def get(self, booking_id: str) -> dict[str, Any]:
        """Get details for a specific booking."""
        module = _get_module()
        user_id = _get_user_id()
        
        booking = module.get_booking(booking_id)
        if not booking:
            return create_api_base_response(None, err.ERROR_BOOKING_NOT_FOUND)
        
        # Verify user owns this booking
        if booking.get("organizer_id") != user_id:
            return create_api_base_response(None, err.ERROR_BOOKING_ACCESS_DENIED)
        
        return create_api_base_response(booking)

    @blp.response(200)
    def delete(self, booking_id: str) -> dict[str, Any]:
        """Cancel a booking."""
        module = _get_module()
        user_id = _get_user_id()
        
        booking = module.get_booking(booking_id)
        if not booking:
            return create_api_base_response(None, err.ERROR_BOOKING_NOT_FOUND)
        
        # Verify user owns this booking
        if booking.get("organizer_id") != user_id:
            return create_api_base_response(None, err.ERROR_BOOKING_ACCESS_DENIED)
        
        try:
            module.cancel_booking(booking_id)
            return create_api_base_response({
                "message": "Booking cancelled successfully",
                "booking_id": booking_id,
            })
        except RequestException as ex:
            return create_api_base_response(None, ex.error, error_msg=str(ex))
        except Exception as ex:
            return create_api_base_response(None, err.ERROR_UNKOWN, error_msg=str(ex))
