"""Coverage-focused unit tests for the file storage managers.

Targets ``app.manager.storage.DbFileStorage`` (binary blob store over
sogo6_file_storage) and ``app.manager.storage.ClientStorageDatabase`` (managed
media-reference adapter over DbFileStorage). Every path is exercised against a
mocked SQL client — no real database, network or redis:

* DbFileStorage: init (default + overridden max size), write() happy path and
  its three validation error branches (key format, size, content type),
  content-type parameter stripping / case normalisation, is_equal (match,
  mismatch, absent), read (present + absent), delete, all_keys and
  purge_older_than.
* ClientStorageDatabase: save/load/matches/delete (reference vs plain URI),
  _all_references, purge_older_than, both ``_run`` connection modes (shared db
  reused+never closed; short-lived connection opened+closed per operation,
  including close-on-error in the finally), and _connect building the client
  from the process setting.
"""
import hashlib
from unittest.mock import MagicMock, patch

import pytest

from app.config.db import tables as tbl
from app.manager.storage.ClientStorage import ClientStorage
from app.manager.storage.ClientStorageDatabase import ClientStorageDatabase
from app.manager.storage.DbFileStorage import DbFileStorage
from app.manager.storage.StorageSource import StorageSource
from app.utils import errors as err
from app.utils.exceptions import RequestException

_MOD = "app.manager.storage.ClientStorageDatabase"
_PREFIX = ClientStorage.REFERENCE_PREFIX


# ===================== DbFileStorage =====================

class TestDbFileStorageInit:
    def test_default_max_file_size(self):
        store = DbFileStorage(MagicMock())
        assert store.MAX_FILE_SIZE == 100 * 1024 * 1024

    def test_max_file_size_override_and_db_stored(self):
        db = MagicMock()
        store = DbFileStorage(db, max_file_size=64)
        assert store.MAX_FILE_SIZE == 64
        assert store._db is db

    def test_hash_is_sha256_hexdigest(self):
        assert DbFileStorage._hash(b"png") == hashlib.sha256(b"png").hexdigest()


class TestDbFileStorageWrite:
    def test_write_inserts_full_row(self):
        db = MagicMock()
        DbFileStorage(db).write("k1", b"\x89PNG\r\n", "image/png", "contact")
        kwargs = db.insert_in_table.call_args.kwargs
        cols, values = kwargs["column_tuple"], kwargs["values_tuple"][0]
        assert values[cols.index(tbl.COL_FS_KEY.name)] == "k1"
        assert values[cols.index(tbl.COL_FS_SOURCE.name)] == "contact"
        assert values[cols.index(tbl.COL_FS_DATA.name)] == b"\x89PNG\r\n"
        assert values[cols.index(tbl.COL_FS_CONTENT_TYPE.name)] == "image/png"
        assert values[cols.index(tbl.COL_FS_CONTENT_HASH.name)] == hashlib.sha256(b"\x89PNG\r\n").hexdigest()
        assert values[cols.index(tbl.COL_FS_CREATED_AT.name)] is not None
        assert values[cols.index(tbl.COL_FS_UPDATED_AT.name)] is not None

    def test_write_accepts_content_type_with_parameters(self):
        # RFC 9110 media type parameters are stripped before the allow-list match.
        db = MagicMock()
        DbFileStorage(db).write("k2", b"v", "text/vcard; charset=utf-8; version=3.0", "agent")
        kwargs = db.insert_in_table.call_args.kwargs
        cols = kwargs["column_tuple"]
        assert kwargs["values_tuple"][0][cols.index(tbl.COL_FS_CONTENT_TYPE.name)] == \
            "text/vcard; charset=utf-8; version=3.0"

    def test_write_normalises_uppercase_content_type(self):
        db = MagicMock()
        DbFileStorage(db).write("k3", b"v", "IMAGE/PNG", "contact")
        db.insert_in_table.assert_called_once()

    def test_write_rejects_invalid_key_format(self):
        db = MagicMock()
        with pytest.raises(RequestException) as exc:
            DbFileStorage(db).write("bad key!", b"x", "image/png", "contact")
        assert exc.value.error == err.ERROR_FILE_TYPE_NOT_ALLOWED
        assert "Invalid file key format" in exc.value.args[0]
        assert "bad ke" in exc.value.args[0]  # truncated to 50 chars
        db.insert_in_table.assert_not_called()

    def test_write_rejects_empty_key(self):
        with pytest.raises(RequestException) as exc:
            DbFileStorage(MagicMock()).write("", b"x", "image/png", "contact")
        assert exc.value.error == err.ERROR_FILE_TYPE_NOT_ALLOWED

    def test_write_rejects_oversized_file(self):
        db = MagicMock()
        with pytest.raises(RequestException) as exc:
            DbFileStorage(db, max_file_size=4).write("k1", b"12345", "image/png", "contact")
        assert exc.value.error == err.ERROR_FILE_TOO_LARGE
        assert "exceeds maximum allowed" in exc.value.args[0]
        db.insert_in_table.assert_not_called()

    def test_write_rejects_disallowed_content_type(self):
        db = MagicMock()
        with pytest.raises(RequestException) as exc:
            DbFileStorage(db).write("k1", b"x", "foo/bar", "contact")
        assert exc.value.error == err.ERROR_FILE_TYPE_NOT_ALLOWED
        assert "not allowed" in exc.value.args[0]
        db.insert_in_table.assert_not_called()


