"""Unit tests for the unified Share / ACL engine (app.factory.share)."""

import pytest
from unittest.mock import MagicMock, patch

from app.factory.share import (
    AclEntry,
    CALENDAR_LEVEL_TO_STR,
    CALENDAR_RESOURCE_TYPE,
    CALENDAR_STR_TO_LEVEL,
    CONTACT_RESOURCE_TYPE,
    FOLDER_RESOURCE_TYPE,
    RepositoryAcl,
    RIGHT_CREATE,
    RIGHT_EDIT,
    RIGHT_ERASE,
    RIGHT_VIEW,
    ShareCalendar,
    ShareContact,
)
from app.factory.share.share import Share
from app.module.calendar.model.enums.CalendarPermissionAction import CalendarPermissionAction
from app.module.calendar.model.enums.CalendarShareLevel import CalendarShareLevel
from app.module.calendar.model.enums.EventVisibility import EventVisibility
from app.utils import errors as err
from app.utils.exceptions import RequestException


# ---- AclEntry ---------------------------------------------------------------


class TestAclEntry:
    def test_basic_creation(self):
        entry = AclEntry(
            resource_type=CALENDAR_RESOURCE_TYPE,
            key="cal-123",
            owner="alice",
            to_user="bob",
            rights={"public": "view-all"},
        )
        assert entry.resource_type == CALENDAR_RESOURCE_TYPE
        assert entry.key == "cal-123"
        assert entry.owner == "alice"
        assert entry.to_user == "bob"
        assert entry.rights == {"public": "view-all"}


# ---- RepositoryAcl ----------------------------------------------------------


class TestRepositoryAcl:
    def test_find_all_for_key_empty(self):
        db = MagicMock()
        db.select_from_table.return_value = []
        repo = RepositoryAcl(db)
        result = repo.find_all_for_key(CALENDAR_RESOURCE_TYPE, "cal-123")
        assert result == []
        db.select_from_table.assert_called_once()

    def test_find_one_found(self):
        db = MagicMock()
        # Simulate a single row returned from DB
        db.select_from_table.return_value = [
            (1, CALENDAR_RESOURCE_TYPE, "cal-123", "alice", "bob", {"public": "view-all"})
        ]
        repo = RepositoryAcl(db)
        result = repo.find_one(CALENDAR_RESOURCE_TYPE, "cal-123", "bob")
        assert result is not None
        assert result.resource_type == CALENDAR_RESOURCE_TYPE
        assert result.key == "cal-123"
        assert result.to_user == "bob"
        assert result.rights == {"public": "view-all"}

    def test_find_one_not_found(self):
        db = MagicMock()
        db.select_from_table.return_value = []
        repo = RepositoryAcl(db)
        result = repo.find_one(CALENDAR_RESOURCE_TYPE, "cal-123", "bob")
        assert result is None

    def test_find_all_for_to_user(self):
        db = MagicMock()
        db.select_from_table.return_value = [
            (1, CALENDAR_RESOURCE_TYPE, "cal-1", "alice", "charlie", {"public": "view-all"}),
            (2, CALENDAR_RESOURCE_TYPE, "cal-2", "alice", "charlie", {"public": "respond-to"}),
        ]
        repo = RepositoryAcl(db)
        result = repo.find_all_for_to_user(CALENDAR_RESOURCE_TYPE, "charlie")
        assert len(result) == 2
        keys = {e.key for e in result}
        assert keys == {"cal-1", "cal-2"}

    def test_upsert_insert_new(self):
        db = MagicMock()
        db.select_from_table.return_value = []  # No existing entry
        db.insert_in_table.return_value = None
        db.update_in_table.return_value = 0
        repo = RepositoryAcl(db)
        entry = AclEntry(
            resource_type=CALENDAR_RESOURCE_TYPE,
            key="cal-123",
            owner="alice",
            to_user="bob",
            rights={"public": "view-all"},
        )
        repo.upsert(entry)
        db.insert_in_table.assert_called_once()
        db.update_in_table.assert_not_called()

    def test_upsert_update_existing(self):
        db = MagicMock()
        db.select_from_table.return_value = [
            (1, CALENDAR_RESOURCE_TYPE, "cal-123", "alice", "bob", {"public": "none"})
        ]
        db.update_in_table.return_value = 1
        repo = RepositoryAcl(db)
        entry = AclEntry(
            resource_type=CALENDAR_RESOURCE_TYPE,
            key="cal-123",
            owner="alice",
            to_user="bob",
            rights={"public": "view-all"},
        )
        repo.upsert(entry)
        db.insert_in_table.assert_not_called()
        db.update_in_table.assert_called_once()

    def test_delete_existing(self):
        db = MagicMock()
        db.delete_row_in_table.return_value = 1
        repo = RepositoryAcl(db)
        count = repo.delete(CALENDAR_RESOURCE_TYPE, "cal-123", "bob")
        assert count == 1

    def test_delete_all_for_key(self):
        db = MagicMock()
        db.delete_row_in_table.return_value = None
        repo = RepositoryAcl(db)
        repo.delete_all_for_key(CALENDAR_RESOURCE_TYPE, "cal-123")
        db.delete_row_in_table.assert_called_once()


# ---- Share (ABC) ------------------------------------------------------------


class TestShareAbstractBase:
    def test_resource_type_not_set(self):
        # Share is abstract, but we can check the attribute exists on subclasses
        with pytest.raises(TypeError):
            Share(db=MagicMock())  # Can't instantiate abstract class


# ---- ShareCalendar ----------------------------------------------------------


