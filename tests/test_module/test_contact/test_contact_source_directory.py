# pylint: disable=invalid-sequence-index
"""Unit tests for ContactSourceDirectory (21% -> high).

LDAP-backed directory address book covering client build, field resolution,
filter building, entry mapping, query/sort/pagination, key/uid lookups and
all read-only (raise) paths for contacts and lists.
"""
from __future__ import annotations

import os

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.module.contact.model.CardAddressBook import CardAddressBook
from app.module.contact.source.ContactSourceDirectory import (
    MAP_KEY_CLASS,
    MAP_KEY_PATH,
    ContactSourceDirectory,
)
from app.utils import errors as err
from app.utils.db.Condition import Order
from app.utils.exceptions import RequestException


def make_us(**overrides):
    base = dict(
        US_TYPE="ldap",
        US_UID="us1",
        US_SEARCH=[],
        US_DISPLAY_NAME="cn",
        US_MAIL=["mail"],
        US_LDAP_CN="cn",
        US_LDAP_UID="uid",
        US_LDAP_FILTER="",
        US_LDAP_HOSTNAME="ldap.example.org",
        US_LDAP_BASE_DN="dc=example,dc=org",
        US_HIDDEN_USER=[],
        US_EXTRA_CONTACT_INFO="",
        US_AUTO_QUERY_LIMIT=0,
    )
    base.update(overrides)
    us = SimpleNamespace(**base)
    us.get_user_source_settings = MagicMock(return_value={"host": "ldap.example.org"})
    return us


def make_ab():
    ab = CardAddressBook(user_uid="user1", name="Directory")
    ab.key = "dir-us1-key"
    return ab


def make_dir(**overrides):
    us = make_us(**overrides.pop("us", {}))
    ab = overrides.pop("ab", None) or make_ab()
    d = ContactSourceDirectory(ab, us)
    for attr, val in overrides.items():
        setattr(d, attr, val)
    return us, d


def base_entry(**overrides):
    entry = {
        "dn": ["uid=alice,dc=example,dc=org"],
        "uid": ["alice"],
        "cn": ["Alice Example"],
        "givenName": ["Alice"],
        "sn": ["Example"],
        "mail": ["alice@example.org", "a.second@example.org"],
        "telephoneNumber": ["+49 123"],
        "o": ["SOGo"],
        "ou": ["IT"],
        "title": ["Engineer"],
    }
    entry.update(overrides)
    return entry


