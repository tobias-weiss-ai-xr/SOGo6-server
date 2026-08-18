"""Real dependency health probes — single source of truth.

Every probe returns a dict ``{"status": "ok"|"error", "latency_ms": float}``
with an optional ``"error"``/``"detail"`` message.  The probes are shared by:

  * the public ``/health`` endpoint (``ApiHealth``)
  * the admin ``/health-dashboard`` (``ApiHealthDashboard``)
  * the Prometheus dependency gauges (via ``record_dependency_health``)

A probe only ever reports the truth of a live connection attempt — there is
no hardcoded "ok".
"""
from __future__ import annotations

import os
import socket as socket_module
from time import time
from typing import Any


def _proc_setting(key: str, default: str) -> str:
    """Return *key* from the environment, else the process settings object."""
    val = os.environ.get(key)
    if val:
        return val
    try:
        # Module-level singleton (pydantic-settings reads process.conf at
        # import time) — works even without a Flask app context, which is
        # what the unit tests rely on.
        from app.config.settings.ProcessSetting import process_config as _pc

        if hasattr(_pc, key):
            v = getattr(_pc, key)
            if v:
                return str(v)
    except Exception:  # pragma: no cover - import failure
        pass
    try:
        from flask import current_app

        proc = current_app.config.get("process_config") or {}
        if hasattr(proc, key):
            return str(getattr(proc, key))
    except Exception:  # pragma: no cover - no app context in scripts
        pass
    return default


def check_database() -> dict:
    """Return database connectivity status (real connection + SELECT 1).

    Supports **MySQL/MariaDB** and **PostgreSQL** based on the
    ``SOGO_P_DB_TYPE`` process setting (default ``MySQL``).
    """
    start = time()
    result: dict[str, Any] = {"status": "ok", "latency_ms": 0.0}

    db_type = _proc_setting("SOGO_P_DB_TYPE", "MySQL")
    host = _proc_setting("SOGO_P_DB_HOST", "localhost")
    port = int(_proc_setting("SOGO_P_DB_PORT", "3306" if db_type == "MySQL" else "5432"))
    user = _proc_setting("SOGO_P_DB_USER", "sogo")
    password = _proc_setting("SOGO_P_DB_PASS", "sogo")
    dbname = _proc_setting("SOGO_P_DB_NAME", "sogo")

    try:
        if db_type == "PostgreSQL":
            import psycopg  # type: ignore[import-untyped]

            conn = psycopg.connect(
                host=host, port=port, user=user,
                password=password, dbname=dbname,
                connect_timeout=5,
            )
            conn.execute("SELECT 1")
            conn.close()
        else:
            import mysql.connector  # type: ignore[import-untyped]

            conn = mysql.connector.connect(
                host=host, port=port, user=user,
                password=password, database=dbname,
                connection_timeout=5,
            )
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchall()
            cursor.close()
            conn.close()

        result["latency_ms"] = round((time() - start) * 1000, 1)
    except Exception as exc:  # pylint: disable=broad-except
        result["status"] = "error"
        result["error"] = str(exc)
        result["latency_ms"] = round((time() - start) * 1000, 1)
    return result


def check_ldap() -> dict:
    """Return LDAP connectivity status (anonymous bind over the wire)."""
    start = time()
    result: dict[str, Any] = {"status": "ok", "latency_ms": 0.0}
    try:
        import ldap  # type: ignore[import-untyped]

        ldap_uri = _proc_setting("SOGO_LDAP_URI", "ldap://localhost:389")
        conn = ldap.initialize(ldap_uri)
        conn.simple_bind_s("", "")
        conn.unbind_s()
        result["latency_ms"] = round((time() - start) * 1000, 1)
    except ldap.SERVER_DOWN:  # type: ignore[attr-defined]
        result["status"] = "error"
        result["error"] = "LDAP server is down or unreachable"
        result["latency_ms"] = round((time() - start) * 1000, 1)
    except Exception as exc:  # pylint: disable=broad-except
        # A successful TCP connection but failed bind is still "ok" for
        # connectivity — the server is reachable even if auth is required.
        if "Can't contact LDAP server" in str(exc):
            result["status"] = "error"
            result["error"] = "LDAP server is down or unreachable"
        else:
            result["status"] = "ok"
            result["detail"] = f"Connected (bind rejected: {exc})"
        result["latency_ms"] = round((time() - start) * 1000, 1)
    return result


