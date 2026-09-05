"""Functional tests for ApiDomainBranding (per-domain login branding via cache).

Covers both the admin endpoint (/branding/<domain>) and the public endpoint
(/branding/<domain>/public) including cache-miss, cache-hit, malformed-JSON and
public-safe-field filtering paths.
"""
import json
from unittest import mock

import pytest
from flask import Flask

from app.api.v1.admin.ApiDomainBranding import blp


class FakeCache:
    def __init__(self):
        self.data = {}
        self.set_calls = []

    def get(self, key, as_type=None):
        value = self.data.get(key)
        if value is None:
            return None
        return value

    def set(self, key, value, ttl=None):
        self.set_calls.append((key, value, ttl))
        self.data[key] = value


CACHE = FakeCache()


@pytest.fixture(autouse=True)
def _reset_and_patch_cache():
    CACHE.data.clear()
    CACHE.set_calls.clear()
    with mock.patch("app.api.v1.admin.ApiDomainBranding.sogo_cache", return_value=CACHE):
        yield


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(blp)
    return app.test_client()


FULL_BRANDING = {
    "logo": "data:image/png;base64,AAAA",
    "primary_color": "#3B82F6",
    "custom_css": "body { color: red; }",
    "login_header": "Welcome",
    "login_footer": "Impressum",
    "favicon": "data:image/png;base64,BBBB",
    "private_field": "should-not-leak",
}


class TestAdminBranding:
    def test_get_missing_returns_empty(self, client):
        resp = client.get("/branding/example.org")
        assert resp.status_code == 200
        assert resp.json == {}

    def test_get_existing_parses_json(self, client):
        CACHE.data["branding:example.org"] = json.dumps(FULL_BRANDING)
        resp = client.get("/branding/example.org")
        assert resp.status_code == 200
        body = resp.json
        assert body["primary_color"] == "#3B82F6"
        assert body["login_header"] == "Welcome"
        # admin response still only contains the declared branding fields
        assert "private_field" not in body
        assert set(body.keys()) == {
            "logo", "primary_color", "custom_css", "login_header", "login_footer", "favicon",
        }

    def test_get_malformed_json_returns_empty(self, client):
        CACHE.data["branding:example.org"] = "{not json"
        resp = client.get("/branding/example.org")
        assert resp.status_code == 200
        assert resp.json == {}

    def test_put_stores_branding(self, client):
        payload = {
            "logo": None,
            "primary_color": "#10B981",
            "custom_css": "/* x */",
            "login_header": "Hello",
            "login_footer": "Bye",
            "favicon": None,
        }
        resp = client.put("/branding/example.org", json=payload)
        assert resp.status_code == 200
        body = resp.json
        assert body["primary_color"] == "#10B981"
        # stored serialized in cache
        key = CACHE.set_calls[-1][0]
        stored = CACHE.set_calls[-1][1]
        assert key == "branding:example.org"
        assert json.loads(stored)["login_header"] == "Hello"
        # round-trips through get
        stored_resp = client.get("/branding/example.org")
        assert stored_resp.json["primary_color"] == "#10B981"

    def test_put_ttl_is_one_year(self, client):
        client.put("/branding/example.org", json={"primary_color": "#000000"})
        assert CACHE.set_calls[0][2] == 86400 * 365


class TestPublicBranding:
    def test_public_get_missing_returns_empty(self, client):
        resp = client.get("/branding/example.org/public")
        assert resp.status_code == 200
        assert resp.json == {}

    def test_public_get_filters_private_fields(self, client):
        CACHE.data["branding:example.org"] = json.dumps(FULL_BRANDING)
        resp = client.get("/branding/example.org/public")
        assert resp.status_code == 200
        body = resp.json
        assert body["primary_color"] == "#3B82F6"
        assert body["logo"] == "data:image/png;base64,AAAA"
        assert "private_field" not in body
        assert set(body.keys()) == {
            "logo", "primary_color", "custom_css", "login_header", "login_footer", "favicon",
        }

    def test_public_get_malformed_json_returns_empty(self, client):
        CACHE.data["branding:example.org"] = "nope{"
        resp = client.get("/branding/example.org/public")
        assert resp.status_code == 200
        assert resp.json == {}

    def test_public_get_ignores_extra_keys(self, client):
        CACHE.data["branding:example.org"] = json.dumps({"primary_color": "#FFF", "zz": 1})
        resp = client.get("/branding/example.org/public")
        assert resp.status_code == 200
        assert resp.json == {"primary_color": "#FFF"}
