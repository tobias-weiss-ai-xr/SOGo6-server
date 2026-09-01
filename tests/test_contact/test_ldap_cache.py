"""Tests for LDAP query caching and pagination (BACKEND-GAPS F3, subsection 5).

Covers:
- ``app.utils.cache.redis_cache`` (Redis cache utility with TTL)
- ``app.module.contact.LdapGroupService.list_groups`` (cached group listing)
- ``app.module.contact.LDAPListService.list_lists`` (pagination support)
- Cache invalidation on member operations (add/remove member)

All LDAP / Redis / DB interactions are mocked; no live Redis, LDAP, or MySQL is needed.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

# The ProcessSetting singleton is instantiated at import time; provide the
# minimal required env before any ``app.*`` module is imported.
for _env_key, _env_val in (
    ("SOGO_P_REDIS_URL", "redis://localhost:6379/0"),
    ("SOGO_P_VOUCHER_SECRET", "1234567890abcdef1234567890abcdef"),
    ("SOGO_AES_ENC_KEY", "12345678901234567890123456789012"),
):
    os.environ.setdefault(_env_key, _env_val)

import pytest

from app.module.contact.LdapGroupService import LDAPGroupService
from app.module.contact.LDAPListService import LDAPListService
from app.utils.cache.redis_cache import RedisCache
from app.utils.exceptions import RequestException

GROUPS_BASE = "ou=groups,dc=example,dc=org"
USERS_BASE = "dc=example,dc=org"

GROUP_DN = f"cn=engineering,{GROUPS_BASE}"
MEMBER_DN = f"uid=jsmith,{USERS_BASE}"
MEMBER_DN_2 = f"uid=janedoe,{USERS_BASE}"


class FakeLdapConn:
    """Replacement for a python-ldap connection: records modify_s calls."""

    def __init__(self) -> None:
        self.modify_calls: list[tuple[str, list]] = []
        self._pending_errors: list[Exception] = []

    def queue_error(self, exc: Exception) -> None:
        self._pending_errors.append(exc)

    def modify_s(self, dn: str, modlist: list) -> None:
        if self._pending_errors:
            raise self._pending_errors.pop(0)
        self.modify_calls.append((dn, modlist))


class FakeLdapClient:
    """Replacement for ClientLdap with a scriptable search/modify surface."""

    def __init__(self, entries: list[dict[str, list[str]]] | None = None) -> None:
        self.ldap_conn = FakeLdapConn()
        self.connected = True
        self.binded = True
        self.base_dn = USERS_BASE
        self.entries: list[dict[str, list[str]]] = entries if entries is not None else []
        self.last_search: tuple | None = None
        self.closed = False

    def search_entries(self, base_dn=None, l_filter=None, attributes=None):
        self.last_search = (base_dn, l_filter, attributes)
        return self.entries

    def close(self) -> None:
        self.closed = True


class FakeRedisClient:
    """Replacement for Redis client with a scriptable interface."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self._ttl: dict[str, int] = {}
        self.get_calls: list[str] = []
        self.setex_calls: list[tuple[str, int, bytes]] = []
        self.delete_calls: list[str] = []
        self.scan_calls: list[str] = []

    def get(self, key: str) -> bytes | None:
        self.get_calls.append(key)
        return self._data.get(key)

    def setex(self, key: str, ttl: int, value: bytes) -> None:
        self.setex_calls.append((key, ttl, value))
        self._data[key] = value

    def delete(self, key: str) -> int:
        self.delete_calls.append(key)
        if key in self._data:
            del self._data[key]
        return 1

    def scan_iter(self, match: str | None = None):
        self.scan_calls.append(match)
        for key in self._data.keys():
            if match is None or key == match.replace("*", ".*"):
                yield key


# Fake LDAP groups data
LDAP_GROUPS = [
    {
        "dn": [GROUP_DN],
        "cn": ["engineering"],
        "description": ["Engineering team"],
        "member": [MEMBER_DN, MEMBER_DN_2],
    },
    {
        "dn": [f"cn=sales,{GROUPS_BASE}"],
        "cn": ["sales"],
        "description": ["Sales team"],
        "member": [f"uid=alice,{USERS_BASE}"],
    },
    {
        "dn": [f"cn=devops,{GROUPS_BASE}"],
        "cn": ["devops"],
        # no description / member -> defaults (member_count 0)
    },
]


