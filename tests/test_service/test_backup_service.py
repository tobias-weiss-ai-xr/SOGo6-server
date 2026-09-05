"""Unit tests for BackupService covering every per-source dump, retention,
verification and restore branch with a fake Redis + fake subprocess/psycopg.

Complements the functional suite in tests/test_api/test_backup.py by exercising
the branchy internals (readers for each key type, tamper gates, prune edge
cases, postgres success/failure, ldap bind/timeout/skip, config redaction).
"""
import gzip
import json
import os
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

from app.service.backup.BackupService import BackupService, _redact


class FakeRedis:
    """Minimal dict-backed fake exposing the redis primitives the service uses."""

    def __init__(self):
        self.data = {}
        self.types = {}
        self.ttls = {}

    # --- history / cache interface ---
    def get(self, key, as_type=None):
        return self.data.get(key)

    def set(self, key, value, ttl=None, px=None):
        self.data[key] = value
        self.types[key] = "string"
        self.ttls[key] = px

    # --- redis commands ---
    def scan_iter(self, match="*", count=200):
        for k in list(self.data.keys()):
            yield k

    def type(self, key):
        return self.types.get(key, "none")

    def pttl(self, key):
        if key not in self.data:
            return -2
        px = self.ttls.get(key)
        return -1 if px is None else px

    def hgetall(self, key):
        return dict(self.data[key])

    def hset(self, key, mapping=None):
        self.types[key] = "hash"
        self.data[key] = dict(mapping or {})

    def lrange(self, key, start, end):
        return list(self.data[key])

    def rpush(self, key, *values):
        if key not in self.data or self.types.get(key) != "list":
            self.data[key] = []
            self.types[key] = "list"
        self.data[key].extend(values)

    def smembers(self, key):
        return set(self.data[key])

    def sadd(self, key, *values):
        if key not in self.data or self.types.get(key) != "set":
            self.data[key] = set()
            self.types[key] = "set"
        self.data[key].update(values)

    def zrange(self, key, start, end, withscores=False):
        items = self.data[key]
        if withscores:
            return [(m, s) for m, s in items]
        return [m for m, s in items]

    def zadd(self, key, mapping=None):
        self.types[key] = "zset"
        self.data[key] = list(mapping.items())

    def pexpire(self, key, ms):
        self.ttls[key] = ms

    def delete(self, *keys):
        for k in keys:
            self.data.pop(k, None)
            self.types.pop(k, None)
            self.ttls.pop(k, None)


def make_service(tmp_path, env=None, **overrides):
    cache = FakeRedis()
    base_env = {"SOGO_BACKUP_DIR": str(tmp_path)}
    if env:
        base_env.update(env)
    if "env" in overrides:
        base_env.update(overrides.pop("env"))
    svc = BackupService(cache=cache, backup_dir=tmp_path, env=base_env, **overrides)
    svc.raw = cache  # ensure raw == our fake
    return svc, cache


