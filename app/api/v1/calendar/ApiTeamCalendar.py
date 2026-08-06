from __future__ import annotations

from typing import TYPE_CHECKING

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.interface.calendar.InterfaceApiTeamCalendar import InterfaceApiTeamCalendar
from app.utils.logger.logger import logger_api
from .schemas.calendar import (
    CalendarListResponseSchema,
    CalendarResponseSchema,
)
from .schemas.team_calendar import (
    TeamCalendarCreateSchema,
    TeamCalendarUpdateSchema,
    TeamCalendarMemberListResponseSchema,
    TeamCalendarAddMemberSchema,
    TeamCalendarUpdateMemberSchema,
    TeamCalendarMemberResponseSchema,
    TeamCalendarInviteListResponseSchema,
    TeamCalendarInviteResponseSchema,
    TeamCalendarInviteAcceptResponseSchema,
)

if TYPE_CHECKING:
    from app.auth.User import User
    from app.config.settings.ProcessSetting import ProcessSetting

blp = Blueprint("Team Calendar", __name__, url_prefix="")


@blp.before_request
def init_team_calendar_config() -> None:  # pylint: disable=missing-function-docstring
    g.inter = InterfaceApiTeamCalendar(
        process_setting=g.process_settings,
        user=g.user,
    )


# --------------------------------------------------------------------------- #
# Team calendar CRUD                                                           #
# --------------------------------------------------------------------------- #


