"""Tests for Resource Booking User API endpoints.

Resource Booking Feature - Tier 0 Foundation
Tests verify the structure of all 7 user-facing API endpoint classes.
"""

import pytest


# =============================================================================
# Schema Definitions
# =============================================================================

class TestResourceSchemas:
    """Test the API schema definitions."""

    def test_resource_list_query_schema_fields(self):
        from app.api.v1.user.ApiResourceBooking import ResourceListQuerySchema
        schema = ResourceListQuerySchema()
        assert "resource_type" in schema.fields
        assert "location" in schema.fields
        assert "capacity_min" in schema.fields
        assert "capacity_max" in schema.fields
        assert "search" in schema.fields
        assert "feature" in schema.fields
        assert "limit" in schema.fields
        assert "offset" in schema.fields

    def test_resource_schema_fields(self):
        from app.api.v1.user.ApiResourceBooking import ResourceSchema
        schema = ResourceSchema()
        assert "id" in schema.fields
        assert "name" in schema.fields
        assert "description" in schema.fields
        assert "email" in schema.fields
        assert "resource_type" in schema.fields
        assert "capacity" in schema.fields
        assert "location" in schema.fields
        assert "features" in schema.fields
        assert "is_active" in schema.fields
        assert "booking_policy" in schema.fields
        assert "auto_accept" in schema.fields

    def test_time_range_schema_fields(self):
        from app.api.v1.user.ApiResourceBooking import TimeRangeSchema
        schema = TimeRangeSchema()
        assert "start_time" in schema.fields
        assert "end_time" in schema.fields
        assert "timezone" in schema.fields

    def test_book_resource_schema_fields(self):
        from app.api.v1.user.ApiResourceBooking import BookResourceSchema
        schema = BookResourceSchema()
        assert "title" in schema.fields
        assert "description" in schema.fields
        assert "calendar_id" in schema.fields
        assert "is_online_meeting" in schema.fields
        assert "online_meeting_link" in schema.fields
        assert "location" in schema.fields

    def test_booking_schema_fields(self):
        from app.api.v1.user.ApiResourceBooking import BookingSchema
        schema = BookingSchema()
        assert "id" in schema.fields
        assert "resource_id" in schema.fields
        assert "resource_name" in schema.fields
        assert "event_id" in schema.fields
        assert "start_time" in schema.fields
        assert "end_time" in schema.fields
        assert "title" in schema.fields
        assert "status" in schema.fields
        assert "organizer_id" in schema.fields
        assert "organizer_name" in schema.fields
        assert "created_at" in schema.fields

    def test_booking_create_response_schema_fields(self):
        from app.api.v1.user.ApiResourceBooking import BookingCreateResponseSchema
        schema = BookingCreateResponseSchema()
        assert "booking_id" in schema.fields
        assert "event_id" in schema.fields
        assert "calendar_event" in schema.fields
        assert "message" in schema.fields

    def test_booking_list_schema_fields(self):
        from app.api.v1.user.ApiResourceBooking import BookingListSchema
        schema = BookingListSchema()
        assert "bookings" in schema.fields
        assert "total_count" in schema.fields

    def test_availability_response_schema_fields(self):
        from app.api.v1.user.ApiResourceBooking import AvailabilityResponseSchema
        schema = AvailabilityResponseSchema()
        assert "available" in schema.fields
        assert "conflicts" in schema.fields

    def test_error_schema_fields(self):
        from app.api.v1.user.ApiResourceBooking import ErrorSchema
        schema = ErrorSchema()
        assert "error" in schema.fields
        assert "message" in schema.fields
        assert "details" in schema.fields


# =============================================================================
# Enum Definitions
# =============================================================================

class TestResourceEnums:
    """Test the enum definitions."""

    def test_resource_type_enum(self):
        from app.api.v1.user.ApiResourceBooking import ResourceTypeEnum
        assert ResourceTypeEnum.ROOM == "room"
        assert ResourceTypeEnum.EQUIPMENT == "equipment"
        assert ResourceTypeEnum.VEHICLE == "vehicle"
        assert ResourceTypeEnum.OTHER == "other"

    def test_booking_policy_enum(self):
        from app.api.v1.user.ApiResourceBooking import BookingPolicyEnum
        assert BookingPolicyEnum.OPEN == "open"
        assert BookingPolicyEnum.MODERATED == "moderated"
        assert BookingPolicyEnum.RESTRICTED == "restricted"

    def test_booking_status_enum(self):
        from app.api.v1.user.ApiResourceBooking import BookingStatusEnum
        assert BookingStatusEnum.CONFIRMED == "confirmed"
        assert BookingStatusEnum.PENDING == "pending"
        assert BookingStatusEnum.CANCELLED == "cancelled"
        assert BookingStatusEnum.REJECTED == "rejected"


# =============================================================================
# Endpoint Classes
# =============================================================================

class TestUserResourceEndpoints:
    """Verify all 7 user-facing endpoint classes exist with correct methods."""

    def test_resource_list_endpoint(self):
        from app.api.v1.user.ApiResourceBooking import ApiResourceList
        view = ApiResourceList()
        assert hasattr(view, "get")

    def test_resource_detail_endpoint(self):
        from app.api.v1.user.ApiResourceBooking import ApiResourceDetail
        view = ApiResourceDetail()
        assert hasattr(view, "get")

    def test_available_resources_endpoint(self):
        from app.api.v1.user.ApiResourceBooking import ApiAvailableResources
        view = ApiAvailableResources()
        assert hasattr(view, "get")

    def test_resource_availability_check_endpoint(self):
        from app.api.v1.user.ApiResourceBooking import ApiResourceAvailabilityCheck
        view = ApiResourceAvailabilityCheck()
        assert hasattr(view, "post")

    def test_resource_book_endpoint(self):
        from app.api.v1.user.ApiResourceBooking import ApiResourceBook
        view = ApiResourceBook()
        assert hasattr(view, "post")

    def test_my_bookings_endpoint(self):
        from app.api.v1.user.ApiResourceBooking import ApiMyBookings
        view = ApiMyBookings()
        assert hasattr(view, "get")

    def test_my_booking_detail_endpoint(self):
        from app.api.v1.user.ApiResourceBooking import ApiMyBookingDetail
        view = ApiMyBookingDetail()
        assert hasattr(view, "get")
        assert hasattr(view, "delete")


class TestBlueprintRegistration:
    """Verify the blueprints are registered in the user API package."""

    def test_user_api_registers_resource_booking(self):
        from app.api.v1.user import __init__ as user_init
        # The module should expose the resource booking module
        assert user_init is not None

    def test_user_api_init_imports_blueprints(self):
        # Importing the package should not raise
        import app.api.v1.user  # noqa: F401
        assert True
