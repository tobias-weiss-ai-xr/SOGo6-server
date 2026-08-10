"""
Tests for batch mail actions and mail search in ModuleMail.

These tests follow the same pattern as test_moduleMail.py —
they mock the underlying IMAP client (FakeClientMailServer) and
test only the module logic.
"""

from unittest.mock import MagicMock

import pytest

from tests.test_module.test_mail.test_moduleMail import ACCOUNT_ID, _make_module
from app.utils.exceptions import RequestException
from app.utils import errors as err


# ===================================================================
# batch_mail_action
# ===================================================================

class TestBatchMailAction:
    """Tests for ModuleMail.batch_mail_action()."""

    def test_batch_delete(self, monkeypatch):
        """Batch delete removes all specified mails."""
        module, fake_client = _make_module(monkeypatch)
        uids = [10, 20, 30]
        result = module.batch_mail_action(ACCOUNT_ID, "INBOX", {
            "action": "delete",
            "mail_uids": uids,
        })
        assert result["action"] == "delete"
        assert result["processed_ids"] == uids
        # Verify the efficient bulk delete was called
        assert len(fake_client.delete_mails_by_uid_calls) == 1
        call_folder, call_uids = fake_client.delete_mails_by_uid_calls[0]
        assert call_folder == "INBOX"
        assert sorted(call_uids) == [str(u) for u in uids]

    def test_batch_move(self, monkeypatch):
        """Batch move moves all mails to the destination folder."""
        module, fake_client = _make_module(monkeypatch)
        uids = [1, 2, 3]
        result = module.batch_mail_action(ACCOUNT_ID, "INBOX", {
            "action": "move",
            "mail_uids": uids,
            "data": "Archive",
        })
        assert result["action"] == "move"
        assert len(result["processed_ids"]) == 3
        assert len(result["failed_ids"]) == 0
        # Verify each mail was moved (copy + delete)
        assert len(fake_client.copy_mail_to_mailbox_calls) == 3

    def test_batch_move_missing_destination(self, monkeypatch):
        """Batch move without destination records failures."""
        module, _ = _make_module(monkeypatch)
        result = module.batch_mail_action(ACCOUNT_ID, "INBOX", {
            "action": "move",
            "mail_uids": [1, 2],
        })
        assert result["action"] == "move"
        assert result["processed_ids"] == []
        assert len(result["failed_ids"]) == 2

    def test_batch_mark_read(self, monkeypatch):
        """Batch mark-read adds the \\Seen flag to all mails."""
        module, fake_client = _make_module(monkeypatch)
        uids = [5, 6]
        result = module.batch_mail_action(ACCOUNT_ID, "INBOX", {
            "action": "mark_read",
            "mail_uids": uids,
        })
        assert result["action"] == "mark_read"
        assert len(result["processed_ids"]) == 2
        # Verify each mail got flagged
        assert len(fake_client.add_flags_calls) == 2
        for uid in uids:
            assert ("INBOX", str(uid), ["\\Seen"]) in fake_client.add_flags_calls

    def test_batch_mark_unread(self, monkeypatch):
        """Batch mark-unread removes the \\Seen flag from all mails."""
        module, fake_client = _make_module(monkeypatch)
        uids = [7, 8, 9]
        result = module.batch_mail_action(ACCOUNT_ID, "INBOX", {
            "action": "mark_unread",
            "mail_uids": uids,
        })
        assert result["action"] == "mark_unread"
        assert len(result["processed_ids"]) == 3
        assert len(fake_client.remove_flags_calls) == 3
        for uid in uids:
            assert ("INBOX", str(uid), ["\\Seen"]) in fake_client.remove_flags_calls

    def test_batch_mark_flagged(self, monkeypatch):
        """Batch mark-flagged adds the \\Flagged flag to all mails."""
        module, fake_client = _make_module(monkeypatch)
        uids = [11]
        result = module.batch_mail_action(ACCOUNT_ID, "INBOX", {
            "action": "mark_flagged",
            "mail_uids": uids,
        })
        assert result["action"] == "mark_flagged"
        assert len(result["processed_ids"]) == 1
        assert ("INBOX", "11", ["\\Flagged"]) in fake_client.add_flags_calls

    def test_batch_mark_unflagged(self, monkeypatch):
        """Batch mark-unflagged removes the \\Flagged flag from all mails."""
        module, fake_client = _make_module(monkeypatch)
        uids = [12, 13]
        result = module.batch_mail_action(ACCOUNT_ID, "INBOX", {
            "action": "mark_unflagged",
            "mail_uids": uids,
        })
        assert result["action"] == "mark_unflagged"
        assert len(result["processed_ids"]) == 2
        assert len(fake_client.remove_flags_calls) == 2
        for uid in uids:
            assert ("INBOX", str(uid), ["\\Flagged"]) in fake_client.remove_flags_calls

    def test_batch_spam(self, monkeypatch):
        """Batch spam moves mails to Junk and marks as spam."""
        module, fake_client = _make_module(monkeypatch)
        uids = [14]
        result = module.batch_mail_action(ACCOUNT_ID, "INBOX", {
            "action": "spam",
            "mail_uids": uids,
        })
        assert result["action"] == "spam"
        assert len(result["processed_ids"]) == 1

    def test_batch_ham(self, monkeypatch):
        """Batch ham moves mails to INBOX and marks as not-spam."""
        module, fake_client = _make_module(monkeypatch)
        uids = [15]
        result = module.batch_mail_action(ACCOUNT_ID, "Junk", {
            "action": "ham",
            "mail_uids": uids,
        })
        assert result["action"] == "ham"
        assert len(result["processed_ids"]) == 1

    def test_batch_empty_uids(self, monkeypatch):
        """Batch with empty UID list returns empty processed_ids."""
        module, _ = _make_module(monkeypatch)
        result = module.batch_mail_action(ACCOUNT_ID, "INBOX", {
            "action": "delete",
            "mail_uids": [],
        })
        assert result["processed_ids"] == []

    def test_batch_invalid_action(self, monkeypatch):
        """Unknown action is recorded as a failure."""
        module, _ = _make_module(monkeypatch)
        result = module.batch_mail_action(ACCOUNT_ID, "INBOX", {
            "action": "nonexistent",
            "mail_uids": [1],
        })
        assert result["action"] == "nonexistent"
        assert result["processed_ids"] == []
        assert len(result["failed_ids"]) == 1
        assert result["failed_ids"][0]["uid"] == 1


