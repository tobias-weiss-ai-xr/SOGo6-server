"""SCIM 2.0 provisioning endpoint tests.

SCIM routes must hit the real user source (LDAP via ScimIdentityGateway), not
only Redis. The directory is faked at the ``_gateway()`` seam; the Redis
sidecar (externalId/groups/active-flag) is real.  Auth is the SCIM bearer
token in ``SCIM_BEARER_TOKEN`` — no open fallback.
"""
from __future__ import annotations

import pytest

from app import create_app
from app.utils import constants as cs

SCIM = "/api/admin/v1/scim/v2"
TOKEN = "scim-test-token"


@pytest.fixture()
def client(monkeypatch):
    from app.auth.Admin import Admin

    app = create_app(cs.SOGO_NOT_INIT)
    app.config["TESTING"] = True
    monkeypatch.setenv("SCIM_BEARER_TOKEN", TOKEN)
    # the admin middleware still instantiates the voucher service before the
    # public_access check; keep it inert like every other admin-API test
    monkeypatch.setattr("app.VoucherAdminService.__init__", lambda self, ps: None)
    monkeypatch.setattr(
        "app.VoucherAdminService.generate_admin_from_voucher",
        staticmethod(lambda token: Admin("smoke-admin")),
    )
    client = app.test_client()
    return client


