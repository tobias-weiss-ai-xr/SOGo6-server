"""Tests for the hybrid SQL+LDAP contact list service (BACKEND-GAPS F3, subsection 1).

Covers:
- ``app.module.contact.LDAPListService`` (hybrid SQL+LDAP listing / member routing)
- ``app.module.contact.LDAPListService.ModuleSQLListProvider`` (SQL side adapter)
- ``app.module.contact.LdapGroupService.list_groups`` / ``has_client`` (LDAP listing)
- ``app.interface.contact.InterfaceApiContactContact.list_lists`` hybrid envelope

All LDAP / DB interactions are mocked; no live LDAP, MySQL or Redis is needed.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

# The ProcessSetting singleton is instantiated at import time; provide the
# minimal required env before any ``app.*`` module is imported.
for _env_key, _env_val in (
    ("SOGO_P_REDIS_URL", "redis://localhost:6379/0"),
    ("SOGO_P_VOUCHER_SECRET", "1234567890abcdef1234567890abcdef"),
    ("SOGO_AES_ENC_KEY", "12345678901234567890123456789012"),
):
    os.environ.setdefault(_env_key, _env_val)

import ldap
import pytest

from app.interface.contact.InterfaceApiContactContact import InterfaceApiContactContact
from app.module.contact.LDAPListService import LDAPListService, ModuleSQLListProvider
from app.module.contact.LdapGroupService import LDAPGroupService
from app.utils import errors as err
from app.utils.exceptions import RequestException

GROUPS_BASE = "ou=groups,dc=example,dc=org"
USERS_BASE = "dc=example,dc=org"

GROUP_DN = f"cn=engineering,{GROUPS_BASE}"
MEMBER_DN = f"uid=jsmith,{USERS_BASE}"
MEMBER_DN_2 = f"uid=janedoe,{USERS_BASE}"
MEMBER_DN_BYTES = MEMBER_DN.encode()

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
        # no description / member -> defaults (member_count 0)
    },
]


# ---------------------------------------------------------------------------
# Fake LDAP plumbing (mirrors test_ldap_group_ops)
# ---------------------------------------------------------------------------
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

    def __init__(self, entries: list[dict] | None = None) -> None:
        self.ldap_conn = FakeLdapConn()
        self.connected = True
        self.binded = True
        self.base_dn = USERS_BASE
        self.entries: list[dict] = entries if entries is not None else []
        self.last_search: tuple | None = None
        self.closed = False

    def search_entries(self, base_dn=None, l_filter=None, attributes=None):
        self.last_search = (base_dn, l_filter, attributes)
        return self.entries

    def close(self) -> None:
        self.closed = True


class FakeSQLProvider:
    """Duck-typed sql_provider recording calls and returning scripted data."""

    def __init__(self, books: list[dict] | None = None, get_members_result: list[str] | None = None,
                 add_member_result: str = "") -> None:
        self.books_result: list[dict] = books if books is not None else []
        self.get_members_result: list[str] = get_members_result if get_members_result is not None else []
        self.add_member_result: str = add_member_result
        self.books_calls: list = []
        self.get_members_calls: list = []
        self.add_member_calls: list = []
        self.remove_member_calls: list = []

    def books(self, user_sources=None):
        self.books_calls.append(user_sources)
        return self.books_result

    def get_members(self, list_id, user_sources=None):
        self.get_members_calls.append((list_id, user_sources))
        return self.get_members_result

    def add_member(self, list_id, contact_id, user_sources=None):
        self.add_member_calls.append((list_id, contact_id, user_sources))
        return self.add_member_result

    def remove_member(self, list_id, contact_id, user_sources=None):
        self.remove_member_calls.append((list_id, contact_id, user_sources))
        return self.add_member_result


def _make_service(client=None, provider=None) -> LDAPListService:
    return LDAPListService(
        process_settings=None,
        user_domain_settings={},
        client=client,
        groups_base=GROUPS_BASE,
        users_base=USERS_BASE,
        sql_provider=provider,
    )


# ---------------------------------------------------------------------------
# LDAPGroupService: group listing + client availability (F3 subsection 3)
# ---------------------------------------------------------------------------
class TestLDAPGroupServiceListing:
    def test_list_groups_returns_raw_entries(self):
        fake = FakeLdapClient(entries=LDAP_GROUPS)
        svc = _make_service(client=fake)
        raw = svc._groups.list_groups()
        assert raw == LDAP_GROUPS
        assert fake.last_search[0] == GROUPS_BASE
        assert fake.last_search[1] == "(objectClass=groupOfNames)"
        assert "cn" in fake.last_search[2] and "member" in fake.last_search[2]

    def test_list_groups_failure_raises_cannot_search(self):
        fake = FakeLdapClient(entries=[])
        fake.search_entries = MagicMock(side_effect=RuntimeError("boom"))
        svc = _make_service(client=fake)
        with pytest.raises(RequestException) as excinfo:
            svc._groups.list_groups()
        assert excinfo.value.error == err.ERROR_LDAP_CANNOT_SEARCH

    def test_has_client(self):
        assert _make_service(client=None)._groups.has_client is False
        assert _make_service(client=FakeLdapClient())._groups.has_client is True


# ---------------------------------------------------------------------------
# Hybrid listing (F3 subsection 1: list_all / list_lists)
# ---------------------------------------------------------------------------
class TestLDAPListServiceListing:
    def test_hybrid_merge_sql_then_ldap(self):
        fake = FakeLdapClient(entries=LDAP_GROUPS)
        provider = FakeSQLProvider(books=[
            {"source": "sql", "id": "book-1", "name": "Personal", "description": None,
             "member_count": 3, "members": []},
        ])
        svc = _make_service(client=fake, provider=provider)
        lists = svc.list_lists()
        assert [lst["source"] for lst in lists] == ["sql", "ldap", "ldap"]
        assert lists[0]["id"] == "book-1"
        assert lists[0]["member_count"] == 3

        eng = lists[1]
        assert eng["id"] == "ldap:engineering"
        assert eng["name"] == "engineering"
        assert eng["description"] == "Engineering team"
        assert eng["member_count"] == 2
        assert eng["members"] == [MEMBER_DN, MEMBER_DN_2]

        sales = lists[2]
        assert sales["id"] == "ldap:sales"
        assert sales["description"] is None
        assert sales["member_count"] == 0
        assert sales["members"] == []
        # user_sources forwarded to the SQL provider
        assert provider.books_calls == [None]

    def test_no_ldap_client_degrades_to_sql_only(self):
        provider = FakeSQLProvider(books=[{"source": "sql", "id": "b1", "name": "B", "member_count": 0}])
        svc = _make_service(client=None, provider=provider)
        lists = svc.list_lists()
        assert [lst["source"] for lst in lists] == ["sql"]
        assert lists[0]["id"] == "b1"

    def test_no_provider_returns_ldap_only(self):
        svc = _make_service(client=FakeLdapClient(entries=LDAP_GROUPS), provider=None)
        lists = svc.list_lists()
        assert [lst["source"] for lst in lists] == ["ldap", "ldap"]

    def test_neither_side_returns_empty(self):
        assert _make_service(client=None, provider=None).list_lists() == []

    def test_ldap_search_failure_surfaces(self):
        fake = FakeLdapClient(entries=[])
        fake.search_entries = MagicMock(side_effect=RuntimeError("boom"))
        svc = _make_service(client=fake, provider=FakeSQLProvider())
        with pytest.raises(RequestException) as excinfo:
            svc.list_lists()
        assert excinfo.value.error == err.ERROR_LDAP_CANNOT_SEARCH

    def test_user_sources_forwarded_to_provider(self):
        us = {"ldap": MagicMock()}
        fake = FakeLdapClient(entries=LDAP_GROUPS)
        provider = FakeSQLProvider()
        svc = _make_service(client=fake, provider=provider)
        svc.list_lists(user_sources=us)
        assert provider.books_calls == [us]


# ---------------------------------------------------------------------------
# Member routing (F3 subsection 1: get_members / add_member)
# ---------------------------------------------------------------------------
class TestLDAPListServiceMemberRouting:
    def test_get_members_ldap_returns_dns(self):
        fake = FakeLdapClient(entries=[{"member": [MEMBER_DN, MEMBER_DN_2]}])
        svc = _make_service(client=fake, provider=FakeSQLProvider())
        assert svc.get_members("ldap:engineering") == [MEMBER_DN, MEMBER_DN_2]
        assert fake.last_search[0] == GROUP_DN

    def test_get_members_sql_calls_provider(self):
        provider = FakeSQLProvider(get_members_result=[MEMBER_DN])
        svc = _make_service(client=None, provider=provider)
        assert svc.get_members("42") == [MEMBER_DN]
        assert provider.get_members_calls == [("42", None)]

    def test_get_members_sql_without_provider_raises_not_found(self):
        svc = _make_service(client=None, provider=None)
        with pytest.raises(RequestException) as excinfo:
            svc.get_members("42")
        assert excinfo.value.error == err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND

    def test_add_member_ldap_mod_add(self):
        fake = FakeLdapClient()
        svc = _make_service(client=fake, provider=FakeSQLProvider())
        assert svc.add_member("ldap:engineering", "jsmith") == MEMBER_DN
        assert fake.ldap_conn.modify_calls == [
            (GROUP_DN, [(ldap.MOD_ADD, "member", MEMBER_DN_BYTES)]),
        ]

    def test_add_member_sql_calls_provider(self):
        provider = FakeSQLProvider(add_member_result="contact-1")
        svc = _make_service(client=None, provider=provider)
        assert svc.add_member("42", "contact-1") == "contact-1"
        assert provider.add_member_calls == [("42", "contact-1", None)]

    def test_add_member_sql_provider_rejection_passthrough(self):
        def _reject(list_id, contact_id, user_sources=None):
            raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED)

        provider = FakeSQLProvider()
        provider.add_member = _reject
        svc = _make_service(client=None, provider=provider)
        with pytest.raises(RequestException) as excinfo:
            svc.add_member("42", "contact-1")
        assert excinfo.value.error == err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED

    def test_add_member_sql_without_provider_raises(self):
        svc = _make_service(client=None, provider=None)
        with pytest.raises(RequestException) as excinfo:
            svc.add_member("42", "contact-1")
        assert excinfo.value.error == err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND

    def test_remove_member_routing(self):
        fake = FakeLdapClient()
        svc = _make_service(client=fake, provider=FakeSQLProvider())
        assert svc.remove_member("ldap:engineering", "jsmith") == MEMBER_DN
        assert fake.ldap_conn.modify_calls == [
            (GROUP_DN, [(ldap.MOD_DELETE, "member", MEMBER_DN_BYTES)]),
        ]

        provider = FakeSQLProvider(add_member_result="contact-1")
        svc2 = _make_service(client=None, provider=provider)
        svc2.remove_member("42", "contact-1")
        assert provider.remove_member_calls == [("42", "contact-1", None)]

    def test_is_ldap_routing_flag(self):
        svc = _make_service()
        assert svc.is_ldap("ldap:engineering") is True
        assert svc.is_ldap("cn=engineering,ou=groups,dc=example,dc=org") is True
        assert svc.is_ldap("42") is False


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------
class TestLDAPListServiceFactories:
    def test_from_user_sources_no_ldap_raises(self):
        with pytest.raises(RequestException) as excinfo:
            LDAPListService.from_user_sources(None)
        assert excinfo.value.error == err.ERROR_LDAP_CANNOT_CONNECT

    def test_from_user_sources_no_ldap_among_others(self):
        with pytest.raises(RequestException) as excinfo:
            LDAPListService.from_user_sources({"db": MagicMock(US_TYPE="mysql")})
        assert excinfo.value.error == err.ERROR_LDAP_CANNOT_CONNECT

    def test_from_user_source_rejects_non_ldap(self):
        with pytest.raises(RequestException) as excinfo:
            LDAPListService.from_user_source(MagicMock(US_TYPE="mysql", US_UID="db"))
        assert excinfo.value.error == err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED


# ---------------------------------------------------------------------------
# ModuleSQLListProvider (production SQL adapter, module mocked)
# ---------------------------------------------------------------------------
class TestModuleSQLListProvider:
    @staticmethod
    def _contact(book_key: str, uid: str):
        contact = MagicMock()
        contact.addressbook_key = book_key
        contact.uid = uid
        contact.name = uid
        return contact

    @staticmethod
    def _book(key: str, name: str, description):
        from types import SimpleNamespace
        return SimpleNamespace(key=key, name=name, description=description)

    def test_books_maps_addressbooks_and_counts(self):
        module = MagicMock()
        module.get_all_addressbooks.return_value = [
            self._book("b1", "One", "d1"),
            self._book("b2", "Two", None),
        ]
        module.get_contacts.return_value = (
            [
                self._contact("b1", "u1"), self._contact("b1", "u2"),
                self._contact("b2", "u3"),
            ],
            3,
        )
        provider = ModuleSQLListProvider(module, MagicMock())
        books = provider.books()
        assert books[0] == {
            "source": "sql", "id": "b1", "name": "One", "description": "d1",
            "member_count": 2, "members": [],
        }
        assert books[1]["id"] == "b2"
        assert books[1]["member_count"] == 1
        # one transverse scan + one book listing
        module.get_contacts.assert_called_once()
        module.get_all_addressbooks.assert_called_once()

    def test_get_members_returns_contact_uids(self):
        module = MagicMock()
        module.get_contacts.return_value = (
            [self._contact("b1", "u1"), self._contact("b1", "u2")], 2,
        )
        user = MagicMock()
        provider = ModuleSQLListProvider(module, user)
        assert provider.get_members("b1") == ["u1", "u2"]
        args = module.get_contacts.call_args.args
        kwargs = module.get_contacts.call_args.kwargs
        assert args[0] is user
        assert args[1] == "b1"  # scoped to the requested book
        assert kwargs["limit"] == 0
        assert kwargs["resolve_ab"] is False
        assert kwargs["resolve_images"] is False

    def test_add_member_sql_rejected(self):
        provider = ModuleSQLListProvider(MagicMock(), MagicMock())
        with pytest.raises(RequestException) as excinfo:
            provider.add_member("b1", "c1")
        assert excinfo.value.error == err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED

    def test_remove_member_sql_rejected(self):
        provider = ModuleSQLListProvider(MagicMock(), MagicMock())
        with pytest.raises(RequestException) as excinfo:
            provider.remove_member("b1", "c1")
        assert excinfo.value.error == err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED


# ---------------------------------------------------------------------------
# Interface delegation (list_lists hybrid envelope)
# ---------------------------------------------------------------------------
class TestInterfaceHybridListMethods:
    @staticmethod
    def _build_interface(fake_service):
        inter = object.__new__(InterfaceApiContactContact)
        inter.user = MagicMock()
        inter.user.uid = "alice@example.com"
        inter._process_setting = None
        inter._user_sources = {}
        inter._hybrid_list_service = lambda: fake_service  # type: ignore[method-assign]
        return inter

    def test_list_lists_envelope(self):
        fake = MagicMock()
        fake.list_lists.return_value = [
            {"source": "sql", "id": "b1", "name": "One", "member_count": 1},
            {"source": "ldap", "id": "ldap:engineering", "name": "engineering", "member_count": 2},
        ]
        data, status = self._build_interface(fake).list_lists()
        assert status == 200
        assert data["data"]["total_count"] == 2
        assert data["data"]["lists"][0]["source"] == "sql"
        assert data["data"]["lists"][1]["id"] == "ldap:engineering"
        assert data["error_code"] == ""
        fake.list_lists.assert_called_once_with(user_sources={})

    def test_list_lists_ldap_error_envelope(self):
        fake = MagicMock()
        fake.list_lists.side_effect = RequestException(error=err.ERROR_LDAP_CANNOT_SEARCH)
        data, status = self._build_interface(fake).list_lists()
        assert data["data"] is None
        assert data["error_code"] == err.ERROR_LDAP_CANNOT_SEARCH.c
        assert status == err.ERROR_LDAP_CANNOT_SEARCH.h

    def test_hybrid_list_service_builds_and_caches(self):
        inter = object.__new__(InterfaceApiContactContact)
        inter._process_setting = None
        inter._user_sources = {}
        inter.module = MagicMock()
        inter.user = MagicMock()
        first = inter._hybrid_list_service()
        second = inter._hybrid_list_service()
        assert isinstance(first, LDAPListService)
        assert first is second  # cached on the instance
        assert isinstance(first._sql_provider, ModuleSQLListProvider)
