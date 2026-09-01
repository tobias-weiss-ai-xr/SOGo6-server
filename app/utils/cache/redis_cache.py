"""Redis caching utility with configurable TTL for SOGo6.

Provides a simple cache interface backed by Redis with type-safe key management
and automatic serialization/deserialization.

Usage:
    from app.utils.cache.redis_cache import RedisCache

    cache = RedisCache(prefix="sogo:ldap", ttl=300)  # 5 min TTL
    cache.set("groups", data)
    data = cache.get("groups")
"""

from __future__ import annotations

import json
import pickle
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from app.service import sogo_cache

if TYPE_CHECKING:
    from redis import ClientRedis

_T = TypeVar("_T")


class RedisCache(Generic[_T]):
    """Generic Redis cache with configurable TTL.

    :param prefix: Key prefix for namespacing (e.g., 'sogo:ldap').
    :param ttl: Time-to-live in seconds (default 300 / 5 minutes).
    :param client: Optional Redis client (uses default sogo_cache() if omitted).
    """

    def __init__(
        self,
        prefix: str,
        ttl: int = 300,
        client: ClientRedis | None = None,
    ) -> None:
        self._prefix: str = prefix
        self._ttl: int = ttl
        self._client: ClientRedis = client or sogo_cache()

    def _make_key(self, key: str) -> str:
        """Build a namespaced cache key."""
        return f"{self._prefix}:{key}"

    def get(self, key: str) -> _T | None:
        """Get a cached value, or None if missing/expired.

        :param key: The cache key (without prefix; prefix is added automatically).
        :return: The cached value, or None if not found or expired.
        """
        full_key = self._make_key(key)
        try:
            value = self._client.get(full_key)
            if value is None:
                return None
            # Try JSON first, fall back to pickle for complex objects
            try:
                return json.loads(value.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return pickle.loads(value)  # type: ignore[no-any-return]
        except Exception:
            return None

    def set(self, key: str, value: _T) -> None:
        """Set a cached value with TTL.

        :param key: The cache key (without prefix; prefix is added automatically).
        :param value: The value to cache (must be JSON-serializable or picklable).
        """
        full_key = self._make_key(key)
        try:
            # Try JSON serialization first
            serialized = json.dumps(value).encode("utf-8")
        except (TypeError, ValueError):
            # Fall back to pickle for complex objects
            serialized = pickle.dumps(value)
        self._client.setex(full_key, self._ttl, serialized)

    def delete(self, key: str) -> None:
        """Delete a cached value.

        :param key: The cache key (without prefix; prefix is added automatically).
        """
        full_key = self._make_key(key)
        self._client.delete(full_key)

    def clear(self) -> None:
        """Delete all keys with this cache's prefix."""
        pattern = f"{self._prefix}:*"
        for key in self._client.scan_iter(match=pattern):
            self._client.delete(key)