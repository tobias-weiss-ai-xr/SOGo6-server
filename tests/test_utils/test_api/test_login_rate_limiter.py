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


# ── Happy-path coverage (success branches) ──────────────────────────────────


def _happy_limiter() -> LoginRateLimiter:
    wrapper = MagicMock()
    store: dict = {}

    def _get(key):
        return store.get(key)

    def _incr(key):
        store[key] = int(store.get(key, 0)) + 1
        return store[key]

    def _delete(key):
        store.pop(key, None)

    wrapper.redis.get = _get
    wrapper.redis.incr = _incr
    wrapper.redis.delete = _delete
    wrapper.redis.setex = MagicMock()
    wrapper.redis.expire = MagicMock()
    return LoginRateLimiter(wrapper)


def test_is_blocked_disabled_when_max_attempt_zero(limiter: LoginRateLimiter) -> None:
    assert limiter.is_blocked("u", max_attempt=0, block_time=60) is False


def test_is_blocked_ok_true_and_false() -> None:
    limiter = _happy_limiter()
    assert limiter.is_blocked("u", max_attempt=5, block_time=60) is False
    limiter._redis.redis.get = MagicMock(return_value=b"1")
    assert limiter.is_blocked("u", max_attempt=5, block_time=60) is True


def test_record_failure_first_sets_expiry() -> None:
    limiter = _happy_limiter()
    first = limiter.record_failure("u", time_span=120)
    assert first == 1
    limiter._r.expire.assert_called_once()


def test_record_failure_increments_without_expire() -> None:
    limiter = _happy_limiter()
    limiter.record_failure("u", time_span=120)
    limiter._r.expire.reset_mock()
    second = limiter.record_failure("u", time_span=120)
    assert second == 2
    limiter._r.expire.assert_not_called()


def test_block_ok() -> None:
    limiter = _happy_limiter()
    limiter.block("u", block_time=30)
    limiter._r.setex.assert_called_once_with(limiter._block_key("u"), 30, "1")


def test_reset_failures_clears_both_keys() -> None:
    limiter = _happy_limiter()
    limiter.record_failure("u", time_span=60)
    limiter.block("u", 30)
    limiter.reset_failures("u")
    assert limiter.get_fail_count("u") == 0


def test_get_fail_count_returns_value() -> None:
    limiter = _happy_limiter()
    assert limiter.get_fail_count("u") == 0
    limiter.record_failure("u", time_span=60)
    limiter.record_failure("u", time_span=60)
    assert limiter.get_fail_count("u") == 2


def test_reset_ip_rate_limit() -> None:
    limiter = _happy_limiter()
    limiter._redis.redis.delete = MagicMock()
    limiter.is_ip_rate_limited("1.2.3.4", max_attempts=10, window_seconds=60)
    limiter.reset_ip_rate_limit("1.2.3.4")
    limiter._redis.redis.delete.assert_called_with(limiter._ip_key("1.2.3.4"))


def test_is_ip_rate_limited_below_cap() -> None:
    limiter = _happy_limiter()
    assert limiter.is_ip_rate_limited("1.2.3.5", max_attempts=20, window_seconds=60) is False
    limiter._r.expire.assert_called_once()
