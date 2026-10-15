"""Unit tests for the wired calendar ACL path (CalendarAclEngine <-> sogo6_acl).

Covers the migration wiring with a mocked ClientSQL (no live DB required),
following the pattern of tests/unit/test_factory/test_share.py:

- unified path: a sogo6_acl entry (type='calendar') is resolved by a real
  ShareCalendar backed by a mocked ClientSQL, and bridged into the expected
  CalendarPermissions via ShareCalendar.to_calendar_permissions();
- legacy fallback: an empty sogo6_acl (ShareCalendar.get_entry -> None) falls
  back to a mocked legacy RepositoryCalendarShare and yields the legacy
  permissions; when both sources are empty the engine denies.
"""

from unittest.mock import MagicMock

import pytest

from app.auth.User import User
from app.config.db import tables as tbl
from app.factory.share import CALENDAR_RESOURCE_TYPE, ShareCalendar
from app.module.calendar.acl.CalendarAclEngine import CalendarAclEngine
from app.module.calendar.model.CalCalendar import CalCalendar
from app.module.calendar.model.CalendarPermissions import CalendarPermissions
from app.module.calendar.model.CalendarShare import CalendarShare
from app.module.calendar.model.CalendarUser import CalendarUser
from app.module.calendar.model.enums.CalendarPermissionAction import CalendarPermissionAction
from app.module.calendar.model.enums.CalendarShareLevel import CalendarShareLevel
from app.module.calendar.model.enums.CalendarSourceType import CalendarSourceType
from app.module.calendar.repository.RepositoryCalendarShare import RepositoryCalendarShare
from app.utils import errors as err
from app.utils.exceptions import RequestException

OWNER_UID = "alice@example.org"
ACTING_UID = "bob@example.org"
CALENDAR_KEY = "cal-123"

# API-shaped rights blob as stored in sogo6_acl.rights (CalendarShareRightsSchema).
ACL_RIGHTS = {
    "public": "view-all",
    "confidential": "respond-to",
    "private": "none",
    "can_create_objects": True,
    "can_erase_objects": False,
}


def _acl_db(rows):
    """Mocked ClientSQL whose select_from_table returns the given sogo6_acl rows."""
    db = MagicMock()
    db.select_from_table.return_value = rows
    return db


def _acl_row(rights):
    """One sogo6_acl row in ALL_ACL_COL order: (id, type, key, owner, to_user, rights)."""
    return (1, CALENDAR_RESOURCE_TYPE, CALENDAR_KEY, OWNER_UID, ACTING_UID, rights)


def _share_calendar(rows):
    return ShareCalendar(db=_acl_db(rows))


def _legacy_repo(share=None):
    repo = MagicMock(spec=RepositoryCalendarShare)
    repo.find_by_calendar_and_user.return_value = share
    return repo


def _calendar():
    return CalCalendar(
        user_uid=OWNER_UID,
        name="Alice Calendar",
        key=CALENDAR_KEY,
        source_type=CalendarSourceType.LOCAL,
    )


def _calendar_user():
    user: User = User(uid=ACTING_UID)
    owner: User = User(uid=OWNER_UID)
    return CalendarUser(user=user, owner=owner)


def _assert_acl_queried(engine_db):
    """Assert every select went to sogo6_acl (the unified table), not the legacy one."""
    assert engine_db.select_from_table.call_args_list
    for call in engine_db.select_from_table.call_args_list:
        assert call.kwargs.get("table") is tbl.TABLE_ACL


class TestCalendarUnifiedPath:
    """Non-owner resolution through a ShareCalendar-backed sogo6_acl entry."""

    def test_sogo6_acl_entry_bridges_to_expected_calendar_permissions(self):
        # A ShareCalendar-backed sogo6_acl entry must yield exactly the
        # CalendarPermissions produced by ShareCalendar.to_calendar_permissions().
        share_calendar = _share_calendar([_acl_row(ACL_RIGHTS)])
        engine = CalendarAclEngine(
            share_repo=_legacy_repo(), share_calendar=share_calendar,
        )

        permissions = engine.get_permissions(_calendar(), _calendar_user())

        assert permissions == ShareCalendar.to_calendar_permissions(ACL_RIGHTS)
        # Explicit bridging assertions (level strings -> CalendarShareLevel enums).
        assert permissions.public_level is CalendarShareLevel.VIEW_ALL
        assert permissions.confidential_level is CalendarShareLevel.RESPOND
        assert permissions.private_level is CalendarShareLevel.NONE
        assert permissions.can_create is True
        assert permissions.can_delete is False

    def test_unified_path_skips_legacy_repository(self):
        # When sogo6_acl holds the entry, the legacy RepositoryCalendarShare
        # must not be consulted at all.
        legacy_repo = _legacy_repo()
        share_calendar = _share_calendar([_acl_row(ACL_RIGHTS)])
        engine = CalendarAclEngine(share_repo=legacy_repo, share_calendar=share_calendar)

        engine.get_permissions(_calendar(), _calendar_user())

        legacy_repo.find_by_calendar_and_user.assert_not_called()
        _assert_acl_queried(share_calendar._repo._db)

    def test_unified_path_permissions_drive_check_permission(self):
        # The bridged permissions flow into the engine's action checks.
        engine = CalendarAclEngine(share_calendar=_share_calendar([_acl_row(ACL_RIGHTS)]))
        permissions = engine.get_permissions(_calendar(), _calendar_user())

        engine.check_permission(permissions, CalendarPermissionAction.VIEW)
        engine.check_permission(permissions, CalendarPermissionAction.CREATE)
        with pytest.raises(RequestException) as exc_info:
            engine.check_permission(permissions, CalendarPermissionAction.DELETE)
        assert exc_info.value.error == err.ERROR_CALENDAR_ACCESS_DENIED


