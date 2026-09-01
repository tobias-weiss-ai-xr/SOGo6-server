"""Acceptance-gate tests for the hybrid SQL+LDAP address book API (BACKEND-GAPS F3, subsection 2).

Covers the "Update Address Books API to Use Hybrid Backend" endpoints:

* ``GET    /api/user/v1/addressbooks/lists``                          - hybrid list (SQL books + LDAP groups)
* ``GET    /api/user/v1/addressbooks/<list_id>/members``              - list members (routed by id type)
* ``POST   /api/user/v1/addressbooks/<list_id>/members``              - add a contact to a list
* ``DELETE /api/user/v1/addressbooks/<list_id>/members/<contact_id>`` - remove a contact from a list

The hybrid routes stay thin: they delegate to the contact API interface, which
routes member operations by id type (numeric SQL book key vs ``ldap:<cn>``/DN)
through :class:`app.module.contact.LDAPListService`. The underlying LDAP/SQL
behaviour is covered by ``tests/test_contact/test_ldap_list_service.py`` and
``tests/test_contact/test_ldap_group_ops.py``; here the interface is replaced
by a controllable fake, so every test runs WITHOUT a live stack.
"""
from __future__ import annotations

import os

# Required env for ProcessSetting (mirrors the rest of the suite).
os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

from unittest.mock import MagicMock

import pytest

from app import create_app
from app.utils import constants as cs
from app.utils.errors import (
    ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND,
    ERROR_CONTACT_LIST_NOT_FOUND,
    ERROR_LDAP_GROUP_NOT_FOUND,
)

CAL = "/api/user/v1"
LISTS = f"{CAL}/addressbooks/lists"
MEMBERS_LDAP = f"{CAL}/addressbooks/ldap:engineering/members"
MEMBERS_SQL = f"{CAL}/addressbooks/42/members"

MEMBER_DN = "uid=jsmith,dc=example,dc=org"


# --------------------------------------------------------------------------- #
# App + auth fixture (no live DB/LDAP/Redis - see tests/test_api/test_jmap_protocol.py)
# --------------------------------------------------------------------------- #

@pytest.fixture()
def client(monkeypatch):
    """An authenticated test client for the USER (basic) API in the SOGo_OK state."""
    from app.auth.User import User

    app = create_app(cs.SOGO_OK)
    app.config["TESTING"] = True

    class FakeAuthUser:
        def __init__(self, *args, **kwargs):  # noqa: D401
            pass

        def check_user_and_fill_info(self, user):
            return True, user

    monkeypatch.setattr("app.init_get_system_and_default_domain_settings", lambda: ({}, {}))
    monkeypatch.setattr("app.init_get_user_domain_settings", lambda user: {})
    monkeypatch.setattr("app.InterfaceAuthUser", FakeAuthUser)
    monkeypatch.setattr("app.VoucherUserService.__init__", lambda self, ps: None)
    monkeypatch.setattr(
        "app.VoucherUserService.generate_user_from_voucher",
        staticmethod(lambda token: User("testuser@example.org", cn="Test User", domain="example.org")),
    )
    # The global per-IP rate limiter is Redis-backed; without a live Redis it
    # would burn a connection-retry timeout on every request. It is defensive
    # only, so tests skip it outright (rule: no live stack).
    monkeypatch.setattr("app.utils.api.ratelimit.check_global_rate_limit", lambda: None)
    test_client = app.test_client()
    test_client.environ_base["HTTP_AUTHORIZATION"] = "Bearer test-token"
    return test_client


@pytest.fixture()
def fake_interface(monkeypatch):
    """Replace the contact API interface the Contact blueprint builds per request."""
    inter = MagicMock()
    monkeypatch.setattr(
        "app.api.v1.contact.ApiContact.InterfaceApiContactContact", lambda **kwargs: inter
    )
    return inter


# --------------------------------------------------------------------------- #
# Route registration (pure app build - no requests, no stack)
# --------------------------------------------------------------------------- #

def test_hybrid_routes_registered():
    """The four hybrid-backend routes must be live on the /api/user/v1/contact tree."""
    app = create_app(cs.SOGO_OK)
    found: dict[tuple, frozenset] = {}
    for rule in app.url_map.iter_rules():
        path = rule.rule or ""
        if "members" not in path and path != LISTS:
            continue
        found[(path, frozenset(m for m in rule.methods if m not in {"HEAD", "OPTIONS"}))] = rule.endpoint

    assert (LISTS, frozenset({"GET"})) in found
    assert (f"{CAL}/addressbooks/<string:key>/members", frozenset({"GET", "POST"})) in found
    assert (
        f"{CAL}/addressbooks/<string:key>/members/<string:contact_id>",
        frozenset({"DELETE"}),
    ) in found


