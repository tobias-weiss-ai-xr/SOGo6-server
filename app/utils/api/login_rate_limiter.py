"""Login rate-limiter and brute-force protection using Redis.

Tracks failed login attempts per user UID and optionally per source IP.
Uses the same Redis connection as the session cache, keyed under a
dedicated namespace.

Settings (from domain AuthSettings):
  SOGO_D_LOGIN_CHECK_MAX_ATTEMPT — max failed attempts before blocking (per UID)
  SOGO_D_LOGIN_CHECK_TIME_SPAN   — window (seconds) for counting failures (per UID)
  SOGO_D_LOGIN_CHECK_BLOCK_TIME  — how long (seconds) the block lasts (per UID)

Additionally, per-IP rate limiting is always active with configurable limits.

When MAX_ATTEMPT == 0 (the default), UID-based tracking is disabled.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.manager.cache.ClientRedis import ClientRedis

# Redis key prefixes
_PREFIX_FAIL = "login:fail:"
_PREFIX_BLOCK = "login:block:"
_PREFIX_IP = "login:ip:"


class LoginRateLimiter:
    """Check and record failed login attempts backed by Redis."""

    def __init__(self, redis_client: ClientRedis) -> None:
        self._redis = redis_client

    @property
    def _r(self):
        """Return the raw Redis connection from the ClientRedis wrapper."""
        return self._redis.redis

    # ── Public API ─────────────────────────────────────────────────────────
    #
    # All Redis-backed methods FAIL OPEN: a cache hiccup (e.g. a stale pooled
    # connection raising ``ValueError: I/O operation on closed file`` — which
    # bypasses redis-py's ConnectionError retry) must never turn into a 500
    # on the login endpoint. Rate limiting is an optimization, not a
    # precondition, for authentication.

    def is_blocked(self, uid: str, max_attempt: int, block_time: int) -> bool:
        """Return ``True`` if *uid* is currently blocked."""
        if max_attempt <= 0:
            return False
        try:
            blocked = self._r.get(self._block_key(uid))
        except Exception:
            logger_api.warning("Login rate-limiter is_blocked failed (fail open)", exc_info=True)
            return False
        return blocked is not None

    def record_failure(self, uid: str, time_span: int) -> int:
        """Increment the failure counter for *uid* and return the new count.

        The counter lives for *time_span* seconds, after which it
        auto-expires.
        """
        key = self._fail_key(uid)
        try:
            count = self._r.incr(key)
            if count == 1:
                self._r.expire(key, time_span)
        except Exception:
            logger_api.warning("Login rate-limiter record_failure failed (fail open)", exc_info=True)
            return 0
        return count

    def block(self, uid: str, block_time: int) -> None:
        """Mark *uid* as blocked for *block_time* seconds."""
        try:
            self._r.setex(self._block_key(uid), block_time, "1")
        except Exception:
            logger_api.warning("Login rate-limiter block failed (fail open)", exc_info=True)
            return
        logger_api.warning("Login blocked for uid=%s (%d seconds)", uid, block_time)

    def reset_failures(self, uid: str) -> None:
        """Clear the failure counter (e.g. after a successful login)."""
        self._r.delete(self._fail_key(uid))
        self._r.delete(self._block_key(uid))

    def get_fail_count(self, uid: str) -> int:
        """Return the current number of consecutive failures."""
        try:
            val = self._r.get(self._fail_key(uid))
        except Exception:
            logger_api.warning("Login rate-limiter get_fail_count failed (fail open)", exc_info=True)
            return 0
        return int(val) if val else 0

    # ── Per-IP Rate Limiting ──────────────────────────────────────────────

    def is_ip_rate_limited(self, ip: str, max_attempts: int = 20, window_seconds: int = 60) -> bool:
        """Check if an IP address is currently rate-limited.
        
        :param ip: IP address to check
        :param max_attempts: Maximum number of attempts allowed (default: 20)
        :param window_seconds: Time window in seconds (default: 60)
        :return: True if the IP is rate-limited
        """
        key = self._ip_key(ip)
        try:
            count = self._r.incr(key)
            if count == 1:
                self._r.expire(key, window_seconds)
        except Exception:
            logger_api.warning("Login rate-limiter is_ip_rate_limited failed (fail open)", exc_info=True)
            return False
        return count > max_attempts

    def reset_ip_rate_limit(self, ip: str) -> None:
        """Clear the rate limit counter for an IP address."""
        self._r.delete(self._ip_key(ip))

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _fail_key(uid: str) -> str:
        return f"{_PREFIX_FAIL}{uid}"

    @staticmethod
    def _block_key(uid: str) -> str:
        return f"{_PREFIX_BLOCK}{uid}"

    @staticmethod
    def _ip_key(ip: str) -> str:
        return f"{_PREFIX_IP}{ip}"
