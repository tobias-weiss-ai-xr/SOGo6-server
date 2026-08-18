"""Monitoring API tests: honest health dashboard, /health, access-log levels.

The dashboard must reflect REAL probe results (monkeypatched here at the
module seam) — a dependency that is down must surface as ``error`` in the
response, never as a hardcoded "ok".
"""
from __future__ import annotations

import pytest

from app import create_app, _access_log_level
from app.utils import constants as cs

ADMIN = "/api/admin/v1/health-dashboard"
HEALTH = "/api/user/v1/health"


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


def _fake_probes(monkeypatch, overrides: dict):
    """Patch the dashboard probes so each returns a fixed status/latency."""
    defaults = {
        "check_redis": {"status": "ok", "latency_ms": 1.2, "detail": "PONG"},
        "check_database": {"status": "ok", "latency_ms": 3.4, "detail": "Connected"},
        "check_ldap": {"status": "ok", "latency_ms": 2.3, "detail": "Connected"},
        "check_stalwart": {"status": "ok", "latency_ms": 4.5, "detail": "Connected via IMAP:143"},
        "check_agent": {"status": "ok", "latency_ms": 5.6, "detail": "2 worker(s) responded"},
    }
    defaults.update(overrides)
    for name, probe in defaults.items():
        # accept a plain dict (fixed result) or a callable (raised probe)
        if callable(probe):
            target = probe
        else:
            target = (lambda r: (lambda: dict(r)))(probe)
        monkeypatch.setattr(f"app.api.v1.admin.ApiHealthDashboard.{name}", target)
    return defaults


def test_dashboard_reports_real_probe_statuses(admin_client, monkeypatch):
    _fake_probes(monkeypatch, {"check_database": {"status": "error", "latency_ms": 999.0, "error": "down"}})
    resp = admin_client.get(ADMIN, headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    services = {s["name"]: s for s in data["services"]}
    assert len(services) == 5
    assert services["Database"]["status"] == "error"
    assert services["Database"]["latency_ms"] == 999.0
    assert services["Database"]["detail"] == "down"
    assert services["Redis"]["status"] == "ok"
    assert services["Celery Agent"]["detail"] == "2 worker(s) responded"
    assert data["healthy_count"] == 4
    assert data["uptime_seconds"] >= 0


def test_dashboard_all_down(admin_client, monkeypatch):
    _fake_probes(monkeypatch, {name: {"status": "error", "latency_ms": 1.0, "error": f"{name} down"} for name in
                               ["check_redis", "check_database", "check_ldap", "check_stalwart", "check_agent"]})
    resp = admin_client.get(ADMIN, headers={"Authorization": "Bearer test-token"})
    data = resp.get_json()["data"]
    assert data["healthy_count"] == 0
    assert all(s["status"] == "error" for s in data["services"])


def test_dashboard_probe_raise_is_error_row(admin_client, monkeypatch):
    def boom():
        raise RuntimeError("password=hunter2 host=localhost")

    _fake_probes(monkeypatch, {"check_redis": boom})
    resp = admin_client.get(ADMIN, headers={"Authorization": "Bearer test-token"})
    services = {s["name"]: s for s in resp.get_json()["data"]["services"]}
    assert services["Redis"]["status"] == "error"
    assert "hunter2" not in services["Redis"]["detail"]
    assert "[REDACTED]" in services["Redis"]["detail"]


def test_health_run_checks_delegates_to_probes():
    """The /health logic runs all four probes and publishes gauges."""
    from app.api.v1.health.ApiHealth import _run_checks

    checks = _run_checks()
    assert set(checks) == {"database", "ldap", "redis", "stalwart_mail"}
    assert checks["redis"]["status"] == "ok"
    assert "latency_ms" in checks["redis"]
    from prometheus_client import REGISTRY
    up = REGISTRY.get_sample_value("sogo_dependency_up", {"name": "redis"})
    assert up is not None


# --------------------------------------------------------------------- #
# access-log severity mapping (5xx ERROR / 4xx WARNING / else INFO)
# --------------------------------------------------------------------- #

def test_access_log_level_mapping():
    import logging
    assert _access_log_level(500) == logging.ERROR
    assert _access_log_level(503) == logging.ERROR
    assert _access_log_level(404) == logging.WARNING
    assert _access_log_level(400) == logging.WARNING
    assert _access_log_level(200) == logging.INFO
    assert _access_log_level(302) == logging.INFO