def test_hybrid_static_route_wins_over_key_route():
    """``GET /addressbooks/lists`` is the static hybrid list, never a book lookup."""
    app = create_app(cs.SOGO_OK)
    # The static path must resolve to the ApiContactLists view, not ApiAddressBookDetail.
    from app.api.v1.contact.ApiContact import ApiContactLists

    adapter = app.url_map.bind("localhost")
    assert adapter.match("/api/user/v1/addressbooks/lists")[0].endswith("ApiContactLists")
    # A normal numeric id still matches the detail route.
    klass = app.view_functions[adapter.match("/api/user/v1/addressbooks/42")[0]].view_class
    assert klass.__name__ == "ApiAddressBookDetail"
    assert ApiContactLists is not None  # keeps the import honest


# --------------------------------------------------------------------------- #
# GET /addressbooks/lists - hybrid listing
# --------------------------------------------------------------------------- #

def _sql_entry(**overrides):
    entry = {"source": "sql", "id": "42", "name": "Personal", "description": None,
             "member_count": 1, "members": []}
    entry.update(overrides)
    return entry


def _ldap_entry(**overrides):
    entry = {"source": "ldap", "id": "ldap:engineering", "name": "engineering",
             "description": "Engineering team", "member_count": 1,
             "members": [MEMBER_DN]}
    entry.update(overrides)
    return entry


def _ok(data):
    return {"data": data, "error_code": "S000000", "error_msg": "No Error"}, 200


def test_hybrid_listing_merges_sql_and_ldap(client, fake_interface):
    fake_interface.list_lists.return_value = _ok(
        {"lists": [_sql_entry(), _ldap_entry()], "total_count": 2}
    )

    resp = client.get(LISTS)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["error_code"] == "S000000"
    data = body["data"]
    assert data["total_count"] == 2
    by_id = {entry["id"]: entry for entry in data["lists"]}
    assert by_id["42"]["source"] == "sql"
    assert by_id["ldap:engineering"]["source"] == "ldap"
    assert by_id["ldap:engineering"]["members"] == [MEMBER_DN]
    # the LDAP group surfaces its member list, the SQL book does not
    assert by_id["42"]["members"] == []
    fake_interface.list_lists.assert_called_once_with()


def test_hybrid_listing_empty_is_valid(client, fake_interface):
    fake_interface.list_lists.return_value = _ok({"lists": [], "total_count": 0})
    resp = client.get(LISTS)
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["lists"] == []
    assert data["total_count"] == 0


def test_hybrid_listing_propagates_ldap_error(client, fake_interface):
    # LDAP search failure -> 500, never a naked exception.
    fake_interface.list_lists.return_value = (
        {"data": None, "error_code": "S000903", "error_msg": "Cannot bind to the ldap server"}, 500
    )
    resp = client.get(LISTS)
    assert resp.status_code == 500
    assert resp.get_json()["error_code"] == "S000903"


# --------------------------------------------------------------------------- #
# GET /addressbooks/<list_id>/members
# --------------------------------------------------------------------------- #

def test_get_members_lists_ldap_group(client, fake_interface):
    fake_interface.get_list_members.return_value = _ok({"members": [MEMBER_DN], "total_count": 1})

    resp = client.get(MEMBERS_LDAP)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["error_code"] == "S000000"
    assert body["data"] == {"members": [MEMBER_DN], "total_count": 1}
    # the hybrid id is forwarded verbatim to the interface for routing
    fake_interface.get_list_members.assert_called_once_with("ldap:engineering")


def test_get_members_sql_book_is_routed(client, fake_interface):
    fake_interface.get_list_members.return_value = _ok({"members": ["contact-1", "contact-2"], "total_count": 2})
    resp = client.get(MEMBERS_SQL)
    assert resp.status_code == 200
    assert resp.get_json()["data"]["members"] == ["contact-1", "contact-2"]
    fake_interface.get_list_members.assert_called_once_with("42")


def test_get_members_empty_group_is_valid(client, fake_interface):
    fake_interface.get_list_members.return_value = _ok({"members": [], "total_count": 0})
    resp = client.get(MEMBERS_LDAP)
    assert resp.status_code == 200
    assert resp.get_json()["data"] == {"members": [], "total_count": 0}


def test_get_members_propagates_group_not_found(client, fake_interface):
    fake_interface.get_list_members.return_value = (
        {"data": None, "error_code": ERROR_LDAP_GROUP_NOT_FOUND.c,
         "error_msg": ERROR_LDAP_GROUP_NOT_FOUND.m}, 404
    )
    resp = client.get(MEMBERS_LDAP)
    assert resp.status_code == 404
    assert resp.get_json()["error_code"] == ERROR_LDAP_GROUP_NOT_FOUND.c