class TestDbFileStorageIsEqual:
    def test_true_when_stored_hash_matches(self):
        db = MagicMock()
        db.select_from_table.return_value = iter([(hashlib.sha256(b"png").hexdigest(),)])
        assert DbFileStorage(db).is_equal("k1", b"png", "contact") is True
        assert db.select_from_table.call_args.kwargs["limit"] == 1

    def test_false_when_stored_hash_differs(self):
        db = MagicMock()
        db.select_from_table.return_value = iter([(hashlib.sha256(b"other").hexdigest(),)])
        assert DbFileStorage(db).is_equal("k1", b"png", "contact") is False

    def test_false_when_row_absent(self):
        db = MagicMock()
        db.select_from_table.return_value = iter([])
        assert DbFileStorage(db).is_equal("missing", b"png", "contact") is False


class TestDbFileStorageRead:
    def test_returns_bytes_and_content_type_from_memoryview(self):
        db = MagicMock()
        db.select_from_table.return_value = iter([(memoryview(b"png-bytes"), "image/png")])
        result = DbFileStorage(db).read("k1", "contact")
        assert result == (b"png-bytes", "image/png")
        assert isinstance(result[0], bytes)

    def test_returns_none_when_absent(self):
        db = MagicMock()
        db.select_from_table.return_value = iter([])
        assert DbFileStorage(db).read("missing", "contact") is None


class TestDbFileStorageDelete:
    def test_delete_is_scoped_by_key_and_source(self):
        db = MagicMock()
        DbFileStorage(db).delete("k1", "agent")
        cond = db.delete_row_in_table.call_args.kwargs["condition"]
        assert cond.conditions[0].param_name == tbl.COL_FS_KEY.name
        assert cond.conditions[0].param_value == "k1"
        assert cond.conditions[1].param_name == tbl.COL_FS_SOURCE.name
        assert cond.conditions[1].param_value == "agent"


class TestDbFileStorageAllKeys:
    def test_returns_set_of_keys_for_source(self):
        db = MagicMock()
        db.select_from_table.return_value = iter([("k1",), ("k2",)])
        assert DbFileStorage(db).all_keys("contact") == {"k1", "k2"}
        cond = db.select_from_table.call_args.kwargs["condition"]
        assert cond.param_name == tbl.COL_FS_SOURCE.name
        assert cond.param_value == "contact"


class TestDbFileStoragePurgeOlderThan:
    def test_returns_count_and_builds_age_condition(self):
        db = MagicMock()
        db.delete_row_in_table.return_value = 2
        removed = DbFileStorage(db).purge_older_than(900, "contact")
        assert removed == 2
        cond = db.delete_row_in_table.call_args.kwargs["condition"]
        assert cond.conditions[0].param_name == tbl.COL_FS_SOURCE.name
        assert cond.conditions[0].param_value == "contact"
        assert cond.conditions[1].param_name == tbl.COL_FS_CREATED_AT.name
        assert db.delete_row_in_table.call_args.kwargs["table_name"] == tbl.TABLE_FILE_STORAGE.name


# ===================== ClientStorageDatabase =====================

def _adapter(process_setting=None, source=StorageSource.CONTACT, db=None):
    return ClientStorageDatabase(process_setting or MagicMock(), source, db=db)


class TestClientStorageDatabaseInit:
    def test_stores_process_setting_and_db(self):
        ps = MagicMock()
        db = MagicMock()
        adapter = ClientStorageDatabase(ps, StorageSource.AGENT, db=db)
        assert adapter._process_setting is ps
        assert adapter._db is db
        assert adapter._source == StorageSource.AGENT


class TestClientStorageDatabaseSave:
    def test_save_writes_uuid_key_and_returns_managed_reference(self):
        storage = MagicMock()
        db = MagicMock()
        with patch(f"{_MOD}.DbFileStorage", return_value=storage) as build, \
             patch(f"{_MOD}.generate_uuid", return_value="fixed-key"):
            ref = _adapter(db=db).save(b"\xff\xd8\xff", "image/jpeg")
        assert ref == f"{_PREFIX}fixed-key"
        assert storage.write.call_args.args == \
            ("fixed-key", b"\xff\xd8\xff", "image/jpeg", StorageSource.CONTACT)
        build.assert_called_once_with(db)


class TestClientStorageDatabaseLoad:
    def test_load_reads_behind_reference(self):
        storage = MagicMock()
        storage.read.return_value = (b"png", "image/png")
        with patch(f"{_MOD}.DbFileStorage", return_value=storage):
            result = _adapter(db=MagicMock()).load(f"{_PREFIX}abc")
        assert result == (b"png", "image/png")
        assert storage.read.call_args.args == ("abc", StorageSource.CONTACT)

    def test_load_returns_none_for_plain_uri(self):
        storage = MagicMock()
        with patch(f"{_MOD}.DbFileStorage", return_value=storage):
            assert _adapter(db=MagicMock()).load("https://example.com/p.png") is None
        storage.read.assert_not_called()


