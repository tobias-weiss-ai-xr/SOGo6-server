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


def _get_redis():
    """Lazy import to avoid circular dependencies."""
    from app.manager.cache.ClientRedis import ClientRedis
    return ClientRedis()


def _make_rl_key(endpoint_name: str) -> str:
    """Generate Redis key for rate limiting using client IP."""
    return f"ratelimit:{request.remote_addr}:{endpoint_name}"


def _trim_window(zset_key: str, window_seconds: int) -> None:
    """Remove old entries from the sliding window."""
    redis_client = _get_redis()
    redis_client.zset_trim(zset_key, 0, window_seconds)


def _count_current(zset_key: str, window_seconds: int) -> int:
    """Count entries in the current window."""
    redis_client = _get_redis()
    now = int(time.time())
    window_start = now - window_seconds
    # Use ZCOUNT to count scores in [window_start, +inf)
    return redis_client.zset_count(zset_key, window_start, float('inf'))


def _add_request(zset_key: str, now: int) -> None:
    """Add current request timestamp to the window."""
    redis_client = _get_redis()
    # Use a monotonic counter per key to avoid memory bloat from unique members
    request_id = redis_client.incr(f"{zset_key}:counter")
    redis_client.zset_add(zset_key, request_id, now)


def rate_limit(limit: int = WEBAUTHN_AUTHENTICATION_LIMIT, window_seconds: int = DEFAULT_WINDOW_SECONDS, endpoint_name: str = None):
    """
    Decorator for sliding-window rate limiting.
    
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
            zset_key = _make_rl_key(name)
            now = int(time.time())
            
            _trim_window(zset_key, window_seconds)
            count = _count_current(zset_key, window_seconds)
            
            if count >= limit:
                # Compute when the oldest entry expires
                redis_client = _get_redis()
                oldest = redis_client.zset_range(zset_key, 0, 0, with_scores=True)
                oldest_ts = int(oldest[0][1]) if oldest else now
                retry_after = max(1, oldest_ts + window_seconds - now)
                from flask import make_response
                response = make_response({'error': 'Too many requests'}, 429)
                response.headers['Retry-After'] = str(retry_after)
                return response
            
            _add_request(zset_key, now)
            return func(*args, **kwargs)
        return wrapper  # type: ignore
    return decorator


def webauthn_registration_rate_limit(func: F) -> F:
    """Rate limit for WebAuthn registration: max 5 requests/minute per IP."""
    return rate_limit(WEBAUTHN_REGISTRATION_LIMIT, DEFAULT_WINDOW_SECONDS)(func)


def webauthn_authentication_rate_limit(func: F) -> F:
    """Rate limit for WebAuthn authentication: max 10 requests/minute per IP."""
    return rate_limit(WEBAUTHN_AUTHENTICATION_LIMIT, DEFAULT_WINDOW_SECONDS)(func)
