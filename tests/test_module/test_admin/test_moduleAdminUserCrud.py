"""
Tests unitaires pour les opérations CRUD utilisateur de ModuleAdminUser.

Ces tests mockent _get_ldap_client() pour éviter toute dépendance
à un annuaire LDAP réel.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.module.admin.ModuleAdminUser import ModuleAdminUser
from app.utils import errors as err
from app.utils.exceptions import RequestException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client(**search_results):
    """
    Build a MagicMock that simulates a connected ClientLdap.
    """
    client = MagicMock()
    client.base_dn = "dc=example,dc=org"
    client.filter = "(objectClass=inetOrgPerson)"
    client.ldap_conn = MagicMock()

    def search_side_effect(base_dn, l_filter=None, attributes=None):
        # Allow tests to inject canned results
        results = search_results.get("search", [])
        if callable(results):
            return results(l_filter, attributes)
        return results

    client._search.side_effect = search_side_effect
    return client


def _make_module(monkeypatch, mock_client=None):
    """Create a ModuleAdminUser with a mocked _get_ldap_client."""
    if mock_client is None:
        mock_client = _make_mock_client()
    monkeypatch.setattr(
        "app.module.admin.ModuleAdminUser.ModuleAdminUser._get_ldap_client",
        lambda self: mock_client,
    )
    module = ModuleAdminUser()
    return module, mock_client


# ===================================================================
# list_users
# ===================================================================

class TestListUsers:
    def test_list_all_users(self, monkeypatch):
        """list_users returns all users without a query."""
        mock = _make_mock_client(search=[
            ("uid=alice,dc=example,dc=org", {
                "uid": [b"alice"],
                "cn": [b"Alice Johnson"],
                "sn": [b"Johnson"],
                "mail": [b"alice@example.org"],
            }),
            ("uid=bob,dc=example,dc=org", {
                "uid": [b"bob"],
                "cn": [b"Bob Smith"],
                "sn": [b"Smith"],
                "mail": [b"bob@example.org"],
            }),
        ])
        module, _ = _make_module(monkeypatch, mock)
        total, users = module.list_users()
        assert total == 2
        assert len(users) == 2
        assert users[0]["uid"][0] == "alice"
        assert users[1]["uid"][0] == "bob"

    def test_list_users_with_query(self, monkeypatch):
        """list_users filters results when a query is given."""
        mock = _make_mock_client(search=[
            ("uid=alice,dc=example,dc=org", {
                "uid": [b"alice"],
                "cn": [b"Alice Johnson"],
                "sn": [b"Johnson"],
                "mail": [b"alice@example.org"],
            }),
        ])
        module, _ = _make_module(monkeypatch, mock)
        total, users = module.list_users(query="alice")
        assert total == 1
        assert users[0]["uid"][0] == "alice"

    def test_list_users_pagination(self, monkeypatch):
        """list_users paginates correctly."""
        all_users = []
        for i in range(10):
            all_users.append((
                f"uid=user{i},dc=example,dc=org",
                {"uid": [f"user{i}".encode()], "cn": [f"User {i}".encode()],
                 "sn": [b"Test"], "mail": [f"user{i}@test.org".encode()]},
            ))
        mock = _make_mock_client(search=all_users)
        module, _ = _make_module(monkeypatch, mock)
        total, users = module.list_users(page=1, per_page=3)
        assert total == 10
        assert len(users) == 3
        assert users[0]["uid"][0] == "user0"
        assert users[2]["uid"][0] == "user2"

    def test_list_users_sorting(self, monkeypatch):
        """list_users sorts by the requested field."""
        mock = _make_mock_client(search=[
            ("uid=bob,dc=example,dc=org", {
                "uid": [b"bob"], "cn": [b"Bob"], "sn": [b"B"],
                "mail": [b"bob@test.org"],
            }),
            ("uid=alice,dc=example,dc=org", {
                "uid": [b"alice"], "cn": [b"Alice"], "sn": [b"A"],
                "mail": [b"alice@test.org"],
            }),
        ])
        module, _ = _make_module(monkeypatch, mock)
        _, users = module.list_users(sort_by="uid", sort_order="asc")
        assert users[0]["uid"][0] == "alice"
        assert users[1]["uid"][0] == "bob"

    def test_list_users_paginate_last_page(self, monkeypatch):
        """list_users returns fewer items on the last page."""
        all_users = []
        for i in range(5):
            all_users.append((
                f"uid=user{i},dc=example,dc=org",
                {"uid": [f"user{i}".encode()], "cn": [f"User {i}".encode()],
                 "sn": [b"T"], "mail": [f"u{i}@t.org".encode()]},
            ))
        mock = _make_mock_client(search=all_users)
        module, _ = _make_module(monkeypatch, mock)
        total, users = module.list_users(page=2, per_page=3)
        assert total == 5
        assert len(users) == 2  # remaining on last page

    def test_list_users_empty(self, monkeypatch):
        """list_users returns empty when no users exist."""
        mock = _make_mock_client(search=[])
        module, _ = _make_module(monkeypatch, mock)
        total, users = module.list_users()
        assert total == 0
        assert users == []

    def test_list_users_no_filter(self, monkeypatch):
        """When client.filter is empty, use default objectClass."""
        mock = _make_mock_client(search=[])
        mock.filter = ""
        module, _ = _make_module(monkeypatch, mock)
        total, users = module.list_users()
        assert total == 0
        assert users == []


# ===================================================================
# get_user
# ===================================================================

class TestGetUser:
    def test_get_user_found(self, monkeypatch):
        """get_user returns the matching record."""
        mock = _make_mock_client(search=[
            ("uid=alice,dc=example,dc=org", {
                "uid": [b"alice"],
                "cn": [b"Alice Johnson"],
                "sn": [b"Johnson"],
                "mail": [b"alice@example.org"],
            }),
        ])
        module, _ = _make_module(monkeypatch, mock)
        user = module.get_user("alice")
        assert user["uid"][0] == "alice"
        assert user["cn"][0] == "Alice Johnson"

    def test_get_user_not_found(self, monkeypatch):
        """get_user raises RequestException for missing user."""
        mock = _make_mock_client(search=[])
        module, _ = _make_module(monkeypatch, mock)
        with pytest.raises(RequestException) as exc:
            module.get_user("nonexistent")
        assert exc.value.error == err.ERROR_USER_PROFILE_NOT_FOUND


# ===================================================================
# create_user
# ===================================================================

class TestCreateUser:
    def test_create_user_minimal(self, monkeypatch):
        """create_user with required fields only."""
        client = MagicMock()
        client.base_dn = "dc=example,dc=org"
        client.filter = "(objectClass=inetOrgPerson)"
        client.ldap_conn = MagicMock()
        client._search.return_value = []  # no existing users → uid starts at 1001

        module, _ = _make_module(monkeypatch, client)
        # uid must be the full email-format login (it IS the login name and
        # the LDAP RDN) — a bare uid would create an un-loginable account
        result = module.create_user({
            "uid": "newuser@example.org",
            "cn": "New User",
            "sn": "User",
            "givenName": "New",
            "mail": "newuser@example.org",
            "password": "secret123",
        })
        assert result["uid"] == "newuser@example.org"
        assert result["dn"] == "uid=newuser@example.org,dc=example,dc=org"
        # Verify the LDAP add was called
        client.ldap_conn.add_s.assert_called_once()
        call_dn, call_attrs = client.ldap_conn.add_s.call_args[0]
        assert call_dn == "uid=newuser@example.org,dc=example,dc=org"
        attr_dict = dict(call_attrs)
        assert b"inetOrgPerson" in attr_dict["objectClass"]
        assert attr_dict["uid"] == [b"newuser@example.org"]

    def test_create_user_with_custom_ids(self, monkeypatch):
        """create_user respects provided uidNumber/gidNumber."""
        client = MagicMock()
        client.base_dn = "dc=example,dc=org"
        client.filter = "(objectClass=inetOrgPerson)"
        client.ldap_conn = MagicMock()
        client._search.return_value = []

        module, _ = _make_module(monkeypatch, client)
        result = module.create_user({
            "uid": "customuser@example.org",
            "cn": "Custom",
            "sn": "User",
            "givenName": "Custom",
            "mail": "customuser@example.org",
            "password": "pwd",
            "uidNumber": 5000,
            "gidNumber": 5000,
        })
        assert result["uid"] == "customuser@example.org"
        call_dn, call_attrs = client.ldap_conn.add_s.call_args[0]
        attr_dict = dict(call_attrs)
        assert attr_dict["uidNumber"] == [b"5000"]
        assert attr_dict["gidNumber"] == [b"5000"]

    def test_create_user_default_home_dir(self, monkeypatch):
        """create_user auto-generates home directory from UID."""
        client = MagicMock()
        client.base_dn = "dc=example,dc=org"
        client.filter = "(objectClass=inetOrgPerson)"
        client.ldap_conn = MagicMock()
        client._search.return_value = []

        module, _ = _make_module(monkeypatch, client)
        module.create_user({
            "uid": "user@domain.org",
            "cn": "User",
            "sn": "Test",
            "mail": "user@domain.org",
            "password": "pwd",
        })
        call_dn, call_attrs = client.ldap_conn.add_s.call_args[0]
        attr_dict = dict(call_attrs)
        assert attr_dict["homeDirectory"] == [b"/home/user"]

    def test_create_user_connection_error(self, monkeypatch):
        """create_user raises when LDAP connection is None."""
        client = MagicMock()
        client.base_dn = "dc=example,dc=org"
        client.ldap_conn = None

        module, _ = _make_module(monkeypatch, client)
        with pytest.raises(RequestException) as exc:
            module.create_user({
                "uid": "failuser@example.org",
                "cn": "Fail",
                "sn": "User",
                "mail": "failuser@example.org",
                "password": "pwd",
            })
        assert exc.value.error == err.ERROR_LDAP_CANNOT_CONNECT


# ===================================================================
# update_user
# ===================================================================

class TestUpdateUser:
    def test_update_user_basic(self, monkeypatch):
        """update_user modifies LDAP attributes."""
        client = MagicMock()
        client.base_dn = "dc=example,dc=org"
        client.filter = "(objectClass=inetOrgPerson)"
        client.ldap_conn = MagicMock()
        client._search.return_value = [
            ("uid=alice,dc=example,dc=org", {"dn": ["uid=alice,dc=example,dc=org"]}),
        ]

        module, _ = _make_module(monkeypatch, client)
        result = module.update_user("alice", {"cn": "Alice Updated", "sn": "Updated"})
        assert result["uid"] == "alice"
        # modify_s should be called with MOD_REPLACE for each attr
        assert client.ldap_conn.modify_s.call_count == 1
        call_dn, call_mods = client.ldap_conn.modify_s.call_args[0]
        assert call_dn == "uid=alice,dc=example,dc=org"
        assert len(call_mods) == 2
        mod_attrs = {m[1]: m[2] for m in call_mods}
        assert mod_attrs["cn"] == [b"Alice Updated"]
        assert mod_attrs["sn"] == [b"Updated"]

    def test_update_user_not_found(self, monkeypatch):
        """update_user raises when user doesn't exist."""
        client = MagicMock()
        client.base_dn = "dc=example,dc=org"
        client.filter = "(objectClass=inetOrgPerson)"
        client._search.return_value = []

        module, _ = _make_module(monkeypatch, client)
        with pytest.raises(RequestException) as exc:
            module.update_user("ghost", {"cn": "Ghost"})
        assert exc.value.error == err.ERROR_USER_PROFILE_NOT_FOUND

    def test_update_user_password(self, monkeypatch):
        """update_user hashes the password attribute."""
        client = MagicMock()
        client.base_dn = "dc=example,dc=org"
        client.filter = "(objectClass=inetOrgPerson)"
        client.ldap_conn = MagicMock()
        client._search.return_value = [
            ("uid=bob,dc=example,dc=org", {"dn": ["uid=bob,dc=example,dc=org"]}),
        ]

        module, _ = _make_module(monkeypatch, client)
        module.update_user("bob", {"cn": "Bob", "password": "newpass"})
        call_dn, call_mods = client.ldap_conn.modify_s.call_args[0]
        mod_attrs = {m[1]: m[2] for m in call_mods}
        # Password should be hashed (starts with {SSHA})
        assert mod_attrs["userPassword"][0].startswith(b"{SSHA}")

    def test_update_user_skips_none(self, monkeypatch):
        """update_user ignores None-valued attributes."""
        client = MagicMock()
        client.base_dn = "dc=example,dc=org"
        client.filter = "(objectClass=inetOrgPerson)"
        client.ldap_conn = MagicMock()
        client._search.return_value = [
            ("uid=alice,dc=example,dc=org", {"dn": ["uid=alice,dc=example,dc=org"]}),
        ]

        module, _ = _make_module(monkeypatch, client)
        module.update_user("alice", {"cn": None, "sn": "StillUpdated"})
        call_dn, call_mods = client.ldap_conn.modify_s.call_args[0]
        # Only sn should be in mods (cn was None)
        mod_attrs = {m[1]: m[2] for m in call_mods}
        assert "cn" not in mod_attrs
        assert mod_attrs["sn"] == [b"StillUpdated"]


# ===================================================================
# delete_user
# ===================================================================

class TestDeleteUser:
    def test_delete_user_success(self, monkeypatch):
        """delete_user removes the LDAP entry."""
        client = MagicMock()
        client.base_dn = "dc=example,dc=org"
        client.filter = "(objectClass=inetOrgPerson)"
        client.ldap_conn = MagicMock()
        client._search.return_value = [
            ("uid=alice,dc=example,dc=org", {"dn": ["uid=alice,dc=example,dc=org"]}),
        ]

        module, _ = _make_module(monkeypatch, client)
        result = module.delete_user("alice")
        assert "alice" in result["uid"]
        client.ldap_conn.delete_s.assert_called_once_with("uid=alice,dc=example,dc=org")

    def test_delete_user_not_found(self, monkeypatch):
        """delete_user raises when user doesn't exist."""
        client = MagicMock()
        client.base_dn = "dc=example,dc=org"
        client.filter = "(objectClass=inetOrgPerson)"
        client._search.return_value = []

        module, _ = _make_module(monkeypatch, client)
        with pytest.raises(RequestException) as exc:
            module.delete_user("ghost")
        assert exc.value.error == err.ERROR_USER_PROFILE_NOT_FOUND