@blp.route("/calendars/teams")
class ApiTeamCalendarList(MethodView):
    """List and create team calendars."""

    @blp.response(200, CalendarListResponseSchema)
    def get(self) -> ResponseReturnValue:
        """List all team calendars the user has access to."""
        logger_api.debug("GET /calendars/teams user=%s", g.user.uid)
        interface: InterfaceApiTeamCalendar = g.inter
        return interface.list_team_calendars()

    @blp.arguments(TeamCalendarCreateSchema)
    @blp.response(201, CalendarResponseSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """Create a new team calendar."""
        logger_api.debug("POST /calendars/teams user=%s body=%s", g.user.uid, body)
        interface: InterfaceApiTeamCalendar = g.inter
        return interface.create_team_calendar(body)


@blp.route("/calendars/teams/<string:team_id>")
class ApiTeamCalendarDetail(MethodView):
    """Get, update and delete a team calendar."""

    @blp.response(200, CalendarResponseSchema)
    def get(self, team_id: str) -> ResponseReturnValue:
        """Get team calendar details."""
        logger_api.debug("GET /calendars/teams/%s user=%s", team_id, g.user.uid)
        interface: InterfaceApiTeamCalendar = g.inter
        return interface.get_team_calendar(team_id)

    @blp.arguments(TeamCalendarUpdateSchema)
    @blp.response(200, CalendarResponseSchema)
    def patch(self, body: dict, team_id: str) -> ResponseReturnValue:
        """Update a team calendar's metadata."""
        logger_api.debug("PATCH /calendars/teams/%s user=%s body=%s", team_id, g.user.uid, body)
        interface: InterfaceApiTeamCalendar = g.inter
        return interface.update_team_calendar(team_id, body)

    @blp.response(200, CalendarResponseSchema)
    def delete(self, team_id: str) -> ResponseReturnValue:
        """Delete a team calendar."""
        logger_api.debug("DELETE /calendars/teams/%s user=%s", team_id, g.user.uid)
        interface: InterfaceApiTeamCalendar = g.inter
        return interface.delete_team_calendar(team_id)


# --------------------------------------------------------------------------- #
# Membership                                                                   #
# --------------------------------------------------------------------------- #


@blp.route("/calendars/teams/<string:team_id>/members")
class ApiTeamCalendarMemberList(MethodView):
    """List members and add/invite members to a team calendar."""

    @blp.response(200, TeamCalendarMemberListResponseSchema)
    def get(self, team_id: str) -> ResponseReturnValue:
        """List team calendar members."""
        logger_api.debug("GET /calendars/teams/%s/members user=%s", team_id, g.user.uid)
        interface: InterfaceApiTeamCalendar = g.inter
        return interface.list_members(team_id)

    @blp.arguments(TeamCalendarAddMemberSchema)
    @blp.response(201, TeamCalendarMemberResponseSchema)
    def post(self, body: dict, team_id: str) -> ResponseReturnValue:
        """Add a member directly to the team calendar."""
        logger_api.debug("POST /calendars/teams/%s/members user=%s body=%s", team_id, g.user.uid, body)
        interface: InterfaceApiTeamCalendar = g.inter
        return interface.add_member(team_id, body)


@blp.route("/calendars/teams/<string:team_id>/members/<string:member_uid>")
class ApiTeamCalendarMemberDetail(MethodView):
    """Update or remove a team calendar member."""

    @blp.arguments(TeamCalendarUpdateMemberSchema)
    @blp.response(200, TeamCalendarMemberResponseSchema)
    def patch(self, body: dict, team_id: str, member_uid: str) -> ResponseReturnValue:
        """Update a member's permission level."""
        logger_api.debug("PATCH /calendars/teams/%s/members/%s user=%s", team_id, member_uid, g.user.uid)
        interface: InterfaceApiTeamCalendar = g.inter
        return interface.update_member(team_id, member_uid, body)

    @blp.response(200, TeamCalendarMemberResponseSchema)
    def delete(self, team_id: str, member_uid: str) -> ResponseReturnValue:
        """Remove a member from the team calendar."""
        logger_api.debug("DELETE /calendars/teams/%s/members/%s user=%s", team_id, member_uid, g.user.uid)
        interface: InterfaceApiTeamCalendar = g.inter
        return interface.remove_member(team_id, member_uid)


# --------------------------------------------------------------------------- #
# Invitations                                                                  #
# --------------------------------------------------------------------------- #


@blp.route("/calendars/teams/<string:team_id>/invites")
class ApiTeamCalendarInviteList(MethodView):
    """Send an invitation to join a team calendar."""

    @blp.arguments(TeamCalendarAddMemberSchema)
    @blp.response(201, TeamCalendarInviteResponseSchema)
    def post(self, body: dict, team_id: str) -> ResponseReturnValue:
        """Invite a user to the team calendar."""
        logger_api.debug("POST /calendars/teams/%s/invites user=%s body=%s", team_id, g.user.uid, body)
        interface: InterfaceApiTeamCalendar = g.inter
        return interface.invite_user(team_id, body)


@blp.route("/calendars/teams/invites")
class ApiTeamCalendarInvitePendingList(MethodView):
    """List pending invitations for the current user."""

    @blp.response(200, TeamCalendarInviteListResponseSchema)
    def get(self) -> ResponseReturnValue:
        """List all pending invitations for the current user."""
        logger_api.debug("GET /calendars/teams/invites user=%s", g.user.uid)
        interface: InterfaceApiTeamCalendar = g.inter
        return interface.list_invites()


@blp.route("/calendars/teams/invites/<string:invite_id>")
class ApiTeamCalendarInviteDetail(MethodView):
    """Get or cancel a team calendar invitation."""

    @blp.response(200, TeamCalendarInviteResponseSchema)
    def get(self, invite_id: str) -> ResponseReturnValue:
        """Get invitation details."""
        logger_api.debug("GET /calendars/teams/invites/%s user=%s", invite_id, g.user.uid)
        interface: InterfaceApiTeamCalendar = g.inter
        return interface.get_invite(invite_id)

    @blp.response(200, TeamCalendarInviteResponseSchema)
    def delete(self, invite_id: str) -> ResponseReturnValue:
        """Cancel/revoke an invitation (owner only)."""
        logger_api.debug("DELETE /calendars/teams/invites/%s user=%s", invite_id, g.user.uid)
        interface: InterfaceApiTeamCalendar = g.inter
        return interface.cancel_invite(invite_id)


@blp.route("/calendars/teams/invites/<string:invite_id>/accept")
class ApiTeamCalendarInviteAccept(MethodView):
    """Accept a pending invitation."""

    @blp.response(200, TeamCalendarInviteAcceptResponseSchema)
    def post(self, invite_id: str) -> ResponseReturnValue:
        """Accept the invitation and become a member."""
        logger_api.debug("POST /calendars/teams/invites/%s/accept user=%s", invite_id, g.user.uid)
        interface: InterfaceApiTeamCalendar = g.inter
        return interface.accept_invite(invite_id)


@blp.route("/calendars/teams/invites/<string:invite_id>/reject")
class ApiTeamCalendarInviteReject(MethodView):
    """Reject a pending invitation."""

    @blp.response(200, TeamCalendarInviteResponseSchema)
    def post(self, invite_id: str) -> ResponseReturnValue:
        """Reject the invitation."""
        logger_api.debug("POST /calendars/teams/invites/%s/reject user=%s", invite_id, g.user.uid)
        interface: InterfaceApiTeamCalendar = g.inter
        return interface.reject_invite(invite_id)
