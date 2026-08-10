"""Usage quotas — real usage, honest unknown statuses, over-quota logic.

The previous implementation returned hardcoded usage zeros ("In production this
would query actual storage"). These tests pin the replacement: usage values
flow from the real probes (seamed), unreachable/unconfigured sources report
used=null with an honest status, and over-quota is computed only from known
usage.
"""
from __future__ import annotations

import pytest

from app import create_app
from app.utils import constants as cs
from app.service import sogo_cache

ADMIN = "/api/admin/v1/quotas"


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


@pytest.fixture(autouse=True)
def _isolate():
    cache = sogo_cache()
    cache.delete("quota:alice@test", "quota:bob@test", "quota:carol@test")


# ------------------------------------------------------------------------
# Limit storage
# ------------------------------------------------------------------------
def test_put_stores_and_sanitizes_limits(admin_client):
    resp = admin_client.put(
        f"{ADMIN}/alice@test",
        json={"mailbox_size_mb": -5, "calendar_count": 10, "contact_count": 0},
        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"] == {"mailbox_size_mb": 0, "calendar_count": 10, "contact_count": 0}


def test_get_returns_saved_limits(admin_client):
    admin_client.put(
        f"{ADMIN}/bob@test",
        json={"mailbox_size_mb": 2048, "calendar_count": 5, "contact_count": 500},
        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
    )
    resp = admin_client.get(f"{ADMIN}/bob@test", headers={"Authorization": "Bearer test-token"})
    data = resp.get_json()["data"]
    assert data["limits"] == {"mailbox_size_mb": 2048, "calendar_count": 5, "contact_count": 500}


# ------------------------------------------------------------------------
# Real usage flows through the probes (seamed) and drives over-quota flags
# ------------------------------------------------------------------------
def _inject_probes(monkeypatch, **uses):
    from app.service.quota.QuotaUsageService import QuotaUsageService

    def factory(uid, limits):
        return QuotaUsageService(
            uid,
            limits,
            calendar_probe=lambda: {"status": "completed", "used": uses.get("calendar", 0)},
            contact_probe=lambda: {"status": "completed", "used": uses.get("contact", 0)},
            mailbox_probe=lambda: {"status": "completed", "used": uses.get("mailbox", 0.0)},
        )

    monkeypatch.setattr("app.api.v1.admin.ApiUsageQuotas._usage_service", factory)


def test_over_quota_detected_from_real_usage(admin_client, monkeypatch):
    admin_client.put(
        f"{ADMIN}/alice@test",
        json={"mailbox_size_mb": 2, "calendar_count": 5, "contact_count": 10},
        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
    )
    _inject_probes(monkeypatch, calendar=3, contact=4, mailbox=2.5)

    data = admin_client.get(
        f"{ADMIN}/alice@test", headers={"Authorization": "Bearer test-token"}
    ).get_json()["data"]
    assert data["usage"] == {"calendar_count": 3, "contact_count": 4, "mailbox_used_mb": 2.5}
    assert data["over_quota"] is True
    assert data["over_limits"] == ["mailbox_size_mb"]


def test_no_false_over_quota_when_under_limits(admin_client, monkeypatch):
    admin_client.put(
        f"{ADMIN}/bob@test",
        json={"mailbox_size_mb": 10, "calendar_count": 5, "contact_count": 10},
        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
    )
    _inject_probes(monkeypatch, calendar=3, contact=4, mailbox=1.0)

    data = admin_client.get(
        f"{ADMIN}/bob@test", headers={"Authorization": "Bearer test-token"}
    ).get_json()["data"]
    assert data["over_quota"] is False
    assert data["over_limits"] == []


# ------------------------------------------------------------------------
# Honesty: unknown usage is null, never a fabricated zero
# ------------------------------------------------------------------------
def test_defaults_are_honest_unknowns_not_zeroes():
    from app.service.quota.QuotaUsageService import QuotaUsageService

    svc = QuotaUsageService(
        "carol@test",
        {"mailbox_size_mb": 1, "calendar_count": 3, "contact_count": 3},
        process_settings=None,  # no storage reachable in this context
        env={},                 # no IMAP probe credentials
    )
    report = svc.usage()
    used = report["used"]
    assert used["mailbox_used_mb"] is None
    assert used["calendar_count"] is None
    assert used["contact_count"] is None
    assert report["sources"]["mailbox"]["status"] == "not_configured"
    assert report["sources"]["calendar"]["status"] == "unreachable"
    assert report["sources"]["contact"]["status"] == "unreachable"
    # unknown usage can neither claim compliance nor trigger over-quota
    assert report["over_quota"] is False
    assert report["over_limits"] == []


def test_over_quota_never_claims_when_usage_unknown(admin_client, monkeypatch):
    from app.service.quota.QuotaUsageService import QuotaUsageService

    admin_client.put(
        f"{ADMIN}/carol@test",
        json={"mailbox_size_mb": 1},  # 1 MB limit, but mailbox usage is unknown
        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
    )

    def factory(uid, limits):
        return QuotaUsageService(uid, limits, process_settings=None, env={})

    monkeypatch.setattr("app.api.v1.admin.ApiUsageQuotas._usage_service", factory)
    data = admin_client.get(
        f"{ADMIN}/carol@test", headers={"Authorization": "Bearer test-token"}
    ).get_json()["data"]
    assert data["usage"]["mailbox_used_mb"] is None
    assert data["over_quota"] is False
    assert data["over_limits"] == []