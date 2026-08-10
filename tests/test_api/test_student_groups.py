"""Student Groups — real LDAP group sync (replaces Redis-only mocks).

These tests assert that every student group operation results in a real
LDAP interaction (create_group, add_member, remove_member, delete_group)
via ModuleGroup. The Redis index only stores metadata; group membership
lives in LDAP. The seam is the _group_module factory in ApiStudentGroups.
"""
from __future__ import annotations

import json

import pytest

from app import create_app
from app.utils import constants as cs
from app.service import sogo_cache

ADMIN = "/api/admin/v1/student-groups"


@pytest.fixture()
def admin_client(monkeypatch):
    from app.auth.Admin import Admin

    app = create_app(cs.SOGO_NOT_INIT)
    app.config["TESTING"] = True
    monkeypatch.setattr("app.VoucherAdminService.__init__", lambda self, ps: None)
    monkeypatch.setattr(
        "app.VoucherAdminService.generate_admin_from_voucher",
        staticmethod(lambda token: Admin("smoke-admin")),
    )
    return app.test_client()


@pytest.fixture(autouse=True)
def _isolate():
    cache = sogo_cache()
    cache.delete("stu_grp:index", "stu_grp_test_grp")


# ------------------------------------------------------------
# Fake ModuleGroup for tests (seam)
# ------------------------------------------------------------
class FakeModuleGroup:
    """In-memory substitute for ModuleGroup: tracks calls, simulates LDAP."""

    def __init__(self):
        self.groups: dict = {}  # dn -> {cn, description, mail, member: set}
        self.users: dict = {}    # email -> dn
        self._groups_base = "ou=groups,dc=test,dc=org"
        self._users_base = "ou=users,dc=test,dc=org"
        self.calls: list = []

    def create_group(self, cn, description=None, mail=None):
        dn = f"cn={cn},{self._groups_base}"
        self.groups[dn] = {"cn": cn, "description": description, "mail": mail, "member": set()}
        self.calls.append(("create_group", cn))
        return dn

    def get_group(self, dn):
        entry = self.groups.get(dn)
        if not entry:
            from app.utils.exceptions import RequestException
            raise RequestException("not found", error=None)
        # Return MatrixSigning style: {attr: [val, ...]}
        attrs: dict = {"dn": [dn], "cn": [entry["cn"]]}
        if entry.get("description"):
            attrs["description"] = [entry["description"]]
        if entry.get("mail"):
            attrs["mail"] = [entry["mail"]]
        if entry["member"]:
            attrs["member"] = list(entry["member"])
        return attrs

    def delete_group(self, dn):
        if dn in self.groups:
            del self.groups[dn]
        self.calls.append(("delete_group", dn))

    def add_member(self, group_dn, member_dn):
        if group_dn in self.groups:
            self.groups[group_dn]["member"].add(member_dn)
        self.calls.append(("add_member", group_dn, member_dn))

    def remove_member(self, group_dn, member_dn):
        if group_dn in self.groups:
            self.groups[group_dn]["member"].discard(member_dn)
        self.calls.append(("remove_member", group_dn, member_dn))

    def user_dn_from_email(self, email):
        if email not in self.users:
            dn = f"uid={email.split('@')[0]},{self._users_base}"
            self.users[email] = dn
        return self.users[email]

    user_dn_from_uid = user_dn_from_email  # simplify


@pytest.fixture
def fake_mod(monkeypatch):
    f = FakeModuleGroup()
    monkeypatch.setattr("app.api.v1.admin.ApiStudentGroups._group_module", lambda: f)
    return f


