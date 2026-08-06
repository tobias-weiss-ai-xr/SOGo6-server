"""Tests for Resource Booking User API endpoints.

Resource Booking Feature - Tier 0 Foundation
Tests cover all 7 user-facing API endpoints for resource booking.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def mock_module_resource_booking():
    """Mock the ModuleResourceBooking module."""
    with patch('app.api.v1.user.ApiResourceBooking.ModuleResourceBooking') as mock:
        yield mock


@pytest.fixture
def mock_has_admin_access():
    """Mock the has_admin_access function."""
    with patch('app.api.v1.user.ApiResourceBooking.has_admin_access') as mock:
        mock.return_value = False
        yield mock


# =============================================================================
# Resource Listing Endpoints
# =============================================================================

class TestUserResourceListing:
    """Tests for user resource listing endpoints."""

    BASE_URL = "/api/user/v1/resources"

    def test_list_resources_endpoint_exists(self):
        """Verify the resource listing endpoint exists and is callable."""
        from app.api.v1.user.ApiResourceBooking import ApiResourceBooking
        view = ApiResourceBooking()
        assert hasattr(view, 'get')

    def test_list_all_resources(self, client, user_auth_headers, mock_module_resource_booking):
        """Test listing all resources."""
        # Mock the module to return sample resources
        mock_instance = MagicMock()
        mock_instance.list_all.return_value = [
            {"id": "res-001", "name": "Conference Room A", "resource_type": "room"},
            {"id": "res-002", "name": "Projector Cart", "resource_type": "equipment"},
        ]
        mock_module_resource_booking.return_value = mock_instance

        resp = client.get(self.BASE_URL, headers=user_auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "data" in data
        # The response should contain resource data
        # Note: The actual response structure depends on Flask-Smorest envelope

    def test_list_resources_filter_by_type(self, client, user_auth_headers, mock_module_resource_booking):
        """Test filtering resources by type."""
        mock_instance = MagicMock()
        mock_instance.list_all.return_value = [
            {"id": "res-001", "name": "Room A", "resource_type": "room"},
        ]
        mock_module_resource_booking.return_value = mock_instance

        resp = client.get(
            f"{self.BASE_URL}?resource_type=room",
            headers=user_auth_headers
        )
        assert resp.status_code == 200

    def test_list_resources_filter_by_capacity(self, client, user_auth_headers, mock_module_resource_booking):
        """Test filtering resources by minimum capacity."""
        mock_instance = MagicMock()
        mock_instance.list_all.return_value = [
            {"id": "res-001", "name": "Large Room", "capacity": 50},
        ]
        mock_module_resource_booking.return_value = mock_instance

        resp = client.get(
            f"{self.BASE_URL}?min_capacity=20",
            headers=user_auth_headers
        )
        assert resp.status_code == 200

    def test_list_resources_filter_by_features(self, client, user_auth_headers, mock_module_resource_booking):
        """Test filtering resources by features."""
        mock_instance = MagicMock()
        mock_instance.list_all.return_value = [
            {"id": "res-001", "name": "Room A", "features": ["projector", "whiteboard"]},
        ]
        mock_module_resource_booking.return_value = mock_instance

        resp = client.get(
            f"{self.BASE_URL}?features=projector",
            headers=user_auth_headers
        )
        assert resp.status_code == 200


class TestUserResourceAvailability:
    """Tests for resource availability checking."""

    BASE_URL = "/api/user/v1/resources"

    def test_check_single_resource_availability(self, client, user_auth_headers, mock_module_resource_booking):
        """Test checking availability for a single resource."""
        mock_instance = MagicMock()
        start = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 15, 11, 0, tzinfo=timezone.utc)
        mock_instance.check_availability.return_value = {
            "available": True,
            "conflicts": []
        }
        mock_module_resource_booking.return_value = mock_instance

        resp = client.get(
            f"{self.BASE_URL}/res-001/availability?start=2025-01-15T10:00:00Z&end=2025-01-15T11:00:00Z",
            headers=user_auth_headers
        )
        assert resp.status_code == 200

    def test_check_multiple_resources_availability(self, client, user_auth_headers, mock_module_resource_booking):
        """Test checking availability for multiple resources."""
        mock_instance = MagicMock()
        start = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 15, 11, 0, tzinfo=timezone.utc)
        mock_instance.check_multiple_availability.return_value = {
            "res-001": {"available": True, "conflicts": []},
            "res-002": {"available": False, "conflicts": ["existing-booking"]}
        }
        mock_module_resource_booking.return_value = mock_instance

        resp = client.post(
            f"{self.BASE_URL}/availability",
            data=json.dumps({
                "resource_ids": ["res-001", "res-002"],
                "start": "2025-01-15T10:00:00Z",
                "end": "2025-01-15T11:00:00Z"
            }),
            content_type="application/json",
            headers=user_auth_headers
        )
        assert resp.status_code == 200

    def test_list_available_resources_in_date_range(self, client, user_auth_headers, mock_module_resource_booking):
        """Test listing all available resources for a date/time range."""
        mock_instance = MagicMock()
        start = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 15, 11, 0, tzinfo=timezone.utc)
        mock_instance.list_available.return_value = [
            {"id": "res-001", "name": "Room A", "available": True},
            {"id": "res-002", "name": "Room B", "available": True},
        ]
        mock_module_resource_booking.return_value = mock_instance

        resp = client.get(
            f"{self.BASE_URL}/available?start=2025-01-15T10:00:00Z&end=2025-01-15T11:00:00Z",
            headers=user_auth_headers
        )
        assert resp.status_code == 200


# =============================================================================
# Booking Endpoints
# =============================================================================

class TestUserBookingEndpoints:
    """Tests for user booking management endpoints."""

    BASE_URL = "/api/user/v1/resource-bookings"

    def test_book_resource_endpoint_exists(self):
        """Verify the book resource endpoint exists."""
        from app.api.v1.user.ApiResourceBooking import ApiResourceBooking
        view = ApiResourceBooking()
        assert hasattr(view, 'post')

    def test_create_booking(self, client, user_auth_headers, mock_module_resource_booking):
        """Test creating a new resource booking."""
        mock_instance = MagicMock()
        start = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 15, 11, 0, tzinfo=timezone.utc)
        mock_instance.book_resource.return_value = {
            "id": "booking-001",
            "resource_id": "res-001",
            "user_id": "user-001",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "status": "confirmed"
        }
        mock_module_resource_booking.return_value = mock_instance

        data = {
            "resource_id": "res-001",
            "start": "2025-01-15T10:00:00Z",
            "end": "2025-01-15T11:00:00Z",
            "title": "Team Meeting",
            "description": "Quarterly planning session"
        }
        resp = client.post(
            self.BASE_URL,
            data=json.dumps(data),
            content_type="application/json",
            headers=user_auth_headers
        )
        assert resp.status_code in [200, 201]

    def test_create_booking_missing_required_fields(self, client, user_auth_headers):
        """Test creating a booking with missing required fields."""
        data = {
            "resource_id": "res-001"
            # Missing start, end, title
        }
        resp = client.post(
            self.BASE_URL,
            data=json.dumps(data),
            content_type="application/json",
            headers=user_auth_headers
        )
        # Should return 400 Bad Request or similar error
        assert resp.status_code >= 400

    def test_create_booking_resource_not_found(self, client, user_auth_headers, mock_module_resource_booking):
        """Test creating a booking for a non-existent resource."""
        mock_instance = MagicMock()
        start = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 15, 11, 0, tzinfo=timezone.utc)
        from app.utils.errors import ERROR_RESOURCE_NOT_FOUND
        mock_instance.book_resource.side_effect = RequestException(
            ERROR_RESOURCE_NOT_FOUND, 404
        )
        mock_module_resource_booking.return_value = mock_instance

        data = {
            "resource_id": "non-existent",
            "start": "2025-01-15T10:00:00Z",
            "end": "2025-01-15T11:00:00Z",
            "title": "Test Booking"
        }
        resp = client.post(
            self.BASE_URL,
            data=json.dumps(data),
            content_type="application/json",
            headers=user_auth_headers
        )
        assert resp.status_code == 404

    def test_create_booking_resource_not_available(self, client, user_auth_headers, mock_module_resource_booking):
        """Test creating a booking for an unavailable resource."""
        mock_instance = MagicMock()
        from app.utils.errors import ERROR_RESOURCE_NOT_AVAILABLE
        mock_instance.book_resource.side_effect = RequestException(
            ERROR_RESOURCE_NOT_AVAILABLE, 409
        )
        mock_module_resource_booking.return_value = mock_instance

        data = {
            "resource_id": "res-001",
            "start": "2025-01-15T10:00:00Z",
            "end": "2025-01-15T11:00:00Z",
            "title": "Test Booking"
        }
        resp = client.post(
            self.BASE_URL,
            data=json.dumps(data),
            content_type="application/json",
            headers=user_auth_headers
        )
        assert resp.status_code == 409


class TestUserBookingRetrieval:
    """Tests for retrieving user bookings."""

    BASE_URL = "/api/user/v1/resource-bookings"

    def test_get_all_user_bookings(self, client, user_auth_headers, mock_module_resource_booking):
        """Test getting all bookings for the current user."""
        mock_instance = MagicMock()
        mock_instance.get_user_bookings.return_value = [
            {"id": "booking-001", "resource_id": "res-001", "status": "confirmed"},
            {"id": "booking-002", "resource_id": "res-002", "status": "confirmed"},
        ]
        mock_module_resource_booking.return_value = mock_instance

        resp = client.get(self.BASE_URL, headers=user_auth_headers)
        assert resp.status_code == 200

    def test_get_booking_by_id(self, client, user_auth_headers, mock_module_resource_booking):
        """Test getting a specific booking by ID."""
        mock_instance = MagicMock()
        mock_instance.get_booking.return_value = {
            "id": "booking-001",
            "resource_id": "res-001",
            "user_id": "user-001",
            "start": "2025-01-15T10:00:00Z",
            "end": "2025-01-15T11:00:00Z",
            "status": "confirmed"
        }
        mock_module_resource_booking.return_value = mock_instance

        resp = client.get(
            f"{self.BASE_URL}/booking-001",
            headers=user_auth_headers
        )
        assert resp.status_code == 200

    def test_get_booking_not_found(self, client, user_auth_headers, mock_module_resource_booking):
        """Test getting a non-existent booking."""
        mock_instance = MagicMock()
        from app.utils.errors import ERROR_BOOKING_NOT_FOUND
        mock_instance.get_booking.side_effect = RequestException(
            ERROR_BOOKING_NOT_FOUND, 404
        )
        mock_module_resource_booking.return_value = mock_instance

        resp = client.get(
            f"{self.BASE_URL}/non-existent",
            headers=user_auth_headers
        )
        assert resp.status_code == 404

    def test_get_booking_access_denied(self, client, user_auth_headers, mock_module_resource_booking):
        """Test getting a booking that belongs to another user."""
        mock_instance = MagicMock()
        from app.utils.errors import ERROR_BOOKING_ACCESS_DENIED
        mock_instance.get_booking.side_effect = RequestException(
            ERROR_BOOKING_ACCESS_DENIED, 403
        )
        mock_module_resource_booking.return_value = mock_instance

        resp = client.get(
            f"{self.BASE_URL}/other-user-booking",
            headers=user_auth_headers
        )
        assert resp.status_code == 403


class TestUserBookingManagement:
    """Tests for updating and canceling bookings."""

    BASE_URL = "/api/user/v1/resource-bookings"

    def test_update_booking(self, client, user_auth_headers, mock_module_resource_booking):
        """Test updating an existing booking."""
        mock_instance = MagicMock()
        mock_instance.update_booking.return_value = {
            "id": "booking-001",
            "resource_id": "res-001",
            "title": "Updated Meeting",
            "description": "Updated description"
        }
        mock_module_resource_booking.return_value = mock_instance

        data = {
            "title": "Updated Meeting",
            "description": "Updated description"
        }
        resp = client.put(
            f"{self.BASE_URL}/booking-001",
            data=json.dumps(data),
            content_type="application/json",
            headers=user_auth_headers
        )
        assert resp.status_code == 200

    def test_cancel_booking(self, client, user_auth_headers, mock_module_resource_booking):
        """Test canceling a booking."""
        mock_instance = MagicMock()
        mock_instance.cancel_booking.return_value = {
            "id": "booking-001",
            "status": "cancelled"
        }
        mock_module_resource_booking.return_value = mock_instance

        data = {"reason": "Meeting rescheduled"}
        resp = client.delete(
            f"{self.BASE_URL}/booking-001",
            data=json.dumps(data),
            content_type="application/json",
            headers=user_auth_headers
        )
        assert resp.status_code == 200

    def test_cancel_booking_not_found(self, client, user_auth_headers, mock_module_resource_booking):
        """Test canceling a non-existent booking."""
        mock_instance = MagicMock()
        from app.utils.errors import ERROR_BOOKING_NOT_FOUND
        mock_instance.cancel_booking.side_effect = RequestException(
            ERROR_BOOKING_NOT_FOUND, 404
        )
        mock_module_resource_booking.return_value = mock_instance

        resp = client.delete(
            f"{self.BASE_URL}/non-existent",
            data=json.dumps({}),
            content_type="application/json",
            headers=user_auth_headers
        )
        assert resp.status_code == 404

    def test_cancel_booking_access_denied(self, client, user_auth_headers, mock_module_resource_booking):
        """Test canceling a booking that belongs to another user."""
        mock_instance = MagicMock()
        from app.utils.errors import ERROR_BOOKING_ACCESS_DENIED
        mock_instance.cancel_booking.side_effect = RequestException(
            ERROR_BOOKING_ACCESS_DENIED, 403
        )
        mock_module_resource_booking.return_value = mock_instance

        resp = client.delete(
            f"{self.BASE_URL}/other-user-booking",
            data=json.dumps({}),
            content_type="application/json",
            headers=user_auth_headers
        )
        assert resp.status_code == 403
