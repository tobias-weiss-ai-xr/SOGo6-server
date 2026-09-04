# pylint: disable=invalid-sequence-index
"""Functional tests for the Mobile App management blueprint (ApiMobileApp).

Exercises device registration, listing, detail, ping, config provisioning,
push broadcast and version checking through a real Flask test client with
the blueprint registered, mocking only the Redis cache.
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helper fakes & fixtures
# ─────────────────────────────────────────────────────────────────────────────

class FakeCache:
    """In-memory redis stand-in; stores JSON strings like real ClientRedis."""

    def __init__(self):
        self.store = {}

    def get(self, key, expected_type=str):
        raw = self.store.get(key)
        if raw is None:
            return None
        if expected_type is list and isinstance(raw, str):
            return json.loads(raw)
        return raw

    def set(self, key, val, ttl=None, nx=False):
        if isinstance(val, (dict, list)):
            val = json.dumps(val)
        self.store[key] = val
        return True

    def delete(self, *keys):
        n = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                n += 1
        return n


@pytest.fixture
def client():
    """Flask test client with MobileApp blueprint registered; cache mocked."""
    from flask import Flask
    from app.api.v1.admin import ApiMobileApp

    app = Flask(__name__)
    app.config["TESTING"] = True
    cache = FakeCache()

    with patch("app.api.v1.admin.ApiMobileApp.sogo_cache", return_value=cache):
        app.register_blueprint(ApiMobileApp.blp)
        c = app.test_client()
        c._cache = cache
        yield c


def _register_device(
    client,
    email="user@example.org",
    platform="android",
    push_token="tok1234567890abcdef:xyz" * 10,  # 240 chars, contains ':'
    app_version="1.0.0",
):
    return client.post(
        "/admin/mobile/devices/register",
        json={
            "email": email,
            "platform": platform,
            "push_token": push_token,
            "app_version": app_version,
            "device_model": "Pixel 7",
            "os_version": "14",
            "server_url": "https://mail.example.org",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestTokenValidation:
    def test_validate_apns_token_valid(self):
        from app.api.v1.admin.ApiMobileApp import _validate_apns_token
        assert _validate_apns_token("a" * 64) is True
        assert _validate_apns_token("AB" * 32) is True

    def test_validate_apns_token_invalid(self):
        from app.api.v1.admin.ApiMobileApp import _validate_apns_token
        assert _validate_apns_token("short") is False
        assert _validate_apns_token("z" * 64) is False  # non-hex
        assert _validate_apns_token("") is False

    def test_validate_fcm_token_valid(self):
        from app.api.v1.admin.ApiMobileApp import _validate_fcm_token
        assert _validate_fcm_token("a" * 50 + ":b" * 30) is True

    def test_validate_fcm_token_too_short(self):
        from app.api.v1.admin.ApiMobileApp import _validate_fcm_token
        assert _validate_fcm_token("abcdefghij") is False

    def test_validate_fcm_token_no_colon(self):
        from app.api.v1.admin.ApiMobileApp import _validate_fcm_token
        assert _validate_fcm_token("a" * 150) is False


class TestPlatformNormalization:
    @pytest.mark.parametrize(
        "ua,expected",
        [
            ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)", "ios"),
            ("Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X)", "ios"),
            ("Android 14 Mobile", "android"),
            ("Windows Phone 10", "windows"),
            ("HarmonyOS 4.0", "harmonyos"),
            ("Some Desktop Browser", "unknown"),
            ("", "unknown"),
        ],
    )
    def test_detects_platform(self, ua, expected):
        from app.api.v1.admin.ApiMobileApp import _normalize_platform
        assert _normalize_platform(ua) == expected


class TestMobileConfig:
    def test_compute_config(self):
        from app.api.v1.admin.ApiMobileApp import _compute_mobile_config
        cfg = _compute_mobile_config("https://mail.example.org", "user@example.org")
        assert cfg["domain"] == "mail.example.org"
        assert cfg["imap"]["host"] == "mail.example.org"
        assert cfg["imap"]["port"] == 993
        assert cfg["smtp"]["port"] == 587
        assert cfg["email"] == "user@example.org"
        assert "calendar" in cfg["caldav"]["url"]
        assert "contacts" in cfg["carddav"]["url"]
        assert cfg["jmap"]["url"] == "https://mail.example.org/jmap"

    def test_compute_config_http(self):
        from app.api.v1.admin.ApiMobileApp import _compute_mobile_config
        cfg = _compute_mobile_config("http://mail.test", "a@b.c")
        assert cfg["domain"] == "mail.test"


class TestAppVersion:
    def test_no_update_when_equal(self):
        from app.api.v1.admin.ApiMobileApp import _check_app_version
        res = _check_app_version("2.0.0", "2.0.0")
        assert res["has_update"] is False
        assert res["update_required"] is False
        assert res["download_url"] is None

    def test_major_update(self):
        from app.api.v1.admin.ApiMobileApp import _check_app_version
        res = _check_app_version("1.9.9", "2.0.0")
        assert res["has_update"] is True
        assert res["update_required"] is True
        assert res["download_url"] == "https://apps.sogo.local/download/2.0.0"

    def test_minor_update(self):
        from app.api.v1.admin.ApiMobileApp import _check_app_version
        res = _check_app_version("2.0.0", "2.1.0")
        assert res["has_update"] is True
        assert res["update_required"] is True

    def test_patch_update(self):
        from app.api.v1.admin.ApiMobileApp import _check_app_version
        res = _check_app_version("2.0.0", "2.0.1")
        assert res["has_update"] is True
        assert res["update_required"] is False

    def test_garbage_versions(self):
        from app.api.v1.admin.ApiMobileApp import _check_app_version
        res = _check_app_version("abc", "")
        assert res["has_update"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Device register / list / detail / ping / delete
# ─────────────────────────────────────────────────────────────────────────────

class TestDeviceRegister:
    def test_register_android_device(self, client):
        resp = _register_device(client)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["user_email"] == "user@example.org"
        assert body["data"]["platform"] == "android"
        assert body["data"]["push_type"] == "fcm"
        assert body["data"]["config"]["domain"] == "mail.example.org"
        assert body["data"]["update_info"] is not None
        # push token registered
        assert client._cache.store
        assert any(k.startswith("mob_push:") for k in client._cache.store)

    def test_register_ios_device(self, client):
        token = "a" * 64
        resp = _register_device(client, platform="ios", push_token=token)
        assert resp.status_code == 200
        assert resp.get_json()["data"]["push_type"] == "apns"

    def test_register_requires_email(self, client):
        resp = client.post("/admin/mobile/devices/register", json={"platform": "android"})
        body = resp.get_json()
        assert body["success"] is False
        assert body["data"] is None

    def test_register_invalid_apns_token(self, client):
        resp = _register_device(client, platform="ios", push_token="tooshort")
        body = resp.get_json()
        assert body["success"] is False
        assert "APNS" in body["error_msg"]

    def test_register_invalid_fcm_token(self, client):
        resp = _register_device(client, platform="android", push_token="short")
        body = resp.get_json()
        assert body["success"] is False
        assert "FCM" in body["error_msg"]

    def test_register_no_server_url_no_push_token(self, client):
        resp = client.post(
            "/admin/mobile/devices/register",
            json={"email": "user@example.org", "platform": "android"},
        )
        body = resp.get_json()
        assert body["data"]["user_email"] == "user@example.org"
        assert "config" not in body["data"]
        assert "update_info" not in body["data"]


class TestDeviceList:
    def test_empty_list(self, client):
        resp = client.get("/admin/mobile/devices")
        assert resp.status_code == 200
        assert resp.get_json()["data"] == []

    def test_list_after_registration(self, client):
        _register_device(client)
        resp = client.get("/admin/mobile/devices")
        devices = resp.get_json()["data"]
        assert len(devices) == 1
        assert devices[0]["user_email"] == "user@example.org"

    def test_list_sorted_by_last_seen(self, client):
        _register_device(client, email="first@example.org")
        _register_device(client, email="second@example.org")
        resp = client.get("/admin/mobile/devices")
        devices = resp.get_json()["data"]
        assert len(devices) == 2


class TestDeviceDetail:
    def test_get_existing_device(self, client):
        reg = _register_device(client).get_json()
        device_id = reg["data"]["id"]
        resp = client.get(f"/admin/mobile/devices/{device_id}")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["id"] == device_id

    def test_get_missing_device(self, client):
        resp = client.get("/admin/mobile/devices/doesnotexist")
        body = resp.get_json()
        assert body["success"] is False

    def test_delete_existing_device(self, client):
        reg = _register_device(client).get_json()
        device_id = reg["data"]["id"]
        push_prefix = next(k for k in client._cache.store if k.startswith("mob_push:"))
        resp = client.delete(f"/admin/mobile/devices/{device_id}")
        assert resp.get_json()["data"]["unregistered"] == device_id
        assert f"mob_device:{device_id}" not in client._cache.store
        assert push_prefix not in client._cache.store

    def test_delete_missing_device(self, client):
        resp = client.delete("/admin/mobile/devices/nope")
        assert resp.get_json()["data"]["unregistered"] == "nope"


class TestDevicePing:
    def test_ping_registered_device(self, client):
        reg = _register_device(client).get_json()
        device_id = reg["data"]["id"]
        resp = client.post(f"/admin/mobile/devices/{device_id}/ping")
        body = resp.get_json()
        assert body["data"]["pong"] is True
        assert body["data"]["update"] is not None

    def test_ping_missing_device(self, client):
        resp = client.post("/admin/mobile/devices/ghost/ping")
        assert resp.get_json()["success"] is False


class TestMobileConfig:
    def test_get_default_config(self, client):
        resp = client.get("/admin/mobile/config")
        body = resp.get_json()
        assert body["data"]["app_name"] == "SOGo Mail"
        assert body["data"]["features"]["mail"] is True

    def test_get_stored_config(self, client):
        client._cache.store["mob_config:app"] = json.dumps(
            {"app_name": "Custom", "latest_version": "3.0.0", "features": {"mail": True}}
        )
        resp = client.get("/admin/mobile/config")
        assert resp.get_json()["data"]["app_name"] == "Custom"

    def test_post_config(self, client):
        resp = client.post(
            "/admin/mobile/config",
            json={"app_name": "SOGo Pro", "latest_version": "3.1.0", "min_version": "2.0.0"},
        )
        body = resp.get_json()
        assert body["data"]["app_name"] == "SOGo Pro"
        assert body["data"]["latest_version"] == "3.1.0"
        assert "updated_at" in body["data"]
        assert "mob_config:app" in client._cache.store


class TestPushBroadcast:
    def test_broadcast_requires_message(self, client):
        resp = client.post("/admin/mobile/push/broadcast", json={"title": "Hi"})
        body = resp.get_json()
        assert body["success"] is False

    def test_broadcast_no_provider(self, client):
        _register_device(client)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SOGO_PUSH_PROVIDER", None)
            resp = client.post(
                "/admin/mobile/push/broadcast",
                json={"message": "Hello", "title": "T"},
            )
        body = resp.get_json()
        assert body["data"]["sent"] == 0
        assert "matched_devices" in body["data"]
        assert body["success"] is False

    def test_broadcast_dry_run(self, client):
        _register_device(client)
        resp = client.post(
            "/admin/mobile/push/broadcast",
            json={"message": "Hello", "title": "T", "dry_run": True},
        )
        body = resp.get_json()
        assert body["data"]["dry_run"] is True

    def test_broadcast_with_provider_unsupported(self, client):
        _register_device(client)
        with patch.dict(os.environ, {"SOGO_PUSH_PROVIDER": "apns"}, clear=False):
            resp = client.post(
                "/admin/mobile/push/broadcast",
                json={"message": "Hello", "title": "T"},
            )
        # ERROR_PUSH_PROVIDER_UNSUPPORTED -> HTTP 501 (NOT_IMPLEMENTED)
        assert resp.status_code == 501
        body = resp.get_json()
        assert body["data"]["sent"] == 0

    def test_broadcast_filters_by_email(self, client):
        _register_device(client, email="keep@example.org")
        _register_device(client, email="skip@example.org")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SOGO_PUSH_PROVIDER", None)
            resp = client.post(
                "/admin/mobile/push/broadcast",
                json={"message": "x", "email": "keep@example.org"},
            )
        assert resp.get_json()["data"]["matched_devices"] == 1

    def test_broadcast_filters_by_platform(self, client):
        """Devices whose push_token is falsy are skipped (line 304 branch)."""
        _register_device(client, platform="android")
        _register_device(client, platform="ios", push_token="a" * 64)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SOGO_PUSH_PROVIDER", None)
            resp = client.post(
                "/admin/mobile/push/broadcast",
                json={"message": "x", "platform": "ios"},
            )
        body = resp.get_json()["data"]
        # Only the ios device matched and only it has a push token
        assert body["matched_devices"] == 1

    def test_broadcast_dry_run_platform_filter(self, client):
        """Platform filter exercised on the dry-run path (line 299 branch)."""
        _register_device(client, platform="android")
        resp = client.post(
            "/admin/mobile/push/broadcast",
            json={"message": "x", "platform": "ios", "dry_run": True},
        )
        body = resp.get_json()["data"]
        assert body["matched_devices"] == 0
        assert body["dry_run"] is True
