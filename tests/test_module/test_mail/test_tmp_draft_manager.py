"""
Unit tests for TmpDraftManager — the tmp_draft DB state machine behind the
mail compose/draft flow (acquire → lock → release/unlock).

Pins down:
  * row lookup + owner check + fetch_headers typing
  * lock/unlock/release/insert semantics and their error contracts
  * acquire() resolution (existing vs brand-new, locked-row behavior)
  * the ``locked`` context manager (unlock-on-exception, no unlock on success)

The underlying ClientSQL is faked: the fake records the (method, args) calls and
returns scripted rows, so no database is needed.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.module.mail.model.TmpDraftManager import TmpDraftManager
from app.utils import errors as err
from app.utils.db.Condition import EqualCondition
from app.utils.exceptions import RequestException


class FakeSql:
    """Scriptable fake for the ClientSQL surface TmpDraftManager uses."""

    def __init__(self, rows=None, update_count=1, insert_count=1, delete_count=1, select_sequence=None):
        self.rows = rows if rows is not None else []
        self.select_sequence = list(select_sequence) if select_sequence is not None else None
        self.update_count = update_count
        self.insert_count = insert_count
        self.delete_count = delete_count
        self.calls = []  # (method, args)

    # -- scripted primitives -------------------------------------------------
    def select_from_table(self, table_name, column_tuple, condition, *args, **kwargs):
        self.calls.append(("select", (table_name, column_tuple, condition)))
        if self.select_sequence is not None:
            # Consume one scripted result-set per select call.
            if not self.select_sequence:
                raise AssertionError("select_sequence exhausted")
            return self.select_sequence.pop(0)
        return self.rows

    def update_in_table(self, table_name, column_tuple, values_list, condition, *args, **kwargs):
        self.calls.append(("update", (table_name, column_tuple, values_list, condition)))
        return self.update_count

    def insert_in_table(self, table_name, column_tuple, values_list, *args, **kwargs):
        self.calls.append(("insert", (table_name, column_tuple, values_list)))
        return self.insert_count

    def delete_row_in_table(self, table_name, condition, expected_row=0, *args, **kwargs):
        self.calls.append(("delete", (table_name, condition, expected_row)))
        return self.delete_count

    # -- helpers ---------------------------------------------------------------
    def last(self, method):
        return next(c for c in reversed(self.calls) if c[0] == method)[1]


def make_manager(db=None, user_uid="user-1"):
    return TmpDraftManager(db if db is not None else FakeSql(), user_uid)


# ---------------------------------------------------------------------------
# fetch_row / fetch_headers / check_owner
# ---------------------------------------------------------------------------

def test_fetch_row_returns_tuple():
    db = FakeSql(rows=[("k1", "user-1", "uid-9", True)])
    manager = make_manager(db)
    assert manager.fetch_row("k1") == ("k1", "user-1", "uid-9", True)
    table, cols, cond = db.last("select")
    assert isinstance(cond, EqualCondition)
    assert cond.param_value == "k1"


def test_fetch_row_raises_404_when_missing():
    db = FakeSql(rows=[])
    manager = make_manager(db)
    with pytest.raises(RequestException) as exc:
        manager.fetch_row("nope")
    assert exc.value.http_status == 404
    assert exc.value.error.c == err.ERROR_TMP_DRAFT_NOT_FOUND.c


def test_fetch_headers_returns_dict():
    db = FakeSql(rows=[({"In-Reply-To": "<x@y>", "References": "<a@b> <c@d>"},)])
    manager = make_manager(db)
    assert manager.fetch_headers("k1") == {"In-Reply-To": "<x@y>", "References": "<a@b> <c@d>"}


def test_fetch_headers_maps_non_dict_to_empty_dict():
    db = FakeSql(rows=[("not-a-dict",)])
    manager = make_manager(db)
    assert manager.fetch_headers("k1") == {}


def test_fetch_headers_raises_404_when_missing():
    db = FakeSql(rows=[])
    manager = make_manager(db)
    with pytest.raises(RequestException) as exc:
        manager.fetch_headers("nope")
    assert exc.value.http_status == 404


def test_check_owner_accepts_matching_user():
    make_manager().check_owner("user-1")  # must not raise


def test_check_owner_raises_403_on_mismatch():
    with pytest.raises(RequestException) as exc:
        make_manager().check_owner("other-user")
    assert exc.value.http_status == 403
    assert exc.value.error.c == err.ERROR_TMP_DRAFT_OWNER_MISMATCH.c


# ---------------------------------------------------------------------------
# generate_key
# ---------------------------------------------------------------------------

def test_generate_key_returns_hex_of_expected_length():
    manager = make_manager()
    key = manager.generate_key()
    # TMP_DRAFT_KEY_SIZE = 32 chars; token_hex(N/2) -> N hex chars
    assert len(key) == 32
    int(key, 16)  # must be valid hex


def test_generate_key_randomizes():
    manager = make_manager()
    assert len({manager.generate_key() for _ in range(50)}) > 1


# ---------------------------------------------------------------------------
# lock_existing / insert_locked / insert_with_headers / unlock / release / delete
# ---------------------------------------------------------------------------

def test_lock_existing_updates_row_and_sets_lock_true():
    db = FakeSql(update_count=1)
    make_manager(db).lock_existing("k1")
    table, cols, values, cond = db.last("update")
    assert cols == ("lock_state",)
    assert values == [True]
    assert cond.param_value == "k1"


def test_lock_existing_raises_when_update_count_unexpected():
    db = FakeSql(update_count=0)
    with pytest.raises(RequestException) as exc:
        make_manager(db).lock_existing("k1")
    assert exc.value.error.c == err.ERROR_TMP_DRAFT_UPDATE_FAILED.c


def test_insert_locked_inserts_unlocked_free_row():
    db = FakeSql(insert_count=1)
    make_manager(db, user_uid="user-7").insert_locked("newk")
    table, cols, values = db.last("insert")
    assert cols == ("key", "owner", "mail_server_uid", "lock_state", "last_updated")
    assert values[0][:4] == ["newk", "user-7", "", True]


def test_insert_locked_raises_when_insert_count_unexpected():
    db = FakeSql(insert_count=0)
    with pytest.raises(RequestException) as exc:
        make_manager(db).insert_locked("newk")
    assert exc.value.error.c == err.ERROR_TMP_DRAFT_INSERT_FAILED.c


def test_insert_with_headers_stores_unlocked_row_with_headers():
    db = FakeSql(insert_count=1)
    headers = {"In-Reply-To": "<id@host>"}
    make_manager(db, user_uid="user-7").insert_with_headers("k1", "uid-12", headers)
    table, cols, values = db.last("insert")
    assert cols == ("key", "owner", "mail_server_uid", "lock_state", "headers", "last_updated")
    row = values[0]
    assert row[0] == "k1" and row[1] == "user-7" and row[2] == "uid-12"
    assert row[3] is False and row[4] == headers


def test_unlock_sets_lock_false_and_keeps_uid():
    db = FakeSql()
    make_manager(db).unlock("k1")
    table, cols, values, cond = db.last("update")
    assert cols == ("lock_state",)
    assert values == [False]
    assert cond.param_value == "k1"


def test_release_updates_uid_locks_off_and_touches_timestamp():
    db = FakeSql(update_count=1)
    make_manager(db).release("k1", "uid-55")
    table, cols, values, cond = db.last("update")
    assert cols == ("mail_server_uid", "lock_state", "last_updated")
    assert values[0] == "uid-55"
    assert values[1] is False
    assert isinstance(values[2], int)


def test_release_raises_when_update_count_unexpected():
    db = FakeSql(update_count=0)
    with pytest.raises(RequestException) as exc:
        make_manager(db).release("k1", "uid-55")
    assert exc.value.error.c == err.ERROR_TMP_DRAFT_UPDATE_FAILED.c


def test_list_all_maps_rows_to_dicts_filtered_by_owner():
    db = FakeSql(rows=[
        ("k1", "uid-1", False, 111),
        ("k2", "uid-2", True, 222),
    ])
    result = make_manager(db, user_uid="user-1").list_all()
    assert result == [
        {"key": "k1", "mail_server_uid": "uid-1", "locked": False, "last_updated": 111},
        {"key": "k2", "mail_server_uid": "uid-2", "locked": True, "last_updated": 222},
    ]
    table, cols, cond = db.last("select")
    assert cond.param_value == "user-1"


def test_delete_removes_row():
    db = FakeSql(delete_count=1)
    make_manager(db).delete("k1")
    table, cond, expected = db.last("delete")
    assert cond.param_value == "k1"
    assert expected == 1


def test_delete_raises_when_row_not_deleted():
    db = FakeSql(delete_count=0)
    with pytest.raises(RequestException) as exc:
        make_manager(db).delete("k1")
    assert exc.value.error.c == err.ERROR_TMP_DRAFT_DELETE_FAILED.c


# ---------------------------------------------------------------------------
# acquire
# ---------------------------------------------------------------------------

def test_acquire_existing_unlocked_locks_and_returns_uid():
    db = FakeSql(rows=[("k1", "user-1", "uid-9", False)])
    manager = make_manager(db)
    assert manager.acquire("k1") == ("k1", "uid-9")
    assert db.calls[-1][0] == "update"  # lock applied last


def test_acquire_existing_with_empty_uid_returns_none():
    db = FakeSql(rows=[("k1", "user-1", "", False)])
    assert make_manager(db).acquire("k1") == ("k1", None)


def test_acquire_locked_without_wait_raises_conflict():
    db = FakeSql(rows=[("k1", "user-1", "uid-9", True)])
    with pytest.raises(RequestException) as exc:
        make_manager(db).acquire("k1")
    assert exc.value.http_status == 409
    assert exc.value.error.c == err.ERROR_TMP_DRAFT_LOCKED.c


def test_acquire_locked_with_wait_polls_until_unlocked(monkeypatch):
    # fetch_row select #1 returns the full locked row; wait_for_unlock polls
    # only the lock_state column (1-tuples): still locked, then unlocked.
    db = FakeSql(select_sequence=[
        [("k1", "user-1", "uid-9", True)],  # fetch_row
        [(True,)],                              # poll 1: still locked
        [(False,)],                             # poll 2: unlocked
    ])
    monkeypatch.setattr("app.module.mail.model.TmpDraftManager.time.sleep", lambda s: None)
    assert make_manager(db).acquire("k1", wait_if_locked=True) == ("k1", "uid-9")


def test_acquire_locked_with_wait_gives_up_after_timeout(monkeypatch):
    import time as real_time

    # fetch_row select #1 returns the row; the single poll (before the fake
    # clock jumps past the deadline) reports still locked.
    db = FakeSql(select_sequence=[
        [("k1", "user-1", "uid-9", True)],
        [(True,)],
    ])
    # Fake clock: starts at now, jumps past the 2s deadline on the next call so
    # the poll loop exits immediately with the row still locked.
    clock = {"now": real_time.monotonic()}

    def fake_monotonic():
        if clock["now"] is not None:
            value = clock["now"]
            clock["now"] = value + 10.0  # past deadline for every later call
            return value
        return clock["now"]

    monkeypatch.setattr("app.module.mail.model.TmpDraftManager.time.monotonic", fake_monotonic)
    monkeypatch.setattr("app.module.mail.model.TmpDraftManager.time.sleep", lambda s: None)
    with pytest.raises(RequestException) as exc:
        make_manager(db).acquire("k1", wait_if_locked=True)
    assert exc.value.error.c == err.ERROR_TMP_DRAFT_LOCKED.c


def test_acquire_new_key_inserts_locked_row():
    db = FakeSql(insert_count=1)
    key, uid = make_manager(db, user_uid="user-1").acquire(None)
    assert uid is None
    assert len(key) == 32
    table, cols, values = db.last("insert")
    assert values[0][1] == "user-1" and values[0][3] is True


def test_acquire_rechecks_owner_and_raises_403():
    db = FakeSql(rows=[("k1", "someone-else", "uid-9", False)])
    with pytest.raises(RequestException) as exc:
        make_manager(db, user_uid="user-1").acquire("k1")
    assert exc.value.http_status == 403


# ---------------------------------------------------------------------------
# locked() context manager
# ---------------------------------------------------------------------------

def test_locked_yields_resolved_key_and_unlocks_on_error():
    db = FakeSql(rows=[("k1", "user-1", "uid-9", False)])
    manager = make_manager(db)
    with pytest.raises(RuntimeError):
        with manager.locked("k1") as (resolved_key, uid):
            assert (resolved_key, uid) == ("k1", "uid-9")
            raise RuntimeError("boom")
    # unlock must have been applied after the failure
    assert db.calls[-1][0] == "update"
    assert db.calls[-1][1][1] == ("lock_state",)
    assert db.calls[-1][1][2] == [False]


def test_locked_does_not_unlock_on_success():
    db = FakeSql(rows=[("k1", "user-1", "uid-9", False)])
    manager = make_manager(db)
    with manager.locked("k1") as (resolved_key, uid):
        assert (resolved_key, uid) == ("k1", "uid-9")
    # last call is still the LOCK update, not an unlock
    assert db.calls[-1][1][1] == ("lock_state",)
    assert db.calls[-1][1][2] == [True]


def test_locked_create_new_key_path():
    db = FakeSql(insert_count=1)
    with make_manager(db, user_uid="user-1").locked(None) as (resolved_key, uid):
        assert uid is None
        assert len(resolved_key) == 32
    assert db.calls[-1][0] == "insert"
