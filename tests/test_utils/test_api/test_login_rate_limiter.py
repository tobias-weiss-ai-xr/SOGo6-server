# SPDX-FileCopyrightText: 2025 SOGo project contributors
# SPDX-License-Identifier: LGPL-2.1-only
"""LoginRateLimiter must FAIL OPEN on Redis errors.

A stale pooled Redis connection can surface as a raw ``ValueError``
("I/O operation on closed file") which bypasses redis-py's
``ConnectionError``-based retry. Authentication must never 500 because of a
cache hiccup: every limiter method degrades to its safe default instead of
raising (bug: POST /api/user/v1/auth/login returned 500 mid-suite).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.utils.api.login_rate_limiter import LoginRateLimiter


class _BrokenRedis:
    """Redis stub whose every operation dies like a stale pooled socket."""

    def __getattr__(self, name):
        def _raise(*args, **kwargs):
            raise ValueError("I/O operation on closed file")

        return _raise


@pytest.fixture()
def limiter() -> LoginRateLimiter:
    wrapper = MagicMock()
    wrapper.redis = _BrokenRedis()
    return LoginRateLimiter(wrapper)


def test_is_ip_rate_limited_fails_open(limiter: LoginRateLimiter) -> None:
    assert limiter.is_ip_rate_limited("10.0.0.9", max_attempts=20, window_seconds=60) is False


def test_is_blocked_fails_open(limiter: LoginRateLimiter) -> None:
    assert limiter.is_blocked("user@example.org", max_attempt=5, block_time=60) is False


def test_record_failure_fails_open(limiter: LoginRateLimiter) -> None:
    assert limiter.record_failure("user@example.org", time_span=60) == 0


def test_block_fails_open(limiter: LoginRateLimiter) -> None:
    # Must not raise; block state is best-effort.
    limiter.block("user@example.org", block_time=30)


def test_get_fail_count_fails_open(limiter: LoginRateLimiter) -> None:
    assert limiter.get_fail_count("user@example.org") == 0


def test_healthy_redis_still_limits(limiter: LoginRateLimiter) -> None:
    """Sanity: with a working backend the limiter still enforces the IP cap."""
    wrapper = MagicMock()
    store: dict = {}

    def incr(key):
        store[key] = store.get(key, 0) + 1
        return store[key]

    wrapper.redis.incr = incr
    limiter = LoginRateLimiter(wrapper)
    for _ in range(20):
        assert limiter.is_ip_rate_limited("10.0.0.10", max_attempts=20, window_seconds=60) is False
    assert limiter.is_ip_rate_limited("10.0.0.10", max_attempts=20, window_seconds=60) is True
