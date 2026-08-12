"""Backup automation — real snapshots, honest source statuses, retention,
verification and restore.

The trigger must never fabricate success: per-source status is whatever really
happened (LDAP/Postgres unreachable -> skipped/failed recorded), artifacts are
real bytes on disk, size/duration are real, and verify/restore are gated on
recomputed SHA-256s.
"""
from __future__ import annotations

import gzip
import json

import pytest

from app import create_app
from app.utils import constants as cs
from app.service import sogo_cache

ADMIN = "/api/admin/v1/backup"

# global middleware requires application/json on POSTs (even bodyless)
_AUTH = {"Authorization": "Bearer test-token", "Content-Type": "application/json"}


@pytest.fixture()
def admin_client(monkeypatch):
    from app.auth.Admin import Admin

    app = create_app(cs.SOGO_NOT_INIT)
    app.config["TESTING"] = True
    monkeypatch.setattr("app.VoucherAdminService.__init__", lambda self, ps: None)
    monkeypatch.setattr(
        "app.VoucherAdminService.generate_admin_from_voucher",
        staticmethod(lambda token: Admin("smoke-admin")),
    )
    return app.test_client()


@pytest.fixture()
def backup_dir(monkeypatch, tmp_path):
    """Isolate backup artifacts + Redis history/config per test."""
    cache = sogo_cache()
    cache.delete("backup:history", "backup:config")
    monkeypatch.setenv("SOGO_BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("SOGO_BACKUP_MAX_HISTORY", "50")
    return tmp_path


def _service(backup_dir):
    from app.service.backup.BackupService import BackupService

    return BackupService(cache=sogo_cache(), backup_dir=backup_dir)


# ------------------------------------------------------------------------
# Trigger produces a REAL artifact with honest statuses
# ------------------------------------------------------------------------
def test_trigger_creates_real_artifact(admin_client, backup_dir):
    cache = sogo_cache()
    cache.set("uniquekey:trigger", {"note": "seed-data"}, ttl=3600)

    resp = admin_client.post(f"{ADMIN}/trigger", headers=_AUTH, json={})
    assert resp.status_code == 200
    entry = resp.get_json()["data"]

    assert entry["status"] == "completed"
    assert entry["duration_s"] > 0
    assert entry["size_mb"] >= 0
    assert entry["sources"]["redis"]["size_bytes"] > 0
    assert entry["filename"].endswith("manifest.json")
    sources = entry["sources"]
    assert sources["redis"]["status"] == "completed"
    assert sources["redis"]["entries"] >= 1
    assert sources["redis"]["sha256"]
    # LDAP/Postgres may be unreachable or unconfigured, but never fabricated
    assert sources["ldap"]["status"] in ("completed", "skipped", "failed")
    assert sources["postgres"]["status"] in ("completed", "skipped", "failed")
    assert sources["config"]["status"] == "completed"

    # real artifact bytes on disk
    manifest = backup_dir / entry["filename"]
    assert manifest.is_file()
    data = json.loads(manifest.read_text("utf-8"))
    assert data["id"] == entry["id"]
    snapshot = backup_dir / f"backup-{entry['id']}" / "redis_snapshot.json.gz"
    assert snapshot.is_file() and snapshot.stat().st_size > 0
    # the seed key is captured inside the snapshot
    keys = json.loads(gzip.decompress(snapshot.read_bytes()))
    assert any(k["key"] == "uniquekey:trigger" for k in keys)


def test_trigger_records_failure_not_success_when_redis_downed(admin_client, backup_dir, monkeypatch):
    """If the snapshot itself explodes, status must be `failed`, not `completed`."""
    from app.service.backup.BackupService import BackupService

    class Boom:
        def scan_iter(self, *a, **k):
            raise RuntimeError("redis is down")

    svc = BackupService(cache=object(), backup_dir=backup_dir)
    svc.raw = Boom()
    entry = svc.run_backup()
    assert entry["status"] == "failed"
    assert entry["sources"]["redis"]["status"] == "failed"
    assert "redis is down" in entry["sources"]["redis"]["error"]


def test_config_snapshot_redacts_secrets(admin_client, backup_dir, monkeypatch):
    # The snapshot captures SOGO_* env vars; make the secret + a non-secret
    # explicit so the test is deterministic regardless of host environment.
    monkeypatch.setenv("SOGO_AES_ENC_KEY", "0123456789abcdef")
    monkeypatch.setenv("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
    resp = admin_client.post(f"{ADMIN}/trigger", headers=_AUTH, json={})
    entry = resp.get_json()["data"]
    cfg = (backup_dir / f"backup-{entry['id']}" / "config.json").read_text("utf-8")
    assert "0123456789abcdef" not in cfg  # SOGO_AES_ENC_KEY value must not leak
    assert '"SOGO_AES_ENC_KEY": "***"' in cfg
    assert '"SOGO_P_REDIS_URL": "redis://localhost:6379' in cfg  # non-secret is captured


# ------------------------------------------------------------------------
# History / config
# ------------------------------------------------------------------------
def test_list_history_and_config_roundtrip(admin_client, backup_dir):
    resp = admin_client.post(f"{ADMIN}/trigger", headers=_AUTH, json={})
    entry = resp.get_json()["data"]

    resp = admin_client.get(f"{ADMIN}", headers=_AUTH)
    data = resp.get_json()["data"]
    assert data["entries"][0]["id"] == entry["id"]

    # config round-trip
    resp = admin_client.put(
        f"{ADMIN}/config",
        json={"retention_days": 7, "include_mailstore": False},
        headers=_AUTH,
    )
    assert resp.status_code == 200
    resp = admin_client.get(f"{ADMIN}/config", headers=_AUTH)
    cfg = resp.get_json()["data"]
    assert cfg["retention_days"] == 7
    assert cfg["include_mailstore"] is False
    assert cfg["s3_enabled"] is False


# ------------------------------------------------------------------------
# Retention prunes real directories
# ------------------------------------------------------------------------
def test_retention_deletes_old_backup_dirs(backup_dir, monkeypatch):
    import time

    svc = _service(backup_dir)
    old = backup_dir / "backup-old-timestamp"
    old.mkdir()
    (old / "manifest.json").write_text(
        json.dumps({"id": "old-timestamp", "timestamp": time.time() - 10 * 86400}), "utf-8"
    )
    entry = svc.run_backup(retention_days=5)
    assert not old.exists()  # really unlinked
    assert (backup_dir / f"backup-{entry['id']}").is_dir()


def test_retention_caps_history_count(backup_dir):
    _service(backup_dir).run_backup()
    svc = _service(backup_dir)
    svc.max_history = 2
    for i in range(3):
        svc.run_backup()
    dirs = sorted(p.name for p in backup_dir.iterdir() if p.is_dir())
    assert len(dirs) == 2


# ------------------------------------------------------------------------
# Verify: recomputed hashes, tamper detection
# ------------------------------------------------------------------------
def test_verify_passes_for_intact_backup(admin_client, backup_dir):
    resp = admin_client.post(f"{ADMIN}/trigger", headers=_AUTH, json={})
    backup_id = resp.get_json()["data"]["id"]

    resp = admin_client.get(f"{ADMIN}/{backup_id}/verify", headers=_AUTH)
    data = resp.get_json()["data"]
    assert data["found"] is True
    assert data["manifest_parseable"] is True
    assert data["valid"] is True
    assert data["entries_count"] >= 1
    assert data["checksum_mismatch"] == []
    assert data["entries_count"] >= 1


def test_verify_detects_tampered_artifact(admin_client, backup_dir):
    resp = admin_client.post(f"{ADMIN}/trigger", headers=_AUTH, json={})
    backup_id = resp.get_json()["data"]["id"]
    artifact = backup_dir / f"backup-{backup_id}" / "redis_snapshot.json.gz"
    artifact.write_bytes(artifact.read_bytes() + b"\xff")  # tamper

    data = admin_client.get(
        f"{ADMIN}/{backup_id}/verify", headers=_AUTH
    ).get_json()["data"]
    assert data["valid"] is False
    assert "redis_snapshot.json.gz" in data["checksum_mismatch"]
    assert data["reason"]


def test_verify_reports_missing_backup(admin_client, backup_dir):
    data = admin_client.get(
        f"{ADMIN}/no-such-id/verify", headers=_AUTH
    ).get_json()["data"]
    assert data["found"] is False
    assert data["valid"] is False


# ------------------------------------------------------------------------
# Restore: real key re-apply, integrity gate
# ------------------------------------------------------------------------
def test_restore_reapplies_keys(admin_client, backup_dir):
    cache = sogo_cache()
    cache.set("restorekey:alpha", {"payload": "original"}, ttl=7200)

    resp = admin_client.post(f"{ADMIN}/trigger", headers=_AUTH, json={})
    backup_id = resp.get_json()["data"]["id"]

    cache.delete("restorekey:alpha")
    assert cache.get("restorekey:alpha", dict) is None

    resp = admin_client.post(f"{ADMIN}/{backup_id}/restore", headers=_AUTH, json={})
    data = resp.get_json()["data"]
    assert data["restored"] is True
    assert cache.get("restorekey:alpha", dict) == {"payload": "original"}


def test_restore_refuses_tampered_artifact(admin_client, backup_dir):
    cache = sogo_cache()
    cache.set("restorekey:beta", {"payload": "original"}, ttl=7200)
    resp = admin_client.post(f"{ADMIN}/trigger", headers=_AUTH, json={})
    backup_id = resp.get_json()["data"]["id"]

    artifact = backup_dir / f"backup-{backup_id}" / "redis_snapshot.json.gz"
    artifact.write_bytes(artifact.read_bytes() + b"tampered")

    _rr = admin_client.post(
        f"{ADMIN}/{backup_id}/restore", headers=_AUTH, json={}
    )
    data = _rr.get_json()["data"]
    assert data["restored"] is False
    assert "integrity" in data["reason"]