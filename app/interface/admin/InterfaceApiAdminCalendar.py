from __future__ import annotations

from typing import TYPE_CHECKING

from app.module.calendar.ModuleCalendar import ModuleCalendar
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import RequestException
from app.utils import errors as err

if TYPE_CHECKING:
    from app.config.settings.ProcessSetting import ProcessSetting


class InterfaceApiAdminCalendar:
    """
    Interface for calendar administration operations (maintenance, clean, etc.).
    """

    def __init__(self, process_setting: ProcessSetting) -> None:
        self._module: ModuleCalendar = ModuleCalendar(process_settings=process_setting)

    def clean(self, user_uid: str | None = None, calendar_key: str | None = None) -> tuple[dict, int]:
        """
        Physically remove soft-deleted event and reminder rows.

        At least one of *user_uid* or *calendar_key* must be provided. When *user_uid*
        is given, all calendars currently owned by that user are cleaned.

        :param user_uid: Clean all calendars owned by this user (optional).
        :param calendar_key: Clean a specific calendar by its key (optional).
        :return: API envelope with ``purged_rows``, plus HTTP status code.
        """
        if not user_uid and not calendar_key:
            return create_api_base_response(
                None, err.ERROR_CALENDAR_MAINTENANCE_REQUIRE_TARGET,
            )
        try:
            purged: int = self._module.clean(user_uid=user_uid, calendar_key=calendar_key)
            return create_api_base_response({"purged_rows": purged})
        except RequestException as ex:
            return create_api_base_response(None, ex.error)
