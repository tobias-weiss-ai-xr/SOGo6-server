"""Unit tests for InterfaceApiTeamCalendar.

Tests the team calendar interface layer that wraps ModuleTeamCalendar for:
- Team calendar CRUD (list, get, create, update, delete)
- Membership management (list, add, update, remove members)
- Invitations (invite, list, get, accept, reject, cancel)
- Serialization of members and invites
"""
from unittest.mock import MagicMock, patch

import pytest

from app.interface.calendar.InterfaceApiTeamCalendar import InterfaceApiTeamCalendar
from app.utils.exceptions import RequestException


class FakeUser:
    def __init__(self, uid="user1@example.org"):
        self.uid = uid


class FakeProcessSettings:
    SOGO_P_DB_TYPE = "PostgreSQL"

    def get_db_settings(self):
        return {"host": "localhost"}


class FakeShare:
    """Fake share/member object with public_level enum."""
    def __init__(self, user_uid="member@example.org", level_name="view_all",
                 can_create=True, can_delete=False):
        self.user_uid = user_uid
        self.public_level = type("Lvl", (), {"name": level_name})()
        self.can_create = can_create
        self.can_delete = can_delete


class FakeInvite:
    def __init__(self, invite_id="inv1", calendar_key="cal1", user_uid="u1",
                 invited_by="u2", status="pending", share_level="view_all",
                 created_at="2026-01-01"):
        self.id = invite_id
        self.calendar_key = calendar_key
        self.user_uid = user_uid
        self.invited_by = invited_by
        self.status = status
        self.share_level = share_level
        self.created_at = created_at


@pytest.fixture
def interface():
    with patch(
        "app.interface.calendar.InterfaceApiTeamCalendar.ModuleTeamCalendar",
        return_value=MagicMock(),
    ):
        with patch(
            "app.interface.calendar.InterfaceApiTeamCalendar.CalCalendarSerializerDict",
            return_value=MagicMock(),
        ):
            with patch(
                "app.interface.calendar.InterfaceApiTeamCalendar.CalendarShareSerializerDict",
                return_value=MagicMock(),
            ):
                iface = InterfaceApiTeamCalendar(FakeProcessSettings(), FakeUser())
                yield iface


class TestListTeamCalendars:
    def test_returns_serialized_calendars(self, interface):
        cal1 = MagicMock()
        cal2 = MagicMock()
        interface.module.list_team_calendars.return_value = [cal1, cal2]
        interface._calendar_serializer.serialize.side_effect = lambda c: {"id": f"serialized_{id(c)}"}

        body, status = interface.list_team_calendars()

        assert status == 200
        assert body["data"]["total_count"] == 2
        assert len(body["data"]["calendars"]) == 2

    def test_empty_list(self, interface):
        interface.module.list_team_calendars.return_value = []

        body, status = interface.list_team_calendars()

        assert body["data"]["total_count"] == 0
        assert body["data"]["calendars"] == []

    def test_error_returns_error_response(self, interface):
        interface.module.list_team_calendars.side_effect = RequestException(
            "boom", error=type("E", (), {"c": "E001", "m": "Failed", "h": 400})()
        )

        body, status = interface.list_team_calendars()

        assert body["data"] is None
        assert body["error_code"] == "E001"


class TestGetTeamCalendar:
    def test_returns_serialized_calendar(self, interface):
        cal = MagicMock()
        interface.module.get_team_calendar.return_value = cal
        interface._calendar_serializer.serialize.return_value = {"id": "cal1"}

        body, status = interface.get_team_calendar("team1")

        interface.module.get_team_calendar.assert_called_once_with(interface.user, "team1")
        assert body["data"] == {"id": "cal1"}

    def test_error_returns_error_response(self, interface):
        interface.module.get_team_calendar.side_effect = RequestException(
            "boom", error=type("E", (), {"c": "E002", "m": "Failed", "h": 400})()
        )

        body, status = interface.get_team_calendar("team1")

        assert body["data"] is None
        assert body["error_code"] == "E002"


class TestCreateTeamCalendar:
    def test_creates_with_name_and_defaults(self, interface):
        cal = MagicMock()
        interface.module.create_team_calendar.return_value = cal
        interface._calendar_serializer.serialize.return_value = {"id": "new_cal"}

        body, status = interface.create_team_calendar({"name": "Team Cal"})

        assert status == 201
        interface.module.create_team_calendar.assert_called_once_with(
            interface.user,
            name="Team Cal",
            color=None,
            description=None,
            timezone="UTC",
        )

    def test_creates_with_all_fields(self, interface):
        cal = MagicMock()
        interface.module.create_team_calendar.return_value = cal
        interface._calendar_serializer.serialize.return_value = {"id": "cal"}

        body, status = interface.create_team_calendar({
            "name": "Team",
            "color": "#ff0000",
            "description": "desc",
            "timezone": "Europe/Berlin",
        })

        interface.module.create_team_calendar.assert_called_once_with(
            interface.user,
            name="Team",
            color="#ff0000",
            description="desc",
            timezone="Europe/Berlin",
        )

    def test_error_returns_error_response(self, interface):
        interface.module.create_team_calendar.side_effect = RequestException(
            "boom", error=type("E", (), {"c": "E003", "m": "Failed", "h": 400})()
        )

        body, status = interface.create_team_calendar({"name": "Team"})

        assert body["data"] is None
        assert body["error_code"] == "E003"


