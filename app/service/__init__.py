from app.config.settings.ProcessSetting import process_config
from app.manager.agent.ClientAgent import ClientAgent
from app.manager.cache.ClientRedis import ClientRedis
from app.utils import exceptions as exc
import threading

cache_client: ClientRedis|None = None
agent_client: ClientAgent|None = None
_cache_lock = threading.Lock()
_agent_lock = threading.Lock()

def sogo_cache() -> ClientRedis:
    """
    Return the cache client.
    
    Uses the globally-initialised ``cache_client`` when available (set by
    ``run.py`` / ``agent/run.py`` via ``set_cache()``).  Falls back to
    creating a fresh instance only if the global is not yet set.
    Thread-safe via a lock to prevent race conditions during initialization.
    This avoids the 160+ connection leaks that would occur if every caller
    created a new ``ClientRedis``.
    """
    global cache_client
    if isinstance(cache_client, ClientRedis):
        return cache_client
    with _cache_lock:
        if isinstance(cache_client, ClientRedis):
            return cache_client
        redis_conf = process_config.get_redis_settings()
        cache_client = ClientRedis(**redis_conf)
        return cache_client

def set_cache(new_cache: ClientRedis) -> None:
    """
    Set the cache, will be the same for all requests of this worker
    """
    global cache_client # pylint: disable=global-statement
    cache_client = new_cache

def sogo_agent() -> ClientAgent:
    """Return the agent client. Set by ``run.py`` at process start.
    Thread-safe initialization to prevent race conditions."""
    if isinstance(agent_client, ClientAgent):
        return agent_client
    with _agent_lock:
        if isinstance(agent_client, ClientAgent):
            return agent_client
        raise exc.AggravatedException("Agent client not instantiated when needed")

def set_agent(new_client: ClientAgent) -> None:
    """Set the agent client, shared by all requests of this worker."""
    global agent_client # pylint: disable=global-statement
    agent_client = new_client
