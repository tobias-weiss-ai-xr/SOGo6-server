"""Tests for UserCalendarGeneralSettings — Working Hours / Location preferences."""

from app.config.settings.UserSettings import UserCalendarGeneralSettings


def _load(payload: dict) -> dict:
    res = UserCalendarGeneralSettings().load(payload)
    return res[0] if isinstance(res, tuple) else res


class TestWorkingHoursPreferences:
    def test_defaults(self):
        data = _load({})
        assert data["SOGO_U_WORKDAY_START_TIME"] == "09:00"
        assert data["SOGO_U_WORKDAY_END_TIME"] == "18:00"
        assert data["SOGO_U_BUSY_OFF_HOURS"] is False
        assert data["SOGO_U_NON_WORKING_WEEKDAYS"] == [5, 6]
        assert data["SOGO_U_DEFAULT_LOCATION"] == ""

    def test_load_working_hours(self):
        data = _load({
            "SOGO_U_WORKDAY_START_TIME": "08:30",
            "SOGO_U_WORKDAY_END_TIME": "17:45",
            "SOGO_U_BUSY_OFF_HOURS": True,
        })
        assert data["SOGO_U_WORKDAY_START_TIME"] == "08:30"
        assert data["SOGO_U_WORKDAY_END_TIME"] == "17:45"
        assert data["SOGO_U_BUSY_OFF_HOURS"] is True

    def test_load_non_working_weekdays(self):
        data = _load({"SOGO_U_NON_WORKING_WEEKDAYS": [0, 6]})
        assert data["SOGO_U_NON_WORKING_WEEKDAYS"] == [0, 6]

    def test_load_default_location(self):
        data = _load({"SOGO_U_DEFAULT_LOCATION": "Conference Room A"})
        assert data["SOGO_U_DEFAULT_LOCATION"] == "Conference Room A"

    def test_dump_roundtrip(self):
        schema = UserCalendarGeneralSettings()
        data = _load({
            "SOGO_U_DEFAULT_LOCATION": "Room 42",
            "SOGO_U_NON_WORKING_WEEKDAYS": [5, 6],
        })
        dumped = schema.dump(data)
        assert dumped["SOGO_U_DEFAULT_LOCATION"] == "Room 42"
        assert dumped["SOGO_U_NON_WORKING_WEEKDAYS"] == [5, 6]

    def test_rejects_invalid_weekday(self):
        import pytest
        from marshmallow import ValidationError

        with pytest.raises(ValidationError):
            UserCalendarGeneralSettings().load({"SOGO_U_NON_WORKING_WEEKDAYS": [9]})
