"""Tests for LDAP group operations (F3: add/remove member) and the address book
ID resolver.

These tests run without any live stack: LDAP is mocked with a fake client
object exposing a fake python-ldap connection, and no database / SMTP / Redis
services are touched.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import ldap
import pytest

from app.module.contact.LdapGroupService import LDAPGroupService
from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.id_resolver import (
    ResolvedId,
    is_ldap_group,
    is_sql_address_book,
    normalize_id,
    resolve_address_book_id,
)


# ---------------------------------------------------------------------------
# Address book / group ID resolution
# ---------------------------------------------------------------------------


class TestResolveAddressBookId:
    """The id resolver must route ids to SQL address books or LDAP groups."""

    def test_numeric_id_is_sql(self):
        resolved = resolve_address_book_id("123")
        assert isinstance(resolved, ResolvedId)
        assert resolved.source_type == "sql"
        assert resolved.raw_id == "123"
        assert resolved.normalized_id == "123"
        assert resolved.is_ldap is False
        assert resolved.is_sql is True

    def test_empty_id_defaults_to_sql(self):
        for raw in ("", None):
            resolved = resolve_address_book_id(raw)
            assert resolved.source_type == "sql"
            assert resolved.is_ldap is False

    def test_ldap_prefix_is_ldap(self):
        resolved = resolve_address_book_id("ldap:engineering-team")
        assert resolved.source_type == "ldap"
        assert resolved.is_ldap is True
        assert resolved.normalized_id == "engineering-team"

    def test_ldap_dn_is_ldap(self):
        resolved = resolve_address_book_id("cn=engineering-team,ou=groups,dc=example,dc=org")
        assert resolved.source_type == "ldap"
        assert resolved.is_ldap is True
        assert resolved.normalized_id == "engineering-team"

    def test_ldap_dn_any_case(self):
        resolved = resolve_address_book_id("CN=Sales,OU=Groups,DC=Example,DC=Org")
        assert resolved.source_type == "ldap"
        assert resolved.normalized_id == "Sales"

    def test_ldap_prefix_case_insensitive(self):
        resolved = resolve_address_book_id("LDAP:finance")
        assert resolved.is_ldap is True
        assert resolved.normalized_id == "finance"

    def test_unrecognized_string_defaults_to_sql(self):
        # Backwards compatibility: non-numeric text ids are SQL address books.
        resolved = resolve_address_book_id("my-address-book")
        assert resolved.source_type == "sql"
        assert resolved.is_ldap is False
        assert resolved.normalized_id == "my-address-book"

    def test_helpers(self):
        assert is_ldap_group("ldap:team") is True
        assert is_ldap_group("cn=team,ou=groups,dc=x") is True
        assert is_ldap_group("42") is False
        assert is_sql_address_book("42") is True
        assert is_sql_address_book("ldap:team") is False
        assert normalize_id("ldap:team") == "team"
        assert normalize_id("cn=team,ou=groups,dc=x") == "team"
        assert normalize_id("42") == "42"


# ---------------------------------------------------------------------------
# LDAP group operations
# ---------------------------------------------------------------------------


class FakeLdapClient:
    """Duck-typed ClientLdap stand-in for tests (no live LDAP)."""

    def __init__(self, entries: list[dict[str, list[str]]] | None = None) -> None:
        self.base_dn = "dc=example,dc=org"
        self.connected = True
        self.binded = True
        self.ldap_conn: MagicMock = MagicMock()
        self._entries = entries or []
        self.search_calls: list[dict] = []

    def search_entries(self, base_dn=None, l_filter=None, attributes=None):
        self.search_calls.append(
            {"base_dn": base_dn, "l_filter": l_filter, "attributes": attributes}
        )
        return self._entries

    def close(self) -> None:
        pass


def _service(
    entries: list[dict[str, list[str]]] | None = None,
) -> tuple[LDAPGroupService, FakeLdapClient]:
    client = FakeLdapClient(entries=entries)
    return LDAPGroupService(client=client), client


class TestLDAPGroupServiceAddMember:
    def test_add_member_success(self):
        service, client = _service()
        member_dn = service.add_member("ldap:engineering-team", "jdoe")

        assert member_dn == "uid=jdoe,dc=example,dc=org"
        args = client.ldap_conn.modify_s.call_args.args
        assert args[0] == "cn=engineering-team,ou=groups,dc=example,dc=org"
        assert args[1] == [(ldap.MOD_ADD, "member", b"uid=jdoe,dc=example,dc=org")]

    def test_add_member_accepts_dn_group_id(self):
        service, client = _service()
        group_id = "cn=engineering-team,ou=groups,dc=example,dc=org"
        member_dn = service.add_member(group_id, "jdoe")

        assert member_dn == "uid=jdoe,dc=example,dc=org"
        args = client.ldap_conn.modify_s.call_args.args
        assert args[0] == group_id

    def test_add_member_accepts_email_local_part(self):
        service, client = _service()
        service.add_member("ldap:team", "jdoe@example.org")

        args = client.ldap_conn.modify_s.call_args.args
        assert args[1] == [(ldap.MOD_ADD, "member", b"uid=jdoe,dc=example,dc=org")]

    def test_add_member_accepts_full_member_dn(self):
        service, _ = _service()
        member_dn = service.add_member("ldap:team", "uid=jdoe,ou=people,dc=example,dc=org")
        assert member_dn == "uid=jdoe,ou=people,dc=example,dc=org"

    def test_add_member_already_exists_is_idempotent(self):
        service, client = _service()
        client.ldap_conn.modify_s.side_effect = ldap.ALREADY_EXISTS("member exists")

        member_dn = service.add_member("ldap:engineering-team", "jdoe")
        assert member_dn == "uid=jdoe,dc=example,dc=org"

    def test_add_member_group_not_found(self):
        service, client = _service()
        client.ldap_conn.modify_s.side_effect = ldap.NO_SUCH_OBJECT("no such group")

        with pytest.raises(RequestException) as exc_info:
            service.add_member("ldap:ghost", "jdoe")
        assert exc_info.value.error == err.ERROR_LDAP_GROUP_NOT_FOUND

    def test_add_member_ldap_error_maps_to_modify_failed(self):
        service, client = _service()
        client.ldap_conn.modify_s.side_effect = ldap.UNWILLING_TO_PERFORM("nope")

        with pytest.raises(RequestException) as exc_info:
            service.add_member("ldap:engineering-team", "jdoe")
        assert exc_info.value.error == err.ERROR_LDAP_MODIFY_FAILED

    def test_add_member_rejects_sql_address_book(self):
        service, client = _service()
        with pytest.raises(RequestException) as exc_info:
            service.add_member("123", "jdoe")
        assert exc_info.value.error == err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND
        client.ldap_conn.modify_s.assert_not_called()

    def test_add_member_needs_client(self):
        service = LDAPGroupService()
        with pytest.raises(RequestException) as exc_info:
            service.add_member("ldap:team", "jdoe")
        assert exc_info.value.error == err.ERROR_LDAP_CANNOT_CONNECT


class TestLDAPGroupServiceRemoveMember:
    def test_remove_member_success(self):
        service, client = _service()
        member_dn = service.remove_member("ldap:engineering-team", "jdoe")

        assert member_dn == "uid=jdoe,dc=example,dc=org"
        args = client.ldap_conn.modify_s.call_args.args
        assert args[0] == "cn=engineering-team,ou=groups,dc=example,dc=org"
        assert args[1] == [(ldap.MOD_DELETE, "member", b"uid=jdoe,dc=example,dc=org")]

    def test_remove_member_no_such_object_is_idempotent(self):
        service, client = _service()
        client.ldap_conn.modify_s.side_effect = ldap.NO_SUCH_OBJECT("member absent")

        member_dn = service.remove_member("ldap:engineering-team", "jdoe")
        assert member_dn == "uid=jdoe,dc=example,dc=org"

    def test_remove_member_ldap_error_maps_to_modify_failed(self):
        service, client = _service()
        client.ldap_conn.modify_s.side_effect = ldap.OTHER("boom")

        with pytest.raises(RequestException) as exc_info:
            service.remove_member("ldap:engineering-team", "jdoe")
        assert exc_info.value.error == err.ERROR_LDAP_MODIFY_FAILED

    def test_remove_member_rejects_sql_address_book(self):
        service, client = _service()
        with pytest.raises(RequestException) as exc_info:
            service.remove_member("123", "jdoe")
        assert exc_info.value.error == err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND
        client.ldap_conn.modify_s.assert_not_called()


class TestLDAPGroupServiceGetMembers:
    def test_get_members_success(self):
        group_dn = "cn=engineering-team,ou=groups,dc=example,dc=org"
        entries = [
            {
                "dn": [group_dn],
                "member": ["uid=john,dc=example,dc=org", "uid=jane,dc=example,dc=org"],
            }
        ]
        service, client = _service(entries=entries)

        members = service.get_members("ldap:engineering-team")

        assert members == ["uid=john,dc=example,dc=org", "uid=jane,dc=example,dc=org"]
        assert client.search_calls[-1]["base_dn"] == group_dn
        assert client.search_calls[-1]["l_filter"] == "(objectClass=groupOfNames)"
        assert client.search_calls[-1]["attributes"] == ["member"]

    def test_get_members_group_missing(self):
        service, _ = _service(entries=[])
        with pytest.raises(RequestException) as exc_info:
            service.get_members("ldap:ghost")
        assert exc_info.value.error == err.ERROR_CONTACT_LIST_NOT_FOUND

    def test_get_members_group_without_member_attribute(self):
        entries = [{"dn": ["cn=empty,ou=groups,dc=example,dc=org"]}]
        service, _ = _service(entries=entries)
        assert service.get_members("ldap:empty") == []

    def test_get_members_rejects_sql_address_book(self):
        service, _ = _service()
        with pytest.raises(RequestException) as exc_info:
            service.get_members("123")
        assert exc_info.value.error == err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND


class TestLDAPGroupServiceDNHelpers:
    def test_group_dn_from_prefix(self):
        service, _ = _service()
        assert (
            service._build_group_dn(service._resolve_cn("ldap:engineering-team"))
            == "cn=engineering-team,ou=groups,dc=example,dc=org"
        )

    def test_member_dn_from_uid(self):
        service, _ = _service()
        assert service.to_dn("jdoe") == "uid=jdoe,dc=example,dc=org"

    def test_member_dn_from_email(self):
        service, _ = _service()
        assert service.to_dn("jdoe@example.org") == "uid=jdoe,dc=example,dc=org"

    def test_member_dn_from_full_dn(self):
        service, _ = _service()
        assert service.to_dn("uid=jdoe,ou=people,dc=example,dc=org") == \
            "uid=jdoe,ou=people,dc=example,dc=org"