class TestUpdateTeamCalendar:
    def test_updates_calendar(self, interface):
        cal = MagicMock()
        interface.module.update_team_calendar.return_value = cal
        interface._calendar_serializer.serialize.return_value = {"id": "cal1"}

        body, status = interface.update_team_calendar("team1", {"name": "New"})

        interface.module.update_team_calendar.assert_called_once_with(
            interface.user, "team1", {"name": "New"}
        )
        assert body["data"] == {"id": "cal1"}

    def test_error_returns_error_response(self, interface):
        interface.module.update_team_calendar.side_effect = RequestException(
            "boom", error=type("E", (), {"c": "E004", "m": "Failed", "h": 400})()
        )

        body, status = interface.update_team_calendar("team1", {"name": "New"})

        assert body["data"] is None
        assert body["error_code"] == "E004"


class TestDeleteTeamCalendar:
    def test_deletes_calendar(self, interface):
        body, status = interface.delete_team_calendar("team1")

        interface.module.delete_team_calendar.assert_called_once_with(interface.user, "team1")
        assert body["data"] is None

    def test_error_returns_error_response(self, interface):
        interface.module.delete_team_calendar.side_effect = RequestException(
            "boom", error=type("E", (), {"c": "E005", "m": "Failed", "h": 400})()
        )

        body, status = interface.delete_team_calendar("team1")

        assert body["data"] is None
        assert body["error_code"] == "E005"


class TestListMembers:
    def test_returns_serialized_members(self, interface):
        interface.module.list_members.return_value = [
            FakeShare(user_uid="m1", level_name="view_all", can_create=True, can_delete=False),
            FakeShare(user_uid="m2", level_name="edit", can_create=True, can_delete=True),
        ]

        body, status = interface.list_members("team1")

        assert body["data"]["total_count"] == 2
        first = body["data"]["members"][0]
        assert first["user_uid"] == "m1"
        assert first["share_level"] == "view_all"
        assert first["can_create"] is True
        assert first["can_delete"] is False

    def test_error_returns_error_response(self, interface):
        interface.module.list_members.side_effect = RequestException(
            "boom", error=type("E", (), {"c": "E006", "m": "Failed", "h": 400})()
        )

        body, status = interface.list_members("team1")

        assert body["data"] is None
        assert body["error_code"] == "E006"


class TestAddMember:
    def test_adds_member_with_default_level(self, interface):
        interface.module.add_member.return_value = FakeShare(user_uid="m1")

        body, status = interface.add_member("team1", {"user_uid": "m1"})

        assert status == 201
        interface.module.add_member.assert_called_once_with(
            interface.user, "team1", "m1", share_level="view_all"
        )
        assert body["data"]["user_uid"] == "m1"

    def test_adds_member_with_custom_level(self, interface):
        interface.module.add_member.return_value = FakeShare(user_uid="m1")

        body, status = interface.add_member("team1", {"user_uid": "m1", "share_level": "edit"})

        interface.module.add_member.assert_called_once_with(
            interface.user, "team1", "m1", share_level="edit"
        )

    def test_error_returns_error_response(self, interface):
        interface.module.add_member.side_effect = RequestException(
            "boom", error=type("E", (), {"c": "E007", "m": "Failed", "h": 400})()
        )

        body, status = interface.add_member("team1", {"user_uid": "m1"})

        assert body["data"] is None
        assert body["error_code"] == "E007"


class TestUpdateMember:
    def test_updates_member(self, interface):
        interface.module.update_member.return_value = FakeShare(user_uid="m1", level_name="edit")

        body, status = interface.update_member("team1", "m1", {"share_level": "edit"})

        interface.module.update_member.assert_called_once_with(
            interface.user, "team1", "m1", "edit"
        )
        assert body["data"]["share_level"] == "edit"

    def test_error_returns_error_response(self, interface):
        interface.module.update_member.side_effect = RequestException(
            "boom", error=type("E", (), {"c": "E008", "m": "Failed", "h": 400})()
        )

        body, status = interface.update_member("team1", "m1", {"share_level": "edit"})

        assert body["data"] is None
        assert body["error_code"] == "E008"


class TestRemoveMember:
    def test_removes_member(self, interface):
        body, status = interface.remove_member("team1", "m1")

        interface.module.remove_member.assert_called_once_with(interface.user, "team1", "m1")
        assert body["data"] is None

    def test_error_returns_error_response(self, interface):
        interface.module.remove_member.side_effect = RequestException(
            "boom", error=type("E", (), {"c": "E009", "m": "Failed", "h": 400})()
        )

        body, status = interface.remove_member("team1", "m1")

        assert body["data"] is None
        assert body["error_code"] == "E009"


