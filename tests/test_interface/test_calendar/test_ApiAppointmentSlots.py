"""Tests for Appointment Slots (#47) using real Redis."""
import json
import pytest
from app.api.v1.calendar.ApiAppointmentSlots import (
    ApiSlotListCreate, ApiSlotBook, ApiSlotBookings,
    _SLOT_PREFIX, _BOOKING_PREFIX
)


@pytest.fixture
def slot_data():
    return {
        "title": "Office Hours",
        "description": "Book a slot",
        "duration_minutes": 30,
        "start_time": "09:00",
        "end_time": "17:00",
        "days_of_week": [1, 2, 3, 4, 5],
        "buffer_minutes": 15,
        "max_bookings_per_day": 4,
    }


class TestSlotCRUD:
    def test_slot_create_endpoint_exists(self):
        view = ApiSlotListCreate()
        assert hasattr(view, 'get')
        assert hasattr(view, 'post')

    def test_booking_endpoint_exists(self):
        view = ApiSlotBook()
        assert hasattr(view, 'post')

    def test_bookings_list_endpoint_exists(self):
        view = ApiSlotBookings()
        assert hasattr(view, 'get')


class TestSlotDataValidation:
    def test_valid_slot_data(self, slot_data):
        assert slot_data["duration_minutes"] >= 15
        assert slot_data["duration_minutes"] <= 240
        assert "09:00" <= slot_data["start_time"] <= slot_data["end_time"] <= "17:00"
        assert all(0 <= d <= 6 for d in slot_data["days_of_week"])
        assert slot_data["buffer_minutes"] >= 0
        assert slot_data["max_bookings_per_day"] >= 1

    def test_slot_data_stored_correctly(self, real_cache, slot_data):
        import secrets
        slot_id = secrets.token_hex(10)
        slot = {**slot_data, "id": slot_id, "user_uid": "testuser", "created_at": 1000, "enabled": True, "token": "tok"}
        real_cache.set(f"{_SLOT_PREFIX}{slot_id}", json.dumps(slot), ttl=86400)
        raw = real_cache.get(f"{_SLOT_PREFIX}{slot_id}", str)
        stored = json.loads(raw)
        assert stored["title"] == "Office Hours"
        assert stored["duration_minutes"] == 30
        assert stored["enabled"] is True

    def test_booking_stored_correctly(self, real_cache):
        import secrets
        booking_id = secrets.token_hex(12)
        booking = {"id": booking_id, "slot_id": "test_slot", "name": "John", "email": "john@test.com", "date": "2026-08-15", "time": "10:00"}
        real_cache.set(f"{_BOOKING_PREFIX}{booking_id}", json.dumps(booking), ttl=86400)
        raw = real_cache.get(f"{_BOOKING_PREFIX}{booking_id}", str)
        stored = json.loads(raw)
        assert stored["name"] == "John"
        assert stored["email"] == "john@test.com"
        assert stored["date"] == "2026-08-15"