# ------------------------------------------------------------
# CRUD + membership tests
# ------------------------------------------------------------
def test_create_group_calls_ldap(admin_client, fake_mod):
    payload = {
        "name": "CS101 Intro",
        "course_code": "CS101",
        "semester": "Fall",
        "academic_year": "2024",
        "faculty_email": "prof@test.org",
    }
    resp = admin_client.post(
        f"{ADMIN}/",
        json=payload,
        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["name"] == "CS101 Intro"
    assert data["cn"]  # LDAP-safe cn generated
    assert data["ldap_dn"]  # real DN promise
    # check the LDAP create was called
    assert any(call[0] == "create_group" for call in fake_mod.calls)


def test_list_groups_fetches_member_count_from_ldap(admin_client, fake_mod):
    # Setup: fake_mod has a group created externally
    fake_mod.create_group("test-group", mail="test@x.org")
    fake_mod.add_member(
        "cn=test-group,ou=groups,dc=test,dc=org",
        "uid=alice,ou=users,dc=test,dc=org",
    )
    # Also store a group meta entry for Redis
    cache = sogo_cache()
    meta = {"id": "test_grp", "name": "Test Group", "cn": "test-group", "faculty_email": "p@x.org"}
    cache.set("stu_grp:test_grp", json.dumps(meta), 3600)
    cache.set("stu_grp:index", json.dumps(["test_grp"]), 3600)

    resp = admin_client.get(f"{ADMIN}/", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert len(data) == 1
    assert data[0]["member_count"] == 1  # honest count from LDAP


def test_detail_returns_ldap_members(admin_client, fake_mod):
    # setup meta in Redis
    cache = sogo_cache()
    meta = {"id": "grp1", "name": "G1", "cn": "g1", "faculty_email": "p@x.org"}
    cache.set("stu_grp:grp1", json.dumps(meta), 3600)
    cache.set("stu_grp:index", json.dumps(["grp1"]), 3600)

    fake_mod.create_group("g1", mail="g1@x.org")
    fake_mod.add_member("cn=g1,ou=groups,dc=test,dc=org", "uid=bob,ou=users,dc=test,dc=org")

    resp = admin_client.get(f"{ADMIN}/grp1", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["member_count"] == 1


def test_enroll_adds_members_to_ldap_group(admin_client, fake_mod):
    cache = sogo_cache()
    meta = {"id": "grp1", "name": "G1", "cn": "g1", "faculty_email": "p@x.org", "ldap_dn": "cn=g1,ou=groups,dc=test,dc=org"}
    cache.set("stu_grp:grp1", json.dumps(meta), 3600)
    cache.set("stu_grp:index", json.dumps(["grp1"]), 3600)

    # Ensure group exists in LDAP
    fake_mod.create_group("g1", mail="g1@x.org")

    resp = admin_client.post(
        f"{ADMIN}/enroll",
        json={"group_id": "grp1", "emails": ["alice@x.org", "bob@x.org"]},
        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["added"] == ["alice@x.org", "bob@x.org"]
    # Check the LDAP group now has 2 members
    dn = "cn=g1,ou=groups,dc=test,dc=org"
    members = fake_mod.groups[dn]["member"]
    assert len(members) == 2


def test_drop_removes_members_from_ldap_group(admin_client, fake_mod):
    cache = sogo_cache()
    meta = {"id": "grp1", "name": "G1", "cn": "g1", "faculty_email": "p@x.org", "ldap_dn": "cn=g1,ou=groups,dc=test,dc=org"}
    cache.set("stu_grp:grp1", json.dumps(meta), 3600)
    cache.set("stu_grp:index", json.dumps(["grp1"]), 3600)

    dn = "cn=g1,ou=groups,dc=test,dc=org"
    fake_mod.create_group("g1", mail="g1@x.org")
    fake_mod.add_member(dn, "uid=alice,ou=users,dc=test,dc=org")
    fake_mod.add_member(dn, "uid=bob,ou=users,dc=test,dc=org")

    resp = admin_client.post(
        f"{ADMIN}/drop",
        json={"group_id": "grp1", "emails": ["alice@x.org"]},
        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["removed"] == ["alice@x.org"]
    members = fake_mod.groups[dn]["member"]
    assert len(members) == 1


def test_delete_group_calls_ldap_delete(admin_client, fake_mod):
    cache = sogo_cache()
    meta = {"id": "grp1", "name": "G1", "cn": "g1", "faculty_email": "p@x.org", "ldap_dn": "cn=g1,ou=groups,dc=test,dc=org"}
    cache.set("stu_grp:grp1", json.dumps(meta), 3600)
    cache.set("stu_grp:index", json.dumps(["grp1"]), 3600)

    dn = "cn=g1,ou=groups,dc=test,dc=org"
    fake_mod.create_group("g1", mail="g1@x.org")

    resp = admin_client.delete(f"{ADMIN}/grp1", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["deleted"] == "grp1"
    # LDAP group is gone
    assert dn not in fake_mod.groups
    # Redis meta is gone
    assert not sogo_cache().get("stu_grp:grp1", str)


# ------------------------------------------------------------
# Honesty: fail if LDAP unavailable
# ------------------------------------------------------------
class BrokenModuleGroup:
    """ModuleGroup that always raises (simulates unreachable LDAP)."""

    def __init__(self):
        self._groups_base = "ou=groups"

    def create_group(self, *a, **kw):
        raise ConnectionError("LDAP unreachable")

    def get_group(self, *a, **kw):
        raise ConnectionError("LDAP unreachable")


def test_create_fails_honestly_when_ldap_unreachable(admin_client, monkeypatch):
    monkeypatch.setattr("app.api.v1.admin.ApiStudentGroups._group_module", lambda: BrokenModuleGroup())

    resp = admin_client.post(
        f"{ADMIN}/",
        json={"name": "CS101", "faculty_email": "prof@test.org"},
        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    if isinstance(body, list):
        body = body[0]
    # Envelope wraps the actual data in body["data"]
    data = body.get("data", body)
    # Must NOT return 200 with fabricated gid
    assert data.get("success") is False or "ldap" in data.get("error_msg", "").lower() or "E000101" in str(data)


def test_enroll_fails_honestly_when_ldap_unreachable(admin_client, monkeypatch):
    # Setup Redis meta so group "exists" in metadata
    cache = sogo_cache()
    meta = {"id": "grp1", "name": "G1", "cn": "g1", "faculty_email": "p@x.org", "ldap_dn": "cn=g1,ou=groups"}
    cache.set("stu_grp:grp1", json.dumps(meta), 3600)
    cache.set("stu_grp:index", json.dumps(["grp1"]), 3600)
    monkeypatch.setattr("app.api.v1.admin.ApiStudentGroups._group_module", lambda: BrokenModuleGroup())

    resp = admin_client.post(
        f"{ADMIN}/enroll",
        json={"group_id": "grp1", "emails": ["alice@test.org"]},
        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
