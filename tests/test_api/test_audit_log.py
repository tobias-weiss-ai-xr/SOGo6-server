"""Audit log — tamper-evident chain + SIEM export tests.

The chain must detect any mutation of a retained entry and any forged link,
and retention trimming must be real (previous code removed score-strings,
which silently removed nothing) while reporting the trimmed boundary honestly.
"""
from __future__ import annotations

import json

import pytest

from app import create_app
from app.utils import constants as cs
from app.service import sogo_cache

ADMIN = "/api/admin/v1/audit-log"


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


def _clean(monkeypatch):
    """Isolate this test's audit trail — fresh keys per test (also clears
    leftovers from previous runs whose member strings differ)."""
    from app.api.v1.admin.ApiAuditLog import _AUDIT_ZSET, _AUDIT_SEQ_KEY

    cache = sogo_cache()
    cache.delete(_AUDIT_ZSET, _AUDIT_SEQ_KEY)
    monkeypatch.setattr("app.api.v1.admin.ApiAuditLog._MAX_ENTRIES", 10000)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    _clean(monkeypatch)


def _append(*actions):
    from app.api.v1.admin.ApiAuditLog import audit

    for a in actions:
        audit(a, actor="tester", target="mailbox:1", detail="detail for " + a, ip="10.1.1.1")


def _members():
    from app.api.v1.admin.ApiAuditLog import _AUDIT_ZSET

    raw = sogo_cache().zset_revrange(_AUDIT_ZSET, 0, -1)
    return [json.loads(m) for m in raw]


# --------------------------------------------------------------------- #
# chain construction
# --------------------------------------------------------------------- #

def test_audit_appends_hashed_chain():
    _append("login", "logout")
    members = _members()
    assert len(members) == 2
    first, second = sorted(members, key=lambda e: e["seq"])
    assert first["seq"] == 1 and second["seq"] == 2
    assert first["prev_seq"] == 0 and first["prev_hash"] == ""
    assert second["prev_seq"] == 1
    assert second["prev_hash"] == first["hash"]
    assert first["hash"] and second["hash"]


def test_verify_chain_valid():
    _append("login", "mail.read", "delete.user")
    resp = _verify()
    data = resp["data"]
    assert data["chain_valid"] is True
    assert data["entries"] == 3
    assert data["trimmed"] is False
    assert data["broken"] == []


def _verify():
    from app.api.v1.admin.ApiAuditLog import verify_chain

    return {"data": verify_chain()}


# --------------------------------------------------------------------- #
# tamper detection
# --------------------------------------------------------------------- #

def test_verify_detects_content_mutation():
    _append("login", "delete.user")
    cache = sogo_cache()
    members = _members()
    target = next(m for m in members if m["seq"] == 1)
    tampered = dict(target)
    tampered["detail"] = "changed by attacker"
    cache.zset_remove("audit_log", json.dumps(target, sort_keys=True))
    cache.zset_add("audit_log", json.dumps(tampered, sort_keys=True), float(tampered["seq"]))
    data = _verify()["data"]
    assert data["chain_valid"] is False
    assert any(b["seq"] == 1 and "content" in b["reason"] for b in data["broken"])


def test_verify_detects_forged_link():
    _append("login", "mail.read", "logout")
    cache = sogo_cache()
    members = _members()
    # replace entry 2 with one whose prev_hash is forged (does not match entry 1)
    forged = dict(members[1])
    forged["prev_hash"] = "f" * 64
    forged["hash"] = None  # drop — recomputed from content by verifier
    from app.api.v1.admin.ApiAuditLog import _entry_hash

    forged["hash"] = _entry_hash(forged)
    cache.zset_remove("audit_log", json.dumps(members[1], sort_keys=True))
    cache.zset_add("audit_log", json.dumps(forged, sort_keys=True), float(forged["seq"]))
    data = _verify()["data"]
    assert data["chain_valid"] is False
    # the break is reported on the successor of the forged entry (seq 3)
    reasons = [b["reason"] for b in data["broken"] if b["seq"] == 3]
    assert any("mismatch" in r for r in reasons)


# --------------------------------------------------------------------- #
# retention trimming
# --------------------------------------------------------------------- #

def test_trim_actually_removes_and_reports_boundary(monkeypatch):
    monkeypatch.setattr("app.api.v1.admin.ApiAuditLog._MAX_ENTRIES", 5)
    _append("a1", "a2", "a3", "a4", "a5")   # fills the log
    _append("a6")                            # exceeds → trim to 5
    members = _members()
    assert len(members) == 5
    assert {m["seq"] for m in members} == {2, 3, 4, 5, 6}
    data = _verify()["data"]
    assert data["chain_valid"] is True
    assert data["trimmed"] is True
    assert data["entries"] == 5


# --------------------------------------------------------------------- #
# SIEM export
# --------------------------------------------------------------------- #

def test_export_jsonl_oldest_first(admin_client):
    _append("first", "second")
    resp = admin_client.get(f"{ADMIN}/export?format=jsonl", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    assert resp.content_type.startswith("application/x-ndjson")
    lines = resp.get_data(as_text=True).strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["seq"] == 1 and second["seq"] == 2
    assert first["prev_hash"] == ""


def test_export_cef_escapes(admin_client):
    from app.api.v1.admin.ApiAuditLog import audit

    audit("sensitive|action", actor="bob=admin", detail="path=/x y=1|2\\3", target="t", ip="")
    resp = admin_client.get(f"{ADMIN}/export?format=cef", headers={"Authorization": "Bearer test-token"})
    text = resp.get_data(as_text=True)
    assert text.startswith("CEF:0|SOGo|SOGo Server|6.0.0-alpha1|audit|")
    line = text.strip().split("\n")[0]
    # pipe escaped inside extension fields, header still has its 8 header pipes
    assert "sensitive\\|action" in line
    assert "bob\\=admin" in line
    assert "1\\|2\\\\3" in line
    assert "\n" not in line


# --------------------------------------------------------------------- #
# client primitives
# --------------------------------------------------------------------- #

def test_incr_monotonic():
    cache = sogo_cache()
    cache.delete("test:audit:seq")
    assert cache.incr("test:audit:seq") == 1
    assert cache.incr("test:audit:seq") == 2
    assert cache.incr("test:audit:seq") == 3


def test_zset_trim_keeps_highest():
    cache = sogo_cache()
    for i in range(1, 7):
        cache.zset_add("test:audit:z", f"member{i}", float(i))
    removed = cache.zset_trim("test:audit:z", 3)
    assert removed == 3
    rest = cache.zset_revrange("test:audit:z", 0, -1)
    assert sorted(rest) == ["member4", "member5", "member6"]
    assert cache.zset_trim("test:audit:z", 3) == 0