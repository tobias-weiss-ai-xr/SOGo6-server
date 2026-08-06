"""Tests for Resource Booking Admin API endpoints.

Resource Booking Feature - Tier 0 Foundation
Tests cover all 7 admin API endpoints for resource management.
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def mock_admin_module_resource_booking():
    """Mock the admin ModuleResourceBooking module."""
    with patch('app.api.v1.admin.ApiResourceBooking.ModuleResourceBooking') as mock:
        module_mock = MagicMock()
        # Ensure the admin-specific methods exist
        module_mock.list_all.return_value = []
        module_mock.get_by_id.return_value = None
        module_mock.create.return_value = {}
        module_mock.update.return_value = None
        module_mock.delete.return_value = None
        mock.return_value = module_mock
        yield mock


@pytest.fixture
def mock_has_admin_access():
    """Mock the has_admin_access function to return True for admin tests."""
    with patch('app.api.v1.admin.ApiResourceBooking.has_admin_access') as mock:
        mock.return_value = True
        yield mock


# =============================================================================
# Resource CRUD Endpoints
# =============================================================================

class TestAdminResourceCRUD:
    """Tests for admin resource CRUD operations."""

    BASE_URL = "/api/admin/v1/resources"

    def test_list_all_resources_admin(self, client, auth_headers, mock_admin_module_resource_booking):
        """Test admin can list all resources including inactive ones."""
        mock_instance = mock_admin_module_resource_booking.return_value
        mock_instance.list_all.return_value = [
            {"id": "res-001", "name": "Room A", "is_active": True},
            {"id": "res-002", "name": "Room B", "is_active": False},
        ]

        resp = client.get(self.BASE_URL, headers=auth_headers)
        assert resp.status_code == 200

    def test_create_resource_admin(self, client, auth_headers, mock_admin_module_resource_booking):
        """Test admin can create a new resource."""
        mock_instance = mock_admin_module_resource_booking.return_value
        mock_instance.create.return_value = {
            "id": "new-resource",
            "name": "New Conference Room",
            "email": "new-room@example.org",
            "resource_type": "room",
            "capacity": 25,
            "is_active": True
        }

        data = {
            "name": "New Conference Room",
            "email": "new-room@example.org",
            "resource_type": "room",
            "capacity": 25,
            "description": "Large conference room with video equipment",
            "location": "Building A, Floor 2",
            "features": ["projector", "video_conference", "whiteboard"],
            "booking_policy": "open",
            "allowed_groups": ["engineering", "sales"],
            "auto_accept": True,
            "is_active": True
        }
        resp = client.post(
            self.BASE_URL,
            data=json.dumps(data),
            content_type="application/json",
            headers=auth_headers
        )
        assert resp.status_code in [200, 201]

    def test_create_resource_duplicate_email(self, client, auth_headers, mock_admin_module_resource_booking):
        """Test creating a resource with duplicate email fails."""
        mock_instance = mock_admin_module_resource_booking.return_value
        from app.utils.errors import ERROR_RESOURCE_DUPLICATE
        from app.utils.exceptions import RequestException
        mock_instance.create.side_effect = RequestException(
            ERROR_RESOURCE_DUPLICATE, 409
        )

        data = {
            "name": "Duplicate Room",
            "email": "existing@example.org",
            "resource_type": "room"
        }
        resp = client.post(
            self.BASE_URL,
            data=json.dumps(data),
            content_type="application/json",
            headers=auth_headers
        )
        assert resp.status_code == 409

    def test_create_resource_invalid_type(self, client, auth_headers, mock_admin_module_resource_booking):
        """Test creating a resource with invalid type fails."""
        mock_instance = mock_admin_module_resource_booking.return_value
        from app.utils.errors import ERROR_INVALID_INPUT
        from app.utils.exceptions import RequestException
        mock_instance.create.side_effect = RequestException(
            ERROR_INVALID_INPUT, 400
        )

        data = {
            "name": "Invalid Room",
            "email": "invalid@example.org",
            "resource_type": "invalid_type"
        }
        resp = client.post(
            self.BASE_URL,
            data=json.dumps(data),
            content_type="application/json",
            headers=auth_headers
        )
        assert resp.status_code == 400

    def test_create_resource_missing_required_fields(self, client, auth_headers):
        """Test creating a resource with missing required fields."""
        data = {
            "name": "Incomplete Room"
            # Missing email, resource_type
        }
        resp = client.post(
            self.BASE_URL,
            data=json.dumps(data),
            content_type="application/json",
            headers=auth_headers
        )
        assert resp.status_code >= 400

    def test_get_resource_by_id_admin(self, client, auth_headers, mock_admin_module_resource_booking):
        """Test admin can get a specific resource by ID."""
        mock_instance = mock_admin_module_resource_booking.return_value
        mock_instance.get_by_id.return_value = {
            "id": "res-001",
            "name": "Conference Room A",
            "email": "room-a@example.org",
            "resource_type": "room",
            "capacity": 20,
            "is_active": True
        }

        resp = client.get(
            f"{self.BASE_URL}/res-001",
            headers=auth_headers
        )
        assert resp.status_code == 200

    def test_get_resource_not_found_admin(self, client, auth_headers, mock_admin_module_resource_booking):
        """Test admin gets 404 for non-existent resource."""
        mock_instance = mock_admin_module_resource_booking.return_value
        from app.utils.errors import ERROR_RESOURCE_NOT_FOUND
        from app.utils.exceptions import RequestException
        mock_instance.get_by_id.side_effect = RequestException(
            ERROR_RESOURCE_NOT_FOUND, 404
        )

        resp = client.get(
            f"{self.BASE_URL}/non-existent",
            headers=auth_headers
        )
        assert resp.status_code == 404

    def test_update_resource_admin(self, client, auth_headers, mock_admin_module_resource_booking):
        """Test admin can update a resource."""
        mock_instance = mock_admin_module_resource_booking.return_value
        mock_instance.update.return_value = {
            "id": "res-001",
            "name": "Updated Conference Room",
            "email": "room-a@example.org",
            "resource_type": "room",
            "capacity": 30
        }

        data = {
            "name": "Updated Conference Room",
            "capacity": 30
        }
        resp = client.put(
            f"{self.BASE_URL}/res-001",
            data=json.dumps(data),
            content_type="application/json",
            headers=auth_headers
        )
        assert resp.status_code == 200

    def test_update_resource_not_found(self, client, auth_headers, mock_admin_module_resource_booking):
        """Test updating a non-existent resource fails."""
        mock_instance = mock_admin_module_resource_booking.return_value
        from app.utils.errors import ERROR_RESOURCE_NOT_FOUND
        from app.utils.exceptions import RequestException
        mock_instance.update.side_effect = RequestException(
            ERROR_RESOURCE_NOT_FOUND, 404
        )

        data = {"name": "Updated Name"}
        resp = client.put(
            f"{self.BASE_URL}/non-existent",
            data=json.dumps(data),
            content_type="application/json",
            headers=auth_headers
        )
        assert resp.status_code == 404

    def test_delete_resource_admin(self, client, auth_headers, mock_admin_module_resource_booking):
        """Test admin can delete a resource."""
        mock_instance = mock_admin_module_resource_booking.return_value
        mock_instance.delete.return_value = None

        resp = client.delete(
            f"{self.BASE_URL}/res-001",
            headers=auth_headers
        )
        assert resp.status_code == 200

    def test_delete_resource_not_found(self, client, auth_headers, mock_admin_module_resource_booking):
        """Test deleting a non-existent resource fails."""
        mock_instance = mock_admin_module_resource_booking.return_value
        from app.utils.errors import ERROR_RESOURCE_NOT_FOUND
        from app.utils.exceptions import RequestException
        mock_instance.delete.side_effect = RequestException(
            ERROR_RESOURCE_NOT_FOUND, 404
        )

        resp = client.delete(
            f"{self.BASE_URL}/non-existent",
            headers=auth_headers
        )
        assert resp.status_code == 404


# =============================================================================
# Resource Bulk Operations
# =============================================================================

class TestAdminResourceBulkOperations:
    """Tests for admin bulk operations on resources."""

    BASE_URL = "/api/admin/v1/resources"

    def test_activate_resource(self, client, auth_headers, mock_admin_module_resource_booking):
        """Test admin can activate a resource."""
        mock_instance = mock_admin_module_resource_booking.return_value
        mock_instance.update.return_value = {
            "id": "res-001",
            "is_active": True
        }

        resp = client.post(
            f"{self.BASE_URL}/res-001/activate",
            headers=auth_headers
        )
        assert resp.status_code == 200

    def test_deactivate_resource(self, client, auth_headers, mock_admin_module_resource_booking):
        """Test admin can deactivate a resource."""
        mock_instance = mock_admin_module_resource_booking.return_value
        mock_instance.update.return_value = {
            "id": "res-001",
            "is_active": False
        }

        resp = client.post(
            f"{self.BASE_URL}/res-001/deactivate",
            headers=auth_headers
        )
        assert resp.status_code == 200


# =============================================================================
# Booking Management Endpoints
# =============================================================================

class TestAdminBookingManagement:
    """Tests for admin booking management endpoints."""

    BASE_URL = "/api/admin/v1/resource-bookings"

    def test_list_all_bookings_admin(self, client, auth_headers, mock_admin_module_resource_booking):
        """Test admin can list all bookings across all users."""
        # Note: Admin uses a different module for booking operations
        with patch('app.api.v1.admin.ApiResourceBooking.ModuleCalendar') as mock_calendar:
            mock_calendar_instance = MagicMock()
            mock_calendar_instance.get_all_bookings.return_value = [
                {"id": "booking-001", "user_id": "user-001", "resource_id": "res-001"},
                {"id": "booking-002", "user_id": "user-002", "resource_id": "res-002"},
            ]
            mock_calendar.return_value = mock_calendar_instance

            resp = client.get(self.BASE_URL, headers=auth_headers)
            assert resp.status_code == 200

    def test_list_bookings_by_resource(self, client, auth_headers):
        """Test admin can list bookings for a specific resource."""
        with patch('app.api.v1.admin.ApiResourceBooking.ModuleCalendar') as mock_calendar:
            mock_calendar_instance = MagicMock()
            mock_calendar_instance.get_bookings_by_resource.return_value = [
                {"id": "booking-001", "user_id": "user-001", "resource_id": "res-001"},
            ]
            mock_calendar.return_value = mock_calendar_instance

            resp = client.get(
                f"{self.BASE_URL}?resource_id=res-001",
                headers=auth_headers
            )
            assert resp.status_code == 200

    def test_list_bookings_by_user(self, client, auth_headers):
        """Test admin can list bookings for a specific user."""
        with patch('app.api.v1.admin.ApiResourceBooking.ModuleCalendar') as mock_calendar:
            mock_calendar_instance = MagicMock()
            mock_calendar_instance.get_bookings_by_user.return_value = [
                {"id": "booking-001", "user_id": "user-001", "resource_id": "res-001"},
            ]
            mock_calendar.return_value = mock_calendar_instance

            resp = client.get(
                f"{self.BASE_URL}?user_id=user-001",
                headers=auth_headers
            )
            assert resp.status_code == 200

    def test_cancel_any_booking_admin(self, client, auth_headers):
        """Test admin can cancel any user's booking."""
        with patch('app.api.v1.admin.ApiResourceBooking.ModuleCalendar') as mock_calendar:
            mock_calendar_instance = MagicMock()
            mock_calendar_instance.cancel_booking.return_value = {
                "id": "booking-001",
                "status": "cancelled"
            }
            mock_calendar.return_value = mock_calendar_instance

            data = {"reason": "Admin cancellation - maintenance"}
            resp = client.delete(
                f"{self.BASE_URL}/booking-001",
                data=json.dumps(data),
                content_type="application/json",
                headers=auth_headers
            )
            assert resp.status_code == 200

    def test_cancel_booking_not_found_admin(self, client, auth_headers):
        """Test admin gets 404 when canceling non-existent booking."""
        with patch('app.api.v1.admin.ApiResourceBooking.ModuleCalendar') as mock_calendar:
            mock_calendar_instance = MagicMock()
            from app.utils.errors import ERROR_BOOKING_NOT_FOUND
            from app.utils.exceptions import RequestException
            mock_calendar_instance.cancel_booking.side_effect = RequestException(
                ERROR_BOOKING_NOT_FOUND, 404
            )
            mock_calendar.return_value = mock_calendar_instance

            resp = client.delete(
                f"{self.BASE_URL}/non-existent",
                data=json.dumps({}),
                content_type="application/json",
                headers=auth_headers
            )
            assert resp.status_code == 404


# =============================================================================
# Non-Admin Access Tests
# =============================================================================

class TestNonAdminAccess:
    """Tests to ensure non-admin users cannot access admin endpoints."""

    BASE_URL = "/api/admin/v1/resources"

    def test_admin_endpoint_rejects_non_admin(self, client, user_auth_headers):
        """Test that admin endpoints reject non-admin users."""
        # Using user_auth_headers (non-admin) on admin endpoint
        resp = client.get(self.BASE_URL, headers=user_auth_headers)
        # Should return 403 Forbidden or similar
        assert resp.status_code >= 400

    def test_create_resource_requires_admin(self, client, user_auth_headers):
        """Test that only admins can create resources."""
        data = {
            "name": "Test Room",
            "email": "test@example.org",
            "resource_type": "room"
        }
        resp = client.post(
            self.BASE_URL,
            data=json.dumps(data),
            content_type="application/json",
            headers=user_auth_headers
        )
        assert resp.status_code >= 400

    def test_delete_resource_requires_admin(self, client, user_auth_headers):
        """Test that only admins can delete resources."""
        resp = client.delete(
            f"{self.BASE_URL}/res-001",
            headers=user_auth_headers
        )
        assert resp.status_code >= 400
