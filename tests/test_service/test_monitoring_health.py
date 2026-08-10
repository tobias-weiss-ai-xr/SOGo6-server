"""Monitoring primitives: metric wiring, dependency probes, sanitization.

These tests pin the observability contract:
  * ``@db_op`` / ``@cache_op`` decorators actually observe the histograms
    (they were declared-but-dead before);
  * every dependency probe reports honest ``error`` when the target is gone;
  * ``record_dependency_health`` publishes 1/0 + latency gauges;
  * ``sanitize_health_error`` redacts secrets.
"""
from __future__ import annotations

import time

import pytest

from app.utils.api.prometheus import (
    db_op,
    record_dependency_health,
    DEPENDENCY_UP,
    DEPENDENCY_LATENCY,
)
from app.service.monitoring.HealthChecks import (
    check_postgres,
    check_ldap,
    check_redis,
    check_stalwart,
    check_agent,
    ALL_CHECKS,
)
from app.api.v1.admin.ApiHealthDashboard import sanitize_health_error


def _cache_client():
    from app.manager.cache.ClientRedis import ClientRedis
    return ClientRedis(url_str="redis://localhost:6379/0", resp3=True)


def _hist_count(name: str, labels: dict) -> float:
    """Return ``name_count`` sample for the histogram, or 0 when never seen."""
    try:
        from prometheus_client import REGISTRY
        value = REGISTRY.get_sample_value(f"{name}_count", labels)
        return float(value or 0.0)
    except Exception:
        return 0.0


# --------------------------------------------------------------------- #
# decorators actually observe the histograms
# --------------------------------------------------------------------- #

def test_db_op_observes_histogram():
    class Probe:
        @db_op("probe_op")
        def run(self):
            time.sleep(0.001)
            return 41

    probe = Probe()
    before = _hist_count("sogo_db_query_duration_seconds", {"operation": "probe_op"})
    assert probe.run() == 41
    assert _hist_count("sogo_db_query_duration_seconds", {"operation": "probe_op"}) == before + 1


def test_cache_op_observes_histogram_on_real_redis():
    client = _cache_client()
    before = _hist_count("sogo_cache_operation_duration_seconds", {"operation": "set"})
    client.set("metric:probe", {"v": 1}, ttl=60)
    assert _hist_count("sogo_cache_operation_duration_seconds", {"operation": "set"}) >= before + 1
    # get observes its own label too
    got = client.get("metric:probe", dict)
    assert got == {"v": 1}
    assert _hist_count("sogo_cache_operation_duration_seconds", {"operation": "get"}) >= 1


# ---------------------------------------------------------------- #
# dependency gauges
# ---------------------------------------------------------------- #

def test_record_dependency_health_sets_gauges():
    record_dependency_health("probe-x", "ok", 12.5)
    assert DEPENDENCY_UP.labels(name="probe-x")._value.get() == 1.0
    assert DEPENDENCY_LATENCY.labels(name="probe-x")._value.get() == pytest.approx(0.0125)

    record_dependency_health("probe-x", "error", 999.0)
    assert DEPENDENCY_UP.labels(name="probe-x")._value.get() == 0.0
    assert DEPENDENCY_LATENCY.labels(name="probe-x")._value.get() == pytest.approx(0.999)


# ---------------------------------------------------------------- #
# honest probes
# ---------------------------------------------------------------- #

def test_check_redis_ok_when_local_redis_up():
    res = check_redis()
    assert res["status"] == "ok"
    assert res["latency_ms"] >= 0


def test_check_stalwart_error_when_unreachable(monkeypatch):
    monkeypatch.setenv("SOGO_SMTP_SERVER", "127.0.0.1")
    monkeypatch.setenv("SOGO_STALWART_IMAP_PORT", "9")
    monkeypatch.setenv("SOGO_STALWART_SMTP_PORT", "9")
    monkeypatch.setenv("SOGO_STALWART_SUBM_PORT", "9")
    res = check_stalwart()
    assert res["status"] == "error"
    assert "Cannot connect" in res["error"]


def test_check_ldap_error_when_unreachable(monkeypatch):
    monkeypatch.setenv("SOGO_LDAP_URI", "ldap://127.0.0.1:9")
    res = check_ldap()
    assert res["status"] == "error"


def test_check_postgres_error_without_server(monkeypatch):
    monkeypatch.setenv("SOGO_P_DB_HOST", "127.0.0.1")
    monkeypatch.setenv("SOGO_P_DB_PORT", "9")
    res = check_postgres()
    assert res["status"] == "error"
    assert res["latency_ms"] >= 0


def test_check_agent_error_without_worker(monkeypatch):
    # local redis is up but no worker responds → honest error, never fake ok
    res = check_agent()
    assert res["status"] == "error"
    assert res["latency_ms"] >= 0


def test_registry_covers_all_dashboards():
    """Every check used by dashboards is registered once."""
    assert list(ALL_CHECKS) == ["postgresql", "ldap", "redis", "stalwart_mail", "agent"]


# ---------------------------------------------------------------- #
# sanitization
# ---------------------------------------------------------------- #

def test_sanitize_health_error_redacts_secrets():
    msg = sanitize_health_error(
        "psycopg.OperationalError: connection failed password=sup3rSecret "
        "for host=localhost user=root db=prod://user:pass@10.0.0.5:5432/sogo"
    )
    assert "sup3rSecret" not in msg
    assert "[REDACTED]" in msg


def test_sanitize_health_error_truncates():
    long_err = "x" * 5000
    out = sanitize_health_error(Exception(long_err))
    assert len(out) <= 503  # 500 + "..."


def test_prometheus_dependency_metric_gauge_label_names():
    """Gauges exist with the ``name`` label and are scrape-able."""
    from prometheus_client import REGISTRY

    seen = {"sogo_dependency_up": False, "sogo_dependency_latency_seconds": False}
    for metric in REGISTRY.collect():
        if metric.name in seen:
            seen[metric.name] = True
            for sample in metric.samples:
                assert "name" in sample.labels
    assert all(seen.values())