class TestRedisCache:
    """Tests for the Redis cache utility."""

    def test_set_and_get_string(self):
        """Set and get a string value with TTL."""
        client = FakeRedisClient()
        cache = RedisCache[str](prefix="sogo:test", ttl=300, client=client)
        cache.set("key1", "value1")
        result = cache.get("key1")
        assert result == "value1"
        assert len(client.setex_calls) == 1
        key, ttl, value = client.setex_calls[0]
        assert "sogo:test:key1" in key
        assert ttl == 300
        assert b"value1" in value

    def test_set_and_get_list(self):
        """Set and get a list of dicts with TTL."""
        client = FakeRedisClient()
        cache = RedisCache[list](prefix="sogo:test", ttl=300, client=client)
        data = [{"name": "test", "value": 1}, {"name": "test2", "value": 2}]
        cache.set("key1", data)
        result = cache.get("key1")
        assert result == data

    def test_cache_miss_returns_none(self):
        """Get for non-existent key returns None."""
        client = FakeRedisClient()
        cache = RedisCache[str](prefix="sogo:test", ttl=300, client=client)
        result = cache.get("nonexistent")
        assert result is None

    def test_delete_invalidates_cache(self):
        """Delete removes the cached value."""
        client = FakeRedisClient()
        cache = RedisCache[str](prefix="sogo:test", ttl=300, client=client)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
        cache.delete("key1")
        assert cache.get("key1") is None

    def test_ttl_is_applied(self):
        """TTL is passed to setex correctly."""
        client = FakeRedisClient()
        cache = RedisCache[str](prefix="sogo:test", ttl=600, client=client)  # 10 min
        cache.set("key1", "value1")
        assert len(client.setex_calls) == 1
        _, ttl, _ = client.setex_calls[0]
        assert ttl == 600


class TestLdapGroupServiceCaching:
    """Tests for LDAP group caching in LdapGroupService."""

    def test_list_groups_caches_result(self):
        """list_groups() caches LDAP results in Redis."""
        fake_client = FakeLdapClient(entries=LDAP_GROUPS)
        fake_redis = FakeRedisClient()
        svc = LDAPGroupService(
            process_settings=None,
            user_domain_settings={},
            client=fake_client,
            redis_client=fake_redis,
            groups_base=GROUPS_BASE,
            users_base=USERS_BASE,
            cache_ttl=300,
        )
        # First call - should fetch from LDAP
        groups1 = svc.list_groups()
        assert len(groups1) == 3
        assert fake_client.last_search[0] == GROUPS_BASE

    def test_list_groups_cache_ttl(self):
        """Cache uses the configured TTL (5 min default)."""
        fake_client = FakeLdapClient(entries=LDAP_GROUPS)
        fake_redis = FakeRedisClient()
        svc = LDAPGroupService(
            process_settings=None,
            user_domain_settings={},
            client=fake_client,
            redis_client=fake_redis,
            groups_base=GROUPS_BASE,
            users_base=USERS_BASE,
            cache_ttl=600,  # 10 min
        )
        svc.list_groups()

        # Check that setex was called with TTL=600
        assert len(fake_redis.setex_calls) == 1
        _, ttl, _ = fake_redis.setex_calls[0]
        assert ttl == 600

    def test_add_member_invalidates_cache(self):
        """add_member() invalidates the cached groups list."""
        fake_client = FakeLdapClient(entries=LDAP_GROUPS)
        fake_redis = FakeRedisClient()

        svc = LDAPGroupService(
            process_settings=None,
            user_domain_settings={},
            client=fake_client,
            redis_client=fake_redis,
            groups_base=GROUPS_BASE,
            users_base=USERS_BASE,
            cache_ttl=300,
        )

        # Populate the cache
        svc.list_groups()

        # Clear the get_calls to track invalidate
        fake_redis.get_calls.clear()

        # Add a member - should invalidate cache
        svc.add_member("ldap:engineering", "newuser")

        # Check that cache delete was called
        assert "sogo:ldap:groups:groups_list" in fake_redis.delete_calls

    def test_remove_member_invalidates_cache(self):
        """remove_member() invalidates the cached groups list."""
        fake_client = FakeLdapClient(entries=LDAP_GROUPS)
        fake_redis = FakeRedisClient()

        svc = LDAPGroupService(
            process_settings=None,
            user_domain_settings={},
            client=fake_client,
            redis_client=fake_redis,
            groups_base=GROUPS_BASE,
            users_base=USERS_BASE,
            cache_ttl=300,
        )

        # Populate the cache
        svc.list_groups()

        # Remove a member - should invalidate cache
        svc.remove_member("ldap:engineering", "jsmith")

        # Check that cache delete was called
        assert "sogo:ldap:groups:groups_list" in fake_redis.delete_calls

    def test_clear_cache_explicitly(self):
        """clear_cache() explicitly invalidates the cache."""
        fake_client = FakeLdapClient(entries=LDAP_GROUPS)
        fake_redis = FakeRedisClient()

        svc = LDAPGroupService(
            process_settings=None,
            user_domain_settings={},
            client=fake_client,
            redis_client=fake_redis,
            groups_base=GROUPS_BASE,
            users_base=USERS_BASE,
            cache_ttl=300,
        )

        # Populate the cache
        svc.list_groups()

        # Clear the cache explicitly
        svc.clear_cache()

        # Check that cache delete was called
        assert "sogo:ldap:groups:groups_list" in fake_redis.delete_calls


