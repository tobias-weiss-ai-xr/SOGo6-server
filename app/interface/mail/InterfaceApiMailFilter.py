from __future__ import annotations
from typing import TYPE_CHECKING, Any

from app.config.settings.DomainSettings import MailSettings, MailSettingsObj
from app.config.settings.UserSettings import UserGeneralSettings
from app.module.mail.ModuleFilter import ModuleFilter
from app.module.user.ModuleUserProfile import ModuleUserProfile
from app.utils.constants import (
    FILTER_SECTION_FILTERS,
    FILTER_SECTION_VACATION,
    FILTER_SECTION_FORWARD,
    FILTER_SECTION_NOTIFICATION,
)
from app.utils.exceptions import RequestException
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User
    from app.config.settings.ProcessSetting import ProcessSetting


class InterfaceApiMailFilter:
    """
    Interface for mail filter operations.

    Pass-through layer between the API and ModuleFilter.
    """

    def __init__(self, process_setting: ProcessSetting, user_domain_settings: dict, user: User) -> None:
        self.process_setting = process_setting
        self.user_domain_settings = user_domain_settings
        self.mail_settings = MailSettingsObj(user_domain_settings[MailSettings.subparent])
        self.user = user
        self.filter_module = ModuleFilter(user, self.mail_settings, process_setting)
        self.user_module = ModuleUserProfile(process_setting, user_domain_settings)

    def set_filters(self, filters: list[dict[str, Any]]) -> tuple[dict[str, Any], int]:
        """Replace the ``filters`` list for the current user.

        :param filters: Validated list of filter dicts.
        :type filters: list[dict[str, Any]]
        :return: Tuple of (API response dict, HTTP status code).
        :rtype: tuple[dict[str, Any], int]
        """
        try:
            saved = self.filter_module.set_section(FILTER_SECTION_FILTERS, filters)
        except RequestException as ex:
            logger_api.error("Request exception in set_filters: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response(saved)

    def set_vacation(self, vacation: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Replace the ``Vacation`` section for the current user.

        Automatically adds the user's timezone to the vacation config if not specified,
        so that start_date/end_date without explicit timezone use the user's timezone.

        :param vacation: Validated vacation settings dict.
        :type vacation: dict[str, Any]
        :return: Tuple of (API response dict, HTTP status code).
        :rtype: tuple[dict[str, Any], int]
        """
        if vacation.get("days", None) is not None:
            if vacation.get("days") == 0 and not self.mail_settings.SOGO_D_VACATION_ALLOW_RESPONSE_ALWAYS:
                return create_api_base_response(code=400, error_msg="Vacation value days must be greater than 0")

        # Ensure timezone is set: if not provided, use user's timezone
        if not vacation.get("timezone"):
            vacation["timezone"] = self._get_user_timezone()
        try:
            saved = self.filter_module.set_section(FILTER_SECTION_VACATION, vacation)
        except RequestException as ex:
            logger_api.error("Request exception in set_vacation: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response(saved)

    def _get_user_timezone(self) -> str:
        """Get the user's IANA timezone from preferences, defaulting to UTC.
        
        :return: IANA timezone string (e.g., 'Europe/Paris', 'UTC')
        :rtype: str
        """
        try:
            raw_gen: dict = self.user_module.get_partial_user_preferences(
                self.user.uid, UserGeneralSettings.subparent.lower()
            )
            return raw_gen.get(UserGeneralSettings.subparent, {}).get("SOGO_U_TIMEZONE", "UTC")
        except Exception as e:
            logger_api.warning("Failed to get user timezone for %s: %s. Defaulting to UTC.", self.user.uid, e)
            return "UTC"

    def set_forward(self, forward: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Replace the ``Forward`` section for the current user.

        :param forward: Validated forward settings dict.
        :type forward: dict[str, Any]
        :return: Tuple of (API response dict, HTTP status code).
        :rtype: tuple[dict[str, Any], int]
        """
        try:
            saved = self.filter_module.set_section(FILTER_SECTION_FORWARD, forward)
        except RequestException as ex:
            logger_api.error("Request exception in set_forward: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response(saved)

    def set_notification(self, notification: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Replace the ``Notification`` section for the current user.

        :param notification: Validated notification settings dict.
        :type notification: dict[str, Any]
        :return: Tuple of (API response dict, HTTP status code).
        :rtype: tuple[dict[str, Any], int]
        """
        try:
            saved = self.filter_module.set_section(FILTER_SECTION_NOTIFICATION, notification)
        except RequestException as ex:
            logger_api.error("Request exception in set_notification: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response(saved)

    # ------------------------------------------------------------------ #
    # GET methods                                                          #
    # ------------------------------------------------------------------ #

    def get_filters(self) -> tuple[dict[str, Any], int]:
        """Return the ``filters`` list for the current user.

        :return: Tuple of (API response dict, HTTP status code).
        :rtype: tuple[dict[str, Any], int]
        """
        try:
            value = self.filter_module.get_section(FILTER_SECTION_FILTERS)
        except RequestException as ex:
            logger_api.error("Request exception in get_filters: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response({"filters": value})

    def get_filter(self, filter_id: str) -> tuple[dict[str, Any], int]:
        """Return a single filter by its name/id for the current user.

        :param filter_id: Name of the filter to retrieve.
        :type filter_id: str
        :return: Tuple of (API response dict, HTTP status code).
        :rtype: tuple[dict[str, Any], int]
        """
        try:
            value = self.filter_module.get_filter(filter_id)
        except RequestException as ex:
            logger_api.error("Request exception in get_filter: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response({"filter": value})

    def set_filter(self, filter_id: str, value: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Create or replace a single filter by name/id for the current user.

        :param filter_id: Name of the filter to create/update.
        :type filter_id: str
        :param value: Validated filter payload.
        :type value: dict[str, Any]
        :return: Tuple of (API response dict, HTTP status code).
        :rtype: tuple[dict[str, Any], int]
        """
        try:
            saved = self.filter_module.set_filter(filter_id, value)
        except RequestException as ex:
            logger_api.error("Request exception in set_filter: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response(saved)

    def delete_filter(self, filter_id: str) -> tuple[dict[str, Any], int]:
        """Delete a single filter by name/id for the current user.

        :param filter_id: Name of the filter to delete.
        :type filter_id: str
        :return: Tuple of (API response dict, HTTP status code).
        :rtype: tuple[dict[str, Any], int]
        """
        try:
            saved = self.filter_module.delete_filter(filter_id)
        except RequestException as ex:
            logger_api.error("Request exception in delete_filter: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response(saved)

    def reorder_filters(self, ordered_names: list[str]) -> tuple[dict[str, Any], int]:
        """Reorder filters for the current user.

        :param ordered_names: Desired filter names in order.
        :type ordered_names: list[str]
        :return: Response with the reordered filters content.
        :rtype: tuple[dict[str, Any], int]
        """
        try:
            saved = self.filter_module.reorder_filters(ordered_names)
        except RequestException as ex:
            logger_api.error("Request exception in reorder_filters: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response(saved)

    def push_to_sieve(self) -> tuple[dict[str, Any], int]:
        """Re-push the current merged configuration to Sieve.

        :return: Response with the pushed filters content.
        :rtype: tuple[dict[str, Any], int]
        """
        try:
            saved = self.filter_module.push_to_sieve()
        except RequestException as ex:
            logger_api.error("Request exception in push_to_sieve: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response(saved)

    def validate_filter(self, value: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Validate a single filter payload without persisting it.

        The payload is assumed to have already passed marshmallow schema
        validation. This method performs an additional structural sanity check
        (name present, actions present) and reports validity.

        :param value: Validated filter payload.
        :type value: dict[str, Any]
        :return: Tuple of (API response dict, HTTP status code).
        :rtype: tuple[dict[str, Any], int]
        """
        errors: list[str] = []
        if not value.get("name"):
            errors.append("Filter must have a non-empty 'name'.")
        if not value.get("actions"):
            errors.append("Filter must have at least one action.")
        if not value.get("rules"):
            errors.append("Filter must have a 'rules' tree.")
        valid = len(errors) == 0
        return create_api_base_response({"valid": valid, "errors": errors})

    def preview_filter(self, value: dict[str, Any], sample: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Simulate whether a filter would execute against provided sample headers.

        Evaluates the filter's rule tree against a ``headers`` dict (e.g.
        ``{"subject": "...", "from": "...", "to": "..."}``). This is a
        best-effort client-side preview and does not require the Sieve engine.

        :param value: Validated filter payload.
        :type value: dict[str, Any]
        :param rules: Sample message headers used for matching.
        :type sample: dict[str, Any]
        :return: Response with match result and matched action.
        :rtype: tuple[dict[str, Any], int]
        """
        try:
            from app.module.mail.filter_preview import preview_filter
            matched, matched_action = preview_filter(value, sample=sample)
        except Exception as ex:  # noqa: BLE001 - preview must never 500 the request
            logger_api.error("Error in preview_filter: %s", str(ex))
            return create_api_base_response({"matched": False, "action": None, "error": str(ex)})
        return create_api_base_response({"matched": matched, "action": matched_action})

    def get_vacation(self) -> tuple[dict[str, Any], int]:
        """Return the ``Vacation`` section for the current user.

        :return: Tuple of (API response dict, HTTP status code).
        :rtype: tuple[dict[str, Any], int]
        """
        try:
            value = self.filter_module.get_section(FILTER_SECTION_VACATION)
        except RequestException as ex:
            logger_api.error("Request exception in get_vacation: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response({"vacation": value})

    def get_forward(self) -> tuple[dict[str, Any], int]:
        """Return the ``Forward`` section for the current user.

        :return: Tuple of (API response dict, HTTP status code).
        :rtype: tuple[dict[str, Any], int]
        """
        try:
            value = self.filter_module.get_section(FILTER_SECTION_FORWARD)
        except RequestException as ex:
            logger_api.error("Request exception in get_forward: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response({"forward": value})

    def get_notification(self) -> tuple[dict[str, Any], int]:
        """Return the ``Notification`` section for the current user.

        :return: Tuple of (API response dict, HTTP status code).
        :rtype: tuple[dict[str, Any], int]
        """
        try:
            value = self.filter_module.get_section(FILTER_SECTION_NOTIFICATION)
        except RequestException as ex:
            logger_api.error("Request exception in get_notification: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response({"notification": value})
