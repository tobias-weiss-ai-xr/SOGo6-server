"""System Health Dashboard — at-a-glance status of all services.

Every service entry reflects a REAL live probe (see
``app/service/monitoring/HealthChecks``); nothing is hardcoded to "ok".
The four API-level probes plus the Celery agent check run on each request,
their latency is measured, results are also pushed to the Prometheus
dependency gauges, and error details are sanitized before display.
"""
from __future__ import annotations

import re
import time

from flask import current_app
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.service.monitoring.HealthChecks import check_postgres, check_ldap, check_redis, check_stalwart, check_agent
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.api.prometheus import record_dependency_health
from app.utils.logger.logger import logger_api

def sanitize_health_error(exc: Exception) -> str:
    """Sanitize exception messages for the dashboard to prevent information leakage."""
    error_str = str(exc)

    sensitive_patterns = [
        r'password["\']?\s*[:=]\s*[^\s"\']+',
        r'passwd["\']?\s*[:=]\s*[^\s"\']+',
        r'secret["\']?\s*[:=]\s*[^\s"\']+',
        r'token["\']?\s*[:=]\s*[^\s"\']+',
        r'key["\']?\s*[:=]\s*[^\s"\']+',
        r'sslcert["\']?\s*[:=]\s*[^\s"\']+',
        r'sslkey["\']?\s*[:=]\s*[^\s"\']+',
        r'localhost',
        r'127\.0\.0\.1',
        r'192\.168',
        r'10\.',
        r'172\.(1[6-9]|2[0-9]|3[0-1])\.',
        r'://[^:\/\s]+@',
    ]
    for pattern in sensitive_patterns:
        error_str = re.sub(pattern, '[REDACTED]', error_str, flags=re.IGNORECASE)

    # Cap the message length to prevent DoS via very long connection errors
    max_length = 500
    if len(error_str) > max_length:
        error_str = error_str[:max_length] + "..."

    return error_str

blp = Blueprint("Health Dashboard", __name__, url_prefix="/health-dashboard")


def _service(name: str, probe) -> dict:
    """Run *probe* and shape the service row (sanitized, prometheus-published).

    Probes may return the shared check dict (``{status, latency_ms, ...}``)
    or a plain value (legacy success) / raise (treated as a failure).
    """
    start = time.time()
    try:
        res = probe()
        latency = (time.time() - start) * 1000
        if isinstance(res, dict):
            status = res.get("status", "ok")
            latency = float(res.get("latency_ms", latency))
            detail = res.get("detail") or res.get("error") or "OK"
        else:
            status = "ok"
            detail = str(res) if res else "OK"
    except Exception as exc:  # pylint: disable=broad-except
        latency = (time.time() - start) * 1000
        logger_api.error("Health probe %s raised: %s", name, exc)
        status = "error"
        detail = sanitize_health_error(exc)
    try:
        record_dependency_health(name, status, latency)
    except Exception:  # pragma: no cover
        pass
    return {"name": name, "status": status, "latency_ms": round(latency, 1), "detail": detail}


# legacy alias kept for callers/tests that imported the original name
_check_service = _service


@blp.route("")
class ApiHealthDashboard(MethodView):
    """System health dashboard."""

    def get(self) -> ResponseReturnValue:
        """Return health status for all services (real probes)."""
        services = [
            _service("Redis", check_redis),
            _service("PostgreSQL", check_postgres),
            _service("LDAP", check_ldap),
            _service("Stalwart Mail", check_stalwart),
            _service("Celery Agent", check_agent),
        ]

        uptime = time.time() - current_app.config.get("SOGO_START_TIME", time.time())

        return create_api_base_response({
            "services": services,
            "uptime_seconds": round(uptime, 1),
            "version": "6.0.0-alpha1",
            "healthy_count": sum(1 for s in services if s["status"] == "ok"),
        })