class TestLDAPListServicePagination:
    """Tests for pagination in LDAPListService.list_lists()."""

    class FakeSQLProvider:
        """Fake SQL provider for testing."""

        def __init__(self, books: list[dict] | None = None) -> None:
            self.books_result: list[dict] = books if books is not None else []

        def books(self, user_sources=None, collection_param=None):
            return self.books_result

    class FakeCollectionPaginateArgs:
        """Fake pagination args for testing."""

        def __init__(self, page: int = 1, page_size: int = 10,
                     sort_by: str | None = None, sort_order: str = "asc") -> None:
            self.page = page
            self.page_size = page_size
            self.sort_by = sort_by
            self.sort_order = sort_order

    def test_list_lists_returns_total_count(self):
        """list_lists() returns a tuple of (total_count, paginated_list)."""
        fake_client = FakeLdapClient(entries=LDAP_GROUPS)
        fake_redis = FakeRedisClient()
        provider = self.FakeSQLProvider(books=[
            {"source": "sql", "id": "book-1", "name": "Personal", "description": None,
             "member_count": 3, "members": []},
        ])
        svc = LDAPListService(
            process_settings=None,
            user_domain_settings={},
            client=fake_client,
            redis_client=fake_redis,
            groups_base=GROUPS_BASE,
            users_base=USERS_BASE,
            sql_provider=provider,
        )
        total, lists = svc.list_lists()
        assert isinstance(total, int)
        assert total == 4  # 1 SQL + 3 LDAP
        assert isinstance(lists, list)
        assert len(lists) == 4

    def test_list_lists_pagination_applies_offset(self):
        """list_lists() respects page/limit for offset."""
        fake_client = FakeLdapClient(entries=LDAP_GROUPS)
        fake_redis = FakeRedisClient()
        svc = LDAPListService(
            process_settings=None,
            user_domain_settings={},
            client=fake_client,
            redis_client=fake_redis,
            groups_base=GROUPS_BASE,
            users_base=USERS_BASE,
            sql_provider=None,
        )

        # Page 1, limit 2 - should get first 2 items
        total, lists = svc.list_lists(collection_param=self.FakeCollectionPaginateArgs(page=1, page_size=2))
        assert total == 3  # 3 LDAP groups total
        assert len(lists) == 2
        assert lists[0]["id"] == "ldap:engineering"
        assert lists[1]["id"] == "ldap:sales"

        # Page 2, limit 2 - should get next 2 items (only 1 left)
        total, lists = svc.list_lists(collection_param=self.FakeCollectionPaginateArgs(page=2, page_size=2))
        assert len(lists) == 1
        assert lists[0]["id"] == "ldap:devops"

    def test_list_lists_pagination_respects_limit(self):
        """list_lists() respects page_size for limit."""
        fake_client = FakeLdapClient(entries=LDAP_GROUPS)
        fake_redis = FakeRedisClient()
        svc = LDAPListService(
            process_settings=None,
            user_domain_settings={},
            client=fake_client,
            redis_client=fake_redis,
            groups_base=GROUPS_BASE,
            users_base=USERS_BASE,
            sql_provider=None,
        )

        # Small limit
        total, lists = svc.list_lists(collection_param=self.FakeCollectionPaginateArgs(page=1, page_size=1))
        assert len(lists) == 1

        # Large limit
        total, lists = svc.list_lists(collection_param=self.FakeCollectionPaginateArgs(page=1, page_size=100))
        assert len(lists) == 3  # All 3 groups fit

    def test_list_lists_pagination_with_sort(self):
        """list_lists() sorts results when sort_by is specified."""
        fake_client = FakeLdapClient(entries=LDAP_GROUPS)
        fake_redis = FakeRedisClient()
        svc = LDAPListService(
            process_settings=None,
            user_domain_settings={},
            client=fake_client,
            redis_client=fake_redis,
            groups_base=GROUPS_BASE,
            users_base=USERS_BASE,
            sql_provider=None,
        )

        # Sort by name ascending
        total, lists = svc.list_lists(
            collection_param=self.FakeCollectionPaginateArgs(page=1, page_size=10, sort_by="name", sort_order="asc")
        )
        assert len(lists) == 3
        assert lists[0]["name"] == "devops"  # d < e < s
        assert lists[1]["name"] == "engineering"
        assert lists[2]["name"] == "sales"

        # Sort by name descending
        total, lists = svc.list_lists(
            collection_param=self.FakeCollectionPaginateArgs(page=1, page_size=10, sort_by="name", sort_order="desc")
        )
        assert len(lists) == 3
        assert lists[0]["name"] == "sales"
        assert lists[1]["name"] == "engineering"
        assert lists[2]["name"] == "devops"

    def test_list_lists_pagination_sql_and_ldap_combined(self):
        """list_lists() merges SQL and LDAP, then paginates together."""
        fake_client = FakeLdapClient(entries=LDAP_GROUPS)
        fake_redis = FakeRedisClient()
        provider = self.FakeSQLProvider(books=[
            {"source": "sql", "id": "book-a", "name": "A-Book", "description": None,
             "member_count": 1, "members": []},
            {"source": "sql", "id": "book-b", "name": "B-Book", "description": "Desc B",
             "member_count": 2, "members": []},
            {"source": "sql", "id": "book-c", "name": "C-Book", "description": "Desc C",
             "member_count": 3, "members": []},
        ])
        svc = LDAPListService(
            process_settings=None,
            user_domain_settings={},
            client=fake_client,
            redis_client=fake_redis,
            groups_base=GROUPS_BASE,
            users_base=USERS_BASE,
            sql_provider=provider,
        )

        # With limit 2, should get first 2 of combined (SQL first, then LDAP)
        total, lists = svc.list_lists(collection_param=self.FakeCollectionPaginateArgs(page=1, page_size=2))
        assert total == 6  # 3 SQL + 3 LDAP
        assert len(lists) == 2
        assert lists[0]["source"] == "sql"
        assert lists[1]["source"] == "sql"

        # Page 2, limit 2 - next 2
        total, lists = svc.list_lists(collection_param=self.FakeCollectionPaginateArgs(page=2, page_size=2))
        assert len(lists) == 2
        # After SQL books, should get LDAP groups
        assert lists[0]["source"] == "sql"
        assert lists[1]["source"] == "ldap"

    def test_list_lists_without_pagination_returns_all(self):
        """list_lists() without pagination returns all items."""
        fake_client = FakeLdapClient(entries=LDAP_GROUPS)
        fake_redis = FakeRedisClient()
        svc = LDAPListService(
            process_settings=None,
            user_domain_settings={},
            client=fake_client,
            redis_client=fake_redis,
            groups_base=GROUPS_BASE,
            users_base=USERS_BASE,
            sql_provider=None,
        )

        total, lists = svc.list_lists()  # No pagination
        assert total == 3
        assert len(lists) == 3