# --------------------------------------------------------------------- #
# _read_key: every value kind
# --------------------------------------------------------------------- #
class TestReadKey:
    def test_string(self, tmp_path):
        svc, cache = make_service(tmp_path)
        cache.set("s:1", "hello")
        entry = svc._read_key("s:1")
        assert entry == {"key": "s:1", "type": "string", "value": "hello", "ttl_ms": None}

    def test_string_with_ttl(self, tmp_path):
        svc, cache = make_service(tmp_path)
        cache.set("s:1", "hello", px=5000)
        entry = svc._read_key("s:1")
        assert entry["ttl_ms"] == 5000

    def test_string_value_none_returns_none(self, tmp_path):
        svc, cache = make_service(tmp_path)
        cache.types["s:1"] = "string"
        cache.data["s:1"] = None
        assert svc._read_key("s:1") is None

    def test_key_vanished_between_scan_and_read(self, tmp_path):
        svc, cache = make_service(tmp_path)
        svc.raw.type = mock.Mock(return_value="string")
        svc.raw.pttl = mock.Mock(return_value=-2)
        assert svc._read_key("ghost") is None

    def test_hash(self, tmp_path):
        svc, cache = make_service(tmp_path)
        cache.hset("h:1", mapping={"a": "1"})
        entry = svc._read_key("h:1")
        assert entry["type"] == "hash"
        assert entry["value"] == {"a": "1"}

    def test_list(self, tmp_path):
        svc, cache = make_service(tmp_path)
        cache.rpush("l:1", "x", "y")
        entry = svc._read_key("l:1")
        assert entry["type"] == "list"
        assert entry["value"] == ["x", "y"]

    def test_set(self, tmp_path):
        svc, cache = make_service(tmp_path)
        cache.sadd("st:1", "a", "b")
        entry = svc._read_key("st:1")
        assert entry["type"] == "set"
        assert set(entry["value"]) == {"a", "b"}

    def test_zset(self, tmp_path):
        svc, cache = make_service(tmp_path)
        cache.zadd("z:1", {"m1": 1.5, "m2": 2.5})
        entry = svc._read_key("z:1")
        assert entry["type"] == "zset"
        assert entry["value"] == [{"member": "m1", "score": 1.5}, {"member": "m2", "score": 2.5}]

    def test_unknown_kind_returns_none(self, tmp_path):
        svc, cache = make_service(tmp_path)
        cache.types["k:1"] = "float"
        cache.data["k:1"] = 1.0
        assert svc._read_key("k:1") is None

    def test_exception_returns_none(self, tmp_path):
        svc, cache = make_service(tmp_path)
        svc.raw.type = mock.Mock(side_effect=RuntimeError("boom"))
        assert svc._read_key("k:1") is None


# --------------------------------------------------------------------- #
# _apply_snapshot: every kind + guards
# --------------------------------------------------------------------- #
class TestApplySnapshot:
    def _svc(self, tmp_path):
        svc, cache = make_service(tmp_path)
        return svc, cache

    def test_skips_entries_without_key(self, tmp_path):
        svc, cache = self._svc(tmp_path)
        applied = svc._apply_snapshot([
            {"key": None, "type": "string", "value": "x", "ttl_ms": None},
            {"key": "", "type": "string", "value": "x", "ttl_ms": None},
        ])
        assert applied == 0

    def test_skips_empty_non_string(self, tmp_path):
        svc, cache = self._svc(tmp_path)
        # empty non-string values fall through the `not value and kind != "string"` guard
        applied = svc._apply_snapshot([
            {"key": "h:1", "type": "hash", "value": {}, "ttl_ms": None},
            {"key": "st:1", "type": "set", "value": [], "ttl_ms": None},
        ])
        assert applied == 0

    def test_applies_string(self, tmp_path):
        svc, cache = self._svc(tmp_path)
        assert svc._apply_snapshot([{"key": "s:1", "type": "string", "value": 42, "ttl_ms": 3000}]) == 1
        assert cache.data["s:1"] == "42"
        assert cache.ttls["s:1"] == 3000

    def test_applies_hash(self, tmp_path):
        svc, cache = self._svc(tmp_path)
        cache.set("h:1", "stale")
        assert svc._apply_snapshot([{"key": "h:1", "type": "hash", "value": {"a": "1"}, "ttl_ms": None}]) == 1
        assert cache.data["h:1"] == {"a": "1"}

    def test_applies_list(self, tmp_path):
        svc, cache = self._svc(tmp_path)
        assert svc._apply_snapshot([{"key": "l:1", "type": "list", "value": ["a", "b"], "ttl_ms": None}]) == 1
        assert cache.data["l:1"] == ["a", "b"]

    def test_applies_set(self, tmp_path):
        svc, cache = self._svc(tmp_path)
        assert svc._apply_snapshot([{"key": "st:1", "type": "set", "value": ["x"], "ttl_ms": None}]) == 1
        assert cache.data["st:1"] == {"x"}

    def test_applies_zset(self, tmp_path):
        svc, cache = self._svc(tmp_path)
        assert svc._apply_snapshot(
            [{"key": "z:1", "type": "zset", "value": [{"member": "m", "score": 3.0}], "ttl_ms": None}]
        ) == 1
        assert cache.data["z:1"] == [("m", 3.0)]

    def test_skips_unknown_kind(self, tmp_path):
        svc, cache = self._svc(tmp_path)
        assert svc._apply_snapshot([{"key": "k:1", "type": "float", "value": 1.0, "ttl_ms": None}]) == 0