class FakeGateway:
    """In-memory LDAP directory (attribute values as lists, like the real one)."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.create_log: list[dict] = []
        self.update_log: list[tuple[str, dict]] = []

    def list_users(self, query=None, page=1, per_page=20):
        records = list(self.users.values())
        return len(records), records

    def get_user(self, uid: str) -> dict:
        if uid not in self.users:
            from app.utils.exceptions import RequestException
            raise RequestException("not found")
        return self.users[uid]

    def create_user(self, data: dict) -> dict:
        self.create_log.append(data)
        uid = data["uid"]
        self.users[uid] = {
            "uid": [uid],
            "cn": [data["cn"]],
            "sn": [data["sn"]],
            "givenName": [data["givenName"]],
            "mail": [data["mail"]],
        }
        return {"dn": f"uid={uid},dc=example", "uid": uid}

    def update_user(self, uid, data):
        self.update_log.append((uid, data))
        rec = self.users[uid]
        for key, value in data.items():
            if value is None:
                rec.pop(key, None)
            else:
                rec[key] = [str(value)]
        return {"uid": uid}

    def delete_user(self, uid):
        if uid not in self.users:
            from app.utils.exceptions import RequestException
            raise RequestException("not found")
        del self.users[uid]
        return {"uid": uid}


def install(monkeypatch, gateway):
    monkeypatch.setattr("app.api.v1.admin.ApiScimProvisioning._gateway", lambda: gateway)
    return gateway


def _auth(headers=None):
    headers = dict(headers or {})
    headers.setdefault("Authorization", f"Bearer {TOKEN}")
    return headers


def _create_user(client, uid="alice@example.org", **overrides):
    payload = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "userName": uid,
        "displayName": "Alice Anderson",
        "name": {"givenName": "Alice", "familyName": "Anderson"},
        "emails": [{"value": uid, "primary": True}],
        "active": True,
        "externalId": "ext-1",
        "groups": ["engineering"],
    }
    payload.update(overrides)
    return client.post(f"{SCIM}/Users", json=payload, headers=_auth())


# ---------------------------------------------------------------- #
# auth gate
# ---------------------------------------------------------------- #

def test_no_token_is_401(client):
    resp = client.get(f"{SCIM}/Users")
    assert resp.status_code == 401
    body = resp.get_json()
    assert body["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert body["scimType"] == "invalid_token"


def test_wrong_token_is_401(client):
    resp = client.get(f"{SCIM}/Users", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


def test_scim_routes_are_public_access(client, monkeypatch):
    """No admin JWT needed — the SCIM bearer token is the gate."""
    install(monkeypatch, FakeGateway())
    resp = client.get(f"{SCIM}/Users", headers=_auth())
    assert resp.status_code == 200


# ---------------------------------------------------------------- #
# create
# ---------------------------------------------------------------- #

def test_create_provisions_real_directory_user(client, monkeypatch):
    gateway = install(monkeypatch, FakeGateway())
    resp = client.post(f"{SCIM}/Users", json={
        "userName": "alice@example.org",
        "displayName": "Alice Anderson",
        "name": {"givenName": "Alice", "familyName": "Anderson"},
        "emails": [{"value": "alice@example.org", "primary": True},
                   {"value": "a@other.org"}],
        "active": True,
        "externalId": "ext-42",
        "groups": ["engineering"],
    }, headers=_auth())
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["userName"] == "alice@example.org"
    assert body["displayName"] == "Alice Anderson"
    assert body["name"]["givenName"] == "Alice"
    assert body["name"]["familyName"] == "Anderson"
    assert body["emails"] == [{"value": "alice@example.org", "primary": True}]
    assert body["active"] is True
    assert body["externalId"] == "ext-42"
    assert body["groups"] == ["engineering"]

    # the real directory received the mapped record
    assert len(gateway.create_log) == 1
    created = gateway.create_log[0]
    assert created["uid"] == "alice@example.org"
    assert created["cn"] == "Alice Anderson"
    assert created["mail"] == "alice@example.org"
    assert created["sn"] == "Anderson"
    assert "password" in created and created["password"]
    assert gateway.users["alice@example.org"]["uid"] == ["alice@example.org"]


def test_create_duplicate_is_409_uniqueness(client, monkeypatch):
    gateway = install(monkeypatch, FakeGateway())
    gateway.users["bob@example.org"] = {"uid": ["bob@example.org"], "cn": ["Bob"]}
    resp = client.post(f"{SCIM}/Users", json={
        "userName": "bob@example.org", "displayName": "Bob",
        "emails": [{"value": "bob@example.org"}],
    }, headers=_auth())
    assert resp.status_code == 409
    assert resp.get_json()["scimType"] == "uniqueness"
    assert gateway.create_log == []


def test_create_without_user_name_is_invalid_syntax(client, monkeypatch):
    install(monkeypatch, FakeGateway())
    resp = client.post(f"{SCIM}/Users", json={"displayName": "x"}, headers=_auth())
    assert resp.status_code == 400
    assert resp.get_json()["scimType"] == "invalidSyntax"


# ---------------------------------------------------------------- #
# list / get
# ---------------------------------------------------------------- #

def test_list_returns_real_directory(client, monkeypatch):
    gateway = install(monkeypatch, FakeGateway())
    gateway.users["alice@example.org"] = {
        "uid": ["alice@example.org"], "cn": ["Alice A"], "sn": ["A"],
        "givenName": ["Alice"], "mail": ["alice@example.org"],
    }
    gateway.users["bob@example.org"] = {
        "uid": ["bob@example.org"], "cn": ["Bob B"], "sn": ["B"],
        "givenName": ["Bob"], "mail": ["bob@example.org"],
    }
    resp = client.get(f"{SCIM}/Users", headers=_auth())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["totalResults"] == 2
    names = {r["userName"] for r in body["Resources"]}
    assert names == {"alice@example.org", "bob@example.org"}


def test_get_detail_and_404(client, monkeypatch):
    gateway = install(monkeypatch, FakeGateway())
    gateway.create_user({"uid": "carol@example.org", "cn": "Carol", "sn": "C",
                         "givenName": "Carol", "mail": "carol@example.org", "password": "x"})
    resp = client.get(f"{SCIM}/Users/carol@example.org", headers=_auth())
    assert resp.status_code == 200
    assert resp.get_json()["displayName"] == "Carol"
    missing = client.get(f"{SCIM}/Users/nope@example.org", headers=_auth())
    assert missing.status_code == 404
    assert missing.get_json()["scimType"] == "noSuchResource"


# ---------------------------------------------------------------- #
# patch (real attribute update)
# ---------------------------------------------------------------- #

def test_patch_updates_ldap_attributes(client, monkeypatch):
    gateway = install(monkeypatch, FakeGateway())
    gateway.create_user({"uid": "dave@example.org", "cn": "Dave", "sn": "D",
                         "givenName": "Dave", "mail": "dave@example.org",
                         "password": "x"})
    resp = client.patch(f"{SCIM}/Users/dave@example.org", json={
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [
            {"op": "Replace", "path": "displayName", "value": "David"},
            {"op": "Replace", "path": "name.familyName", "value": "D2"},
            {"op": "Replace", "path": "active", "value": False},
        ],
    }, headers=_auth())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["displayName"] == "David"
    assert body["name"]["familyName"] == "D2"
    assert body["active"] is False
    # both the real attribute and the LDAP shadowExpire deactivation
    assert gateway.users["dave@example.org"]["cn"] == ["David"]
    assert gateway.users["dave@example.org"]["shadowExpire"] == ["1"]


def test_patch_reenable_removes_shadow_expire(client, monkeypatch):
    gateway = install(monkeypatch, FakeGateway())
    gateway.create_user({"uid": "erin@example.org", "cn": "Erin", "sn": "E",
                         "givenName": "Erin", "mail": "erin@example.org",
                         "password": "x", "shadowExpire": "1"})
    resp = client.patch(f"{SCIM}/Users/erin@example.org", json={
        "Operations": [{"op": "Replace", "path": "active", "value": True}],
    }, headers=_auth())
    assert resp.status_code == 200
    assert resp.get_json()["active"] is True
    assert "shadowExpire" not in gateway.users["erin@example.org"]


def test_patch_missing_user_is_404(client, monkeypatch):
    install(monkeypatch, FakeGateway())
    resp = client.patch(f"{SCIM}/Users/noone@example.org", json={
        "Operations": [{"op": "Replace", "path": "active", "value": False}],
    }, headers=_auth())
    assert resp.status_code == 404


# ---------------------------------------------------------------- #
# delete
# ---------------------------------------------------------------- #

def test_delete_deprovisions_from_directory(client, monkeypatch):
    gateway = install(monkeypatch, FakeGateway())
    gateway.create_user({"uid": "frank@example.org", "cn": "Frank", "sn": "F",
                         "givenName": "Frank", "mail": "frank@example.org",
                         "password": "x"})
    resp = client.delete(f"{SCIM}/Users/frank@example.org", headers=_auth())
    assert resp.status_code == 204
    assert "frank@example.org" not in gateway.users


def test_delete_missing_is_404(client, monkeypatch):
    install(monkeypatch, FakeGateway())
    resp = client.delete(f"{SCIM}/Users/ghost@example.org", headers=_auth())
    assert resp.status_code == 404


# ---------------------------------------------------------------- #
# honest failure without identity source
# ---------------------------------------------------------------- #

def test_no_identity_source_is_server_failure(client, monkeypatch):
    monkeypatch.setattr("app.api.v1.admin.ApiScimProvisioning._gateway", lambda: None)
    resp = client.post(f"{SCIM}/Users", json={
        "userName": "x@example.org", "displayName": "x",
        "emails": [{"value": "x@example.org"}],
    }, headers=_auth())
    assert resp.status_code == 500
    assert resp.get_json()["scimType"] == "serverFailure"