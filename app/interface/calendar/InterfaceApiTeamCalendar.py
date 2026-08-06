from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module.calendar.ModuleTeamCalendar import ModuleTeamCalendar
from app.module.calendar.serializer.CalCalendarSerializerDict import CalCalendarSerializerDict
from app.module.calendar.serializer.CalendarShareSerializerDict import CalendarShareSerializerDict
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User
    from app.config.settings.ProcessSetting import ProcessSetting


class InterfaceApiTeamCalendar:
    """Interface for team calendar operations."""

    def __init__(self, process_setting: ProcessSetting, user: User) -> None:
        self.user: User = user
        self.module: ModuleTeamCalendar = ModuleTeamCalendar(process_setting)
        self._calendar_serializer: CalCalendarSerializerDict = CalCalendarSerializerDict()
        self._share_serializer: CalendarShareSerializerDict = CalendarShareSerializerDict()

    # ------------------------------------------------------------------ #
    # Team calendar CRUD                                                  #
    # ------------------------------------------------------------------ #

    def list_team_calendars(self) -> tuple[dict[str, Any], int]:
        try:
            calendars = self.module.list_team_calendars(self.user)
            serialized = [self._calendar_serializer.serialize(c) for c in calendars]
            return create_api_base_response({"calendars": serialized, "total_count": len(serialized)})
        except RequestException as ex:
            logger_api.error("list_team_calendars failed for user %s: %s", self.user.uid, ex)
            return create_api_base_response(None, ex.error)

    def get_team_calendar(self, team_id: str) -> tuple[dict[str, Any], int]:
        try:
            cal = self.module.get_team_calendar(self.user, team_id)
            return create_api_base_response(self._calendar_serializer.serialize(cal))
        except RequestException as ex:
            logger_api.error("get_team_calendar failed for user %s team %s: %s", self.user.uid, team_id, ex)
            return create_api_base_response(None, ex.error)

    def create_team_calendar(self, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        try:
            cal = self.module.create_team_calendar(
                self.user,
                name=body["name"],
                color=body.get("color"),
                description=body.get("description"),
                timezone=body.get("timezone", "UTC"),
            )
            return create_api_base_response(self._calendar_serializer.serialize(cal), code=201)
        except RequestException as ex:
            logger_api.error("create_team_calendar failed for user %s: %s", self.user.uid, ex)
            return create_api_base_response(None, ex.error)

    def update_team_calendar(self, team_id: str, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        try:
            cal = self.module.update_team_calendar(self.user, team_id, body)
            return create_api_base_response(self._calendar_serializer.serialize(cal))
        except RequestException as ex:
            logger_api.error("update_team_calendar failed for user %s team %s: %s", self.user.uid, team_id, ex)
            return create_api_base_response(None, ex.error)

    def delete_team_calendar(self, team_id: str) -> tuple[dict[str, Any], int]:
        try:
            self.module.delete_team_calendar(self.user, team_id)
            return create_api_base_response(None)
        except RequestException as ex:
            logger_api.error("delete_team_calendar failed for user %s team %s: %s", self.user.uid, team_id, ex)
            return create_api_base_response(None, ex.error)

    # ------------------------------------------------------------------ #
    # Membership                                                          #
    # ------------------------------------------------------------------ #

    def list_members(self, team_id: str) -> tuple[dict[str, Any], int]:
        try:
            members = self.module.list_members(self.user, team_id)
            serialized = [self._serialize_member(m) for m in members]
            return create_api_base_response({"members": serialized, "total_count": len(serialized)})
        except RequestException as ex:
            logger_api.error("list_members failed for team %s: %s", team_id, ex)
            return create_api_base_response(None, ex.error)

    def add_member(self, team_id: str, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        try:
            share = self.module.add_member(
                self.user, team_id, body["user_uid"], share_level=body.get("share_level", "view_all"),
            )
            return create_api_base_response(self._serialize_member(share), code=201)
        except RequestException as ex:
            logger_api.error("add_member failed for team %s user %s: %s", team_id, body.get("user_uid"), ex)
            return create_api_base_response(None, ex.error)

    def update_member(self, team_id: str, member_uid: str, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        try:
            share = self.module.update_member(self.user, team_id, member_uid, body["share_level"])
            return create_api_base_response(self._serialize_member(share))
        except RequestException as ex:
            logger_api.error("update_member failed for team %s user %s: %s", team_id, member_uid, ex)
            return create_api_base_response(None, ex.error)

    def remove_member(self, team_id: str, member_uid: str) -> tuple[dict[str, Any], int]:
        try:
            self.module.remove_member(self.user, team_id, member_uid)
            return create_api_base_response(None)
        except RequestException as ex:
            logger_api.error("remove_member failed for team %s user %s: %s", team_id, member_uid, ex)
            return create_api_base_response(None, ex.error)

    def _serialize_member(self, share) -> dict[str, Any]:
        """Serialize a share entry into a compact member object."""
        return {
            "user_uid": share.user_uid,
            "share_level": share.public_level.name.lower(),
            "can_create": bool(share.can_create),
            "can_delete": bool(share.can_delete),
        }

    # ------------------------------------------------------------------ #
    # Invitations                                                         #
    # ------------------------------------------------------------------ #

    def invite_user(self, team_id: str, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        try:
            invite = self.module.invite_user(
                self.user, team_id, body["user_uid"], share_level=body.get("share_level", "view_all"),
            )
            return create_api_base_response(self._serialize_invite(invite), code=201)
        except RequestException as ex:
            logger_api.error("invite_user failed for team %s user %s: %s", team_id, body.get("user_uid"), ex)
            return create_api_base_response(None, ex.error)

    def list_invites(self) -> tuple[dict[str, Any], int]:
        try:
            invites = self.module.list_invites(self.user)
            serialized = [self._serialize_invite(i) for i in invites]
            return create_api_base_response({"invites": serialized, "total_count": len(serialized)})
        except RequestException as ex:
            logger_api.error("list_invites failed for user %s: %s", self.user.uid, ex)
            return create_api_base_response(None, ex.error)

    def get_invite(self, invite_id: str) -> tuple[dict[str, Any], int]:
        try:
            invite = self.module.get_invite(self.user, invite_id)
            return create_api_base_response(self._serialize_invite(invite))
        except RequestException as ex:
            logger_api.error("get_invite failed for user %s invite %s: %s", self.user.uid, invite_id, ex)
            return create_api_base_response(None, ex.error)

    def accept_invite(self, invite_id: str) -> tuple[dict[str, Any], int]:
        try:
            share = self.module.accept_invite(self.user, invite_id)
            return create_api_base_response(self._serialize_member(share))
        except RequestException as ex:
            logger_api.error("accept_invite failed for user %s invite %s: %s", self.user.uid, invite_id, ex)
            return create_api_base_response(None, ex.error)

    def reject_invite(self, invite_id: str) -> tuple[dict[str, Any], int]:
        try:
            invite = self.module.reject_invite(self.user, invite_id)
            return create_api_base_response(self._serialize_invite(invite))
        except RequestException as ex:
            logger_api.error("reject_invite failed for user %s invite %s: %s", self.user.uid, invite_id, ex)
            return create_api_base_response(None, ex.error)

    def cancel_invite(self, invite_id: str) -> tuple[dict[str, Any], int]:
        try:
            invite = self.module.cancel_invite(self.user, invite_id)
            return create_api_base_response(self._serialize_invite(invite))
        except RequestException as ex:
            logger_api.error("cancel_invite failed for user %s invite %s: %s", self.user.uid, invite_id, ex)
            return create_api_base_response(None, ex.error)

    def _serialize_invite(self, invite) -> dict[str, Any]:
        return {
            "id": invite.id,
            "calendar_key": invite.calendar_key,
            "user_uid": invite.user_uid,
            "invited_by": invite.invited_by,
            "status": invite.status,
            "share_level": invite.share_level,
            "created_at": invite.created_at,
        }