# --------------------------------------------------------------------- #
# _dump_redis + run_backup statuses
# --------------------------------------------------------------------- #
class TestDumpRedis:
    def test_dump_redis_snapshot(self, tmp_path):
        svc, cache = make_service(tmp_path)
        cache.set("s:1", "hello", px=1000)
        cache.hset("h:1", mapping={"a": "1"})
        cache.sadd("st:1", "x")
        result = svc._dump_redis(tmp_path)
        assert result["status"] == "completed"
        assert result["entries"] == 3
        artifact = tmp_path / result["artifact"]
        assert artifact.is_file()
        snapshot = json.loads(gzip.decompress(artifact.read_bytes()))
        kinds = {e["type"] for e in snapshot}
        assert kinds == {"string", "hash", "set"}

    def test_dump_redis_failure(self, tmp_path):
        svc, cache = make_service(tmp_path)
        svc.raw.scan_iter = mock.Mock(side_effect=RuntimeError("conn lost"))
        result = svc._dump_redis(tmp_path)
        assert result["status"] == "failed"
        assert "redis snapshot failed" in result["error"]

    def test_run_backup_status_failed_when_redis_fails(self, tmp_path):
        svc, cache = make_service(tmp_path)
        svc._dump_redis = mock.Mock(return_value={"status": "failed", "error": "x", "size_bytes": 0})
        entry = svc.run_backup()
        assert entry["status"] == "failed"

    def test_run_backup_status_degraded(self, tmp_path):
        svc, cache = make_service(tmp_path)
        svc._dump_redis = mock.Mock(return_value={"status": "completed", "size_bytes": 10})
        svc._dump_ldap = mock.Mock(return_value={"status": "failed", "error": "timeout", "size_bytes": 0})
        entry = svc.run_backup()
        assert entry["status"] == "degraded"

    def test_run_backup_completed_with_mailstore(self, tmp_path):
        svc, cache = make_service(tmp_path)
        for name in ("_dump_redis", "_dump_ldap", "_dump_postgres", "_dump_config"):
            setattr(svc, name, mock.Mock(return_value={"status": "completed", "size_bytes": 2 * 1048576}))
        svc._dump_mailstore = mock.Mock(return_value={"status": "skipped", "size_bytes": 0})
        entry = svc.run_backup(include_mailstore=True)
        svc._dump_mailstore.assert_called_once()
        assert entry["status"] == "completed"
        assert entry["size_mb"] == 8.0
        assert "sources" in entry

    def test_caches_none_defaults_to_sogo_cache(self, tmp_path, monkeypatch):
        fake = FakeRedis()
        monkeypatch.setattr("app.service.sogo_cache", lambda: fake)
        svc = BackupService(backup_dir=tmp_path, env={"SOGO_BACKUP_DIR": str(tmp_path)})
        assert svc.cache is fake
        assert svc.raw is fake


