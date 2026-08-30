"""
Unit tests for ModuleResourceBooking.delete.

Regression: deleting a resource raised AttributeError because ``delete`` called
``self._db.delete_from_table(...)`` — a method that does not exist on
ClientSQL / ClientMySQL (the real method is ``delete_row_in_table``).
"""
import pytest

from app.module.calendar.ModuleResourceBooking import ModuleResourceBooking
from app.utils import errors as err
from app.utils.exceptions import RequestException


class FakeDb:
    """Mirrors the ClientMySQL surface used by ModuleResourceBooking."""

    def __init__(self, existing_row=None):
        self.existing_row = existing_row
        self.deleted = []

    def select_from_table(self, table_name, column_tuple, condition):
        if self.existing_row is None:
            return []
        return [self.existing_row]

    def delete_row_in_table(self, table_name, condition, expected_row=0):
        self.deleted.append((table_name, condition))
        return 1 if self.existing_row else 0


RESOURCE_ROW = [
    "res-1", "Meeting Room Alpha", "desc", "meeting.room@example.org",
    "room", 10, "HQ", [], True, "auto", [], True, "t1", "t1",
]


def test_delete_resource_via_delete_row_in_table():
    db = FakeDb(existing_row=RESOURCE_ROW)
    module = ModuleResourceBooking(db)
    module.delete("res-1")
    assert len(db.deleted) == 1
    assert db.deleted[0][0] == "sogo6_resources"


def test_delete_missing_resource_raises_not_found():
    db = FakeDb(existing_row=None)
    module = ModuleResourceBooking(db)
    with pytest.raises(RequestException) as exc_info:
        module.delete("missing")
    assert exc_info.value.error == err.ERROR_RESOURCE_NOT_FOUND
    assert db.deleted == []
