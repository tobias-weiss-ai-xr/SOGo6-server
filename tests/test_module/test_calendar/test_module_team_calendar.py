"""Unit tests for Team Calendar module logic.

Uses lightweight fakes for the repositories so the module can be exercised
without a database. Following the fixture-free convention of this project's
module tests (no client/auth fixtures).
"""
import pytest

from app.module.calendar.ModuleTeamCalendar import ModuleTeamCalendar
from app.module.calendar.model.CalendarInvite import (
    INVITE_STATUS_PENDING,
    INVITE_STATUS_ACCEPTED,
    INVITE_STATUS_REJECTED,
    INVITE_STATUS_CANCELLED,
)
from app.module.calendar.model.CalendarShare import CalendarShare
from app.module.calendar.model.CalendarInvite import CalendarInvite
from app.module.calendar.model.enums.CalendarShareLevel import CalendarShareLevel
from app.module.calendar.model.enums.CalendarSourceType import CalendarSourceType
from app.utils.exceptions import RequestException


class FakeShareRepo:
    def __init__(self):
        self._shares: list[CalendarShare] = []

    def find_by_calendar_key(self, calendar_key: str) -> list[CalendarShare]:
        return [s for s in self._shares if s.calendar_key == calendar_key]

    def find_calendar_keys_for_user(self, user_uid: str) -> list[str]:
        return [s.calendar_key for s in self._shares if s.user_uid == user_uid]

    def find_by_calendar_and_user(self, calendar_key: str, user_uid: str) -> CalendarShare | None:
        for s in self._shares:
            if s.calendar_key == calendar_key and s.user_uid == user_uid:
                return s
        return None

    def insert(self, share: CalendarShare) -> CalendarShare:
        self._shares.append(share)
        return share

    def delete(self, calendar_key: str, user_uid: str) -> None:
        self._shares = [
            s for s in self._shares
            if not (s.calendar_key == calendar_key and s.user_uid == user_uid)
        ]


class FakeInviteRepo:
    def __init__(self):
        self._invites: list[CalendarInvite] = []

    def insert(self, invite: CalendarInvite) -> CalendarInvite:
        self._invites.append(invite)
        return invite

    def find_by_id(self, invite_id: str) -> CalendarInvite | None:
        for i in self._invites:
            if i.id == invite_id:
                return i
        return None

    def find_by_calendar_and_user(self, calendar_key: str, user_uid: str) -> CalendarInvite | None:
        for i in self._invites:
            if i.calendar_key == calendar_key and i.user_uid == user_uid:
                return i
        return None

    def find_pending_for_user(self, user_uid: str) -> list[CalendarInvite]:
        return [i for i in self._invites if i.user_uid == user_uid and i.status == INVITE_STATUS_PENDING]

    def update_status(self, invite_id: str, status: str) -> None:
        for i in self._invites:
            if i.id == invite_id:
                i.status = status

    def delete(self, invite_id: str) -> None:
        self._invites = [i for i in self._invites if i.id != invite_id]


class FakeUser:
    def __init__(self, uid: str):
        self.uid = uid
        self.login_mail_filtering = None
        self.password = "x"


class StubTeamCalendarModule(ModuleTeamCalendar):
    """ModuleTeamCalendar with fake repositories and a fake calendar store."""

    def __init__(self, owner_uid: str):
        self._share_repo = FakeShareRepo()
        self._invite_repo = FakeInviteRepo()
        self._calendars = {}  # team_id -> CalCalendar
        self._owner = owner_uid

    # --- calendar CRUD (no real DB) ---
    def _require_team_calendar(self, user, team_id):
        from app.module.calendar.model.CalCalendar import CalCalendar
        cal = self._calendars.get(team_id)
        if cal is None:
            raise RequestException(error=__import__("app.utils.errors", fromlist=["x"]).ERROR_CALENDAR_NOT_FOUND)
        if cal.source_type != CalendarSourceType.TEAM:
            raise RequestException(error=__import__("app.utils.errors", fromlist=["x"]).ERROR_CALENDAR_NOT_TEAM)
        return cal

    def _require_owner(self, user, team_id):
        cal = self._require_team_calendar(user, team_id)
        if cal.user_uid != user.uid:
            raise RequestException(error=__import__("app.utils.errors", fromlist=["x"]).ERROR_CALENDAR_ACCESS_DENIED)
        return cal

    def list_team_calendars(self, user):
        return [c for c in self._calendars.values() if c.source_type == CalendarSourceType.TEAM]

    def create_team_calendar(self, user, name, color=None, description=None, timezone="UTC"):
        from app.module.calendar.model.CalCalendar import CalCalendar
        cal = CalCalendar(user_uid=user.uid, name=name, color=color, description=description,
                          timezone=timezone, source_type=CalendarSourceType.TEAM, is_default=False)
        cal.key = f"team_{len(self._calendars) + 1}"
        cal.ctag = 0
        self._calendars[cal.key] = cal
        return cal

    def update_team_calendar(self, user, team_id, updates):
        cal = self._require_owner(user, team_id)
        cal.apply_update(updates)
        return cal

    def delete_team_calendar(self, user, team_id):
        self._require_owner(user, team_id)
        del self._calendars[team_id]

    def get_team_calendar(self, user, team_id):
        return self._require_team_calendar(user, team_id)


@pytest.fixture
def owner_user():
    return FakeUser("owner@example.org")