# --------------------------------------------------------------------- #
# ldap / postgres / mailstore / config sources
# --------------------------------------------------------------------- #
class TestLdapDump:
    def test_bind_dn_appended(self, tmp_path):
        svc, cache = make_service(tmp_path, env={
            "SOGO_LDAP_BINDDN": "cn=admin",
            "SOGO_LDAP_BINDPW": "pw",
        })
        with mock.patch("app.service.backup.BackupService.subprocess.run") as run:
            proc = mock.Mock()
            proc.returncode = 0
            proc.stdout = "dn: dc=sogo\n"
            proc.stderr = ""
            run.return_value = proc
            result = svc._dump_ldap(tmp_path)
        assert result["status"] == "completed"
        cmd = run.call_args[0][0]
        assert "-D" in cmd and "cn=admin" in cmd

    def test_lookup_success(self, tmp_path):
        svc, cache = make_service(tmp_path, env={"SOGO_LDAP_URI": "ldap://x"})
        with mock.patch("app.service.backup.BackupService.subprocess.run") as run:
            proc = mock.Mock()
            proc.returncode = 0
            proc.stdout = "dn: dc=sogo\n"
            proc.stderr = ""
            run.return_value = proc
            result = svc._dump_ldap(tmp_path)
        assert result["status"] == "completed"
        assert (tmp_path / "ldap.ldif").read_text() == "dn: dc=sogo\n"
        assert result["sha256"]

    def test_binary_missing(self, tmp_path):
        svc, cache = make_service(tmp_path)
        with mock.patch(
            "app.service.backup.BackupService.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = svc._dump_ldap(tmp_path)
        assert result["status"] == "skipped"
        assert "not available" in result["error"]

    def test_timeout_is_failed(self, tmp_path):
        svc, cache = make_service(tmp_path)
        with mock.patch(
            "app.service.backup.BackupService.subprocess.run",
            side_effect=__import__("subprocess").TimeoutExpired("ldapsearch", 5),
        ):
            result = svc._dump_ldap(tmp_path)
        assert result["status"] == "failed"
        assert "timed out" in result["error"]

    def test_nonzero_returncode_skips(self, tmp_path):
        svc, cache = make_service(tmp_path)
        with mock.patch("app.service.backup.BackupService.subprocess.run") as run:
            proc = mock.Mock()
            proc.returncode = 32
            proc.stdout = ""
            proc.stderr = "ldap_sasl_interactive_bind_s: Can't contact LDAP server"
            run.return_value = proc
            result = svc._dump_ldap(tmp_path)
        assert result["status"] == "skipped"
        assert "unreachable" in result["error"]


class TestPostgresDump:
    def _fake_psycopg(self, monkeypatch, conn=None, connect=None):
        fake = types.ModuleType("psycopg")
        fake.connect = connect or mock.Mock(return_value=conn)
        monkeypatch.setitem(sys.modules, "psycopg", fake)
        return fake

    def _conn_with_tables(self):
        conn = mock.Mock()
        cur1 = mock.Mock()
        cur1.fetchall.return_value = [("users",), ("emails",)]
        cur2 = mock.Mock()
        cur2.fetchall.return_value = [("u1", 42)]
        cur3 = mock.Mock()
        cur3.fetchall.return_value = []
        cm = mock.MagicMock()
        cm.__enter__.side_effect = [cur1, cur2, cur3]
        conn.cursor.return_value = cm
        return conn

    def test_psycopg_missing_is_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "psycopg", None)
        svc, cache = make_service(tmp_path, env={"SOGO_P_DB_HOST": "db"})
        result = svc._dump_postgres(tmp_path)
        assert result["status"] == "skipped"
        assert "not installed" in result["error"]

    def test_no_db_host_skips(self, tmp_path):
        svc, cache = make_service(tmp_path, env={})
        result = svc._dump_postgres(tmp_path)
        assert result["status"] == "skipped"
        assert "SOGO_P_DB_HOST" in result["error"]

    def test_success(self, tmp_path, monkeypatch):
        conn = self._conn_with_tables()
        self._fake_psycopg(monkeypatch, conn=conn)
        svc, cache = make_service(tmp_path, env={"SOGO_P_DB_HOST": "db"})
        result = svc._dump_postgres(tmp_path)
        conn.close.assert_called_once()
        assert result["status"] == "completed"
        assert result["tables"] == 2
        artifact = tmp_path / result["artifact"]
        assert artifact.is_file()
        payload = json.loads(gzip.decompress(artifact.read_bytes()))
        assert "users" in payload["tables"]

    def test_connect_failure_skips(self, tmp_path, monkeypatch):
        self._fake_psycopg(monkeypatch, connect=mock.Mock(side_effect=RuntimeError("conn refused")))
        svc, cache = make_service(tmp_path, env={"SOGO_P_DB_HOST": "db"})
        result = svc._dump_postgres(tmp_path)
        assert result["status"] == "skipped"
        assert "unreachable" in result["error"]

    def test_query_failure_closes_conn(self, tmp_path, monkeypatch):
        conn = mock.Mock()
        cur = mock.Mock()
        cur.fetchall.side_effect = RuntimeError("table gone")
        cm = mock.MagicMock()
        cm.__enter__.return_value = cur
        conn.cursor.return_value = cm
        self._fake_psycopg(monkeypatch, conn=conn)
        svc, cache = make_service(tmp_path, env={"SOGO_P_DB_HOST": "db"})
        result = svc._dump_postgres(tmp_path)
        assert result["status"] == "skipped"
        conn.close.assert_called_once()

    def test_failure_close_itself_raises_is_swallowed(self, tmp_path, monkeypatch):
        conn = mock.Mock()
        cur = mock.Mock()
        cur.fetchall.side_effect = RuntimeError("table gone")
        cm = mock.MagicMock()
        cm.__enter__.return_value = cur
        conn.cursor.return_value = cm
        conn.close.side_effect = RuntimeError("close exploded")
        self._fake_psycopg(monkeypatch, conn=conn)
        svc, cache = make_service(tmp_path, env={"SOGO_P_DB_HOST": "db"})
        result = svc._dump_postgres(tmp_path)
        assert result["status"] == "skipped"  # finally did not mask the skip


