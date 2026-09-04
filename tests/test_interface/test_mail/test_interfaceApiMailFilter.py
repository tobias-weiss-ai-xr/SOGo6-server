"""Unit tests for InterfaceApiMailFilter."""
from unittest.mock import MagicMock, patch

import pytest

from app.interface.mail.InterfaceApiMailFilter import InterfaceApiMailFilter
from app.utils.exceptions import RequestException


class FakeUser:
    def __init__(self, uid="user@example.org"):
        self.uid = uid


class FakeProcessSetting:
    def __getitem__(self, key):
        return getattr(self, key, None)


class FakeMailSettings:
    SOGO_D_VACATION_ALLOW_RESPONSE_ALWAYS = True


@pytest.fixture
def interface():
    with patch("app.interface.mail.InterfaceApiMailFilter.ModuleFilter") as mock_filter:
        with patch("app.interface.mail.InterfaceApiMailFilter.ModuleUserProfile") as mock_profile:
            with patch("app.interface.mail.InterfaceApiMailFilter.MailSettingsObj", return_value=FakeMailSettings()):
                iface = InterfaceApiMailFilter(
                    FakeProcessSetting(),
                    {"MAIL_SETTINGS": {}},
                    FakeUser()
                )
                # Set up the mock on the actual interface.user_module instance
                iface.user_module.get_partial_user_preferences.return_value = {"USER_GENERAL": {"SOGO_U_TIMEZONE": "UTC"}}
                yield iface


class TestSetFilters:
    def test_sets_filters_successfully(self, interface):
        interface.filter_module.set_section.return_value = [{"name": "filter1"}]
        body, status = interface.set_filters([{"name": "filter1"}])
        interface.filter_module.set_section.assert_called_once_with("filters", [{"name": "filter1"}])
        assert body["data"] == [{"name": "filter1"}]

    def test_handles_request_exception(self, interface):
        error_obj = type("E", (), {"c": "E001", "m": "Failed", "h": 400})()
        interface.filter_module.set_section.side_effect = RequestException("error", error=error_obj)
        body, status = interface.set_filters([{"name": "filter1"}])
        assert body["data"] is None
        assert body["error_code"] == "E001"


class TestSetVacation:
    def test_sets_vacation_with_timezone(self, interface):
        interface.filter_module.set_section.return_value = {"days": 7}
        body, status = interface.set_vacation({"days": 7})
        interface.filter_module.set_section.assert_called_once()
        call_args = interface.filter_module.set_section.call_args[0][1]
        assert call_args["days"] == 7
        assert call_args["timezone"] == "UTC"
        assert body["data"] == {"days": 7}

    def test_sets_vacation_with_provided_timezone(self, interface):
        interface.filter_module.set_section.return_value = {"days": 7, "timezone": "Europe/Berlin"}
        body, status = interface.set_vacation({"days": 7, "timezone": "Europe/Berlin"})
        call_args = interface.filter_module.set_section.call_args[0][1]
        assert call_args["timezone"] == "Europe/Berlin"

    def test_rejects_zero_days_when_not_allowed(self, interface):
        interface.mail_settings.SOGO_D_VACATION_ALLOW_RESPONSE_ALWAYS = False
        body, status = interface.set_vacation({"days": 0})
        assert status == 400
        assert "days must be greater than 0" in body["error_msg"]

    def test_handles_request_exception(self, interface):
        error_obj = type("E", (), {"c": "E002", "m": "Failed", "h": 400})()
        interface.filter_module.set_section.side_effect = RequestException("error", error=error_obj)
        body, status = interface.set_vacation({"days": 7})
        assert body["data"] is None
        assert body["error_code"] == "E002"


class TestGetUserTimezone:
    def test_returns_user_timezone(self, interface):
        interface.user_module.get_partial_user_preferences.return_value = {"USER_GENERAL": {"SOGO_U_TIMEZONE": "Europe/Berlin"}}
        tz = interface._get_user_timezone()
        assert tz == "Europe/Berlin"

    def test_defaults_to_utc_on_error(self, interface):
        interface.user_module.get_partial_user_preferences.side_effect = Exception("DB error")
        tz = interface._get_user_timezone()
        assert tz == "UTC"

    def test_defaults_to_utc_when_missing(self, interface):
        interface.user_module.get_partial_user_preferences.return_value = {}
        tz = interface._get_user_timezone()
        assert tz == "UTC"