class TestCalendarLegacyFallback:
    """Empty sogo6_acl (get_entry -> None) falls back to the legacy repository."""

    def test_empty_acl_falls_back_to_legacy_share(self):
        # No sogo6_acl row -> ShareCalendar.get_entry returns None -> the engine
        # falls back to the mocked legacy RepositoryCalendarShare.
        legacy_share = CalendarShare(
            user_uid=ACTING_UID,
            calendar_key=CALENDAR_KEY,
            public_level=CalendarShareLevel.VIEW_DATETIME,
            confidential_level=CalendarShareLevel.NONE,
            private_level=CalendarShareLevel.NONE,
            can_create=False,
            can_delete=True,
        )
        legacy_repo = _legacy_repo(share=legacy_share)
        share_calendar = _share_calendar([])  # empty sogo6_acl
        engine = CalendarAclEngine(share_repo=legacy_repo, share_calendar=share_calendar)

        permissions = engine.get_permissions(_calendar(), _calendar_user())

        assert permissions == CalendarPermissions(
            public_level=CalendarShareLevel.VIEW_DATETIME,
            confidential_level=CalendarShareLevel.NONE,
            private_level=CalendarShareLevel.NONE,
            can_create=False,
            can_delete=True,
        )
        # The unified table was consulted first, then the legacy repo with
        # (calendar_key, acting user uid).
        _assert_acl_queried(share_calendar._repo._db)
        legacy_repo.find_by_calendar_and_user.assert_called_once_with(
            CALENDAR_KEY, ACTING_UID,
        )

    def test_fallback_permissions_drive_check_permission(self):
        legacy_share = CalendarShare(
            user_uid=ACTING_UID,
            calendar_key=CALENDAR_KEY,
            public_level=CalendarShareLevel.MODIFY,
            confidential_level=CalendarShareLevel.MODIFY,
            private_level=CalendarShareLevel.MODIFY,
            can_create=True,
            can_delete=True,
        )
        engine = CalendarAclEngine(
            share_repo=_legacy_repo(share=legacy_share),
            share_calendar=_share_calendar([]),
        )
        permissions = engine.get_permissions(_calendar(), _calendar_user())

        engine.check_permission(permissions, CalendarPermissionAction.MODIFY)
        engine.check_permission(permissions, CalendarPermissionAction.DELETE)

    def test_no_share_calendar_injected_uses_legacy_directly(self):
        # Engines not yet wired with a ShareCalendar keep the legacy-only path.
        legacy_share = CalendarShare(
            user_uid=ACTING_UID,
            calendar_key=CALENDAR_KEY,
            public_level=CalendarShareLevel.VIEW_ALL,
            confidential_level=CalendarShareLevel.NONE,
            private_level=CalendarShareLevel.NONE,
            can_create=False,
            can_delete=False,
        )
        engine = CalendarAclEngine(share_repo=_legacy_repo(share=legacy_share))

        permissions = engine.get_permissions(_calendar(), _calendar_user())

        assert permissions.public_level is CalendarShareLevel.VIEW_ALL

    def test_denied_when_acl_and_legacy_both_empty(self):
        engine = CalendarAclEngine(
            share_repo=_legacy_repo(share=None),
            share_calendar=_share_calendar([]),
        )

        permissions = engine.get_permissions(_calendar(), _calendar_user())

        assert permissions == CalendarPermissions.denied()
        with pytest.raises(RequestException) as exc_info:
            engine.check_permission(permissions, CalendarPermissionAction.VIEW)
        assert exc_info.value.error == err.ERROR_CALENDAR_ACCESS_DENIED