class TestMailstoreAndConfig:
    def test_mailstore_without_host_skips(self, tmp_path):
        svc, cache = make_service(tmp_path, env={})
        result = svc._dump_mailstore(tmp_path)
        assert result["status"] == "skipped"
        assert "not configured" in result["error"]

    def test_mailstore_with_host_skips_unimplemented(self, tmp_path):
        svc, cache = make_service(tmp_path, env={"SOGO_STALWART_IMAP_ADMIN_HOST": "imap.example.org"})
        result = svc._dump_mailstore(tmp_path)
        assert result["status"] == "skipped"
        assert "not implemented" in result["error"]

    def test_dump_config_redacts_secrets(self, tmp_path):
        svc, cache = make_service(tmp_path, env={
            "SOGO_DB_PASSWORD": "hunter2",
            "SOGO_PUBLIC_HOSTNAME": "mail.example.org",
        })
        result = svc._dump_config(tmp_path)
        assert result["status"] == "completed"
        config = json.loads((tmp_path / "config.json").read_text())
        assert config["SOGO_DB_PASSWORD"] == "***"
        assert config["SOGO_PUBLIC_HOSTNAME"] == "mail.example.org"
        assert result["vars"] == 3


# --------------------------------------------------------------------- #
# verify / restore
# --------------------------------------------------------------------- #
def _write_backup(tmp_path, backup_id, sources=None, tamper=False, bad_manifest=None):
    d = tmp_path / f"backup-{backup_id}"
    d.mkdir(parents=True, exist_ok=True)
    if sources is None:
        gz = gzip.compress(json.dumps([{"key": "s:1", "type": "string", "value": "v", "ttl_ms": None}]).encode())
        sources = {
            "redis": {
                "artifact": "redis_snapshot.json.gz",
                "sha256": hashlib_hex(gz),
                "status": "completed",
            }
        }
        (d / "redis_snapshot.json.gz").write_bytes(gz)
    manifest = {
        "id": backup_id,
        "timestamp": 100.0,
        "sources": sources,
    }
    if bad_manifest is not None:
        d.joinpath("manifest.json").write_text(bad_manifest)
    else:
        d.joinpath("manifest.json").write_text(json.dumps(manifest))
    if tamper:
        p = d / "redis_snapshot.json.gz"
        p.write_bytes(p.read_bytes() + b"!")
    return d