class TestSetForward:
    def test_sets_forward_successfully(self, interface):
        interface.filter_module.set_section.return_value = {"enabled": True}
        body, status = interface.set_forward({"enabled": True})
        interface.filter_module.set_section.assert_called_once_with("forward", {"enabled": True})
        assert body["data"] == {"enabled": True}

    def test_handles_request_exception(self, interface):
        error_obj = type("E", (), {"c": "E003", "m": "Failed", "h": 400})()
        interface.filter_module.set_section.side_effect = RequestException("error", error=error_obj)
        body, status = interface.set_forward({"enabled": True})
        assert body["data"] is None
        assert body["error_code"] == "E003"


class TestSetNotification:
    def test_sets_notification_successfully(self, interface):
        interface.filter_module.set_section.return_value = {"enabled": False}
        body, status = interface.set_notification({"enabled": False})
        interface.filter_module.set_section.assert_called_once_with("notification", {"enabled": False})
        assert body["data"] == {"enabled": False}

    def test_handles_request_exception(self, interface):
        error_obj = type("E", (), {"c": "E004", "m": "Failed", "h": 400})()
        interface.filter_module.set_section.side_effect = RequestException("error", error=error_obj)
        body, status = interface.set_notification({"enabled": False})
        assert body["data"] is None
        assert body["error_code"] == "E004"


class TestGetFilters:
    def test_gets_filters(self, interface):
        interface.filter_module.get_section.return_value = [{"name": "filter1"}]
        body, status = interface.get_filters()
        interface.filter_module.get_section.assert_called_once_with("filters")
        assert body["data"]["filters"] == [{"name": "filter1"}]

    def test_handles_request_exception(self, interface):
        error_obj = type("E", (), {"c": "E005", "m": "Failed", "h": 400})()
        interface.filter_module.get_section.side_effect = RequestException("error", error=error_obj)
        body, status = interface.get_filters()
        assert body["data"] is None
        assert body["error_code"] == "E005"


class TestGetFilter:
    def test_gets_single_filter(self, interface):
        interface.filter_module.get_filter.return_value = {"name": "filter1", "actions": []}
        body, status = interface.get_filter("filter1")
        interface.filter_module.get_filter.assert_called_once_with("filter1")
        assert body["data"]["filter"]["name"] == "filter1"

    def test_handles_request_exception(self, interface):
        error_obj = type("E", (), {"c": "E006", "m": "Failed", "h": 400})()
        interface.filter_module.get_filter.side_effect = RequestException("error", error=error_obj)
        body, status = interface.get_filter("filter1")
        assert body["data"] is None
        assert body["error_code"] == "E006"


class TestSetFilter:
    def test_sets_single_filter(self, interface):
        interface.filter_module.set_filter.return_value = {"name": "filter1"}
        body, status = interface.set_filter("filter1", {"name": "filter1", "actions": ["keep"]})
        interface.filter_module.set_filter.assert_called_once_with("filter1", {"name": "filter1", "actions": ["keep"]})
        assert body["data"]["name"] == "filter1"

    def test_handles_request_exception(self, interface):
        error_obj = type("E", (), {"c": "E007", "m": "Failed", "h": 400})()
        interface.filter_module.set_filter.side_effect = RequestException("error", error=error_obj)
        body, status = interface.set_filter("filter1", {"name": "filter1"})
        assert body["data"] is None
        assert body["error_code"] == "E007"


class TestDeleteFilter:
    def test_deletes_filter(self, interface):
        interface.filter_module.delete_filter.return_value = {"status": "deleted"}
        body, status = interface.delete_filter("filter1")
        interface.filter_module.delete_filter.assert_called_once_with("filter1")
        assert body["data"]["status"] == "deleted"

    def test_handles_request_exception(self, interface):
        error_obj = type("E", (), {"c": "E008", "m": "Failed", "h": 400})()
        interface.filter_module.delete_filter.side_effect = RequestException("error", error=error_obj)
        body, status = interface.delete_filter("filter1")
        assert body["data"] is None
        assert body["error_code"] == "E008"


class TestReorderFilters:
    def test_reorders_filters(self, interface):
        interface.filter_module.reorder_filters.return_value = [{"name": "filter2"}, {"name": "filter1"}]
        body, status = interface.reorder_filters(["filter2", "filter1"])
        interface.filter_module.reorder_filters.assert_called_once_with(["filter2", "filter1"])
        assert len(body["data"]) == 2

    def test_handles_request_exception(self, interface):
        error_obj = type("E", (), {"c": "E009", "m": "Failed", "h": 400})()
        interface.filter_module.reorder_filters.side_effect = RequestException("error", error=error_obj)
        body, status = interface.reorder_filters(["filter2", "filter1"])
        assert body["data"] is None
        assert body["error_code"] == "E009"


