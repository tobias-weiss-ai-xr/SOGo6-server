"""Tests for ModuleSnooze — email snooze management."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.module.mail.ModuleSnooze import ModuleSnooze
from app.utils.exceptions import RequestException


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def module(mock_db: MagicMock) -> ModuleSnooze:
    return ModuleSnooze(mock_db)


FUTURE = datetime.now(timezone.utc) + timedelta(hours=24)
PAST = datetime.now(timezone.utc) - timedelta(hours=1)
NOW = datetime.now(timezone.utc)

SAMPLE_SNOOZE_ROW = [
    1, "user@example.org", "42", "Snoozed", "INBOX",
    FUTURE, NOW.isoformat(), "0",
]


# ── snooze ─────────────────────────────────────────────────────────────────────

class TestSnooze:
    def test_snooze_success(self, module: ModuleSnooze, mock_db: MagicMock):
        mock_db.select_from_table.return_value = []
        mock_db.insert_in_table.return_value = None
        mock_db.select_from_table.side_effect = [
            [],  # no duplicate check
            [[1, "user@example.org", "42", "Snoozed", "INBOX", FUTURE, NOW, "0"]],  # return after insert
        ]

        result = module.snooze(
            user_uid="user@example.org",
            account_id="0",
            mail_uid="42",
            folder="INBOX",
            snooze_until=FUTURE,
        )

        assert result["mail_uid"] == "42"
        assert result["original_folder"] == "INBOX"
        assert mock_db.insert_in_table.called

    def test_snooze_with_original_folder(self, module: ModuleSnooze, mock_db: MagicMock):
        mock_db.select_from_table.return_value = []
        mock_db.insert_in_table.return_value = None
        mock_db.select_from_table.side_effect = [
            [],
            [[2, "user@example.org", "55", "Sent", "Sent", FUTURE, NOW, "0"]],
        ]

        result = module.snooze(
            user_uid="user@example.org",
            account_id="0",
            mail_uid="55",
            folder="Sent",
            snooze_until=FUTURE,
            original_folder="Sent",
        )

        assert result["original_folder"] == "Sent"

    def test_snooze_past_time_raises(self, module: ModuleSnooze):
        with pytest.raises(RequestException):
            module.snooze(
                user_uid="user@example.org",
                account_id="0",
                mail_uid="42",
                folder="INBOX",
                snooze_until=PAST,
            )

    def test_snooze_duplicate_raises(self, module: ModuleSnooze, mock_db: MagicMock):
        mock_db.select_from_table.return_value = [SAMPLE_SNOOZE_ROW]

        with pytest.raises(RequestException):
            module.snooze(
                user_uid="user@example.org",
                account_id="0",
                mail_uid="42",
                folder="INBOX",
                snooze_until=FUTURE,
            )


# ── unsnooze ──────────────────────────────────────────────────────────────────

class TestUnsnooze:
    def test_unsnooze_success(self, module: ModuleSnooze, mock_db: MagicMock):
        mock_db.select_from_table.return_value = [SAMPLE_SNOOZE_ROW]
        mock_db.delete_from_table.return_value = None

        result = module.unsnooze("user@example.org", 1)
        assert result["mail_uid"] == "42"
        assert result["original_folder"] == "INBOX"
        assert mock_db.delete_from_table.called

    def test_unsnooze_not_found_raises(self, module: ModuleSnooze, mock_db: MagicMock):
        mock_db.select_from_table.return_value = []

        with pytest.raises(RequestException):
            module.unsnooze("user@example.org", 999)

    def test_unsnooze_wrong_user_raises(self, module: ModuleSnooze, mock_db: MagicMock):
        mock_db.select_from_table.return_value = []

        with pytest.raises(RequestException):
            module.unsnooze("other@example.org", 1)


# ── list_snoozed ──────────────────────────────────────────────────────────────

class TestListSnoozed:
    def test_list_all(self, module: ModuleSnooze, mock_db: MagicMock):
        future_row = list(SAMPLE_SNOOZE_ROW)
        future_row[5] = FUTURE
        mock_db.select_from_table.return_value = [future_row]

        results = module.list_snoozed("user@example.org")
        assert len(results) == 1
        assert results[0]["mail_uid"] == "42"

    def test_list_excludes_expired(self, module: ModuleSnooze, mock_db: MagicMock):
        past_row = list(SAMPLE_SNOOZE_ROW)
        past_row[5] = PAST
        mock_db.select_from_table.return_value = [past_row]

        results = module.list_snoozed("user@example.org", include_expired=False)
        assert len(results) == 0

    def test_list_includes_expired(self, module: ModuleSnooze, mock_db: MagicMock):
        past_row = list(SAMPLE_SNOOZE_ROW)
        past_row[5] = PAST
        mock_db.select_from_table.return_value = [past_row]

        results = module.list_snoozed("user@example.org", include_expired=True)
        assert len(results) == 1


# ── list_due ──────────────────────────────────────────────────────────────────

class TestListDue:
    def test_list_due_returns_past(self, module: ModuleSnooze, mock_db: MagicMock):
        past_row = list(SAMPLE_SNOOZE_ROW)
        past_row[5] = PAST
        mock_db.select_from_table.return_value = [past_row]

        results = module.list_due()
        assert len(results) == 1


# ── presets ───────────────────────────────────────────────────────────────────

class TestPresets:
    def test_later_today(self):
        result = ModuleSnooze.parse_preset("later_today")
        assert result is not None
        assert "hours" in result

    def test_tomorrow(self):
        result = ModuleSnooze.parse_preset("tomorrow")
        assert result is not None
        assert result["hours"] == 24

    def test_this_weekend(self):
        result = ModuleSnooze.parse_preset("this_weekend")
        assert result is not None
        assert "days" in result

    def test_next_week(self):
        result = ModuleSnooze.parse_preset("next_week")
        assert result is not None
        assert result["days"] == 7

    def test_unknown_preset(self):
        assert ModuleSnooze.parse_preset("never") is None