def check_redis() -> dict:
    """Return Redis connectivity status (real PING over the pooled client)."""
    start = time()
    result: dict[str, Any] = {"status": "ok", "latency_ms": 0.0}
    try:
        from app.manager.cache.ClientRedis import ClientRedis

        redis_url = _proc_setting("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
        client = ClientRedis(url_str=redis_url, resp3=True)
        client.ping()
        result["latency_ms"] = round((time() - start) * 1000, 1)
    except Exception as exc:  # pylint: disable=broad-except
        result["status"] = "error"
        result["error"] = str(exc)
        result["latency_ms"] = round((time() - start) * 1000, 1)
    return result


def check_stalwart() -> dict:
    """Return Stalwart (IMAP/SMTP/SUBM) reachability via real TCP connect.

    Ports are overridable via ``SOGO_STALWART_IMAP_PORT`` / ``SOGO_STALWART_SMTP_PORT``
    / ``SOGO_STALWART_SUBM_PORT`` so the probe can target the Docker host
    port-mapping (20025/20143/20587) instead of in-network service names.
    """
    start = time()
    result: dict[str, Any] = {"status": "ok", "latency_ms": 0.0}

    host = _proc_setting("SOGO_SMTP_SERVER", "sogo6-stalwart")
    ports = [
        ("IMAP", int(_proc_setting("SOGO_STALWART_IMAP_PORT", "143"))),
        ("SMTP", int(_proc_setting("SOGO_STALWART_SMTP_PORT", "25"))),
        ("SUBM", int(_proc_setting("SOGO_STALWART_SUBM_PORT", "587"))),
    ]

    for label, port in ports:
        try:
            sock = socket_module.create_connection((host, port), timeout=5)
            sock.close()
            result["latency_ms"] = round((time() - start) * 1000, 1)
            result["detail"] = f"Connected via {label}:{port}"
            return result
        except Exception:  # pylint: disable=broad-except
            continue

    result["status"] = "error"
    result["error"] = f"Cannot connect to {host} on " + ", ".join(f"{l}({p})" for l, p in ports)
    result["latency_ms"] = round((time() - start) * 1000, 1)
    return result


def check_agent() -> dict:
    """Return Celery agent worker reachability via a real broker ``ping``.

    The probe asks any live worker to answer on the configured Redis broker.
    No worker responding is an honest ``error`` — the agent is not serving jobs.
    """
    start = time()
    result: dict[str, Any] = {"status": "ok", "latency_ms": 0.0}
    try:
        from celery import Celery  # type: ignore[import-untyped]

        broker = _proc_setting("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
        app = Celery("sogo_agent_health", broker=broker, backend=broker)
        pings = app.control.ping(timeout=2)
        if pings:
            result["detail"] = f"{len(pings)} worker(s) responded"
        else:
            result["status"] = "error"
            result["error"] = "No Celery worker responded to broker ping"
    except Exception as exc:  # pylint: disable=broad-except
        result["status"] = "error"
        result["error"] = str(exc)
    result["latency_ms"] = round((time() - start) * 1000, 1)
    return result


# Registry used by the dashboards and the Prometheus snapshot
ALL_CHECKS: dict[str, Any] = {
    "database": check_database,
    "ldap": check_ldap,
    "redis": check_redis,
    "stalwart_mail": check_stalwart,
    "agent": check_agent,
}


def run_all_checks() -> dict[str, dict]:
    """Run every real probe and return ``{name: result_dict}``."""
    return {name: fn() for name, fn in ALL_CHECKS.items()}