class TestShareCalendar:
    def test_resource_type(self):
        assert ShareCalendar.resource_type == "calendar"

    def test_level_for_visibility(self):
        rights = {
            "public": "view-all",
            "confidential": "respond-to",
            "private": "none",
        }
        assert ShareCalendar.level_for_visibility(rights, EventVisibility.PUBLIC) == CalendarShareLevel.VIEW_ALL
        assert ShareCalendar.level_for_visibility(rights, EventVisibility.CONFIDENTIAL) == CalendarShareLevel.RESPOND
        assert ShareCalendar.level_for_visibility(rights, EventVisibility.PRIVATE) == CalendarShareLevel.NONE
        # Missing key falls back to "none"
        assert ShareCalendar.level_for_visibility({}, EventVisibility.PUBLIC) == CalendarShareLevel.NONE

    def test_to_calendar_permissions(self):
        rights = {
            "public": "view-all",
            "confidential": "respond-to",
            "private": "none",
            "can_create_objects": True,
            "can_erase_objects": False,
        }
        perms = ShareCalendar.to_calendar_permissions(rights)
        assert perms.public_level == CalendarShareLevel.VIEW_ALL
        assert perms.confidential_level == CalendarShareLevel.RESPOND
        assert perms.private_level == CalendarShareLevel.NONE
        assert perms.can_create is True
        assert perms.can_delete is False

    def test_rights_satisfy_create(self):
        rights = {"can_create_objects": True, "can_erase_objects": False}
        calendar = ShareCalendar(db=MagicMock())
        assert calendar._rights_satisfy(rights, CalendarPermissionAction.CREATE) is True
        assert calendar._rights_satisfy(rights, CalendarPermissionAction.DELETE) is False

    def test_rights_satisfy_view(self):
        rights = {
            "public": "view-all",
            "confidential": "view-date-time",
            "private": "none",
        }
        calendar = ShareCalendar(db=MagicMock())
        # VIEW on PUBLIC requires >= VIEW_DATETIME
        assert calendar._rights_satisfy(rights, CalendarPermissionAction.VIEW) is True
        assert calendar._rights_satisfy(
            rights, (CalendarPermissionAction.VIEW, EventVisibility.PUBLIC)
        ) is True
        assert calendar._rights_satisfy(
            rights, (CalendarPermissionAction.VIEW, EventVisibility.CONFIDENTIAL)
        ) is True
        assert calendar._rights_satisfy(
            rights, (CalendarPermissionAction.VIEW, EventVisibility.PRIVATE)
        ) is False

    def test_rights_satisfy_modify(self):
        rights = {"public": "modify", "confidential": "modify", "private": "modify"}
        calendar = ShareCalendar(db=MagicMock())
        assert calendar._rights_satisfy(rights, CalendarPermissionAction.MODIFY) is True
        assert calendar._rights_satisfy(
            rights, (CalendarPermissionAction.MODIFY, EventVisibility.PRIVATE)
        ) is True

    def test_rights_satisfy_respond(self):
        rights = {"public": "respond-to", "confidential": "none", "private": "none"}
        calendar = ShareCalendar(db=MagicMock())
        assert calendar._rights_satisfy(rights, CalendarPermissionAction.RESPOND) is True
        assert calendar._rights_satisfy(rights, CalendarPermissionAction.MODIFY) is False


# ---- ShareContact -----------------------------------------------------------


class TestShareContact:
    def test_resource_type(self):
        assert ShareContact.resource_type == "addressbook"

    def test_rights_satisfy(self):
        ab = ShareContact(db=MagicMock())
        rights = {RIGHT_VIEW: True, RIGHT_EDIT: False}
        assert ab._rights_satisfy(rights, RIGHT_VIEW) is True
        assert ab._rights_satisfy(rights, RIGHT_EDIT) is False
        assert ab._rights_satisfy(rights, "nonexistent") is False


# ---- Share add_permissions / update_permissions errors ------------------------


class TestSharePermissionErrors:
    @pytest.fixture
    def share_calendar(self):
        return ShareCalendar(db=MagicMock())

    def test_cannot_share_with_self(self, share_calendar):
        with pytest.raises(RequestException) as exc_info:
            share_calendar.add_permissions(
                for_user="alice", on_key="cal-123", owner="alice", rights={}
            )
        assert exc_info.value.error == err.ERROR_SHARE_CANNOT_SHARE_WITH_SELF

    def test_update_nonexistent_entry(self, share_calendar):
        with pytest.raises(RequestException) as exc_info:
            share_calendar.update_permissions(
                for_user="bob", on_key="cal-123", rights={}
            )
        assert exc_info.value.error == err.ERROR_SHARE_NOT_FOUND


# ---- Round-trip: level strings <-> CalendarShareLevel -------------------------


class TestLevelStringMappings:
    def test_level_to_str(self):
        assert LEVEL_TO_STR[CalendarShareLevel.NONE] == "none"
        assert LEVEL_TO_STR[CalendarShareLevel.VIEW_DATETIME] == "view-date-time"
        assert LEVEL_TO_STR[CalendarShareLevel.VIEW_ALL] == "view-all"
        assert LEVEL_TO_STR[CalendarShareLevel.RESPOND] == "respond-to"
        assert LEVEL_TO_STR[CalendarShareLevel.MODIFY] == "modify"

    def test_str_to_level(self):
        assert STR_TO_LEVEL["none"] == CalendarShareLevel.NONE
        assert STR_TO_LEVEL["view-date-time"] == CalendarShareLevel.VIEW_DATETIME
        assert STR_TO_LEVEL["view-all"] == CalendarShareLevel.VIEW_ALL
        assert STR_TO_LEVEL["respond-to"] == CalendarShareLevel.RESPOND
        assert STR_TO_LEVEL["modify"] == CalendarShareLevel.MODIFY

    def test_round_trip(self):
        for level in CalendarShareLevel:
            assert STR_TO_LEVEL[LEVEL_TO_STR[level]] == level
