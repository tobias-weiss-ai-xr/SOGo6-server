# pylint: disable=invalid-sequence-index
"""Unit tests for RepositoryAddressBook (39% -> high)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest

from app.config.db import tables as tbl
from app.module.contact.model.CardAddressBook import CardAddressBook
from app.module.contact.model.enums.CardSourceType import CardSourceType
from app.module.contact.repository.RepositoryAddressBook import RepositoryAddressBook
from app.utils import errors as err
from app.utils.exceptions import BugException, RequestException


def make_repo():
    db = mock.MagicMock()
    return db, RepositoryAddressBook(db)


def make_book(**overrides):
    base = dict(
        user_uid="user1",
        name="Personal",
        id=1,
        key="ab-1",
        description="desc",
        is_default=True,
        source_type=CardSourceType.LOCAL,
        ctag=7,
        sync_config=None,
    )
    base.update(overrides)
    return CardAddressBook(**base)


# Row: id, key, user_uid, is_default, source_type, name, description, ctag,
# sync_config, created_at, updated_at
def make_row_values(rid=1, key="ab-1", user_uid="user1", is_default=True,
                    source_type="local", name="Personal", description="desc",
                    ctag=7, sync_config=None):
    return [rid, key, user_uid, is_default, source_type, name, description,
            ctag, sync_config, "2024-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"]


class TestRowToAddressbook:
    def test_maps_row(self):
        ab = RepositoryAddressBook._row_to_addressbook(make_row_values())
        assert ab.id == 1
        assert ab.key == "ab-1"
        assert ab.user_uid == "user1"
        assert ab.is_default is True
        assert ab.source_type == CardSourceType.LOCAL
        assert ab.name == "Personal"
        assert ab.ctag == 7


class TestInsert:
    def test_insert_ok(self):
        db, repo = make_repo()
        db.insert_in_table.return_value = 1
        db.select_from_table.return_value = [make_row_values()]
        out = repo.insert(make_book())
        assert out.id == 1
        kwargs = db.insert_in_table.call_args.kwargs
        assert kwargs["table_name"] == tbl.TABLE_ADDRESSBOOK.name
        assert "id" not in kwargs["column_tuple"]
        vals = kwargs["values_tuple"][0]
        assert vals[0] == "ab-1"
        assert vals[3] == "local"
        # fetch-back called
        db.select_from_table.assert_called_once()

    def test_insert_unique_violation(self):
        db, repo = make_repo()
        db.insert_in_table.side_effect = BugException("dup")
        with pytest.raises(RequestException) as e:
            repo.insert(make_book())
        assert e.value.error.c == err.ERROR_CONTACT_ADDRESSBOOK_DUPLICATE.c

    def test_insert_wrong_row_count(self):
        db, repo = make_repo()
        db.insert_in_table.return_value = 0
        with pytest.raises(BugException):
            repo.insert(make_book())

    def test_insert_fetch_back_missing(self):
        db, repo = make_repo()
        db.insert_in_table.return_value = 1
        db.select_from_table.return_value = []
        with pytest.raises(BugException):
            repo.insert(make_book())


class TestFind:
    def test_find_by_key_found(self):
        db, repo = make_repo()
        db.select_from_table.return_value = [make_row_values()]
        ab = repo.find_by_key("user1", "ab-1")
        assert ab is not None and ab.key == "ab-1"
        assert db.select_from_table.call_args.kwargs["limit"] == 1

    def test_find_by_key_missing(self):
        db, repo = make_repo()
        db.select_from_table.return_value = []
        assert repo.find_by_key("user1", "ab-x") is None

    def test_find_by_key_unscoped_found(self):
        db, repo = make_repo()
        db.select_from_table.return_value = [make_row_values()]
        ab = repo.find_by_key_unscoped("ab-1")
        assert ab is not None

    def test_find_by_key_unscoped_missing(self):
        db, repo = make_repo()
        db.select_from_table.return_value = []
        assert repo.find_by_key_unscoped("ab-x") is None

    def test_get_default_for_user_found(self):
        db, repo = make_repo()
        db.select_from_table.return_value = [make_row_values()]
        ab = repo.get_default_for_user("user1")
        assert ab is not None

    def test_get_default_for_user_missing(self):
        db, repo = make_repo()
        db.select_from_table.return_value = []
        assert repo.get_default_for_user("user1") is None

    def test_find_all(self):
        db, repo = make_repo()
        db.select_from_table.return_value = [make_row_values(rid=1), make_row_values(rid=2, key="ab-2")]
        books = repo.find_all("user1")
        assert len(books) == 2
        assert db.select_from_table.call_args.kwargs["sort_by"] == tbl.COL_ID.name


class TestUpdate:
    def test_update_ok(self):
        db, repo = make_repo()
        db.update_in_table.return_value = 1
        repo.update(make_book())
        kwargs = db.update_in_table.call_args.kwargs
        assert kwargs["values_list"][0] == "Personal"
        assert kwargs["column_tuple"][-1] == tbl.COL_AB_UPDATED_AT.name

    def test_update_missing_id(self):
        _, repo = make_repo()
        with pytest.raises(BugException):
            repo.update(make_book(id=None))

    def test_update_not_found(self):
        db, repo = make_repo()
        db.update_in_table.return_value = 0
        with pytest.raises(RequestException) as e:
            repo.update(make_book())
        assert e.value.error.c == err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND.c

    def test_clear_default(self):
        db, repo = make_repo()
        repo.clear_default("user1", exclude_id=3)
        kwargs = db.update_in_table.call_args.kwargs
        assert kwargs["values_list"] == [False]
        assert kwargs["column_tuple"] == (tbl.COL_AB_IS_DEFAULT.name,)


class TestDelete:
    def test_delete_ok(self):
        db, repo = make_repo()
        db.delete_row_in_table.return_value = 1
        repo.delete(1)
        db.delete_row_in_table.assert_called_once()

    def test_delete_not_found(self):
        db, repo = make_repo()
        db.delete_row_in_table.return_value = 0
        with pytest.raises(RequestException) as e:
            repo.delete(1)
        assert e.value.error.c == err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND.c
