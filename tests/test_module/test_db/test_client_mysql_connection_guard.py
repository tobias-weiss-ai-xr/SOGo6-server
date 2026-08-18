"""Test that ClientMySQL/ClientPostgreSQL auto-connect when db_conn is None.

Regression test for the silent no-op bug: `if self.db_conn and not
self.db_conn.is_connected()` evaluates to None (falsy) when db_conn
is None, skipping both connect() and the actual operation.

Uses static source analysis (no module import) so tests run without
heavy dependencies.
"""
import re
from pathlib import Path

import pytest


_MYSQL_SRC = Path(__file__).resolve().parent.parent.parent.parent / "app" / "manager" / "db" / "ClientMySQL.py"
_PG_SRC = Path(__file__).resolve().parent.parent.parent.parent / "app" / "manager" / "db" / "ClientPostgreSQL.py"


class TestMySQLConnectionGuard:
    """ClientMySQL must use `is None or` pattern, not `and not`."""

    def test_no_buggy_and_pattern(self):
        """`if self.db_conn and not self.db_conn.is_connected()` must not exist."""
        src = _MYSQL_SRC.read_text()
        buggy = re.findall(r'if self\.db_conn and not self\.db_conn\.is_connected\(\)', src)
        assert len(buggy) == 0, f"Found {len(buggy)} buggy connection guards in ClientMySQL"

    def test_correct_pattern_used(self):
        """`if self.db_conn is None or not self.db_conn.is_connected()` must be used."""
        src = _MYSQL_SRC.read_text()
        correct = re.findall(r'if self\.db_conn is None or not self\.db_conn\.is_connected\(\)', src)
        # Should have at least the data methods (insert, update, delete, select, count) + DDL methods
        assert len(correct) >= 5, f"Expected >=5 correct guards, found {len(correct)}"


class TestPostgreSQLConnectionGuard:
    """ClientPostgreSQL must use `is None or` pattern, not `and not`."""

    def test_no_buggy_and_pattern(self):
        """`if self.db_conn and self.db_conn.closed` must not exist."""
        src = _PG_SRC.read_text()
        buggy = re.findall(r'if self\.db_conn and self\.db_conn\.closed:', src)
        assert len(buggy) == 0, f"Found {len(buggy)} buggy connection guards in ClientPostgreSQL"

    def test_correct_pattern_used(self):
        """`if self.db_conn is None or self.db_conn.closed` must be used."""
        src = _PG_SRC.read_text()
        correct = re.findall(r'if self\.db_conn is None or self\.db_conn\.closed:', src)
        assert len(correct) >= 5, f"Expected >=5 correct guards, found {len(correct)}"
