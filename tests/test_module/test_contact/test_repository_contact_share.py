# pylint: disable=invalid-sequence-index
"""Unit tests for RepositoryContactShare (49% -> high)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")


import pytest

from app.config.db import tables as tbl
from app.module.contact.model.ContactShare import ContactShare
from app.module.contact.model.enums.ContactShareLevel import ContactShareLevel
from app.module.contact.repository.RepositoryContactShare import RepositoryContactShare
from app.utils import errors as err
from app.utils.exceptions import BugException, RequestException


def make_repo():
    db = mock.MagicMock()
    return db, RepositoryContactShare(db)


def make_share(**overrides):
    base = dict(
        user_uid="user1",
        addressbook_key="ab-key-1",
        share_level=ContactShareLevel.MODIFY,
    )
    base.update(overrides)
    return ContactShare(**base)


# Contact share row: id, addressbook_key, user_uid, share_level, created_at
def make_row_values(addressbook_key="ab-key-1", user_uid="user1", share_level="modify", rid=1):
    return [rid, addressbook_key, user_uid, share_level, "2024-01-01T00:00:00+00:00"]


class TestRowToShare:
    def test_maps_row(self):
        share = RepositoryContactShare._row_to_share(make_row_values())
        assert share.user_uid == "user1"
        assert share.addressbook_key == "ab-key-1"
        assert share.share_level == ContactShareLevel.MODIFY


class TestInsert:
    def test_insert_ok(self):
        db, repo = make_repo()
        db.insert_in_table.return_value = 1
        out = repo.insert(make_share())
        assert out.addressbook_key == "ab-key-1"
        args, kwargs = db.insert_in_table.call_args
        assert kwargs["table_name"] == tbl.TABLE_CONTACT_SHARE.name
        assert "id" not in kwargs["column_tuple"]
        assert kwargs["values_tuple"][0][0] == "ab-key-1"
        assert kwargs["values_tuple"][0][2] == "modify"

    def test_insert_unique_violation(self):
        db, repo = make_repo()
        db.insert_in_table.side_effect = BugException("dup")
        with pytest.raises(RequestException) as e:
            repo.insert(make_share())
        assert e.value.error.c == err.ERROR_CONTACT_ADDRESSBOOK_DUPLICATE.c

    def test_insert_wrong_row_count(self):
        db, repo = make_repo()
        db.insert_in_table.return_value = 2
        with pytest.raises(BugException):
            repo.insert(make_share())


class TestFind:
    def test_find_by_addressbook_key(self):
        db, repo = make_repo()
        db.select_from_table.return_value = [make_row_values()]
        rows = repo.find_by_addressbook_key("ab-key-1")
        assert len(rows) == 1
        assert rows[0].user_uid == "user1"
        assert "sort_by" in db.select_from_table.call_args.kwargs

    def test_find_by_addressbook_and_user_found(self):
        db, repo = make_repo()
        db.select_from_table.return_value = [make_row_values()]
        share = repo.find_by_addressbook_and_user("ab-key-1", "user1")
        assert share is not None

    def test_find_by_addressbook_and_user_missing(self):
        db, repo = make_repo()
        db.select_from_table.return_value = []
        assert repo.find_by_addressbook_and_user("ab-key-1", "user1") is None

    def test_find_addressbook_keys_for_user(self):
        db, repo = make_repo()
        db.select_from_table.return_value = [("ab-a",), ("ab-b",)]
        keys = repo.find_addressbook_keys_for_user("user1")
        assert keys == ["ab-a", "ab-b"]


class TestDelete:
    def test_delete_ok(self):
        db, repo = make_repo()
        db.delete_row_in_table.return_value = 1
        repo.delete("ab-key-1", "user1")
        db.delete_row_in_table.assert_called_once()

    def test_delete_not_found(self):
        db, repo = make_repo()
        db.delete_row_in_table.return_value = 0
        with pytest.raises(RequestException) as e:
            repo.delete("ab-key-1", "user1")
        assert e.value.error.c == err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND.c