class TestClientStorageDatabaseMatches:
    def test_matches_delegates_is_equal_for_reference(self):
        storage = MagicMock()
        storage.is_equal.return_value = True
        with patch(f"{_MOD}.DbFileStorage", return_value=storage):
            assert _adapter(db=MagicMock()).matches(f"{_PREFIX}abc", b"png") is True
        assert storage.is_equal.call_args.args == ("abc", b"png", StorageSource.CONTACT)

    def test_matches_returns_false_for_plain_uri(self):
        storage = MagicMock()
        with patch(f"{_MOD}.DbFileStorage", return_value=storage):
            assert _adapter(db=MagicMock()).matches("https://example.com/p.png", b"png") is False
        storage.is_equal.assert_not_called()


class TestClientStorageDatabaseDelete:
    def test_delete_removes_reference(self):
        storage = MagicMock()
        with patch(f"{_MOD}.DbFileStorage", return_value=storage):
            _adapter(db=MagicMock()).delete(f"{_PREFIX}abc")
        assert storage.delete.call_args.args == ("abc", StorageSource.CONTACT)

    def test_delete_is_noop_for_plain_uri(self):
        storage = MagicMock()
        with patch(f"{_MOD}.DbFileStorage", return_value=storage):
            _adapter(db=MagicMock()).delete("https://example.com/p.png")
        storage.delete.assert_not_called()


class TestClientStorageDatabaseAllReferences:
    def test_maps_keys_to_references(self):
        storage = MagicMock()
        storage.all_keys.return_value = {"k1", "k2"}
        with patch(f"{_MOD}.DbFileStorage", return_value=storage):
            refs = _adapter(source=StorageSource.AGENT, db=MagicMock())._all_references()
        assert refs == {f"{_PREFIX}k1", f"{_PREFIX}k2"}
        assert storage.all_keys.call_args.args == (StorageSource.AGENT,)


class TestClientStorageDatabasePurge:
    def test_purge_older_than_delegates_with_source(self):
        storage = MagicMock()
        storage.purge_older_than.return_value = 3
        with patch(f"{_MOD}.DbFileStorage", return_value=storage):
            removed = _adapter(source=StorageSource.AGENT, db=MagicMock()).purge_older_than(120)
        assert removed == 3
        assert storage.purge_older_than.call_args.args == (120, StorageSource.AGENT)


class TestClientStorageDatabaseRunModes:
    def test_shared_db_is_reused_and_never_closed(self):
        storage = MagicMock()
        db = MagicMock()
        with patch(f"{_MOD}.DbFileStorage", return_value=storage) as build, \
             patch(f"{_MOD}.import_and_instantiate_manager") as connect:
            _adapter(db=db).delete(f"{_PREFIX}abc")
        connect.assert_not_called()
        db.close.assert_not_called()
        build.assert_called_once_with(db)

    def test_without_db_opens_and_closes_short_lived_connection(self):
        storage = MagicMock()
        storage.read.return_value = (b"png", "image/png")
        opened = MagicMock()
        with patch(f"{_MOD}.DbFileStorage", return_value=storage), \
             patch(f"{_MOD}.import_and_instantiate_manager", return_value=opened) as connect:
            result = _adapter(db=None).load(f"{_PREFIX}abc")
        assert result == (b"png", "image/png")
        connect.assert_called_once()
        opened.connect.assert_called_once()
        opened.close.assert_called_once()

    def test_without_db_closes_connection_even_when_op_raises(self):
        storage = MagicMock()
        storage.read.side_effect = RuntimeError("boom")
        opened = MagicMock()
        with patch(f"{_MOD}.DbFileStorage", return_value=storage), \
             patch(f"{_MOD}.import_and_instantiate_manager", return_value=opened):
            with pytest.raises(RuntimeError, match="boom"):
                _adapter(db=None).load(f"{_PREFIX}abc")
        opened.connect.assert_called_once()
        opened.close.assert_called_once()  # finally branch


class TestClientStorageDatabaseConnect:
    def test_builds_client_from_process_setting(self):
        ps = MagicMock()
        ps.SOGO_P_DB_TYPE = "PostgreSQL"
        ps.get_db_settings.return_value = {"db_name": "sogo"}
        opened = MagicMock()
        with patch(f"{_MOD}.import_and_instantiate_manager", return_value=opened) as inst:
            adapter = ClientStorageDatabase(ps, StorageSource.CONTACT)  # db=None
            db = adapter._connect()
        assert db is opened
        inst.assert_called_once_with(
            module_path="app.manager.db",
            module_and_class_name="ClientPostgreSQL",
            module_args={"db_name": "sogo"},
        )
        opened.connect.assert_called_once()
