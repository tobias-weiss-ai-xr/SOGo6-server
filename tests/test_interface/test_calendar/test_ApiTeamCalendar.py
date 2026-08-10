"""Structural tests for the Team Calendars feature (#team-calendars).

Fixture-free structural tests following the ApiMailboxDebug / ApiAppointmentSlots
convention: verify endpoint classes, schema fields and module methods exist.
"""
import pytest


class TestTeamCalendarEndpoints:
    """Verify all Team Calendar endpoint classes exist with correct methods."""

    def test_list_create_endpoint(self):
        from app.api.v1.calendar.ApiTeamCalendar import ApiTeamCalendarList
        view = ApiTeamCalendarList()
        assert hasattr(view, "get")
        assert hasattr(view, "post")

    def test_detail_endpoint(self):
        from app.api.v1.calendar.ApiTeamCalendar import ApiTeamCalendarDetail
        view = ApiTeamCalendarDetail()
        assert hasattr(view, "get")
        assert hasattr(view, "patch")
        assert hasattr(view, "delete")

    def test_member_list_endpoint(self):
        from app.api.v1.calendar.ApiTeamCalendar import ApiTeamCalendarMemberList
        view = ApiTeamCalendarMemberList()
        assert hasattr(view, "get")
        assert hasattr(view, "post")

    def test_member_detail_endpoint(self):
        from app.api.v1.calendar.ApiTeamCalendar import ApiTeamCalendarMemberDetail
        view = ApiTeamCalendarMemberDetail()
        assert hasattr(view, "patch")
        assert hasattr(view, "delete")

    def test_invite_list_endpoint(self):
        from app.api.v1.calendar.ApiTeamCalendar import ApiTeamCalendarInviteList
        view = ApiTeamCalendarInviteList()
        assert hasattr(view, "post")

    def test_invite_pending_list_endpoint(self):
        from app.api.v1.calendar.ApiTeamCalendar import ApiTeamCalendarInvitePendingList
        view = ApiTeamCalendarInvitePendingList()
        assert hasattr(view, "get")

    def test_invite_detail_endpoint(self):
        from app.api.v1.calendar.ApiTeamCalendar import ApiTeamCalendarInviteDetail
        view = ApiTeamCalendarInviteDetail()
        assert hasattr(view, "get")
        assert hasattr(view, "delete")

    def test_invite_accept_endpoint(self):
        from app.api.v1.calendar.ApiTeamCalendar import ApiTeamCalendarInviteAccept
        view = ApiTeamCalendarInviteAccept()
        assert hasattr(view, "post")

    def test_invite_reject_endpoint(self):
        from app.api.v1.calendar.ApiTeamCalendar import ApiTeamCalendarInviteReject
        view = ApiTeamCalendarInviteReject()
        assert hasattr(view, "post")


class TestTeamCalendarSchemas:
    """Verify the team calendar schemas are importable and well-formed."""

    def test_create_schema_requires_name(self):
        from app.api.v1.calendar.schemas.team_calendar import TeamCalendarCreateSchema
        from marshmallow import ValidationError
        with pytest.raises(ValidationError):
            TeamCalendarCreateSchema().load({})
        data = TeamCalendarCreateSchema().load({"name": "Team"})
        assert data["name"] == "Team"
        assert data["timezone"] == "UTC"  # default

    def test_add_member_schema(self):
        from app.api.v1.calendar.schemas.team_calendar import TeamCalendarAddMemberSchema
        data = TeamCalendarAddMemberSchema().load({"user_uid": "a@b.org"})
        assert data["share_level"] == "view_all"

    def test_update_member_schema_requires_level(self):
        from app.api.v1.calendar.schemas.team_calendar import TeamCalendarUpdateMemberSchema
        from marshmallow import ValidationError
        with pytest.raises(ValidationError):
            TeamCalendarUpdateMemberSchema().load({})

    def test_invite_schema_fields(self):
        from app.api.v1.calendar.schemas.team_calendar import TeamCalendarInviteSchema
        fields = TeamCalendarInviteSchema().load({
            "id": "i1", "calendar_key": "k1", "user_uid": "a@b.org",
            "invited_by": "o@b.org", "status": "pending", "share_level": "view_all",
        })
        assert fields["status"] == "pending"


class TestTeamCalendarModule:
    """Verify the ModuleTeamCalendar methods exist."""

    def test_module_methods(self):
        from app.module.calendar.ModuleTeamCalendar import ModuleTeamCalendar
        for method in (
            "list_team_calendars", "get_team_calendar", "create_team_calendar",
            "update_team_calendar", "delete_team_calendar",
            "list_members", "add_member", "update_member", "remove_member",
            "invite_user", "list_invites", "get_invite",
            "accept_invite", "reject_invite", "cancel_invite",
        ):
            assert hasattr(ModuleTeamCalendar, method), f"missing {method}"

    def test_invite_repository_methods(self):
        from app.module.calendar.repository.RepositoryCalendarInvite import RepositoryCalendarInvite
        for method in ("insert", "find_by_id", "find_by_calendar_and_user",
                       "find_pending_for_user", "update_status", "delete"):
            assert hasattr(RepositoryCalendarInvite, method)

    def test_team_source_type_exists(self):
        from app.module.calendar.model.enums.CalendarSourceType import CalendarSourceType
        assert CalendarSourceType.TEAM.value == "team"

    def test_invite_status_constants(self):
        from app.module.calendar.model.CalendarInvite import (
            INVITE_STATUS_PENDING, INVITE_STATUS_ACCEPTED,
            INVITE_STATUS_REJECTED, INVITE_STATUS_CANCELLED, VALID_INVITE_STATUSES,
        )
        assert INVITE_STATUS_PENDING in VALID_INVITE_STATUSES
        assert INVITE_STATUS_ACCEPTED in VALID_INVITE_STATUSES
        assert INVITE_STATUS_REJECTED in VALID_INVITE_STATUSES
        assert INVITE_STATUS_CANCELLED in VALID_INVITE_STATUSES

    def test_error_constants(self):
        from app.utils import errors as err
        assert err.ERROR_CALENDAR_INVITE_NOT_FOUND.m
        assert err.ERROR_CALENDAR_INVITE_ALREADY_EXISTS.h == 409
        assert err.ERROR_CALENDAR_INVITE_INVALID_STATUS.h == 409
        assert err.ERROR_CALENDAR_NOT_TEAM.h == 400
        assert err.ERROR_CALENDAR_MEMBER_NOT_FOUND.h == 404

    def test_invite_table_registered(self):
        from app.config.db import tables as tbl
        assert tbl.TABLE_CALENDAR_INVITE.name == "sogo6_calendar_invites"
        assert tbl.TABLE_CALENDAR_INVITE in tbl.ALL_TABLES


class TestTeamCalendarInterface:
    """Verify the interface pass-through methods exist."""

    def test_interface_methods(self):
        from app.interface.calendar.InterfaceApiTeamCalendar import InterfaceApiTeamCalendar
        for method in (
            "list_team_calendars", "get_team_calendar", "create_team_calendar",
            "update_team_calendar", "delete_team_calendar",
            "list_members", "add_member", "update_member", "remove_member",
            "invite_user", "list_invites", "get_invite",
            "accept_invite", "reject_invite", "cancel_invite",
        ):
            assert hasattr(InterfaceApiTeamCalendar, method), f"missing {method}"

    def test_blueprint_registered(self):
        from app.api.v1.calendar import calendar_apis
        from app.api.v1.calendar.ApiTeamCalendar import blp
        assert blp in calendar_apis
