"""Tests for LDAP group operations (BACKEND-GAPS F3, subsections 3-4).

Covers:
- ``app.utils.id_resolver``          (address book / group ID resolution)
- ``app.module.contact.LdapGroupService`` (LDAP helper: get/add/remove members)
- ``app.interface.contact.InterfaceApiContactContact`` LDAP list member methods

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
from app.module.contact.LdapGroupService import LDAPGroupService
from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.id_resolver import (
    is_ldap_group,
    is_sql_address_book,
    normalize_id,
    resolve_address_book_id,
)

GROUPS_BASE = "ou=groups,dc=example,dc=org"
USERS_BASE = "dc=example,dc=org"

GROUP_DN = f"cn=engineering,{GROUPS_BASE}"
MEMBER_DN = f"uid=jsmith,{USERS_BASE}"
MEMBER_DN_BYTES = MEMBER_DN.encode()


# ---------------------------------------------------------------------------
# Fake LDAP plumbing
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

    def __init__(self) -> None:
        self.ldap_conn = FakeLdapConn()
        self.connected = True
        self.binded = True
        self.base_dn = USERS_BASE
        self.entries: list[dict[str, list[str]]] = []
        self.last_search: tuple | None = None
        self.closed = False

    def search_entries(self, base_dn=None, l_filter=None, attributes=None):
        self.last_search = (base_dn, l_filter, attributes)
        return self.entries

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def service() -> LDAPGroupService:
    return LDAPGroupService(
        process_settings=None,
        user_domain_settings={},
        groups_base=GROUPS_BASE,
        users_base=USERS_BASE,
    )


@pytest.fixture
def client(service, monkeypatch) -> FakeLdapClient:
    fake = FakeLdapClient()
    monkeypatch.setattr(service, "_get_ldap_client", lambda: fake)
    return fake


# ---------------------------------------------------------------------------
# ID resolution (F3 subsection 4)
# ---------------------------------------------------------------------------
class TestAddressBookIdResolver:
    def test_numeric_id_is_sql(self):
        resolved = resolve_address_book_id("123")
        assert resolved.source_type == "sql"
        assert resolved.is_ldap is False
        assert resolved.is_sql is True
        assert resolved.normalized_id == "123"
        assert resolved.raw_id == "123"

    def test_zero_and_negative_style_numeric(self):
        assert resolve_address_book_id("0").is_ldap is False
        assert resolve_address_book_id("-1").is_sql  # falls back to SQL default

    def test_empty_id_falls_back_to_sql(self):
        assert resolve_address_book_id("").is_ldap is False
        assert resolve_address_book_id(None).is_sql is True
        assert resolve_address_book_id("").normalized_id == ""

    def test_ldap_prefix_id(self):
        resolved = resolve_address_book_id("ldap:engineering-team")
        assert resolved.source_type == "ldap"
        assert resolved.is_ldap is True
        assert resolved.normalized_id == "engineering-team"
        assert resolved.raw_id == "ldap:engineering-team"

    def test_ldap_prefix_id_case_insensitive(self):
        assert resolve_address_book_id("LDAP:sales").is_ldap is True
        assert resolve_address_book_id("LDAP:sales").normalized_id == "sales"

    def test_ldap_dn_id_normalized_to_cn(self):
        resolved = resolve_address_book_id("cn=team,ou=groups,dc=example,dc=org")
        assert resolved.is_ldap is True
        assert resolved.normalized_id == "team"

    def test_plain_string_defaults_to_sql(self):
        # Unknown formats keep the legacy SQL behaviour.
        assert resolve_address_book_id("engineering").is_sql is True
        assert resolve_address_book_id("some-uuid-key").is_ldap is False

    def test_helper_functions(self):
        assert is_ldap_group("ldap:engineering") is True
        assert is_ldap_group("cn=x,ou=groups,dc=example,dc=org") is True
        assert is_ldap_group("42") is False
        assert is_sql_address_book("42") is True
        assert is_sql_address_book("ldap:engineering") is False
        assert normalize_id("ldap:engineering") == "engineering"
        assert normalize_id("cn=team,ou=groups,dc=example,dc=org") == "team"
        assert normalize_id("42") == "42"


# ---------------------------------------------------------------------------
# LDAP helper for group operations (F3 subsection 3)
# ---------------------------------------------------------------------------
class TestLDAPGroupServiceIdResolution:
    def test_is_ldap_accepts_prefix_dn_and_rejects_numeric(self, service):
        assert service._is_ldap("ldap:engineering") is True
        assert service._is_ldap("cn=engineering,ou=groups,dc=example,dc=org") is True
        assert service._is_ldap("42") is False

    def test_resolve_cn_extracts_from_prefix_and_dn(self, service):
        assert service._resolve_cn("ldap:engineering") == "engineering"
        assert service._resolve_cn("cn=engineering,ou=groups,dc=example,dc=org") == "engineering"

    def test_dn_helpers(self, service):
        assert service._build_group_dn("engineering") == GROUP_DN
        assert service._build_member_dn("jsmith") == MEMBER_DN
        assert service.to_dn("jsmith") == MEMBER_DN


class TestLDAPGroupServiceGetMembers:
    def test_returns_member_attributes(self, service, client):
        client.entries = [{"member": [MEMBER_DN, f"uid=janedoe,{USERS_BASE}"]}]
        members = service.get_members("ldap:engineering")
        assert members == [MEMBER_DN, f"uid=janedoe,{USERS_BASE}"]
        assert client.last_search[0] == GROUP_DN  # base_dn is the group itself
        assert client.last_search[1] == "(objectClass=groupOfNames)"
        assert "member" in client.last_search[2]

    def test_missing_group_raises_list_not_found(self, service, client):
        client.entries = []
        with pytest.raises(RequestException) as excinfo:
            service.get_members("ldap:engineering")
        assert excinfo.value.error == err.ERROR_CONTACT_LIST_NOT_FOUND

    def test_sql_id_rejected(self, service, client):
        client.entries = [{"member": []}]
        with pytest.raises(RequestException) as excinfo:
            service.get_members("42")
        assert excinfo.value.error == err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND
        assert client.last_search is None


class TestLDAPGroupServiceAddMember:
    def test_add_member_modifies_group(self, service, client):
        result = service.add_member("ldap:engineering", "jsmith")
        assert result == MEMBER_DN
        assert client.ldap_conn.modify_calls == [
            (GROUP_DN, [(ldap.MOD_ADD, "member", MEMBER_DN_BYTES)]),
        ]

    def test_add_member_accepts_dn_id(self, service, client):
        service.add_member("cn=engineering,ou=groups,dc=example,dc=org", "jsmith")
        assert client.ldap_conn.modify_calls[0][0] == GROUP_DN

    def test_add_member_duplicate_is_idempotent(self, service, client):
        client.ldap_conn.queue_error(ldap.TYPE_OR_VALUE_EXISTS())
        assert service.add_member("ldap:engineering", "jsmith") == MEMBER_DN

    def test_add_member_error_raises_modify_failed(self, service, client):
        client.ldap_conn.queue_error(ldap.LDAPError("server down"))
        with pytest.raises(RequestException) as excinfo:
            service.add_member("ldap:engineering", "jsmith")
        assert excinfo.value.error == err.ERROR_LDAP_MODIFY_FAILED

    def test_add_member_missing_group_raises_group_not_found(self, service, client):
        client.ldap_conn.queue_error(ldap.NO_SUCH_OBJECT("no such object"))
        with pytest.raises(RequestException) as excinfo:
            service.add_member("ldap:engineering", "jsmith")
        assert excinfo.value.error == err.ERROR_LDAP_GROUP_NOT_FOUND

    def test_add_member_sql_id_rejected(self, service, client):
        with pytest.raises(RequestException) as excinfo:
            service.add_member("42", "jsmith")
        assert excinfo.value.error == err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND
        assert client.ldap_conn.modify_calls == []


class TestLDAPGroupServiceRemoveMember:
    def test_remove_member_modifies_group(self, service, client):
        result = service.remove_member("ldap:engineering", "jsmith")
        assert result == MEMBER_DN
        assert client.ldap_conn.modify_calls == [
            (GROUP_DN, [(ldap.MOD_DELETE, "member", MEMBER_DN_BYTES)]),
        ]

    def test_remove_member_missing_is_idempotent(self, service, client):
        client.ldap_conn.queue_error(ldap.NO_SUCH_ATTRIBUTE())
        assert service.remove_member("ldap:engineering", "jsmith") == MEMBER_DN

    def test_remove_member_error_raises_modify_failed(self, service, client):
        client.ldap_conn.queue_error(ldap.LDAPError("server down"))
        with pytest.raises(RequestException) as excinfo:
            service.remove_member("ldap:engineering", "jsmith")
        assert excinfo.value.error == err.ERROR_LDAP_MODIFY_FAILED

    def test_remove_member_sql_id_rejected(self, service, client):
        with pytest.raises(RequestException) as excinfo:
            service.remove_member("42", "jsmith")
        assert excinfo.value.error == err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND
        assert client.ldap_conn.modify_calls == []


# ---------------------------------------------------------------------------
# Interface delegation
# ---------------------------------------------------------------------------
class TestInterfaceLDAPListMethods:
    @staticmethod
    def _build_interface(fake_service):
        inter = object.__new__(InterfaceApiContactContact)
        inter.user = MagicMock()
        inter.user.uid = "alice@example.com"
        inter._process_setting = None
        inter._user_sources = {}
        # Inject the fake service seam (no DB / LDAP required).
        inter._ldap_list_service = lambda: fake_service  # type: ignore[method-assign]
        return inter

    def test_get_list_members_envelope(self):
        fake = MagicMock()
        fake.get_members.return_value = [MEMBER_DN]
        data, status = self._build_interface(fake).get_list_members("ldap:engineering")
        assert status == 200
        assert data["data"] == {"members": [MEMBER_DN], "total_count": 1}
        assert data["error_code"] == ""

    def test_add_list_member_envelope(self):
        fake = MagicMock()
        fake.add_member.return_value = MEMBER_DN
        data, status = self._build_interface(fake).add_list_member("ldap:engineering", "jsmith")
        assert status == 201
        assert data["data"] == {"member_dn": MEMBER_DN}
        fake.add_member.assert_called_once_with("ldap:engineering", "jsmith")

    def test_remove_list_member_envelope(self):
        fake = MagicMock()
        fake.remove_member.return_value = MEMBER_DN
        data, status = self._build_interface(fake).remove_list_member("ldap:engineering", "jsmith")
        assert status == 200
        assert data["data"] == {"member_dn": MEMBER_DN}
        fake.remove_member.assert_called_once_with("ldap:engineering", "jsmith")

    def test_add_list_member_sql_id_error_envelope(self):
        fake = MagicMock()
        fake.add_member.side_effect = RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND)
        data, status = self._build_interface(fake).add_list_member("42", "jsmith")
        assert data["data"] is None
        assert data["error_code"] == err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND.c
        assert status == err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND.h

    def test_get_list_members_ldap_error_envelope(self):
        fake = MagicMock()
        fake.get_members.side_effect = RequestException(error=err.ERROR_LDAP_MODIFY_FAILED)
        data, status = self._build_interface(fake).get_list_members("ldap:engineering")
        assert data["data"] is None
        assert data["error_code"] == err.ERROR_LDAP_MODIFY_FAILED.c
        assert status == err.ERROR_LDAP_MODIFY_FAILED.h

    def test_ldap_list_service_builds_and_caches_service(self):
        inter = object.__new__(InterfaceApiContactContact)
        inter._process_setting = None
        inter._user_sources = {}
        first = inter._ldap_list_service()
        second = inter._ldap_list_service()
        assert isinstance(first, LDAPGroupService)
        assert first is second  # cached on the instance
