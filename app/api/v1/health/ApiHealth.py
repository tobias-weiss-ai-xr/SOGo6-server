"""Enhanced health-check endpoint with per-dependency status.

Returns a JSON summary of all external-service reachability so that
load balancers, orchestrators and operators can make informed decisions
without having to scrape individual component logs.

Every probe is a real live connection attempt — see
``app/service/monitoring/HealthChecks`` — and each result is also published
to the Prometheus dependency gauges so scraping ``/metrics`` alone is enough
to alert on outages.
"""

from __future__ import annotations

from time import time
from typing import Any

from flask import Response, current_app
from flask.views import MethodView
from flask_smorest import Blueprint

from app.service.monitoring.HealthChecks import check_database, check_ldap, check_redis, check_stalwart
from app.utils.api.prometheus import record_dependency_health

blp = Blueprint("Health", __name__, url_prefix="/health")
blp.public_access = True  # type: ignore[attr-defined]


def _run_checks() -> dict[str, dict]:
    """Run the real probes and publish them to Prometheus gauges."""
    checks = {
        "database": check_database(),
        "ldap": check_ldap(),
        "redis": check_redis(),
        "stalwart_mail": check_stalwart(),
    }
    # Every probe also lands in Prometheus — one scrape target for everything.
    try:
        for name, res in checks.items():
            record_dependency_health(name, res.get("status", "error"), float(res.get("latency_ms", 0.0)))
    except Exception:  # pragma: no cover - metrics collection must never break the endpoint
        pass
    return checks


@blp.route("")
class ApiHealth(MethodView):
    """Enhanced health-check endpoint.

    Returns 200 with per-dependency status when all services are reachable,
    or 503 when at least one dependency is unhealthy.
    ---
    get:
      summary: "Health check with dependency status"
      responses:
        200:
          description: "All dependencies reachable"
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    example: ok
                  version:
                    type: string
                    example: 6.0.0-alpha1
                  uptime_seconds:
                    type: number
                  dependencies:
                    type: object
        503:
          description: "At least one dependency unreachable"
    """

    public_access = True  # type: ignore[attr-defined]

    def get(self) -> Response:
        checks = _run_checks()

        overall = "ok" if all(c["status"] == "ok" for c in checks.values()) else "degraded"

        # Uptime: use process start time from the Flask app (set in run.py)
        uptime = time() - current_app.config.get("SOGO_START_TIME", time())

        body: dict[str, Any] = {
            "status": overall,
            "version": "6.0.0-alpha1",
            "uptime_seconds": round(uptime, 1),
            "dependencies": checks,
        }

        status_code = 200 if overall == "ok" else 503
        return Response(
            __import__("json").dumps(body, default=str, indent=2),
            status=status_code,
            content_type="application/json",
        )