# pylint: disable=invalid-sequence-index
"""Unit tests for ApiFileSharing (47% -> high)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import json

import pytest


class FakeCache:
    """In-memory cache with str/list casts mimicking redis get(cast)."""

    def __init__(self):
        self.store = {}
        self.ttls = {}

    def get(self, key, cast=str):
        raw = self.store.get(key)
        if raw is None:
            return None
        if cast is list:
            return list(raw)
        return raw

    def set(self, key, value, ttl=0):
        self.store[key] = value
        self.ttls[key] = ttl

    def close(self):
        pass


CACHE = FakeCache()


@pytest.fixture(autouse=True)
def _reset_cache():
    CACHE.store.clear()
    CACHE.ttls.clear()
    yield


@pytest.fixture
def client():
    from flask import Flask
    from app.api.v1.admin import ApiFileSharing

    app = Flask(__name__)
    app.config["TESTING"] = True

    with mock.patch("app.api.v1.admin.ApiFileSharing.sogo_cache", return_value=CACHE):
        app.register_blueprint(ApiFileSharing.blp)
        with app.test_client() as c:
            yield c


class TestListShares:
    def test_empty(self, client):
        resp = client.get("/files/shares")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["shares"] == []

    def test_returns_shares_without_password(self, client):
        CACHE.store["file_shares:index"] = ["s1"]
        CACHE.store["file_share:s1"] = json.dumps({
            "id": "s1", "filename": "a.txt", "size": 10, "token": "t",
            "password": "secret", "downloads": 0, "expires_at": 123, "created_at": 1,
        })
        resp = client.get("/files/shares")
        data = resp.get_json()["data"]["shares"]
        assert len(data) == 1
        assert "password" not in data[0]

    def test_skips_corrupt_share(self, client):
        CACHE.store["file_shares:index"] = ["s1", "s2"]
        CACHE.store["file_share:s1"] = "{not json"
        CACHE.store["file_share:s2"] = json.dumps({"id": "s2"})
        resp = client.get("/files/shares")
        data = resp.get_json()["data"]["shares"]
        assert [s["id"] for s in data] == ["s2"]


class TestCreateShare:
    def test_create(self, client):
        resp = client.post(
            "/files/shares",
            json={"filename": "doc.pdf", "size": 2048, "expires_in_days": 3},
        )
        assert resp.status_code == 201
        data = resp.get_json()["data"]
        assert data["id"]
        assert data["token"]
        assert data["url"].startswith("/files/share/")
        assert data["expires_at"] > 0

    def test_create_requires_filename_size(self, client):
        resp = client.post("/files/shares", json={})
        assert resp.status_code == 422

    def test_create_updates_index(self, client):
        resp = client.post("/files/shares", json={"filename": "x", "size": 1})
        assert resp.status_code == 201
        assert CACHE.store["file_shares:index"] != []
