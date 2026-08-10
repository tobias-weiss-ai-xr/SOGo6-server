"""Shared fixtures for property-based tests.

Uses mocks when Redis is not available (CI without full stack).
"""
import os
import pytest

try:
    from app.service import sogo_cache
    HAS_APP = True
except Exception:
    HAS_APP = False


def _make_fake_cache():
    """Return a fake cache that stores in memory."""
    class FakeCache:
        def __init__(self):
            self._store = {}
        def get(self, key):
            return self._store.get(key)
        def set(self, key, val, *a, **kw):
            self._store[key] = val
        def delete(self, key):
            self._store.pop(key, None)
        def flushdb(self):
            self._store.clear()
        @property
        def redis(self):
            return self
    return FakeCache()


def _try_real_cache():
    """Try to get a real Redis client, fall back to fake."""
    try:
        c = sogo_cache()
        c.redis.ping()
        return c
    except Exception:
        return _make_fake_cache()


@pytest.fixture
def real_cache():
    """Return a cache client (real Redis or in-memory fake)."""
    if HAS_APP and os.getenv("SOGO_REDIS_HOST"):
        cache = _try_real_cache()
    else:
        cache = _make_fake_cache()
    try:
        cache.redis.flushdb()
    except Exception:
        pass
    yield cache
    try:
        cache.redis.flushdb()
    except Exception:
        pass
