"""Tests for ModuleResourceBooking — bookable resource management."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.module.calendar.ModuleResourceBooking import ModuleResourceBooking
from app.module.calendar.model.CalResource import CalResource
from app.utils.exceptions import RequestException


@pytest.fixture
def mock_db() -> MagicMock:
    """Return a mock database client."""
    return MagicMock()


@pytest.fixture
def module(mock_db: MagicMock) -> ModuleResourceBooking:
    """Return a ModuleResourceBooking with mock DB."""
    return ModuleResourceBooking(mock_db)


SAMPLE_RESOURCE_ROW = [
    "res-001", "Conference Room A", "Ground floor, 20 seats",
    "room-a@example.org", "room", 20, "Building A, Floor 1",
    ["projector", "whiteboard"], True, "open", [], True,
    "2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00",
]


# ── create ────────────────────────────────────────────────────────────────────

class TestResourceCreate:
    def test_create_room_success(self, module: ModuleResourceBooking, mock_db: MagicMock):
        mock_db.select_from_table.return_value = []
        mock_db.insert_in_table.return_value = None

        result = module.create(
            name="Conference Room A",
            email="room-a@example.org",
            resource_type="room",
            capacity=20,
        )

        assert result["name"] == "Conference Room A"
        assert result["email"] == "room-a@example.org"
        assert result["resource_type"] == "room"
        assert result["capacity"] == 20
        assert result["is_active"] is True
        assert mock_db.insert_in_table.called

    def test_create_with_all_fields(self, module: ModuleResourceBooking, mock_db: MagicMock):
        mock_db.select_from_table.return_value = []
        mock_db.insert_in_table.return_value = None

        result = module.create(
            name="Projector Cart",
            email="projector@example.org",
            resource_type="equipment",
            description="Mobile projector",
            capacity=None,
            location="Storage Room B",
            features=["projector", "hdmi_cable"],
            booking_policy="moderated",
            allowed_groups=["engineering"],
            auto_accept=False,
        )

        assert result["resource_type"] == "equipment"
        assert result["booking_policy"] == "moderated"
        assert result["auto_accept"] is False
        assert result["allowed_groups"] == ["engineering"]

    def test_create_duplicate_email_raises(self, module: ModuleResourceBooking, mock_db: MagicMock):
        mock_db.select_from_table.return_value = [SAMPLE_RESOURCE_ROW]

        with pytest.raises(RequestException):
            module.create(
                name="Room B",
                email="room-a@example.org",  # duplicate
            )

    def test_create_invalid_resource_type_raises(self, module: ModuleResourceBooking, mock_db: MagicMock):
        with pytest.raises(RequestException):
            module.create(
                name="Invalid",
                email="invalid@example.org",
                resource_type="spaceship",
            )

    def test_create_invalid_booking_policy_raises(self, module: ModuleResourceBooking, mock_db: MagicMock):
        with pytest.raises(RequestException):
            module.create(
                name="Room",
                email="room@example.org",
                booking_policy="first_come_first_served",
            )


# ── get_all / get_by_id / get_by_email ───────────────────────────────────────

class TestResourceGet:
    def test_get_all(self, module: ModuleResourceBooking, mock_db: MagicMock):
        mock_db.select_from_table.return_value = [SAMPLE_RESOURCE_ROW]

        resources = module.get_all()
        assert len(resources) == 1
        assert resources[0]["name"] == "Conference Room A"

    def test_get_all_active_only(self, module: ModuleResourceBooking, mock_db: MagicMock):
        mock_db.select_from_table.return_value = [SAMPLE_RESOURCE_ROW]

        module.get_all(active_only=True)
        call_args = mock_db.select_from_table.call_args
        assert call_args is not None
        # Condition should filter on is_active=True

    def test_get_by_id_found(self, module: ModuleResourceBooking, mock_db: MagicMock):
        mock_db.select_from_table.return_value = [SAMPLE_RESOURCE_ROW]

        resource = module.get_by_id("res-001")
        assert resource is not None
        assert resource["id"] == "res-001"

    def test_get_by_id_not_found(self, module: ModuleResourceBooking, mock_db: MagicMock):
        mock_db.select_from_table.return_value = []

        resource = module.get_by_id("nonexistent")
        assert resource is None

    def test_get_by_email_found(self, module: ModuleResourceBooking, mock_db: MagicMock):
        mock_db.select_from_table.return_value = [SAMPLE_RESOURCE_ROW]

        resource = module.get_by_email("room-a@example.org")
        assert resource is not None
        assert resource["email"] == "room-a@example.org"


# ── update ───────────────────────────────────────────────────────────────────

class TestResourceUpdate:
    def test_update_name(self, module: ModuleResourceBooking, mock_db: MagicMock):
        mock_db.select_from_table.side_effect = [
            [SAMPLE_RESOURCE_ROW],  # get_by_id
            [SAMPLE_RESOURCE_ROW],  # get_by_id in _row_to_dict after update
        ]
        mock_db.update_in_table.return_value = None

        result = module.update("res-001", name="New Name")
        assert result["name"] == "New Name"
        assert mock_db.update_in_table.called

    def test_update_not_found_raises(self, module: ModuleResourceBooking, mock_db: MagicMock):
        mock_db.select_from_table.return_value = []

        with pytest.raises(RequestException):
            module.update("nonexistent", name="X")

    def test_update_duplicate_email_raises(self, module: ModuleResourceBooking, mock_db: MagicMock):
        # First call returns existing resource, second call (email check) returns another
        mock_db.select_from_table.side_effect = [
            [SAMPLE_RESOURCE_ROW],  # get_by_id
            [["other", "Other Room", "", "room-b@example.org", "room", 10, None, [], True, "open", [], True, None, None]],
        ]

        with pytest.raises(RequestException):
            module.update("res-001", email="room-b@example.org")


# ── delete ───────────────────────────────────────────────────────────────────

class TestResourceDelete:
    def test_delete_success(self, module: ModuleResourceBooking, mock_db: MagicMock):
        mock_db.select_from_table.return_value = [SAMPLE_RESOURCE_ROW]
        mock_db.delete_from_table.return_value = None

        module.delete("res-001")
        assert mock_db.delete_from_table.called

    def test_delete_not_found_raises(self, module: ModuleResourceBooking, mock_db: MagicMock):
        mock_db.select_from_table.return_value = []

        with pytest.raises(RequestException):
            module.delete("nonexistent")


# ── availability ─────────────────────────────────────────────────────────────

class TestResourceAvailability:
    def test_check_availability_active(self, module: ModuleResourceBooking, mock_db: MagicMock):
        mock_db.select_from_table.return_value = [SAMPLE_RESOURCE_ROW]

        start = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)

        result = module.check_availability("res-001", start, end)
        assert result["available"] is True
        assert result["conflicts"] == []

    def test_check_availability_inactive(self, module: ModuleResourceBooking, mock_db: MagicMock):
        inactive_row = list(SAMPLE_RESOURCE_ROW)
        inactive_row[8] = False  # is_active = False
        mock_db.select_from_table.return_value = [inactive_row]

        start = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)

        result = module.check_availability("res-001", start, end)
        assert result["available"] is False
        assert "deactivated" in result["reason"]

    def test_check_availability_not_found_raises(self, module: ModuleResourceBooking, mock_db: MagicMock):
        mock_db.select_from_table.return_value = []

        start = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)

        with pytest.raises(RequestException):
            module.check_availability("nonexistent", start, end)

    def test_list_available_filters_by_type(self, module: ModuleResourceBooking, mock_db: MagicMock):
        mock_db.select_from_table.return_value = [
            SAMPLE_RESOURCE_ROW,
            ["res-002", "Projector Cart", "", "proj@example.org", "equipment", None, None, [], True, "open", [], True, None, None],
        ]

        start = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)

        resources = module.list_available(start, end, resource_type="room")
        assert len(resources) == 1
        assert resources[0]["resource_type"] == "room"

    def test_list_available_filters_by_capacity(self, module: ModuleResourceBooking, mock_db: MagicMock):
        mock_db.select_from_table.return_value = [
            SAMPLE_RESOURCE_ROW,  # capacity=20
            ["res-002", "Small Room", "", "small@example.org", "room", 4, None, [], True, "open", [], True, None, None],
        ]

        start = datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)

        resources = module.list_available(start, end, min_capacity=10)
        assert len(resources) == 1
        assert resources[0]["capacity"] == 20


# ── model ─────────────────────────────────────────────────────────────────────

class TestCalResourceModel:
    def test_to_dict(self):
        resource = CalResource(
            id="r1", name="Room", email="room@example.org",
            resource_type="room", capacity=10, features=["wifi"],
        )
        d = resource.to_dict()
        assert d["id"] == "r1"
        assert d["features"] == ["wifi"]
        assert d["is_active"] is True

    def test_from_row(self):
        resource = CalResource.from_row(SAMPLE_RESOURCE_ROW)
        assert resource.id == "res-001"
        assert resource.name == "Conference Room A"
        assert resource.capacity == 20
        assert resource.features == ["projector", "whiteboard"]

    def test_from_row_minimal(self):
        resource = CalResource.from_row(["r1", "Name", "", "e@o.org", "room", None, None, []])
        assert resource.id == "r1"
        assert resource.capacity is None
        assert resource.is_active is True  # default
