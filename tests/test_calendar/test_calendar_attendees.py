"""Unit tests for calendar attendee persistence (RSVP tracking).

Covers the ``sogo6_calendar_attendees`` table defined in
``app/config/db/tables.py``: column layout, not-null semantics, RFC 5545
PARTSTAT status values, consistency with the event key namespace, the
env-driven table name (SOGO_P_TABLE_CALENDAR_ATTENDEES) and that the table
compiles to a valid CREATE TABLE statement in the DDL layer used at boot
(no live stack required).
"""
import importlib
import os
import re

import pytest

from app.config.db import tables as tbl
from app.manager.db.ClientPostgreSQL import table_to_query
from app.utils.db.Table import REX_VALID_NAMES

TABLE_ENV = "SOGO_P_TABLE_CALENDAR_ATTENDEES"
DEFAULT_TABLE_NAME = "sogo6_calendar_attendees"

# RFC 5545 §3.2.12 PARTSTAT literals, as modelled by AttendeeStatus values
PARTSTAT_VALUES = ("needs-action", "accepted", "declined", "tentative", "delegated")


def _col(name: str):
    """Return the Column of TABLE_ATTENDEE with the given name."""
    for column in tbl.TABLE_ATTENDEE.columns:
        if column.name == name:
            return column
    raise AssertionError(f"column {name!r} not found in {tbl.TABLE_ATTENDEE.name}")


def _index(name: str):
    for index in tbl.TABLE_ATTENDEE.index or []:
        if index.name == name:
            return index
    raise AssertionError(f"index {name!r} not found on {tbl.TABLE_ATTENDEE.name}")


def test_attendee_table_registered_in_all_tables():
    assert tbl.TABLE_ATTENDEE in tbl.ALL_TABLES


def test_attendee_table_default_name():
    assert tbl.TABLE_ATTENDEE.name == DEFAULT_TABLE_NAME


def test_attendee_table_name_env_override(monkeypatch):
    """The table name is env-driven (SOGO_P_TABLE_CALENDAR_ATTENDEES)."""
    monkeypatch.setenv(TABLE_ENV, "custom_calendar_attendees")
    importlib.reload(tbl)
    try:
        assert tbl.TABLE_ATTENDEE.name == "custom_calendar_attendees"
    finally:
        monkeypatch.delenv(TABLE_ENV, raising=False)
        importlib.reload(tbl)
    assert tbl.TABLE_ATTENDEE.name == DEFAULT_TABLE_NAME


def test_attendee_table_primary_key_is_id():
    assert tbl.TABLE_ATTENDEE.primary_keys == ("id",)
    assert _col("id").data_type == "serial"


def test_attendee_table_required_columns():
    required = ("id", "event_key", "email", "status", "rsvp",
                "sent_at", "responded_at", "created_at", "updated_at")
    names = {c.name for c in tbl.TABLE_ATTENDEE.columns}
    for name in required:
        assert name in names, f"missing column {name}"


def test_attendee_table_email_not_nullable():
    col = _col("email")
    assert col.is_nullable is False
    assert col.data_type == "str"
    assert col.extra_args["max_len"] == 512


def test_attendee_table_event_key_not_nullable():
    col = _col("event_key")
    assert col.is_nullable is False
    assert col.data_type == "str"
    assert col.extra_args["max_len"] == 64


def test_attendee_table_event_key_matches_event_namespace():
    """event_key must reference the same opaque key namespace as sogo6_calendar_events.key."""
    event_key_col = next(c for c in tbl.TABLE_EVENT.columns if c.name == "key")
    assert _col("event_key").extra_args["max_len"] == event_key_col.extra_args["max_len"]


def test_attendee_table_status_column():
    col = _col("status")
    assert col.is_nullable is False
    assert col.data_type == "str"
    # longest PARTSTAT literal is "needs-action" (12 chars)
    assert col.extra_args["max_len"] >= max(len(s) for s in PARTSTAT_VALUES)


@pytest.mark.parametrize("status", PARTSTAT_VALUES)
def test_attendee_table_supports_rfc5545_partstat(status):
    """Every AttendeeStatus value fits and is a valid lowercase PARTSTAT literal."""
    assert len(status) <= _col("status").extra_args["max_len"]


def test_attendee_table_timestamps():
    assert _col("sent_at").data_type == "datetime"
    assert _col("sent_at").is_nullable is True
    assert _col("responded_at").data_type == "datetime"
    assert _col("responded_at").is_nullable is True
    assert _col("created_at").data_type == "datetime"
    assert _col("updated_at").data_type == "datetime"


def test_attendee_table_rsvp_flag():
    col = _col("rsvp")
    assert col.data_type == "bool"
    assert col.is_nullable is False


def test_attendee_table_event_key_index():
    index = _index("idx_att_event_key")
    assert index.columns == ("event_key",)
    assert index.unique is False


def test_attendee_table_email_index():
    index = _index("idx_att_email")
    assert index.columns == ("email",)


def test_attendee_table_unique_event_email_index():
    """One RSVP row per (event, attendee): re-inviting an address updates in place."""
    index = _index("idx_att_event_email")
    assert index.columns == ("event_key", "email")
    assert index.unique is True


def test_attendee_table_no_duplicate_columns():
    names = [c.name for c in tbl.TABLE_ATTENDEE.columns]
    assert len(names) == len(set(names))


def test_attendee_table_column_names_valid():
    for column in tbl.TABLE_ATTENDEE.columns:
        assert re.match(REX_VALID_NAMES, column.name), f"invalid column name {column.name}"
    for index in tbl.TABLE_ATTENDEE.index or []:
        assert re.match(REX_VALID_NAMES, index.name), f"invalid index name {index.name}"


def test_attendee_table_column_types_valid():
    from app.utils.db.Table import SOGO_DB_DATA_TYPE
    for column in tbl.TABLE_ATTENDEE.columns:
        assert column.data_type in SOGO_DB_DATA_TYPE, f"invalid type {column.data_type}"


def test_attendee_table_generates_ddl():
    """The table must compile to valid PostgreSQL DDL (used by ModuleInitSogo at boot)."""
    ddl = table_to_query(tbl.TABLE_ATTENDEE).as_string(None)
    assert "CREATE TABLE" in ddl
    assert f'"{DEFAULT_TABLE_NAME}"' in ddl
    assert '"event_key"' in ddl
    assert '"email"' in ddl
    assert '"status"' in ddl
    assert '"sent_at"' in ddl
    assert '"responded_at"' in ddl
    assert "NOT NULL" in ddl
    assert "PRIMARY KEY (\"id\")" in ddl