class TestInviteUser:
    def test_invites_user_with_default_level(self, interface):
        interface.module.invite_user.return_value = FakeInvite(invite_id="inv1")

        body, status = interface.invite_user("team1", {"user_uid": "m1"})

        assert status == 201
        interface.module.invite_user.assert_called_once_with(
            interface.user, "team1", "m1", share_level="view_all"
        )
        assert body["data"]["id"] == "inv1"

    def test_error_returns_error_response(self, interface):
        interface.module.invite_user.side_effect = RequestException(
            "boom", error=type("E", (), {"c": "E010", "m": "Failed", "h": 400})()
        )

        body, status = interface.invite_user("team1", {"user_uid": "m1"})

        assert body["data"] is None
        assert body["error_code"] == "E010"


class TestListInvites:
    def test_returns_serialized_invites(self, interface):
        interface.module.list_invites.return_value = [
            FakeInvite(invite_id="i1", status="pending"),
            FakeInvite(invite_id="i2", status="accepted"),
        ]

        body, status = interface.list_invites()

        assert body["data"]["total_count"] == 2
        assert body["data"]["invites"][0]["id"] == "i1"
        assert body["data"]["invites"][0]["status"] == "pending"
        assert body["data"]["invites"][1]["status"] == "accepted"

    def test_error_returns_error_response(self, interface):
        interface.module.list_invites.side_effect = RequestException(
            "boom", error=type("E", (), {"c": "E011", "m": "Failed", "h": 400})()
        )

        body, status = interface.list_invites()

        assert body["data"] is None
        assert body["error_code"] == "E011"


class TestGetInvite:
    def test_gets_invite(self, interface):
        interface.module.get_invite.return_value = FakeInvite(invite_id="i1")

        body, status = interface.get_invite("i1")

        interface.module.get_invite.assert_called_once_with(interface.user, "i1")
        assert body["data"]["id"] == "i1"

    def test_error_returns_error_response(self, interface):
        interface.module.get_invite.side_effect = RequestException(
            "boom", error=type("E", (), {"c": "E012", "m": "Failed", "h": 400})()
        )

        body, status = interface.get_invite("i1")

        assert body["data"] is None
        assert body["error_code"] == "E012"


class TestAcceptInvite:
    def test_accepts_invite(self, interface):
        interface.module.accept_invite.return_value = FakeShare(user_uid="m1")
        interface._share_serializer.serialize.return_value = {"user_uid": "m1"}

        body, status = interface.accept_invite("inv1")

        interface.module.accept_invite.assert_called_once_with(interface.user, "inv1")
        assert body["data"]["user_uid"] == "m1"

    def test_error_returns_error_response(self, interface):
        interface.module.accept_invite.side_effect = RequestException(
            "boom", error=type("E", (), {"c": "E013", "m": "Failed", "h": 400})()
        )

        body, status = interface.accept_invite("inv1")

        assert body["data"] is None
        assert body["error_code"] == "E013"


class TestRejectInvite:
    def test_rejects_invite(self, interface):
        interface.module.reject_invite.return_value = FakeInvite(invite_id="i1", status="rejected")

        body, status = interface.reject_invite("inv1")

        interface.module.reject_invite.assert_called_once_with(interface.user, "inv1")
        assert body["data"]["status"] == "rejected"

    def test_error_returns_error_response(self, interface):
        interface.module.reject_invite.side_effect = RequestException(
            "boom", error=type("E", (), {"c": "E014", "m": "Failed", "h": 400})()
        )

        body, status = interface.reject_invite("inv1")

        assert body["data"] is None
        assert body["error_code"] == "E014"


class TestCancelInvite:
    def test_cancels_invite(self, interface):
        interface.module.cancel_invite.return_value = FakeInvite(invite_id="i1", status="cancelled")

        body, status = interface.cancel_invite("inv1")

        interface.module.cancel_invite.assert_called_once_with(interface.user, "inv1")
        assert body["data"]["status"] == "cancelled"

    def test_error_returns_error_response(self, interface):
        interface.module.cancel_invite.side_effect = RequestException(
            "boom", error=type("E", (), {"c": "E015", "m": "Failed", "h": 400})()
        )

        body, status = interface.cancel_invite("inv1")

        assert body["data"] is None
        assert body["error_code"] == "E015"


class TestSerializeMember:
    def test_serializes_member(self, interface):
        share = FakeShare(user_uid="m1", level_name="view_all", can_create=True, can_delete=False)

        result = interface._serialize_member(share)

        assert result == {
            "user_uid": "m1",
            "share_level": "view_all",
            "can_create": True,
            "can_delete": False,
        }


class TestSerializeInvite:
    def test_serializes_invite(self, interface):
        invite = FakeInvite(
            invite_id="inv1",
            calendar_key="cal1",
            user_uid="u1",
            invited_by="u2",
            status="pending",
            share_level="view_all",
            created_at="2026-01-01",
        )

        result = interface._serialize_invite(invite)

        assert result == {
            "id": "inv1",
            "calendar_key": "cal1",
            "user_uid": "u1",
            "invited_by": "u2",
            "status": "pending",
            "share_level": "view_all",
            "created_at": "2026-01-01",
        }
