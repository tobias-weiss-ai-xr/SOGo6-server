"""Functional tests for ApiAppPassword — list, create, delete, verify.

Uses a mocked InterfaceAppPassword; g.user provided via request context.
Replaces the earlier structural (string-assertion) suite.
"""
from types import SimpleNamespace
from unittest import mock

import pytest
from flask import Flask, g

from app.api.v1.user.ApiAppPassword import blp
from app.utils import errors as err

MOD = "app.api.v1.user.ApiAppPassword"

USER = SimpleNamespace(uid="user-1")


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.before_request
    def _set_user():
        g.user = USER

    app.register_blueprint(blp)

    with mock.patch(f"{MOD}.InterfaceAppPassword") as iface_cls:
        iface = iface_cls.return_value
        yield app.test_client(), iface


class TestList:
    def test_list_empty(self, client):
        c, iface = client
        iface.list_for_user.return_value = []
        resp = c.get("/app-passwords")
        assert resp.status_code == 200
        assert resp.json["app_passwords"] == []
        iface.list_for_user.assert_called_once_with("user-1")

    def test_list_returns_items(self, client):
        c, iface = client
        items = [
            {"id": 1, "label": "Thunderbird", "created_at": 100, "last_used": 200, "expires_at": None}
        ]
        iface.list_for_user.return_value = items
        resp = c.get("/app-passwords")
        assert resp.status_code == 200
        assert resp.json["app_passwords"] == items


class TestCreate:
    def test_create_ok(self, client):
        c, iface = client
        iface.create.return_value = {
            "id": 1, "label": "Outlook", "token": "raw-token", "created_at": 100,
        }
        resp = c.post("/app-passwords", json={"label": "Outlook"})
        assert resp.status_code == 201
        assert resp.json["token"] == "raw-token"
        iface.create.assert_called_once_with("user-1", "Outlook")

    def test_create_validation_error(self, client):
        c, _ = client
        resp = c.post("/app-passwords", json={})
        assert resp.status_code == 422

    def test_create_interface_error_propagates(self, client):
        # The blueprint has no error handling of its own: RequestException
        # raised by the interface propagates to the app-level handler (which
        # a micro-app in these unit tests does not register).
        c, iface = client
        from app.utils.exceptions import RequestException

        iface.create.side_effect = RequestException(
            "nope", err.ERROR_APP_PASSWORD_NOT_FOUND
        )
        with pytest.raises(RequestException):
            c.post("/app-passwords", json={"label": "x"})


class TestDelete:
    def test_delete_ok(self, client):
        c, iface = client
        resp = c.delete("/app-passwords/7")
        assert resp.status_code == 204
        iface.delete.assert_called_once_with(7, "user-1")


class TestVerify:
    def test_verify_valid(self, client):
        c, iface = client
        iface.verify.return_value = True
        resp = c.post("/app-passwords/verify", json={"username": "u@x.org", "token": "t"})
        assert resp.status_code == 200
        assert resp.json == {"valid": True}
        iface.verify.assert_called_once_with("u@x.org", "t")

    def test_verify_invalid(self, client):
        c, iface = client
        iface.verify.return_value = False
        resp = c.post("/app-passwords/verify", json={"username": "u@x.org", "token": "bad"})
        assert resp.status_code == 200
        assert resp.json == {"valid": False}

    def test_verify_validation_error(self, client):
        c, _ = client
        resp = c.post("/app-passwords/verify", json={"username": "u@x.org"})
        assert resp.status_code == 422