def hashlib_hex(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()


class TestVerify:
    def test_verify_not_found(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = svc.verify("missing")
        assert result["found"] is False
        assert "not found" in result["reason"]

    def test_verify_manifest_unreadable(self, tmp_path):
        _write_backup(tmp_path, "b1", bad_manifest="{oops")
        svc, _ = make_service(tmp_path)
        result = svc.verify("b1")
        assert result["manifest_parseable"] is False
        assert "unreadable" in result["reason"]

    def test_verify_artifact_missing(self, tmp_path):
        gz = gzip.compress(b"[]")
        _write_backup(tmp_path, "b1", sources={
            "redis": {"artifact": "redis_snapshot.json.gz", "sha256": hashlib_hex(gz)},
        })
        svc, _ = make_service(tmp_path)
        result = svc.verify("b1")
        assert result["valid"] is False
        assert result["artifact_missing"] == ["redis_snapshot.json.gz"]

    def test_verify_checksum_mismatch(self, tmp_path):
        gz = gzip.compress(b"[]")
        d = _write_backup(tmp_path, "b1", sources={
            "redis": {"artifact": "redis_snapshot.json.gz", "sha256": "0" * 64},
        })
        (d / "redis_snapshot.json.gz").write_bytes(gz)
        svc, _ = make_service(tmp_path)
        result = svc.verify("b1")
        assert result["valid"] is False
        assert result["checksum_mismatch"] == ["redis_snapshot.json.gz"]

    def test_verify_valid(self, tmp_path):
        _write_backup(tmp_path, "b1")
        svc, _ = make_service(tmp_path)
        result = svc.verify("b1")
        assert result["found"] is True
        assert result["valid"] is True
        assert result["entries_count"] == 1

    def test_verify_ignores_sources_without_artifact(self, tmp_path):
        # config source carries no artifact -> skipped (continue branch)
        _write_backup(tmp_path, "b1", sources={
            "redis": {"artifact": "redis_snapshot.json.gz", "sha256": "_"},
            "config": {"status": "completed"},
        })
        svc, _ = make_service(tmp_path)
        result = svc.verify("b1")
        assert result["valid"] is False  # redis artifact missing
        assert "config" not in result["artifact_missing"]


class TestRestore:
    def test_restore_not_found(self, tmp_path):
        svc, _ = make_service(tmp_path)
        assert svc.restore("nope")["restored"] is False

    def test_restore_manifest_unreadable(self, tmp_path):
        _write_backup(tmp_path, "b1", bad_manifest="@@")
        svc, _ = make_service(tmp_path)
        result = svc.restore("b1")
        assert result["restored"] is False
        assert "unreadable" in result["reason"]

    def test_restore_no_redis_artifact(self, tmp_path):
        _write_backup(tmp_path, "b1", sources={"ldap": {"artifact": "ldap.ldif"}})
        svc, _ = make_service(tmp_path)
        result = svc.restore("b1")
        assert result["restored"] is False
        assert "no redis artifact" in result["reason"]

    def test_restore_artifact_missing(self, tmp_path):
        _write_backup(tmp_path, "b1", sources={"redis": {"artifact": "redis_snapshot.json.gz", "sha256": "a" * 64}})
        svc, _ = make_service(tmp_path)
        result = svc.restore("b1")
        assert result["restored"] is False
        assert "artifact missing" in result["reason"]

    def test_restore_tampered_refused(self, tmp_path):
        _write_backup(tmp_path, "b1", tamper=True)
        svc, _ = make_service(tmp_path)
        result = svc.restore("b1")
        assert result["restored"] is False
        assert "integrity" in result["reason"]

    def test_restore_unparseable_snapshot(self, tmp_path):
        gz = gzip.compress(b"not-json")
        _write_backup(tmp_path, "b1", sources={
            "redis": {"artifact": "redis_snapshot.json.gz", "sha256": hashlib_hex(gz)},
        })
        d = tmp_path / "backup-b1"
        (d / "redis_snapshot.json.gz").write_bytes(gz)
        svc, _ = make_service(tmp_path)
        result = svc.restore("b1")
        assert result["restored"] is False
        assert "decompressed" in result["reason"]

    def test_restore_success(self, tmp_path):
        _write_backup(tmp_path, "b1")
        svc, cache = make_service(tmp_path)
        result = svc.restore("b1")
        assert result["restored"] is True
        assert result["keys_applied"] == 1
        assert cache.data["s:1"] == "v"

    def test_snapshot_entry_count_missing_artifact(self, tmp_path):
        svc, _ = make_service(tmp_path)
        assert svc._snapshot_entry_count(tmp_path) is None


# --------------------------------------------------------------------- #
# retain / history / redact
# --------------------------------------------------------------------- #
class TestPrune:
    def test_no_backup_dir_returns_zero(self, tmp_path):
        missing = tmp_path / "nope"
        svc, _ = make_service(missing)
        assert svc._prune() == 0

    def test_non_backup_dirs_skipped_and_age_prune(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc.now = mock.Mock(return_value=1_000_000.0)
        (tmp_path / "other").mkdir()
        (tmp_path / "other" / "manifest.json").write_text("{}")
        _write_backup(tmp_path, "old1")
        d = tmp_path / "backup-old1"
        d.joinpath("manifest.json").write_text(json.dumps({"timestamp": 100.0}))
        _write_backup(tmp_path, "new1")
        d2 = tmp_path / "backup-new1"
        d2.joinpath("manifest.json").write_text(json.dumps({"timestamp": 900_000.0}))
        removed = svc._prune(retention_days=7)
        assert removed == 1
        assert (tmp_path / "backup-old1").exists() is False
        assert (tmp_path / "backup-new1").exists() is True
        assert (tmp_path / "other").exists() is True

    def test_manifest_parse_failure_uses_current_time(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc.now = mock.Mock(return_value=2_000_000.0)
        d = tmp_path / "backup-b1"
        d.mkdir()
        d.joinpath("manifest.json").write_text("{{{{bad")
        svc._prune(retention_days=1)  # ts=now -> not pruned by age
        assert d.exists()

    def test_max_history_cap(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc.now = mock.Mock(return_value=2_000_000.0)
        svc.max_history = 2
        for i in range(5):
            _write_backup(tmp_path, f"h{i}")
            d = tmp_path / f"backup-h{i}"
            d.joinpath("manifest.json").write_text(json.dumps({"timestamp": float(i)}))
        removed = svc._prune()
        assert removed == 3
        remaining = [p for p in tmp_path.iterdir() if p.name.startswith("backup-")]
        assert len(remaining) == 2


class TestHistory:
    def test_load_history_empty(self, tmp_path):
        svc, _ = make_service(tmp_path)
        assert svc.load_history() == []

    def test_load_history_parses(self, tmp_path):
        svc, cache = make_service(tmp_path)
        cache.set("backup:history", json.dumps([{"id": "abc"}]))
        assert svc.load_history() == [{"id": "abc"}]

    def test_load_history_cache_error(self, tmp_path):
        svc, cache = make_service(tmp_path)
        cache.get = mock.Mock(side_effect=RuntimeError("redis down"))
        assert svc.load_history() == []

    def test_save_history(self, tmp_path):
        svc, cache = make_service(tmp_path)
        svc.save_history([{"id": "x"}])
        assert json.loads(cache.data["backup:history"]) == [{"id": "x"}]


class TestRedact:
    def test_redact_name_match(self):
        assert _redact("SOGO_AUTH_PASSWORD", "x") == "***"

    def test_redact_inline_secret_in_value(self):
        assert _redact("SOGO_CUSTOM_CONFIG", "url with token=abc123") == "***"

    def test_redact_unchanged(self):
        assert _redact("SOGO_PUBLIC_HOSTNAME", "mail.example.org") == "mail.example.org"
