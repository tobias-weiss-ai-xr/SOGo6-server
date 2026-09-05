"""Unit tests for the app.service lazy singleton helpers (sogo_cache/sogo_agent).

Covers the double-checked-locking fast paths, the in-lock re-checks (via a lock
whose context manager injects the singleton) and the not-instantiated error.
"""
import threading
import types
from unittest import mock

import pytest

from app.service import sogo_cache, set_cache, sogo_agent, set_agent
from app.utils import exceptions as exc
from app.manager.cache.ClientRedis import ClientRedis
from app.manager.agent.ClientAgent import ClientAgent


@pytest.fixture(autouse=True)
def _reset_globals(monkeypatch):
    import app.service as svc

    monkeypatch.setattr(svc, "cache_client", None)
    monkeypatch.setattr(svc, "agent_client", None)
    monkeypatch.setattr(svc, "_cache_lock", threading.Lock())
    monkeypatch.setattr(svc, "_agent_lock", threading.Lock())
    yield


class _SetCacheOnEnter:
    """Lock stand-in: when context-managed, installs a ClientRedis as the cache."""

    def __enter__(self):
        set_cache(ClientRedis.__new__(ClientRedis))
        return self

    def __exit__(self, *args):
        return False


class _SetAgentOnEnter:
    def __enter__(self):
        set_agent(ClientAgent.__new__(ClientAgent))
        return self

    def __exit__(self, *args):
        return False


class TestSogoCache:
    def test_creates_and_reuses_cache(self, monkeypatch):
        import app.service as svc

        redis_conf = {"url_str": "redis://localhost:6390/0", "resp3": False}
        monkeypatch.setattr(
            svc, "process_config", types.SimpleNamespace(get_redis_settings=lambda: redis_conf)
        )
        first = sogo_cache()
        assert isinstance(first, ClientRedis)
        second = sogo_cache()
        assert second is first  # second call reuses global, no new client

    def test_returns_existing_cache_singleton(self, monkeypatch):
        new = ClientRedis.__new__(ClientRedis)
        set_cache(new)
        assert sogo_cache() is new

    def test_inlock_recheck_returns_injected_cache(self, monkeypatch):
        import app.service as svc

        monkeypatch.setattr(svc, "_cache_lock", _SetCacheOnEnter())
        cache = sogo_cache()
        assert isinstance(cache, ClientRedis)


class TestSogoAgent:
    def test_not_instantiated_raises(self):
        with pytest.raises(exc.AggravatedException):
            sogo_agent()

    def test_returns_set_agent(self):
        new = ClientAgent.__new__(ClientAgent)
        set_agent(new)
        assert sogo_agent() is new

    def test_inlock_recheck_returns_injected_agent(self, monkeypatch):
        import app.service as svc

        monkeypatch.setattr(svc, "_agent_lock", _SetAgentOnEnter())
        agent = sogo_agent()
        assert isinstance(agent, ClientAgent)
