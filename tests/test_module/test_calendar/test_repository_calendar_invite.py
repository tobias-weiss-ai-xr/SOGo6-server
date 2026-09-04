# pylint: disable=invalid-sequence-index
"""Unit tests for RepositoryCalendarInvite (38% -> high)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")


import pytest

from app.config.db import tables as tbl
from app.module.calendar.model.CalendarInvite import CalendarInvite
from app.module.calendar.repository.RepositoryCalendarInvite import RepositoryCalendarInvite
from app.utils import errors as err
from app.utils.exceptions import RequestException


def make_repo():
    db = mock.MagicMock()
    return db, RepositoryCalendarInvite(db)


def make_invite(**overrides):
    base = dict(
        id="inv-1",
        calendar_key="cal-key-1",
        user_uid="user1",
        invited_by="owner",
        status="pending",
        share_level="view_all",
    )
    base.update(overrides)
    return CalendarInvite(**base)


# Invite row: id, calendar_key, user_uid, invited_by, status, share_level,
# created_at, updated_at
def make_row_values(invite_id="inv-1", calendar_key="cal-key-1", user_uid="user1",
                    invited_by="owner", share_level="view_all", status="pending"):
    return [invite_id, calendar_key, user_uid, invited_by, status, share_level,
            "2024-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"]


class TestRowToInvite:
    def test_maps_row(self):
        invite = RepositoryCalendarInvite._row_to_invite(make_row_values())
        assert invite.id == "inv-1"
        assert invite.calendar_key == "cal-key-1"
        assert invite.user_uid == "user1"
        assert invite.invited_by == "owner"
        assert invite.status == "pending"
        assert invite.share_level == "view_all"


class TestInsert:
    def test_insert_ok(self):
        db, repo = make_repo()
        db.insert_in_table.return_value = 1
        out = repo.insert(make_invite())
        assert out.id == "inv-1"
        args, kwargs = db.insert_in_table.call_args
        assert kwargs["table_name"] == tbl.TABLE_CALENDAR_INVITE.name
        # id IS included in invite inserts
        assert kwargs["values_tuple"][0][0] == "inv-1"

    def test_insert_exception_normalized(self):
        db, repo = make_repo()
        db.insert_in_table.side_effect = RuntimeError("db down")
        with pytest.raises(RequestException) as e:
            repo.insert(make_invite())
        assert e.value.error.c == err.ERROR_CALENDAR_INVITE_ALREADY_EXISTS.c

    def test_insert_not_one_row(self):
        db, repo = make_repo()
        db.insert_in_table.return_value = 0
        with pytest.raises(RequestException) as e:
            repo.insert(make_invite())
        assert e.value.error.c == err.ERROR_CALENDAR_INVITE_ALREADY_EXISTS.c


class TestFind:
    def test_find_by_id_found(self):
        db, repo = make_repo()
        db.select_from_table.return_value = [make_row_values()]
        invite = repo.find_by_id("inv-1")
        assert invite is not None and invite.id == "inv-1"
        assert db.select_from_table.call_args.kwargs["limit"] == 1

    def test_find_by_id_missing(self):
        db, repo = make_repo()
        db.select_from_table.return_value = []
        assert repo.find_by_id("nope") is None

    def test_find_by_calendar_and_user_found(self):
        db, repo = make_repo()
        db.select_from_table.return_value = [make_row_values()]
        invite = repo.find_by_calendar_and_user("cal-key-1", "user1")
        assert invite is not None
        assert "sort_by" in db.select_from_table.call_args.kwargs

    def test_find_by_calendar_and_user_missing(self):
        db, repo = make_repo()
        db.select_from_table.return_value = []
        assert repo.find_by_calendar_and_user("cal-key-1", "user1") is None

    def test_find_pending_for_user(self):
        db, repo = make_repo()
        db.select_from_table.return_value = [make_row_values()]
        invites = repo.find_pending_for_user("user1")
        assert len(invites) == 1
        # pending filter
        cond = db.select_from_table.call_args.kwargs["condition"]
        assert cond is not None

    def test_find_by_calendar(self):
        db, repo = make_repo()
        db.select_from_table.return_value = [make_row_values(), make_row_values(invite_id="inv-2")]
        invites = repo.find_by_calendar("cal-key-1")
        assert len(invites) == 2


class TestUpdateStatus:
    def test_update_ok(self):
        db, repo = make_repo()
        db.update_in_table.return_value = 1
        repo.update_status("inv-1", "accepted")
        kwargs = db.update_in_table.call_args.kwargs
        assert kwargs["values_list"] == ["accepted", mock.ANY]

    def test_update_not_found(self):
        db, repo = make_repo()
        db.update_in_table.return_value = 0
        with pytest.raises(RequestException) as e:
            repo.update_status("inv-1", "accepted")
        assert e.value.error.c == err.ERROR_CALENDAR_INVITE_NOT_FOUND.c


class TestDelete:
    def test_delete_ok(self):
        db, repo = make_repo()
        db.delete_row_in_table.return_value = 1
        repo.delete("inv-1")
        db.delete_row_in_table.assert_called_once()

    def test_delete_not_found(self):
        db, repo = make_repo()
        db.delete_row_in_table.return_value = 0
        with pytest.raises(RequestException) as e:
            repo.delete("inv-1")
        assert e.value.error.c == err.ERROR_CALENDAR_INVITE_NOT_FOUND.c