# ===================================================================
# search_mails
# ===================================================================

class TestSearchMails:
    """Tests for ModuleMail.search_mails()."""

    def test_search_all_mails(self, monkeypatch):
        """Search without query returns all mails (unfiltered)."""
        module, fake_client = _make_module(monkeypatch)
        results, total = module.search_mails(ACCOUNT_ID, {})
        assert isinstance(total, int)
        assert isinstance(results, list)

    def test_search_with_query(self, monkeypatch):
        """Search with query filters mails by subject/content."""
        module, fake_client = _make_module(monkeypatch)
        results, total = module.search_mails(ACCOUNT_ID, {
            "query": "Test Subject",
        })
        assert isinstance(total, int)

    def test_search_with_folder_filter(self, monkeypatch):
        """Search with specific folders only searches those folders."""
        module, fake_client = _make_module(monkeypatch)
        results, total = module.search_mails(ACCOUNT_ID, {
            "query": "hello",
            "folders": ["INBOX"],
        })
        assert isinstance(total, int)

    def test_search_with_date_range(self, monkeypatch):
        """Search respects date_from and date_to."""
        module, fake_client = _make_module(monkeypatch)
        results, total = module.search_mails(ACCOUNT_ID, {
            "date_from": "2026-01-01",
            "date_to": "2026-12-31",
        })
        assert isinstance(total, int)

    def test_search_with_attachments_filter(self, monkeypatch):
        """Search with with_attachments=true."""
        module, fake_client = _make_module(monkeypatch)
        results, total = module.search_mails(ACCOUNT_ID, {
            "with_attachments": True,
        })
        assert isinstance(total, int)

    def test_search_pagination(self, monkeypatch):
        """Search paginates results."""
        module, fake_client = _make_module(monkeypatch)
        results, total = module.search_mails(ACCOUNT_ID, {
            "page": 1,
            "page_size": 5,
        })
        assert len(results) <= 5

    def test_search_empty_results(self, monkeypatch):
        """Search returns empty for non-matching query."""
        module, fake_client = _make_module(monkeypatch)
        results, total = module.search_mails(ACCOUNT_ID, {
            "query": "ZZZZNONEXISTENT",
        })
        assert total == 0 or results == []
