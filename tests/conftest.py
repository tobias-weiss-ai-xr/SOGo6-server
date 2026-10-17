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

# ``ProcessSetting`` declares SOGO_P_VOUCHER_SECRET and SOGO_AES_ENC_KEY as
# required fields with no default, and ``ProcessSetting()`` is instantiated at
# module import time (app/config/settings/ProcessSetting.py). Without them,
# importing the app raises a pydantic ValidationError and pytest aborts during
# conftest collection (exit code 4, ZERO tests collected) — which also makes
# the coverage gate report a bogus ~1% total and fail. Pre-seeding obviously
# dummy, test-only values here keeps the suite hermetic: no real secrets are
# required to run the tests, and a real environment variable still overrides
# them because conftest uses setdefault (raw environment takes precedence).
# Values are 32 chars to satisfy the documented key sizes (Fernet 32-char
# string / AES-256 32-byte key) in case a test exercises the crypto directly.
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "test-only-voucher-secret-32chars")
os.environ.setdefault("SOGO_AES_ENC_KEY", "test-only-aes256-key-32-bytes!!!")

# ``init_sogo()`` also calls ``_check_admin_password_hardening()`` (CRA Art. 15)
# at import time and refuses to start when SOGO_P_ADMIN_PWD is empty or the
# literal default 'admin'. The check only requires a non-empty non-'admin'
# value, so a clearly dummy test value clears it without weakening any real
# deployment (real env still wins via setdefault).
os.environ.setdefault("SOGO_P_ADMIN_PWD", "test-only-admin-pwd-not-a-real-secret")

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
