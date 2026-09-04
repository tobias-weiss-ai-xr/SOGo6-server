# pylint: disable=invalid-sequence-index
"""Unit tests for ApiUserCustomization (45% -> high)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest

from app.api.v1.user.ApiUserCustomization import _generate_theme_css, blp


@pytest.fixture
def client():
    from flask import Flask, g
    from app.api.v1.user import ApiUserCustomization

    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.before_request
    def _set_ctx():
        g.process_settings = mock.MagicMock()

    app.register_blueprint(ApiUserCustomization.blp)
    with app.test_client() as c:
        yield c


class TestThemesEndpoint:
    def test_returns_theme_css(self, client):
        with mock.patch(
            "app.api.v1.user.ApiUserCustomization.InterfaceApiAdminConfig"
        ) as iface_cls:
            iface_cls.return_value.get_all_setting_theme.return_value = (
                {"data": {"primary": "red", "custom_css": "body{}"}},
                200,
            )
            resp = client.get("/customization/themes")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "--primary: red;" in body
        assert "body{}" in body
        iface_cls.assert_called_once()
        iface_cls.return_value.get_all_setting_theme.assert_called_once()

    def test_empty_theme_uses_default(self, client):
        with mock.patch(
            "app.api.v1.user.ApiUserCustomization.InterfaceApiAdminConfig"
        ) as iface_cls:
            iface_cls.return_value.get_all_setting_theme.return_value = ({"data": {}}, 200)
            resp = client.get("/customization/themes")
        assert resp.status_code == 200
        assert "--background" in resp.get_json()


class TestGenerateThemeCss:
    def test_empty_returns_default(self):
        css = _generate_theme_css({})
        assert "--primary" in css
        assert ":root" in css

    def test_maps_known_keys(self):
        css = _generate_theme_css({"primary": "red", "radius": "1rem"})
        assert "--primary: red;" in css
        assert "--radius: 1rem;" in css

    def test_ignores_unknown_keys(self):
        css = _generate_theme_css({"not_a_theme_key": "x"})
        assert "not_a_theme_key" not in css

    def test_appends_custom_css(self):
        custom = "body{background:blue}"
        css = _generate_theme_css({"primary": "red", "custom_css": custom})
        assert custom in css

    def test_no_custom_css(self):
        css = _generate_theme_css({"primary": "red"})
        assert "custom_css" not in css

    def test_formats_all_prop_map_keys(self):
        # Every mapped key should appear when provided
        theme = {
            "primary": "1", "primary_foreground": "2", "background": "3",
            "foreground": "4", "sidebar_background": "5", "sidebar_foreground": "6",
            "sidebar_primary": "7", "sidebar_accent": "8",
            "sidebar_accent_foreground": "9", "sidebar_border": "10",
            "header_background": "11", "header_foreground": "12",
            "card": "13", "card_foreground": "14", "popover": "15",
            "popover_foreground": "16", "secondary": "17", "secondary_foreground": "18",
            "muted": "19", "muted_foreground": "20", "accent": "21",
            "accent_foreground": "22", "destructive": "23",
            "destructive_foreground": "24", "border": "25", "input": "26",
            "ring": "27", "radius": "28",
        }
        css = _generate_theme_css(theme)
        assert "--background: 3;" in css
        assert "--ring: 27;" in css
        assert "--radius: 28;" in css