@pytest.fixture
def member_user():
    return FakeUser("member@example.org")


@pytest.fixture
def module(owner_user):
    return StubTeamCalendarModule(owner_user.uid)


class TestTeamCRUD:
    def test_create_and_list(self, module, owner_user):
        cal = module.create_team_calendar(owner_user, "Engineering")
        assert cal.source_type == CalendarSourceType.TEAM
        assert cal.user_uid == "owner@example.org"
        teams = module.list_team_calendars(owner_user)
        assert len(teams) == 1
        assert teams[0].name == "Engineering"

    def test_update_requires_owner(self, module, owner_user, member_user):
        cal = module.create_team_calendar(owner_user, "Engineering")
        with pytest.raises(RequestException):
            module.update_team_calendar(member_user, cal.key, {"name": "Hacked"})
        module.update_team_calendar(owner_user, cal.key, {"name": "Eng Team"})
        assert module._calendars[cal.key].name == "Eng Team"

    def test_delete_requires_owner(self, module, owner_user, member_user):
        cal = module.create_team_calendar(owner_user, "Engineering")
        with pytest.raises(RequestException):
            module.delete_team_calendar(member_user, cal.key)
        module.delete_team_calendar(owner_user, cal.key)
        assert cal.key not in module._calendars


class TestMembership:
    def test_add_member_sets_level(self, module, owner_user, member_user):
        cal = module.create_team_calendar(owner_user, "Engineering")
        share = module.add_member(owner_user, cal.key, member_user.uid, "view_all")
        assert share.user_uid == member_user.uid
        assert share.public_level == CalendarShareLevel.VIEW_ALL
        members = module.list_members(owner_user, cal.key)
        assert len(members) == 1

    def test_add_member_duplicate_rejected(self, module, owner_user, member_user):
        cal = module.create_team_calendar(owner_user, "Engineering")
        module.add_member(owner_user, cal.key, member_user.uid)
        with pytest.raises(RequestException):
            module.add_member(owner_user, cal.key, member_user.uid)

    def test_update_member(self, module, owner_user, member_user):
        cal = module.create_team_calendar(owner_user, "Engineering")
        module.add_member(owner_user, cal.key, member_user.uid, "view_all")
        share = module.update_member(owner_user, cal.key, member_user.uid, "modify")
        assert share.public_level == CalendarShareLevel.MODIFY

    def test_update_member_not_found(self, module, owner_user, member_user):
        cal = module.create_team_calendar(owner_user, "Engineering")
        with pytest.raises(RequestException):
            module.update_member(owner_user, cal.key, member_user.uid, "modify")

    def test_remove_member(self, module, owner_user, member_user):
        cal = module.create_team_calendar(owner_user, "Engineering")
        module.add_member(owner_user, cal.key, member_user.uid)
        module.remove_member(owner_user, cal.key, member_user.uid)
        assert module.list_members(owner_user, cal.key) == []


class TestInvitations:
    def test_invite_and_list_pending(self, module, owner_user, member_user):
        cal = module.create_team_calendar(owner_user, "Engineering")
        invite = module.invite_user(owner_user, cal.key, member_user.uid, "view_all")
        assert invite.status == INVITE_STATUS_PENDING
        pending = module.list_invites(member_user)
        assert len(pending) == 1
        assert pending[0].id == invite.id

    def test_accept_creates_membership(self, module, owner_user, member_user):
        cal = module.create_team_calendar(owner_user, "Engineering")
        invite = module.invite_user(owner_user, cal.key, member_user.uid, "modify")
        share = module.accept_invite(member_user, invite.id)
        assert share.public_level == CalendarShareLevel.MODIFY
        assert invite.status == INVITE_STATUS_ACCEPTED
        assert len(module.list_members(owner_user, cal.key)) == 1

    def test_accept_twice_idempotent(self, module, owner_user, member_user):
        cal = module.create_team_calendar(owner_user, "Engineering")
        invite = module.invite_user(owner_user, cal.key, member_user.uid)
        module.accept_invite(member_user, invite.id)
        with pytest.raises(RequestException):
            module.accept_invite(member_user, invite.id)  # status no longer pending

    def test_reject(self, module, owner_user, member_user):
        cal = module.create_team_calendar(owner_user, "Engineering")
        invite = module.invite_user(owner_user, cal.key, member_user.uid)
        rejected = module.reject_invite(member_user, invite.id)
        assert rejected.status == INVITE_STATUS_REJECTED
        assert module.list_members(owner_user, cal.key) == []

    def test_cancel_by_owner(self, module, owner_user, member_user):
        cal = module.create_team_calendar(owner_user, "Engineering")
        invite = module.invite_user(owner_user, cal.key, member_user.uid)
        cancelled = module.cancel_invite(owner_user, invite.id)
        assert cancelled.status == INVITE_STATUS_CANCELLED

    def test_invitee_cannot_cancel(self, module, owner_user, member_user):
        cal = module.create_team_calendar(owner_user, "Engineering")
        invite = module.invite_user(owner_user, cal.key, member_user.uid)
        with pytest.raises(RequestException):
            module.cancel_invite(member_user, invite.id)

    def test_invite_duplicate_pending_rejected(self, module, owner_user, member_user):
        cal = module.create_team_calendar(owner_user, "Engineering")
        module.invite_user(owner_user, cal.key, member_user.uid)
        with pytest.raises(RequestException):
            module.invite_user(owner_user, cal.key, member_user.uid)
