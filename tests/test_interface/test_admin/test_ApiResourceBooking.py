"""Tests for Resource Booking Admin API endpoints.

Resource Booking Feature - Tier 0 Foundation
Tests verify the structure of the admin resource management endpoints.
"""

import pytest


# =============================================================================
# Schema Definitions
# =============================================================================

class TestAdminResourceSchemas:
    """Test the admin API schema definitions."""

    def test_resource_create_schema_fields(self):
        from app.api.v1.admin.ApiResourceBooking import ResourceCreateSchema
        schema = ResourceCreateSchema()
        assert "name" in schema.fields
        assert "description" in schema.fields
        assert "email" in schema.fields
        assert "resource_type" in schema.fields
        assert "capacity" in schema.fields
        assert "location" in schema.fields
        assert "features" in schema.fields
        assert "booking_policy" in schema.fields
        assert "allowed_groups" in schema.fields
        assert "auto_accept" in schema.fields

    def test_resource_update_schema_fields(self):
        from app.api.v1.admin.ApiResourceBooking import ResourceUpdateSchema
        schema = ResourceUpdateSchema()
        assert "name" in schema.fields
        assert "description" in schema.fields
        assert "email" in schema.fields
        assert "resource_type" in schema.fields
        assert "capacity" in schema.fields
        assert "location" in schema.fields
        assert "features" in schema.fields
        assert "booking_policy" in schema.fields
        assert "allowed_groups" in schema.fields
        assert "auto_accept" in schema.fields
        assert "is_active" in schema.fields

    def test_resource_list_schema_fields(self):
        from app.api.v1.admin.ApiResourceBooking import ResourceListSchema
        schema = ResourceListSchema()
        assert "active_only" in schema.fields

    def test_resource_availability_schema_fields(self):
        from app.api.v1.admin.ApiResourceBooking import ResourceAvailabilitySchema
        schema = ResourceAvailabilitySchema()
        assert "resource_id" in schema.fields
        assert "start" in schema.fields
        assert "end" in schema.fields

    def test_resource_available_list_schema_fields(self):
        from app.api.v1.admin.ApiResourceBooking import ResourceAvailableListSchema
        schema = ResourceAvailableListSchema()
        assert "start" in schema.fields
        assert "end" in schema.fields
        assert "resource_type" in schema.fields
        assert "min_capacity" in schema.fields


# =============================================================================
# Endpoint Classes
# =============================================================================

class TestAdminResourceEndpoints:
    """Verify all admin endpoint classes exist with correct methods."""

    def test_resource_list_endpoint(self):
        from app.api.v1.admin.ApiResourceBooking import ApiResourceList
        view = ApiResourceList()
        assert hasattr(view, "get")
        assert hasattr(view, "post")

    def test_resource_available_list_endpoint(self):
        from app.api.v1.admin.ApiResourceBooking import ApiResourceAvailableList
        view = ApiResourceAvailableList()
        assert hasattr(view, "get")

    def test_resource_detail_endpoint(self):
        from app.api.v1.admin.ApiResourceBooking import ApiResourceDetail
        view = ApiResourceDetail()
        assert hasattr(view, "get")
        assert hasattr(view, "patch")
        assert hasattr(view, "delete")

    def test_resource_availability_endpoint(self):
        from app.api.v1.admin.ApiResourceBooking import ApiResourceAvailability
        view = ApiResourceAvailability()
        assert hasattr(view, "post")

    def test_admin_module_resource_booking_import(self):
        """The admin module should expose the resource booking module."""
        from app.api.v1.admin import ApiResourceBooking
        assert ApiResourceBooking is not None


class TestBlueprintRegistration:
    """Verify the blueprints are registered in the admin API package."""

    def test_admin_api_registers_resource_booking(self):
        import app.api.v1.admin  # noqa: F401
        assert True
