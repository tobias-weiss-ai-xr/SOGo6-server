# pylint: disable=invalid-sequence-index
"""Functional tests for the ApiMailMailbox blueprint."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest
from flask import Flask, g

from app.api.v1.mail.ApiMailMailbox import blp


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(blp)

    class FakeUser:
        uid = "user@example.org"

    @app.before_request
    def _set_g():
        g.process_settings = mock.MagicMock()
        g.user_domain_settings = {}
        g.user = FakeUser()

    with mock.patch(
        "app.api.v1.mail.ApiMailMailbox.InterfaceApiMailMailbox"
    ) as iface_cls:
        iface = iface_cls.return_value
        yield app.test_client(), iface


class TestList:
    def test_get_list(self, client):
        c, iface = client
        iface.list_mailboxes.return_value = {"mailboxes": []}
        resp = c.get("/mailboxes")
        assert resp.status_code == 200
        iface.list_mailboxes.assert_called_once()

    def test_post_create(self, client):
        c, iface = client
        iface.create_mailbox.return_value = {"data": {"account_id": "abc"}}
        resp = c.post("/mailboxes", json={
            "name": "External",
            "mail_server": {
                "server": "imap.example.org", "port": 993,
                "encryption": "None", "type": "imap",
                "username": "u", "password": "p", "auth_mech": "plain",
            },
            "identities": [{"mail": "u@example.org", "name": "U"}],
            "mail_outgoing": {
                "server": "smtp.example.org", "port": 587,
                "encryption": "None", "type": "smtp",
                "username": "u", "password": "p", "auth_mech": "plain",
            },
        })
        assert resp.status_code in (200, 201)
        iface.create_mailbox.assert_called_once()

    def test_post_create_missing_fields_400(self, client):
        c, iface = client
        resp = c.post("/mailboxes", json={})
        assert resp.status_code == 400
        iface.create_mailbox.assert_not_called()


class TestAccount:
    def test_get_account(self, client):
        c, iface = client
        iface.get_mailbox.return_value = {"account_id": "0"}
        resp = c.get("/mailboxes/0")
        assert resp.status_code == 200
        iface.get_mailbox.assert_called_once_with("0")

    def test_patch_account(self, client):
        c, iface = client
        iface.update_mailbox.return_value = {"account_id": "0"}
        resp = c.patch("/mailboxes/0", json={"name": "Main"})
        assert resp.status_code == 200
        iface.update_mailbox.assert_called_once()
        assert iface.update_mailbox.call_args.args[0] == "0"

    def test_patch_invalid_nested_field_400(self, client):
        c, iface = client
        # mail_server.port out of range -> validation failure
        resp = c.patch("/mailboxes/0", json={"mail_server": {"port": 99999}})
        assert resp.status_code == 400
        iface.update_mailbox.assert_not_called()

    def test_patch_empty_object_ok(self, client):
        c, iface = client
        iface.update_mailbox.return_value = {"data": {}}
        resp = c.patch("/mailboxes/0", json={})
        assert resp.status_code == 200
        iface.update_mailbox.assert_called_once()

    def test_delete_account(self, client):
        c, iface = client
        iface.delete_mailbox.return_value = {}
        resp = c.delete("/mailboxes/0")
        assert resp.status_code in (200, 204)
        iface.delete_mailbox.assert_called_once_with("0")


class TestDelegates:
    def test_get_delegates(self, client):
        c, iface = client
        iface.get_mailbox_delegates.return_value = {"delegates": []}
        resp = c.get("/mailboxes/0/delegate")
        assert resp.status_code == 200
        iface.get_mailbox_delegates.assert_called_once_with("0")

    def test_post_delegate(self, client):
        c, iface = client
        iface.create_mailbox_delegate.return_value = {"data": "other@example.org"}
        resp = c.post("/mailboxes/0/delegate", json={"email": "other@example.org"})
        assert resp.status_code in (200, 201)
        iface.create_mailbox_delegate.assert_called_once()
        assert iface.create_mailbox_delegate.call_args.args[0] == "0"


class TestPurge:
    def test_post_purge(self, client):
        c, iface = client
        iface.purge_mailbox.return_value = {"data": {"mails_deleted": 5}}
        resp = c.post("/mailboxes/0/purge", json={"permanently_delete": True, "date": "2025-12-11"})
        assert resp.status_code == 200
        iface.purge_mailbox.assert_called_once()
        assert iface.purge_mailbox.call_args.args[0] == "0"

    def test_post_purge_missing_fields_400(self, client):
        c, iface = client
        resp = c.post("/mailboxes/0/purge", json={})
        assert resp.status_code == 400
        iface.purge_mailbox.assert_not_called()
