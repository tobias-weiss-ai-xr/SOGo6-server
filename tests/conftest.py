"""Shared fixtures for property-based tests.

Uses mocks when Redis is not available (CI without full stack).
"""
import os
import pytest

# Many test modules call ``os.environ.setdefault("SOGO_P_REDIS_URL",
# "redis://localhost:6379/0")`` at import time to satisfy the ProcessSetting
# model. Because ``_proc_setting()`` in app/service/monitoring gives the raw
# environment precedence, the first such module that runs would otherwise pin
# the health probes to the unreachable loopback URL and make
# test_check_redis_ok_when_local_redis_up fail inside the stack. Pre-seeding
# the REAL in-stack URL here (conftest is imported before any test module)
# turns every later setdefault into a no-op.
os.environ.setdefault("SOGO_P_REDIS_URL", "redis://sogo6-redis:6379/0")

try:
    from app.service import sogo_cache
    HAS_APP = True
except Exception:
    HAS_APP = False


def _make_fake_cache():
    """Return a fake cache that stores in memory.

    Implements the same interface as ``ClientRedis`` (get/set with
    expected_type, delete, flushdb, json serialization) so that tests
    behave identically with or without a real Redis server.
    """
    import json as _json

    class FakeCache:
        def __init__(self):
            self._store = {}

        def get(self, key, expected_type=str):
            raw = self._store.get(key)
            if raw is None:
                return None
            if expected_type == str:
                return raw
            try:
                return _json.loads(raw)
            except (TypeError, _json.JSONDecodeError):
                return raw

        def set(self, key, val, ttl=None, nx=False):
            if nx and key in self._store:
                return False
            if not isinstance(val, str):
                val = _json.dumps(val)
            self._store[key] = val
            return True

        def delete(self, *keys):
            removed = 0
            for key in keys:
                if key in self._store:
                    del self._store[key]
                    removed += 1
            return removed

        def flushdb(self):
            self._store.clear()

        def ping(self):
            return True

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
