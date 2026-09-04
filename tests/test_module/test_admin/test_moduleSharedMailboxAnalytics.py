"""Unit tests for ModuleSharedMailboxAnalytics."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from app.module.admin.ModuleSharedMailboxAnalytics import ModuleSharedMailboxAnalytics


class FakeNotesModule:
    """Fake ModuleSharedMailboxNotes for testing."""
    def __init__(self):
        self.list_notes_calls = []
        self.notes_result = []
        
    def list_notes(self, mailbox_id):
        self.list_notes_calls.append(mailbox_id)
        return self.notes_result


class FakeAssignmentModule:
    """Fake ModuleSharedMailboxAssignment for testing."""
    def __init__(self):
        self.list_assignments_calls = []
        self.assignments_result = []
        
    def list_assignments(self, mailbox_id=None):
        self.list_assignments_calls.append(mailbox_id)
        return self.assignments_result


class FakeMailboxModule:
    """Fake ModuleSharedMailbox for testing get_all_analytics."""
    def __init__(self):
        self.get_all_calls = []
        self.mailboxes_result = []
        
    def get_all(self):
        return self.mailboxes_result


@pytest.fixture
def fake_notes():
    """Create a fresh FakeNotesModule."""
    return FakeNotesModule()


@pytest.fixture
def fake_assignments():
    """Create a fresh FakeAssignmentModule."""
    return FakeAssignmentModule()


@pytest.fixture
def analytics(fake_notes, fake_assignments):
    """Create a ModuleSharedMailboxAnalytics with fake dependencies."""
    fake_db = MagicMock()
    
    with patch("app.module.admin.ModuleSharedMailboxAnalytics.ModuleSharedMailboxNotes", return_value=fake_notes):
        with patch("app.module.admin.ModuleSharedMailboxAnalytics.ModuleSharedMailboxAssignment", return_value=fake_assignments):
            mod = ModuleSharedMailboxAnalytics(fake_db)
            mod._notes_module = fake_notes
            mod._assignment_module = fake_assignments
            yield mod, fake_notes, fake_assignments


class TestModuleSharedMailboxAnalyticsGetAnalytics:
    """Tests for get_analytics method."""

    def test_get_analytics_returns_mailbox_id(self, analytics):
        """get_analytics includes the mailbox_id in response."""
        mod, fake_notes, fake_assignments = analytics
        
        result = mod.get_analytics("mailbox-123")
        
        assert result["mailbox_id"] == "mailbox-123"

    def test_get_analytics_counts_notes(self, analytics):
        """get_analytics counts total/public/private notes."""
        mod, fake_notes, fake_assignments = analytics
        
        fake_notes.notes_result = [
            {"id": 1, "is_private": False, "created_at": "2024-01-01T00:00:00+00:00"},
            {"id": 2, "is_private": True, "created_at": "2024-01-01T00:00:00+00:00"},
            {"id": 3, "is_private": False, "created_at": "2024-01-01T00:00:00+00:00"},
        ]
        fake_assignments.assignments_result = []
        
        result = mod.get_analytics("mailbox-123")
        
        assert result["notes"]["total"] == 3
        assert result["notes"]["public"] == 2
        assert result["notes"]["private"] == 1

    def test_get_analytics_counts_assignments_by_status(self, analytics):
        """get_analytics counts assignments by status."""
        mod, fake_notes, fake_assignments = analytics
        
        fake_notes.notes_result = []
        fake_assignments.assignments_result = [
            {"id": 1, "status": "pending", "created_at": "2024-01-01T00:00:00+00:00"},
            {"id": 2, "status": "accepted", "created_at": "2024-01-01T00:00:00+00:00"},
            {"id": 3, "status": "completed", "created_at": "2024-01-01T00:00:00+00:00", "completed_at": "2024-01-02T00:00:00+00:00"},
            {"id": 4, "status": "cancelled", "created_at": "2024-01-01T00:00:00+00:00"},
        ]
        
        result = mod.get_analytics("mailbox-123")
        
        assert result["assignments"]["total"] == 4
        assert result["assignments"]["pending"] == 1
        assert result["assignments"]["accepted"] == 1
        assert result["assignments"]["completed"] == 1
        assert result["assignments"]["cancelled"] == 1

    def test_get_analytics_calculates_7d_30d_trends(self, analytics):
        """get_analytics counts notes/assignments in last 7/30 days."""
        mod, fake_notes, fake_assignments = analytics
        
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(days=3)).isoformat()
        old = (now - timedelta(days=15)).isoformat()
        very_old = (now - timedelta(days=45)).isoformat()
        
        fake_notes.notes_result = [
            {"id": 1, "is_private": False, "created_at": recent},
            {"id": 2, "is_private": False, "created_at": old},
            {"id": 3, "is_private": False, "created_at": very_old},
        ]
        fake_assignments.assignments_result = []
        
        result = mod.get_analytics("mailbox-123")
        
        assert result["notes"]["last_7_days"] == 1
        assert result["notes"]["last_30_days"] == 2

    def test_get_analytics_calculates_completion_rate(self, analytics):
        """get_analytics calculates completion rate as percentage."""
        mod, fake_notes, fake_assignments = analytics
        
        fake_notes.notes_result = []
        fake_assignments.assignments_result = [
            {"id": 1, "status": "completed", "created_at": "2024-01-01T00:00:00+00:00", "completed_at": "2024-01-02T00:00:00+00:00"},
            {"id": 2, "status": "completed", "created_at": "2024-01-01T00:00:00+00:00", "completed_at": "2024-01-02T00:00:00+00:00"},
            {"id": 3, "status": "pending", "created_at": "2024-01-01T00:00:00+00:00"},
        ]
        
        result = mod.get_analytics("mailbox-123")
        
        assert result["assignments"]["completion_rate"] == 66.67  # 2/3 * 100

    def test_get_analytics_calculates_avg_completion_time(self, analytics):
        """get_analytics calculates average completion time in seconds."""
        mod, fake_notes, fake_assignments = analytics
        
        fake_notes.notes_result = []
        fake_assignments.assignments_result = [
            {"id": 1, "status": "completed", "created_at": "2024-01-01T00:00:00+00:00", "completed_at": "2024-01-01T02:00:00+00:00"},  # 2 hours
            {"id": 2, "status": "completed", "created_at": "2024-01-01T00:00:00+00:00", "completed_at": "2024-01-01T04:00:00+00:00"},  # 4 hours
        ]
        
        result = mod.get_analytics("mailbox-123")
        
        # Average of 2 hours (7200s) and 4 hours (14400s) = 10800 seconds
        assert result["assignments"]["avg_completion_seconds"] == 10800.0

    def test_get_analytics_handles_no_assignments(self, analytics):
        """get_analytics returns 0% completion rate when no assignments exist."""
        mod, fake_notes, fake_assignments = analytics
        
        fake_notes.notes_result = []
        fake_assignments.assignments_result = []
        
        result = mod.get_analytics("mailbox-123")
        
        assert result["assignments"]["completion_rate"] == 0
        assert result["assignments"]["avg_completion_seconds"] == 0

    def test_get_analytics_handles_invalid_timestamps(self, analytics):
        """get_analytics skips assignments with invalid timestamps."""
        mod, fake_notes, fake_assignments = analytics
        
        fake_notes.notes_result = []
        fake_assignments.assignments_result = [
            {"id": 1, "status": "completed", "created_at": "invalid", "completed_at": "also-invalid"},
            {"id": 2, "status": "completed", "created_at": "2024-01-01T00:00:00+00:00", "completed_at": "2024-01-02T00:00:00+00:00"},
        ]
        
        result = mod.get_analytics("mailbox-123")
        
        # Only the valid assignment should be counted
        assert result["assignments"]["avg_completion_seconds"] == 86400.0  # 24 hours

    def test_get_analytics_includes_generated_at(self, analytics):
        """get_analytics includes generated_at timestamp."""
        mod, fake_notes, fake_assignments = analytics
        
        fake_notes.notes_result = []
        fake_assignments.assignments_result = []
        
        result = mod.get_analytics("mailbox-123")
        
        assert "generated_at" in result
        assert isinstance(result["generated_at"], str)


class TestModuleSharedMailboxAnalyticsGetAllAnalytics:
    """Tests for get_all_analytics method."""

    def test_get_all_analytics_returns_list(self, analytics, monkeypatch):
        """get_all_analytics returns a list of analytics dicts."""
        mod, fake_notes, fake_assignments = analytics
        
        mock_mailbox = MagicMock()
        mock_mailbox.get_all.return_value = [
            {"id": "mb1", "is_active": True},
            {"id": "mb2", "is_active": True},
        ]
        monkeypatch.setattr(
            "app.module.admin.ModuleSharedMailbox.ModuleSharedMailbox",
            lambda db: mock_mailbox,
        )
        
        result = mod.get_all_analytics()
        
        assert len(result) == 2

    def test_get_all_analytics_skips_inactive(self, analytics, monkeypatch):
        """get_all_analytics skips inactive mailboxes."""
        mod, fake_notes, fake_assignments = analytics
        
        mock_mailbox = MagicMock()
        mock_mailbox.get_all.return_value = [
            {"id": "mb1", "is_active": True},
            {"id": "mb2", "is_active": False},
        ]
        monkeypatch.setattr(
            "app.module.admin.ModuleSharedMailbox.ModuleSharedMailbox",
            lambda db: mock_mailbox,
        )
        
        result = mod.get_all_analytics()
        
        assert len(result) == 1
        assert result[0]["mailbox_id"] == "mb1"

    def test_get_all_analytics_calls_get_analytics_for_each(self, analytics, monkeypatch):
        """get_all_analytics calls get_analytics for each active mailbox."""
        mod, fake_notes, fake_assignments = analytics
        
        mock_mailbox = MagicMock()
        mock_mailbox.get_all.return_value = [
            {"id": "mb1", "is_active": True},
            {"id": "mb2", "is_active": True},
        ]
        monkeypatch.setattr(
            "app.module.admin.ModuleSharedMailbox.ModuleSharedMailbox",
            lambda db: mock_mailbox,
        )
        
        with patch.object(mod, "get_analytics") as mock_get:
            mock_get.return_value = {"mailbox_id": "test", "notes": {}, "assignments": {}, "generated_at": "now"}
            mod.get_all_analytics()
            
            assert mock_get.call_count == 2