class TestPushToSieve:
    def test_pushes_to_sieve(self, interface):
        interface.filter_module.push_to_sieve.return_value = {"status": "pushed"}
        body, status = interface.push_to_sieve()
        interface.filter_module.push_to_sieve.assert_called_once()
        assert body["data"]["status"] == "pushed"

    def test_handles_request_exception(self, interface):
        error_obj = type("E", (), {"c": "E010", "m": "Failed", "h": 400})()
        interface.filter_module.push_to_sieve.side_effect = RequestException("error", error=error_obj)
        body, status = interface.push_to_sieve()
        assert body["data"] is None
        assert body["error_code"] == "E010"


class TestValidateFilter:
    def test_validates_valid_filter(self, interface):
        body, status = interface.validate_filter({"name": "test", "actions": ["keep"], "rules": {"any": {}}})
        assert body["data"]["valid"] is True
        assert body["data"]["errors"] == []

    def test_validates_filter_missing_name(self, interface):
        body, status = interface.validate_filter({"actions": ["keep"], "rules": {"any": {}}})
        assert body["data"]["valid"] is False
        assert "non-empty 'name'" in body["data"]["errors"][0]

    def test_validates_filter_missing_actions(self, interface):
        body, status = interface.validate_filter({"name": "test", "rules": {"any": {}}})
        assert body["data"]["valid"] is False
        assert "at least one action" in body["data"]["errors"][0]

    def test_validates_filter_missing_rules(self, interface):
        body, status = interface.validate_filter({"name": "test", "actions": ["keep"]})
        assert body["data"]["valid"] is False
        assert "'rules' tree" in body["data"]["errors"][0]


class TestPreviewFilter:
    def test_previews_matching_filter(self, interface):
        with patch("app.module.mail.filter_preview.preview_filter", return_value=(True, "action1")):
            body, status = interface.preview_filter({"name": "test"}, {"subject": "test"})
            assert body["data"]["matched"] is True
            assert body["data"]["action"] == "action1"

    def test_previews_non_matching_filter(self, interface):
        with patch("app.module.mail.filter_preview.preview_filter", return_value=(False, None)):
            body, status = interface.preview_filter({"name": "test"}, {"subject": "test"})
            assert body["data"]["matched"] is False
            assert body["data"]["action"] is None

    def test_handles_preview_error(self, interface):
        with patch("app.module.mail.filter_preview.preview_filter", side_effect=Exception("preview error")):
            body, status = interface.preview_filter({"name": "test"}, {"subject": "test"})
            assert body["data"]["matched"] is False
            assert "error" in body["data"]


class TestGetVacation:
    def test_gets_vacation(self, interface):
        interface.filter_module.get_section.return_value = {"days": 7}
        body, status = interface.get_vacation()
        interface.filter_module.get_section.assert_called_once_with("vacation")
        assert body["data"]["vacation"]["days"] == 7

    def test_handles_request_exception(self, interface):
        error_obj = type("E", (), {"c": "E011", "m": "Failed", "h": 400})()
        interface.filter_module.get_section.side_effect = RequestException("error", error=error_obj)
        body, status = interface.get_vacation()
        assert body["data"] is None
        assert body["error_code"] == "E011"


class TestGetForward:
    def test_gets_forward(self, interface):
        interface.filter_module.get_section.return_value = {"enabled": True}
        body, status = interface.get_forward()
        interface.filter_module.get_section.assert_called_once_with("forward")
        assert body["data"]["forward"]["enabled"] is True

    def test_handles_request_exception(self, interface):
        error_obj = type("E", (), {"c": "E012", "m": "Failed", "h": 400})()
        interface.filter_module.get_section.side_effect = RequestException("error", error=error_obj)
        body, status = interface.get_forward()
        assert body["data"] is None
        assert body["error_code"] == "E012"


class TestGetNotification:
    def test_gets_notification(self, interface):
        interface.filter_module.get_section.return_value = {"enabled": False}
        body, status = interface.get_notification()
        interface.filter_module.get_section.assert_called_once_with("notification")
        assert body["data"]["notification"]["enabled"] is False

    def test_handles_request_exception(self, interface):
        error_obj = type("E", (), {"c": "E013", "m": "Failed", "h": 400})()
        interface.filter_module.get_section.side_effect = RequestException("error", error=error_obj)
        body, status = interface.get_notification()
        assert body["data"] is None
        assert body["error_code"] == "E013"
