"""
Rate limiting utilities for SOGo API endpoints.

Uses Redis-based sliding window rate limiting for WebAuthn endpoints
to prevent brute-force attacks.
"""

from __future__ import annotations

import time
from functools import wraps
from typing import Callable, TypeVar

from flask import request

from app.config.settings.ProcessSetting import ProcessSetting

process_config = ProcessSetting()

# Rate limits (requests per window_seconds)
WEBAUTHN_REGISTRATION_LIMIT = 5
WEBAUTHN_AUTHENTICATION_LIMIT = 10
DEFAULT_WINDOW_SECONDS = 60

F = TypeVar('F', bound=Callable)

# Global API rate limit: 300 requests per 60s per IP (broad protection against
# flooding, while allowing normal multi-tab UI usage).
GLOBAL_API_LIMIT = 300
GLOBAL_API_WINDOW = 60

# Paths excluded from global limiting (monitoring, disclosure, docs)
GLOBAL_EXCLUDED_PREFIXES = (
    '/health', '/system', '/metrics',
    '/.well-known', '/security.txt',
    '/docs', '/openapi', '/swagger',
)


def check_global_rate_limit() -> None | Response:
    """Apply global per-IP rate limit to API requests.

    Returns a 429 Response if the limit is exceeded, else None (proceed).
    """
    if not process_config.SOGO_P_REDIS_URL:
        return None
    count_key = f"ratelimit:global:{request.remote_addr}:count"
    try:
        redis_client = _get_redis()
        initialized = redis_client.set(count_key, 1, GLOBAL_API_WINDOW, nx=True)
        current = 1 if initialized else redis_client.incr(count_key)
        if current > GLOBAL_API_LIMIT:
            from flask import make_response
            response = make_response(
                {'error': 'Rate limit exceeded', 'error_code': 'S000429'},
                429,
            )
            response.headers['Retry-After'] = str(GLOBAL_API_WINDOW)
            return response
    except Exception:  # pylint: disable=broad-except
        from app.utils.logger.logger import logger_api
        logger_api.exception("Global rate limiter failed (continuing without it)")
    return None


def _get_redis():
    """Return the shared Redis cache client (avoids per-call connection leaks)."""
    from app.service import sogo_cache
    return sogo_cache()


def _make_rl_key(endpoint_name: str) -> str:
    """Generate Redis key for rate limiting using client IP."""
    return f"ratelimit:{request.remote_addr}:{endpoint_name}"


def rate_limit(limit: int = WEBAUTHN_AUTHENTICATION_LIMIT, window_seconds: int = DEFAULT_WINDOW_SECONDS, endpoint_name: str = None):
    """
    Decorator for fixed-window rate limiting.

    Uses a Redis counter keyed by ``ip:endpoint``. The counter is initialised
    to 1 with a TTL of ``window_seconds`` on the first request (NX), then
    INCR-mented on subsequent requests (Redis preserves the TTL on INCR). When
    the counter exceeds ``limit`` the request is rejected with HTTP 429.

    Args:
        limit: Maximum requests per window
        window_seconds: Window duration in seconds
        endpoint_name: Manually specify endpoint name for key (defaults to request.path)
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not process_config.SOGO_P_REDIS_URL:
                return func(*args, **kwargs)

            name = endpoint_name or request.path
            count_key = f"{_make_rl_key(name)}:count"
            try:
                redis_client = _get_redis()
                # Initialise the window counter with a TTL on first request
                initialized = redis_client.set(count_key, 1, window_seconds, nx=True)
                current = 1 if initialized else redis_client.incr(count_key)

                if current > limit:
                    from flask import make_response
                    response = make_response({'error': 'Too many requests'}, 429)
                    response.headers['Retry-After'] = str(window_seconds)
                    return response
            except Exception:  # pylint: disable=broad-except
                # Rate limiting is defensive only; never break the request if
                # Redis is temporarily unavailable.
                from app.utils.logger.logger import logger_api
                logger_api.exception("Rate limiter failed (continuing without it)")

            return func(*args, **kwargs)
        return wrapper  # type: ignore
    return decorator


def webauthn_registration_rate_limit(func: F) -> F:
    """Rate limit for WebAuthn registration: max 5 requests/minute per IP."""
    return rate_limit(WEBAUTHN_REGISTRATION_LIMIT, DEFAULT_WINDOW_SECONDS)(func)


def webauthn_authentication_rate_limit(func: F) -> F:
    """Rate limit for WebAuthn authentication: max 10 requests/minute per IP."""
    return rate_limit(WEBAUTHN_AUTHENTICATION_LIMIT, DEFAULT_WINDOW_SECONDS)(func)