# ─────────────────────────────────────────────────────────────────────────────
# _build_client
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildClient:
    def test_ldap_build_and_connect(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        client = MagicMock()
        with patch(
            "app.module.contact.source.ContactSourceDirectory.import_and_instantiate_manager",
            return_value=client,
        ) as m:
            out = d._build_client()
        assert out is client
        client.connect.assert_called_once()
        args, kwargs = m.call_args
        assert kwargs["module_path"] == "app.manager.ldap"
        assert kwargs["module_and_class_name"] == "ClientLdap"

    def test_map_tables_consistent(self):
        assert MAP_KEY_CLASS["mysql"] == "ClientMySQL"
        assert MAP_KEY_CLASS["postgresql"] == "ClientPostgreSQL"
        assert MAP_KEY_PATH["postgresql"] == "app.manager.db"


# ─────────────────────────────────────────────────────────────────────────────
# field helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestFields:
    def test_search_fields_confgured(self):
        us = make_us(US_SEARCH=["uid", "cn", "mail"])
        d = ContactSourceDirectory(make_ab(), us)
        assert d._get_search_fields() == ["uid", "cn", "mail"]

    def test_search_fields_fallback(self):
        us = make_us(US_SEARCH=[], US_DISPLAY_NAME="cn", US_MAIL=["mail"])
        d = ContactSourceDirectory(make_ab(), us)
        assert d._get_search_fields() == ["cn", "mail"]

    def test_search_fields_last_resort(self):
        us = make_us(US_SEARCH=[], US_DISPLAY_NAME="", US_MAIL=[])
        d = ContactSourceDirectory(make_ab(), us)
        assert d._get_search_fields() == ["cn", "mail"]

    def test_display_name_field_configured(self):
        us = make_us(US_DISPLAY_NAME="fullname")
        d = ContactSourceDirectory(make_ab(), us)
        assert d._get_display_name_field() == "fullname"

    def test_display_name_field_ldap_fallback(self):
        us = make_us(US_DISPLAY_NAME="", US_LDAP_CN="displayName")
        d = ContactSourceDirectory(make_ab(), us)
        assert d._get_display_name_field() == "displayName"

    def test_display_name_field_ldap_default(self):
        us = make_us(US_DISPLAY_NAME="", US_LDAP_CN="")
        d = ContactSourceDirectory(make_ab(), us)
        assert d._get_display_name_field() == "cn"

    def test_display_name_field_sql_default(self):
        us = make_us(US_TYPE="mysql", US_DISPLAY_NAME="")
        d = ContactSourceDirectory(make_ab(), us)
        assert d._get_display_name_field() == "display_name"

    def test_uid_field_ldap(self):
        us = make_us(US_LDAP_UID="employeeNumber")
        d = ContactSourceDirectory(make_ab(), us)
        assert d._get_uid_field() == "employeeNumber"

    def test_uid_field_ldap_default(self):
        us = make_us(US_LDAP_UID="")
        d = ContactSourceDirectory(make_ab(), us)
        assert d._get_uid_field() == "uid"

    def test_uid_field_sql(self):
        us = make_us(US_TYPE="postgresql")
        d = ContactSourceDirectory(make_ab(), us)
        assert d._get_uid_field() == "uid"

    def test_attributes_to_fetch(self):
        us = make_us(US_SEARCH=["mail"], US_EXTRA_CONTACT_INFO="employeeType")
        d = ContactSourceDirectory(make_ab(), us)
        attrs = d._get_attributes_to_fetch()
        assert "uid" in attrs
        assert "cn" in attrs
        assert "mail" in attrs
        assert "employeeType" in attrs
        assert "sn" in attrs and "givenName" in attrs and "telephoneNumber" in attrs
        assert "o" in attrs and "ou" in attrs and "title" in attrs

    def test_attributes_to_fetch_sql_no_ldap_extra(self):
        us = make_us(US_TYPE="mysql", US_LDAP_CN="")
        d = ContactSourceDirectory(make_ab(), us)
        attrs = d._get_attributes_to_fetch()
        assert "sn" not in attrs
        assert "uid" in attrs


# ─────────────────────────────────────────────────────────────────────────────
# _build_ldap_filter
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildLdapFilter:
    def test_empty_search_no_filter(self):
        us = make_us(US_LDAP_FILTER="")
        d = ContactSourceDirectory(make_ab(), us)
        f = d._build_ldap_filter(None)
        assert f == "(|(objectClass=inetOrgPerson)(objectClass=posixAccount)(objectClass=person))"

    def test_configured_filter_no_search(self):
        us = make_us(US_LDAP_FILTER="(objectClass=employee)")
        d = ContactSourceDirectory(make_ab(), us)
        assert d._build_ldap_filter("") == "(objectClass=employee)"

    def test_search_adds_subfilter(self):
        us = make_us(US_LDAP_FILTER="", US_SEARCH=["uid", "mail"])
        d = ContactSourceDirectory(make_ab(), us)
        f = d._build_ldap_filter("alice")
        assert "(|(uid=*alice*)(mail=*alice*))" in f
        assert "(&" in f

    def test_search_with_configured_filter_anded(self):
        us = make_us(US_LDAP_FILTER="(objectClass=employee)", US_SEARCH=["cn"])
        d = ContactSourceDirectory(make_ab(), us)
        f = d._build_ldap_filter("bob")
        assert f == "(&(objectClass=employee)(|(cn=*bob*)))"

    def test_search_escaped(self):
        us = make_us(US_SEARCH=["cn"])
        d = ContactSourceDirectory(make_ab(), us)
        f = d._build_ldap_filter("a(b")
        assert "(cn=*a\\28b*)" in f


# ─────────────────────────────────────────────────────────────────────────────
# _ldap_entry_to_contact
# ─────────────────────────────────────────────────────────────────────────────

class TestLdapEntryToContact:
    def test_full_mapping(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        c = d._ldap_entry_to_contact(base_entry())
        assert c is not None
        assert c.uid == "dir-us1-alice"
        assert c.display_name == "Alice Example"
        assert c.first_name == "Alice"
        assert c.last_name == "Example"
        assert c.organization == "SOGo"
        assert c.department == "IT"
        assert c.job_title == "Engineer"
        assert len(c.emails) == 2
        assert c.emails[0].value == "alice@example.org"
        assert len(c.phones) == 1
        assert c.phones[0].number == "+49 123"
        assert c.addressbook_key == "dir-us1-key"
        assert c.key.startswith("dir:us1:")

    def test_no_uid_returns_none(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        assert d._ldap_entry_to_contact({"cn": ["x"]}) is None

    def test_hidden_user_returns_none(self):
        us = make_us(US_HIDDEN_USER=["alice"])
        d = ContactSourceDirectory(make_ab(), us)
        assert d._ldap_entry_to_contact(base_entry()) is None

    def test_display_name_fallback_to_cn(self):
        us = make_us(US_DISPLAY_NAME="")
        d = ContactSourceDirectory(make_ab(), us)
        c = d._ldap_entry_to_contact(base_entry())
        assert c.display_name == "Alice Example"

    def test_display_name_fallback_to_uid(self):
        us = make_us(US_DISPLAY_NAME="")
        d = ContactSourceDirectory(make_ab(), us)
        c = d._ldap_entry_to_contact(base_entry(cn=[], givenName=[], sn=[]))
        assert c.display_name == "alice"

    def test_flatten_name_when_no_structured(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        c = d._ldap_entry_to_contact(base_entry(givenName=[], sn=[], cn=["Bob Builder"]))
        assert c.first_name == "Bob"
        assert c.last_name == "Builder"

    def test_flatten_name_single_word(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        c = d._ldap_entry_to_contact(base_entry(givenName=[], sn=[], cn=["Cher"]))
        assert c.first_name == "Cher"
        assert c.last_name == ""

    def test_dn_absent_uses_uid_key(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        c = d._ldap_entry_to_contact(base_entry(dn=[]))
        assert c.key == "dir:us1:alice"


# ─────────────────────────────────────────────────────────────────────────────
# _query_ldap
# ─────────────────────────────────────────────────────────────────────────────

class TestQueryLdap:
    def test_full_flow_with_pagination(self):
        us = make_us(US_AUTO_QUERY_LIMIT=0)
        d = ContactSourceDirectory(make_ab(), us)
        client = MagicMock()
        client.search_entries.return_value = [base_entry(), base_entry(uid=["bob"], cn=["Bob"])]
        d._build_client = MagicMock(return_value=client)
        page, total = d._query_ldap(search="ali", offset=0, limit=1)
        assert total == 2
        assert len(page) == 1
        client.close.assert_called_once()

    def test_auto_query_limit(self):
        us = make_us(US_AUTO_QUERY_LIMIT=1)
        d = ContactSourceDirectory(make_ab(), us)
        client = MagicMock()
        client.search_entries.return_value = [base_entry(), base_entry(uid=["bob"], cn=["Bob"])]
        d._build_client = MagicMock(return_value=client)
        page, total = d._query_ldap()
        assert total == 2
        assert len(page) == 1

    def test_offset_slicing(self):
        us = make_us(US_AUTO_QUERY_LIMIT=1)
        d = ContactSourceDirectory(make_ab(), us)
        client = MagicMock()
        client.search_entries.return_value = [base_entry(), base_entry(uid=["bob"], cn=["Bob"])]
        d._build_client = MagicMock(return_value=client)
        page, total = d._query_ldap(offset=1)
        assert [c.uid for c in page] == ["dir-us1-bob"]

    def test_build_client_failure_returns_empty(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        d._build_client = MagicMock(side_effect=RuntimeError("conn refused"))
        page, total = d._query_ldap()
        assert page == [] and total == 0

    def test_search_failure_returns_empty(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        client = MagicMock()
        client.search_entries.side_effect = RuntimeError("search fail")
        d._build_client = MagicMock(return_value=client)
        page, total = d._query_ldap()
        assert page == [] and total == 0
        client.close.assert_called_once()

    def test_close_failure_swallowed(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        client = MagicMock()
        client.search_entries.return_value = [base_entry()]
        client.close.side_effect = RuntimeError("close boom")
        d._build_client = MagicMock(return_value=client)
        page, total = d._query_ldap()
        assert total == 1

    def test_sort_by_last_name(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        client = MagicMock()
        client.search_entries.return_value = [
            base_entry(uid=["b"], cn=["B Zulu"], sn=["Zulu"]),
            base_entry(uid=["a"], cn=["A Alpha"], sn=["Alpha"]),
        ]
        d._build_client = MagicMock(return_value=client)
        page, _ = d._query_ldap(sort_by="last_name")
        assert [c.uid for c in page] == ["dir-us1-a", "dir-us1-b"]

    def test_sort_desc(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        client = MagicMock()
        client.search_entries.return_value = [
            base_entry(uid=["b"], cn=["B"]),
            base_entry(uid=["a"], cn=["A"]),
        ]
        d._build_client = MagicMock(return_value=client)
        page, _ = d._query_ldap(sort_by="display_name", order=Order.DESC)
        assert [c.uid for c in page] == ["dir-us1-b", "dir-us1-a"]

    def test_sort_by_email(self):
        from app.module.contact.model.CardEmail import CardEmail

        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        client = MagicMock()
        client.search_entries.return_value = [
            base_entry(uid=["b"], mail=["z@b.c"]),
            base_entry(uid=["a"], mail=["a@b.c"]),
        ]
        d._build_client = MagicMock(return_value=client)
        page, _ = d._query_ldap(sort_by="email")
        assert [c.uid for c in page] == ["dir-us1-a", "dir-us1-b"]
        # direct production call exercises the CardEmail.value path
        contacts = []
        for e in ["z@b.c", "a@b.c"]:
            c = MagicMock()
            c.emails = [CardEmail(value=e)]
            c.last_name = None
            c.first_name = None
            c.display_name = "X"
            contacts.append(c)
        ContactSourceDirectory._sort_contacts(contacts, "email", Order.ASC)
        assert contacts[0].emails[0].value == "a@b.c"

    def test_sort_by_email_no_emails(self):
        from app.module.contact.model.CardEmail import CardEmail

        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        client = MagicMock()
        client.search_entries.return_value = [
            base_entry(uid=["b"], mail=[]),
            base_entry(uid=["a"], mail=[]),
        ]
        d._build_client = MagicMock(return_value=client)
        page, _ = d._query_ldap(sort_by="email")
        assert len(page) == 2

    def test_sort_by_first_name(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        contacts = [MagicMock(), MagicMock()]
        contacts[0].last_name = "B"; contacts[0].first_name = "Z"; contacts[0].display_name = "X"
        contacts[0].emails = []
        contacts[1].last_name = "A"; contacts[1].first_name = "A"; contacts[1].display_name = "Y"
        contacts[1].emails = []
        ContactSourceDirectory._sort_contacts(contacts, "first_name", Order.ASC)
        assert contacts[0].first_name == "A"


# ─────────────────────────────────────────────────────────────────────────────
# get_contacts / count_contacts / _query_directory
# ─────────────────────────────────────────────────────────────────────────────

class TestPublicQuery:
    def test_get_contacts_delegates(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        d._query_directory = MagicMock(return_value=(["c1", "c2"], 2))
        assert d.get_contacts(search="x") == ["c1", "c2"]

    def test_count_contacts_delegates(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        d._query_directory = MagicMock(return_value=(["c1"], 7))
        assert d.count_contacts("x") == 7

    def test_query_directory_ldap(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        d._query_ldap = MagicMock(return_value=([], 0))
        d._query_directory()
        d._query_ldap.assert_called_once()

    def test_query_directory_sql(self):
        us = make_us(US_TYPE="mysql")
        d = ContactSourceDirectory(make_ab(), us)
        d._query_sql = MagicMock(return_value=([], 0))
        d._query_directory()
        d._query_sql.assert_called_once()

    def test_query_directory_unsupported(self):
        us = make_us(US_TYPE="cassandra")
        d = ContactSourceDirectory(make_ab(), us)
        assert d._query_directory() == ([], 0)

    def test_query_sql_not_implemented(self):
        us = make_us(US_TYPE="mysql")
        d = ContactSourceDirectory(make_ab(), us)
        assert d._query_sql() == ([], 0)

    def test_get_sql_contact_by_uid_not_implemented(self):
        us = make_us(US_TYPE="mysql")
        d = ContactSourceDirectory(make_ab(), us)
        assert d._get_sql_contact_by_uid("abc") is None


# ─────────────────────────────────────────────────────────────────────────────
# get_contact_by_key / by_uid
# ─────────────────────────────────────────────────────────────────────────────

class TestLookup:
    def test_key_empty_or_wrong_prefix(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        assert d.get_contact_by_key("") is None
        assert d.get_contact_by_key("x:1:2") is None

    def test_key_wrong_source(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        assert d.get_contact_by_key("dir:other:abc") is None

    def test_key_malformed(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        assert d.get_contact_by_key("dir:") is None

    def test_key_found(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        c = d._ldap_entry_to_contact(base_entry())
        d._query_directory = MagicMock(return_value=([c], 1))
        assert d.get_contact_by_key(c.key) is c

    def test_key_not_found(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        c = d._ldap_entry_to_contact(base_entry())
        d._query_directory = MagicMock(return_value=([c], 1))
        assert d.get_contact_by_key("dir:us1:deadbeef") is None

    def test_uid_wrong_prefix(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        assert d.get_contact_by_uid("") is None
        assert d.get_contact_by_uid("uid-alice") is None

    def test_uid_wrong_source(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        assert d.get_contact_by_uid("dir-other-alice") is None

    def test_uid_ldap_lookup(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        d._get_ldap_contact_by_uid = MagicMock(return_value="contact")
        assert d.get_contact_by_uid("dir-us1-alice") == "contact"
        d._get_ldap_contact_by_uid.assert_called_once_with("alice")

    def test_uid_sql_lookup(self):
        us = make_us(US_TYPE="mysql")
        d = ContactSourceDirectory(make_ab(), us)
        d._get_sql_contact_by_uid = MagicMock(return_value="contact")
        assert d.get_contact_by_uid("dir-us1-alice") == "contact"

    def test_ldap_contact_by_uid_success(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        client = MagicMock()
        client.search_entries.return_value = [base_entry()]
        d._build_client = MagicMock(return_value=client)
        c = d._get_ldap_contact_by_uid("alice")
        assert c is not None and c.display_name == "Alice Example"
        client.close.assert_called_once()

    def test_ldap_contact_by_uid_not_found(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        client = MagicMock()
        client.search_entries.return_value = []
        d._build_client = MagicMock(return_value=client)
        assert d._get_ldap_contact_by_uid("ghost") is None

    def test_ldap_contact_by_uid_close_failure(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        client = MagicMock()
        client.search_entries.return_value = [base_entry()]
        client.close.side_effect = RuntimeError("close boom")
        d._build_client = MagicMock(return_value=client)
        c = d._get_ldap_contact_by_uid("alice")
        assert c is not None
        client.close.assert_called_once()

    def test_ldap_contact_by_uid_connect_failure(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        d._build_client = MagicMock(side_effect=RuntimeError("boom"))
        assert d._get_ldap_contact_by_uid("alice") is None

    def test_ldap_contact_by_uid_search_failure(self):
        us = make_us()
        d = ContactSourceDirectory(make_ab(), us)
        client = MagicMock()
        client.search_entries.side_effect = RuntimeError("boom")
        d._build_client = MagicMock(return_value=client)
        assert d._get_ldap_contact_by_uid("alice") is None
        client.close.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# read-only guards (addressbook / contacts / lists / write paths)
# ─────────────────────────────────────────────────────────────────────────────

class TestReadOnly:
    @pytest.fixture
    def d(self):
        return ContactSourceDirectory(make_ab(), make_us())

    def test_is_writable_false(self, d):
        assert d.is_writable() is False

    def test_addressbook_ops_raise(self, d):
        for fn, args in [
            (d.save_addressbook, (None,)),
            (d.update_addressbook, (None,)),
            (d.delete_addressbook, ()),
        ]:
            with pytest.raises(RequestException) as e:
                fn(*args)
            assert e.value.error.c == err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED.c

    def test_contact_ops_raise(self, d):
        for fn, args in [
            (d.insert_contact, (None,)),
            (d.update_contact, (None,)),
            (d.delete_contact, ("k",)),
            (d.delete_by_key, ("k",)),
        ]:
            with pytest.raises(RequestException):
                fn(*args)

    def test_list_ops_raise(self, d):
        for fn, args in [
            (d.insert_list, (None,)),
            (d.update_list, (None,)),
            (d.delete_list, ("k",)),
        ]:
            with pytest.raises(RequestException):
                fn(*args)

    def test_lists_empty(self, d):
        assert d.get_lists() == []
        assert d.count_lists() == 0
        assert d.get_list_by_key("x") is None
        assert d.get_list_by_uid("x") is None

    def test_sync_metadata_empty(self, d):
        assert d.get_sync_metadata() == []
