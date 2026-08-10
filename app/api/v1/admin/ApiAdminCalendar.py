"""
Calendar administration API endpoints — maintenance, clean, etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.interface.admin.InterfaceApiAdminCalendar import InterfaceApiAdminCalendar
from app.utils.logger.logger import logger_api

from .schema import adminCalendar as sch

if TYPE_CHECKING:
    from app.config.settings.ProcessSetting import ProcessSetting


blp = Blueprint("Admin Calendar", __name__, url_prefix="/calendar")


@blp.before_request
def init_admin_calendar() -> None:
    """
    Initialize the calendar admin interface for this request.
    """
    logger_api.debug("Calling before_request for AdminCalendar")
    process: ProcessSetting = g.process_settings
    g.inter = InterfaceApiAdminCalendar(process_setting=process)


@blp.route("/clean")
class ApiAdminCalendarClean(MethodView):
    """
    Purge soft-deleted event and reminder rows from the calendar database.
    """

    @blp.arguments(sch.CalendarCleanPostSchema)
    @blp.response(200, sch.CalendarCleanResponseSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """
        Physically remove soft-deleted event and reminder rows.

        Provide at least one of ``user_uid`` (cleans all calendars of that user)
        or ``calendar_key`` (cleans a specific calendar). Returns the total
        number of rows purged.
        """
        logger_api.debug("POST /admin/calendar/clean body=%s", body)
        interface: InterfaceApiAdminCalendar = g.inter
        return interface.clean(
            user_uid=body.get("user_uid"),
            calendar_key=body.get("calendar_key"),
        )
