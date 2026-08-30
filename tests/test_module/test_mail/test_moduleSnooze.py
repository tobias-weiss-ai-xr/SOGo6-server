"""
Unit tests for ModuleSnooze.unsnooze.

Regression: DELETE /api/user/v1/snooze/<id> returned 500 — ``unsnooze`` called
``self._db.delete_from_table(...)`` which does not exist on ClientSQL /
ClientMySQL / any registered backend (the real method is
``delete_row_in_table``). Exercise the exact client contract with a fake DB
that mirrors ClientMySQL (no ``delete_from_table`` attribute).
"""
from datetime import datetime, timezone

import pytest

from app.module.mail.ModuleSnooze import ModuleSnooze
from app.utils import errors as err
from app.utils.exceptions import RequestException


class FakeDb:
    """Mirrors ClientMySQL surface used by ModuleSnooze."""

    def __init__(self, existing_row=None):
        self.existing_row = existing_row
        self.deleted_with = None

    def select_from_table(self, table_name, column_tuple, condition):
        if self.existing_row is None:
            return []
        return [self.existing_row]

    def delete_row_in_table(self, table_name, condition, expected_row=0):
        self.deleted_with = (table_name, condition)
        return 1 if self.existing_row else 0


FULL_ROW = [
    1,                      # id
    "testuser@example.org",  # user_uid
    "959",                  # mail_uid
    "INBOX",                # folder
    "INBOX",                # original_folder
    datetime(2026, 8, 31, 8, 38, 47, tzinfo=timezone.utc),  # snooze_until
    datetime(2026, 8, 30, 8, 38, 47, tzinfo=timezone.utc),  # created_at
    "0",                    # account_id
]


def test_unsnooze_deletes_via_delete_row_in_table():
    db = FakeDb(existing_row=FULL_ROW)
    module = ModuleSnooze(db)
    record = module.unsnooze("testuser@example.org", 1)

    assert record["mail_uid"] == "959"
    assert db.deleted_with is not None
    table, condition = db.deleted_with
    assert table == "sogo6_snoozed"
    # condition must scope on id (and user, see ModuleSnooze implementation)
    assert condition is not None


def test_unsnooze_missing_record_raises_not_found():
    db = FakeDb(existing_row=None)
    module = ModuleSnooze(db)
    with pytest.raises(RequestException) as exc_info:
        module.unsnooze("testuser@example.org", 999)
    assert exc_info.value.error == err.ERROR_SNOOZE_NOT_FOUND
    assert db.deleted_with is None


def test_remove_record_uses_delete_row_in_table():
    db = FakeDb(existing_row=FULL_ROW)
    module = ModuleSnooze(db)
    module.remove_record(7)
    assert db.deleted_with is not None
    assert db.deleted_with[0] == "sogo6_snoozed"


def test_snooze_client_has_no_delete_from_table_attribute():
    """Guard: if ClientMySQL ever grows delete_from_table this test draws attention."""
    import app.manager.db.ClientMySQL as cm

    assert not hasattr(cm.ClientMySQL, "delete_from_table"), (
        "ClientMySQL gained 'delete_from_table' — remove this guard and re-evaluate."
    )
