# pylint: disable=invalid-sequence-index
"""Unit tests for ApiUserPreferences (63% -> high)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest


def make_resp_base():
    return {
        "data": None,
        "error_code": "NO_ERROR",
        "error_msg": "",
    }


class TestUserPreferencesApi:
    @pytest.fixture
    def client(self):
        from flask import Flask, g
        from app.api.v1.user import ApiUserPreferences

        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.before_request
        def _set_ctx():
            g.process_settings = mock.MagicMock()
            g.system_settings = mock.MagicMock()
            g.user_domain_settings = {}
            g.user = mock.MagicMock()
            g.user.uid = "user@example.org"

        app.register_blueprint(ApiUserPreferences.blp)
        with app.test_client() as c:
            yield c

    def test_get_preferences(self, client):
        with mock.patch(
            "app.api.v1.user.ApiUserPreferences.InterfaceUserPreferences"
        ) as iface_cls:
            iface_cls.return_value.get_all_preferences.return_value = (
                {"data": {"USER_GENERAL": {}}, "error_code": "NO_ERROR", "error_msg": ""},
                200,
            )
            resp = client.get("/preferences")
        assert resp.status_code == 200
        assert resp.get_json()["data"] == {"USER_GENERAL": {}}
        iface_cls.return_value.get_all_preferences.assert_called_once()

    def test_patch_preferences(self, client):
        with mock.patch(
            "app.api.v1.user.ApiUserPreferences.InterfaceUserPreferences"
        ) as iface_cls:
            iface_cls.return_value.update_all_preferences.return_value = (
                {"data": {}, "error_code": "NO_ERROR", "error_msg": ""},
                200,
            )
            body = {"settings": {"USER_GENERAL": {"SOGO_U_LANGUAGE": "French"}}}
            resp = client.patch("/preferences", json=body)
        assert resp.status_code == 200
        iface_cls.return_value.update_all_preferences.assert_called_once_with(
            body["settings"]
        )

    def test_patch_missing_settings_422(self, client):
        with mock.patch(
            "app.api.v1.user.ApiUserPreferences.InterfaceUserPreferences"
        ) as iface_cls:
            resp = client.patch("/preferences", json={})
        # marshmallow validation failure -> error_status_code=400
        assert resp.status_code == 400
        iface_cls.return_value.update_all_preferences.assert_not_called()