def test_get_members_propagates_book_not_found_for_sql_id(client, fake_interface):
    fake_interface.get_list_members.return_value = (
        {"data": None, "error_code": ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND.c,
         "error_msg": ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND.m}, 404
    )
    resp = client.get(MEMBERS_SQL)
    assert resp.status_code == 404
    assert resp.get_json()["error_code"] == ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND.c


# --------------------------------------------------------------------------- #
# POST /addressbooks/<list_id>/members
# --------------------------------------------------------------------------- #

def test_post_member_adds_to_ldap_group(client, fake_interface):
    fake_interface.add_list_member.return_value = (
        {"data": {"member_dn": MEMBER_DN}, "error_code": "S000000", "error_msg": "No Error"}, 201
    )

    resp = client.post(MEMBERS_LDAP, json={"contact_id": "jsmith"})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["error_code"] == "S000000"
    assert body["data"] == {"member_dn": MEMBER_DN}
    fake_interface.add_list_member.assert_called_once_with("ldap:engineering", "jsmith")


def test_post_member_accepts_dn_contact(client, fake_interface):
    fake_interface.add_list_member.return_value = (
        {"data": {"member_dn": MEMBER_DN}, "error_code": "S000000", "error_msg": "No Error"}, 201
    )
    resp = client.post(MEMBERS_LDAP, json={"contact_id": MEMBER_DN})
    assert resp.status_code == 201
    fake_interface.add_list_member.assert_called_once_with("ldap:engineering", MEMBER_DN)


def test_post_member_requires_contact_id(client, fake_interface):
    resp = client.post(MEMBERS_LDAP, json={})
    assert resp.status_code == 422
    fake_interface.add_list_member.assert_not_called()


def test_post_member_missing_body_is_rejected(client, fake_interface):
    # An empty (non-JSON) body is rejected at the transport layer (400) or by the
    # schema validation layer (422); either way the interface is never reached.
    resp = client.post(MEMBERS_LDAP, json=None)
    assert resp.status_code in (400, 422)
    fake_interface.add_list_member.assert_not_called()


def test_post_member_propagates_unsupported_sql_book(client, fake_interface):
    # SQL address books reject direct member addition (S000707).
    fake_interface.add_list_member.return_value = (
        {"data": None, "error_code": ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND.c,
         "error_msg": ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND.m}, 404
    )
    resp = client.post(MEMBERS_SQL, json={"contact_id": "jsmith"})
    assert resp.status_code == 404
    assert resp.get_json()["error_code"] == ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND.c


def test_post_member_propagates_ldap_modify_failure(client, fake_interface):
    fake_interface.add_list_member.return_value = (
        {"data": None, "error_code": "S000905", "error_msg": "Failed to modify the ldap entry"}, 500
    )
    resp = client.post(MEMBERS_LDAP, json={"contact_id": "jsmith"})
    assert resp.status_code == 500
    assert resp.get_json()["error_code"] == "S000905"


# --------------------------------------------------------------------------- #
# DELETE /addressbooks/<list_id>/members/<contact_id>
# --------------------------------------------------------------------------- #

def test_delete_member_removes_from_ldap_group(client, fake_interface):
    fake_interface.remove_list_member.return_value = (
        {"data": {"member_dn": MEMBER_DN}, "error_code": "S000000", "error_msg": "No Error"}, 200
    )

    resp = client.delete(f"{MEMBERS_LDAP}/jsmith")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["error_code"] == "S000000"
    assert body["data"] == {"member_dn": MEMBER_DN}
    fake_interface.remove_list_member.assert_called_once_with("ldap:engineering", "jsmith")


def test_delete_member_absent_is_idempotent(client, fake_interface):
    # Removing a member that is not in the group still succeeds (idempotent).
    fake_interface.remove_list_member.return_value = (
        {"data": {"member_dn": MEMBER_DN}, "error_code": "S000000", "error_msg": "No Error"}, 200
    )
    resp = client.delete(f"{MEMBERS_LDAP}/jsmith")
    assert resp.status_code == 200
    fake_interface.remove_list_member.assert_called_once_with("ldap:engineering", "jsmith")


def test_delete_member_propagates_non_ldap_id(client, fake_interface):
    fake_interface.remove_list_member.return_value = (
        {"data": None, "error_code": ERROR_CONTACT_LIST_NOT_FOUND.c,
         "error_msg": ERROR_CONTACT_LIST_NOT_FOUND.m}, 404
    )
    resp = client.delete(f"{MEMBERS_LDAP}/nobody")
    assert resp.status_code == 404
    assert resp.get_json()["error_code"] == ERROR_CONTACT_LIST_NOT_FOUND.c
