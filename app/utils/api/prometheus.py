"""
Prometheus metrics collection for the SOGo API server.

Exposes a ``/metrics`` endpoint (Prometheus scrape target) and provides
middleware that tracks request count, latency, and error rate per endpoint.

Also owns the timing decorators used to wire the DB and cache histograms:
without these, ``sogo_db_query_duration_seconds`` and
``sogo_cache_operation_duration_seconds`` would be declared-but-never-observed
dead metrics.
"""

from __future__ import annotations

from functools import wraps
from time import perf_counter, time
from typing import Callable, TypeVar, cast

from flask import Flask, Response, request, g

from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    REGISTRY,
    CONTENT_TYPE_LATEST,
)

# ── Metrics ──────────────────────────────────────────────────────────────────

REQUEST_COUNT = Counter(
    "sogo_http_requests_total",
    "Total HTTP requests handled by the SOGo API server",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "sogo_http_request_duration_seconds",
    "HTTP request latency in seconds (histogram)",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

ACTIVE_REQUESTS = Gauge(
    "sogo_http_requests_in_flight",
    "Number of HTTP requests currently being processed",
)

ERROR_COUNT = Counter(
    "sogo_http_errors_total",
    "Total HTTP errors (status >= 400) handled by the API server",
    ["method", "endpoint", "status"],
)

DB_QUERY_DURATION = Histogram(
    "sogo_db_query_duration_seconds",
    "Database query duration in seconds",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

CACHE_OPERATION_DURATION = Histogram(
    "sogo_cache_operation_duration_seconds",
    "Cache (Redis) operation duration in seconds",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

DEPENDENCY_UP = Gauge(
    "sogo_dependency_up",
    "Whether an external dependency is reachable (1 = up, 0 = down)",
    ["name"],
)

DEPENDENCY_LATENCY = Gauge(
    "sogo_dependency_latency_seconds",
    "Measured latency of the last dependency health check, in seconds",
    ["name"],
)

# ── Decorators that wire the DB / cache histograms ───────────────────────────

_T = TypeVar("_T")


def db_op(operation: str) -> Callable[[Callable[..., _T]], Callable[..., _T]]:
    """Decorate a database method to observe ``DB_QUERY_DURATION``."""

    def _decorator(fn: Callable[..., _T]) -> Callable[..., _T]:
        @wraps(fn)
        def _wrapper(*args, **kwargs) -> _T:  # type: ignore[no-untyped-def]
            start = perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                DB_QUERY_DURATION.labels(operation=operation).observe(perf_counter() - start)
        return _wrapper

    return _decorator


def cache_op(operation: str) -> Callable[[Callable[..., _T]], Callable[..., _T]]:
    """Decorate a cache (Redis) method to observe ``CACHE_OPERATION_DURATION``."""

    def _decorator(fn: Callable[..., _T]) -> Callable[..., _T]:
        @wraps(fn)
        def _wrapper(*args, **kwargs) -> _T:  # type: ignore[no-untyped-def]
            start = perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                CACHE_OPERATION_DURATION.labels(operation=operation).observe(perf_counter() - start)
        return _wrapper

    return _decorator


def record_dependency_health(name: str, status: str, latency_ms: float) -> None:
    """Publish one dependency's latest check result to the gauges.

    Called from both the ``/health`` endpoint and the admin health dashboard so
    every probe also populates Prometheus — operators can alert on
    ``sogo_dependency_up == 0`` without scraping the JSON endpoints.
    """
    try:
        DEPENDENCY_UP.labels(name=name).set(1.0 if status == "ok" else 0.0)
        DEPENDENCY_LATENCY.labels(name=name).set(latency_ms / 1000.0)
    except Exception:  # pragma: no cover - label collisions never happen in practice
        pass


def snapshot_dependencies(results: dict[str, dict]) -> None:
    """Record every entry of a ``{name: {status, latency_ms}}`` mapping."""
    for name, res in results.items():
        record_dependency_health(name, res.get("status", "error"), float(res.get("latency_ms", 0.0)))


def init_prometheus(app: Flask) -> None:
    """Register before/after request hooks that collect Prometheus metrics."""

    @app.before_request
    def _before_request_metrics() -> None:
        g._prometheus_request_start = time()
        g._prometheus_endpoint = request.endpoint or "unknown"
        ACTIVE_REQUESTS.inc()

    @app.after_request
    def _after_request_metrics(response: Response) -> Response:
        method = request.method or "UNKNOWN"
        endpoint = cast(str, getattr(g, "_prometheus_endpoint", "unknown"))
        status = str(response.status_code)
        latency = time() - cast(float, getattr(g, "_prometheus_request_start", time()))

        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=status).inc()
        REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(latency)

        if response.status_code >= 400:
            ERROR_COUNT.labels(method=method, endpoint=endpoint, status=status).inc()

        ACTIVE_REQUESTS.dec()
        return response

    # Expose the /metrics endpoint directly on the Flask app (outside the
    # regular API blueprints) so it is available without any auth middleware.
    @app.route("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(REGISTRY), mimetype=CONTENT_TYPE_LATEST)