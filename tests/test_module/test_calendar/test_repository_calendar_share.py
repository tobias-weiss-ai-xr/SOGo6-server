# pylint: disable=invalid-sequence-index
"""Unit tests for RepositoryCalendarShare (49% -> high)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")


import pytest

from app.config.db import tables as tbl
from app.module.calendar.model.CalendarShare import CalendarShare
from app.module.calendar.model.enums.CalendarShareLevel import CalendarShareLevel
from app.module.calendar.repository.RepositoryCalendarShare import RepositoryCalendarShare
from app.utils import errors as err
from app.utils.exceptions import BugException, RequestException


def make_repo():
    db = mock.MagicMock()
    return db, RepositoryCalendarShare(db)


def make_share(**overrides):
    base = dict(
        user_uid="user1",
        calendar_key="cal-key-1",
        public_level=CalendarShareLevel.VIEW_ALL,
        confidential_level=CalendarShareLevel.VIEW_ALL,
        private_level=CalendarShareLevel.NONE,
        can_create=True,
        can_delete=False,
    )
    base.update(overrides)
    return CalendarShare(**base)


# Cal share row: id, calendar_key, user_uid, public_level, confidential_level,
# private_level, can_create, can_delete, created_at
def make_row_values(calendar_key="cal-key-1", user_uid="user1",
                    public_level="view_all", confidential_level="view_all",
                    private_level="none", can_create=True, can_delete=False, rid=1):
    return [rid, calendar_key, user_uid, public_level, confidential_level,
            private_level, can_create, can_delete, "2024-01-01T00:00:00+00:00"]


class TestRowToShare:
    def test_maps_row(self):
        share = RepositoryCalendarShare._row_to_share(make_row_values())
        assert share.user_uid == "user1"
        assert share.calendar_key == "cal-key-1"
        assert share.public_level == CalendarShareLevel.VIEW_ALL
        assert share.confidential_level == CalendarShareLevel.VIEW_ALL
        assert share.private_level == CalendarShareLevel.NONE
        assert share.can_create is True
        assert share.can_delete is False


class TestInsert:
    def test_insert_ok(self):
        db, repo = make_repo()
        db.insert_in_table.return_value = 1
        out = repo.insert(make_share())
        assert out is not None
        assert out.calendar_key == "cal-key-1"
        args, kwargs = db.insert_in_table.call_args
        assert kwargs["table_name"] == tbl.TABLE_CALENDAR_SHARE.name
        assert "id" not in kwargs["column_tuple"]
        assert kwargs["values_tuple"][0][0] == "cal-key-1"
        assert kwargs["values_tuple"][0][1] == "user1"
        assert kwargs["values_tuple"][0][2] == "view_all"

    def test_insert_unique_violation(self):
        db, repo = make_repo()
        db.insert_in_table.side_effect = BugException("dup")
        with pytest.raises(RequestException) as e:
            repo.insert(make_share())
        assert e.value.error.c == err.ERROR_CALENDAR_DUPLICATE.c

    def test_insert_wrong_row_count(self):
        db, repo = make_repo()
        db.insert_in_table.return_value = 0
        with pytest.raises(BugException):
            repo.insert(make_share())


class TestFind:
    def test_find_by_calendar_key(self):
        db, repo = make_repo()
        db.select_from_table.return_value = [make_row_values()]
        rows = repo.find_by_calendar_key("cal-key-1")
        assert len(rows) == 1
        assert rows[0].user_uid == "user1"
        args, kwargs = db.select_from_table.call_args
        assert kwargs["sort_by"] == tbl.COL_ID.name

    def test_find_calendar_keys_for_user(self):
        db, repo = make_repo()
        db.select_from_table.return_value = [("cal-key-a",), ("cal-key-b",)]
        keys = repo.find_calendar_keys_for_user("user1")
        assert keys == ["cal-key-a", "cal-key-b"]

    def test_find_by_calendar_and_user_found(self):
        db, repo = make_repo()
        db.select_from_table.return_value = [make_row_values()]
        share = repo.find_by_calendar_and_user("cal-key-1", "user1")
        assert share is not None and share.calendar_key == "cal-key-1"

    def test_find_by_calendar_and_user_missing(self):
        db, repo = make_repo()
        db.select_from_table.return_value = []
        assert repo.find_by_calendar_and_user("cal-key-1", "user1") is None
        # limit=1 used
        assert "limit" in db.select_from_table.call_args.kwargs


class TestDelete:
    def test_delete_ok(self):
        db, repo = make_repo()
        db.delete_row_in_table.return_value = 1
        repo.delete("cal-key-1", "user1")
        db.delete_row_in_table.assert_called_once()

    def test_delete_not_found(self):
        db, repo = make_repo()
        db.delete_row_in_table.return_value = 0
        with pytest.raises(RequestException) as e:
            repo.delete("cal-key-1", "user1")
        assert e.value.error.c == err.ERROR_CALENDAR_NOT_FOUND.c
