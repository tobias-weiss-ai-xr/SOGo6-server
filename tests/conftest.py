"""Shared fixtures using real infrastructure (Redis)."""
import pytest
from app.service import sogo_cache
from app.manager.cache.ClientRedis import ClientRedis


@pytest.fixture
def real_cache():
    """Return a real Redis client, flushing DB before each test."""
    cache = sogo_cache()
    try:
        cache.redis.flushdb()
    except Exception:
        pass
    yield cache
    try:
        cache.redis.flushdb()
    except Exception:
        pass
