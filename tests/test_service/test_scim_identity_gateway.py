# pylint: disable=invalid-sequence-index
"""Unit tests for ScimIdentityGateway (thin adapter over ModuleAdminUser)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest

from app.service.scim.ScimIdentityGateway import ScimIdentityGateway, record_values


@pytest.fixture
def gw():
    process = {"whatever": 1}
    with mock.patch(
        "app.service.scim.ScimIdentityGateway.ModuleAdminUser"
    ) as module_cls:
        g = ScimIdentityGateway(process)
        module_cls.assert_called_once_with(process)
        yield g, module_cls.return_value


class TestListUsers:
    def test_passes_query_pagination(self, gw):
        g, module = gw
        module.list_users.return_value = (2, [{"uid": "a"}])
        out = g.list_users(query="jo", page=3, per_page=7)
        assert out == (2, [{"uid": "a"}])
        module.list_users.assert_called_once_with(
            query="jo", page=3, per_page=7)

    def test_empty_query_becomes_none(self, gw):
        g, module = gw
        module.list_users.return_value = (0, [])
        g.list_users(query="", page=1, per_page=20)
        module.list_users.assert_called_once_with(
            query=None, page=1, per_page=20)


class TestCrud:
    def test_get_user(self, gw):
        g, module = gw
        module.get_user.return_value = {"uid": "jo"}
        assert g.get_user("jo") == {"uid": "jo"}
        module.get_user.assert_called_once_with("jo")

    def test_create_user(self, gw):
        g, module = gw
        module.create_user.return_value = {"dn": "cn=jo", "uid": "jo"}
        data = {"uid": "jo"}
        assert g.create_user(data) == {"dn": "cn=jo", "uid": "jo"}
        module.create_user.assert_called_once_with(data)

    def test_update_user(self, gw):
        g, module = gw
        module.update_user.return_value = {"uid": "jo"}
        data = {"cn": "New"}
        assert g.update_user("jo", data) == {"uid": "jo"}
        module.update_user.assert_called_once_with("jo", data)

    def test_delete_user(self, gw):
        g, module = gw
        module.delete_user.return_value = {"uid": "jo"}
        assert g.delete_user("jo") == {"uid": "jo"}
        module.delete_user.assert_called_once_with("jo")


class TestRecordValues:
    def test_list_first_value(self):
        assert record_values({"mail": ["a@x.org", "b@x.org"]}, "mail") == "a@x.org"

    def test_empty_list(self):
        assert record_values({"mail": []}, "mail") == ""

    def test_bare_string(self):
        assert record_values({"cn": "John"}, "cn") == "John"

    def test_none(self):
        assert record_values({"cn": None}, "cn") == ""

    def test_missing(self):
        assert record_values({}, "sn") == ""

    def test_tuple(self):
        assert record_values({"xz": ("x", "y")}, "xz") == "x"
