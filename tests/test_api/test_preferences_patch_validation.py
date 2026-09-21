# pylint: disable=invalid-sequence-index
"""Unit tests for PREF-2: non-dict preference payloads must be rejected with 4xx and never written."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByUv")

import pytest


def make_client():
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
    return app.test_client()


class TestPreferencesPatchValidation:
    def test_patch_settings_list_rejected_without_write(self):
        """A JSON list at the settings level must fail argument validation (no write)."""
        client = make_client()
        with mock.patch(
            "app.api.v1.user.ApiUserPreferences.InterfaceUserPreferences"
        ) as iface_cls:
            resp = client.patch("/preferences", json={"settings": ["x"]})
        assert resp.status_code in (400, 422)
        iface_cls.return_value.update_all_preferences.assert_not_called()

    def test_patch_subparent_list_rejected_without_write(self):
        """A JSON list inside a subparent must fail argument validation (no write).

        Regression: this used to be written to the DB first and then crash the
        response serialization with AttributeError ('list' object has no
        attribute 'items') -> 500-after-write.
        """
        client = make_client()
        with mock.patch(
            "app.api.v1.user.ApiUserPreferences.InterfaceUserPreferences"
        ) as iface_cls:
            resp = client.patch(
                "/preferences", json={"settings": {"USER_GENERAL": ["x"]}}
            )
        assert resp.status_code in (400, 422)
        iface_cls.return_value.update_all_preferences.assert_not_called()

    def test_patch_subparent_scalar_rejected_without_write(self):
        client = make_client()
        with mock.patch(
            "app.api.v1.user.ApiUserPreferences.InterfaceUserPreferences"
        ) as iface_cls:
            resp = client.patch(
                "/preferences", json={"settings": {"USER_GENERAL": "oops"}}
            )
        assert resp.status_code in (400, 422)
        iface_cls.return_value.update_all_preferences.assert_not_called()

    def test_patch_valid_dict_still_accepted(self):
        client = make_client()
        with mock.patch(
            "app.api.v1.user.ApiUserPreferences.InterfaceUserPreferences"
        ) as iface_cls:
            iface_cls.return_value.update_all_preferences.return_value = (
                {"data": {}, "error_code": "NO_ERROR", "error_msg": ""},
                200,
            )
            body = {"settings": {"USER_GENERAL": {"SOGO_U_LANGUAGE": "German"}}}
            resp = client.patch("/preferences", json=body)
        assert resp.status_code == 200
        iface_cls.return_value.update_all_preferences.assert_called_once_with(
            body["settings"]
        )
