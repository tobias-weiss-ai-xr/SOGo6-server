"""Functional tests for ApiMigration (migration history / sources / start / detail / cancel).

All endpoints are backed by the shared sogo_cache; this suite exercises the full
job lifecycle including cache-miss, prepend-with-cap and not-found error paths.
"""
import json
import re
from unittest import mock

import pytest
from flask import Flask

from app.api.v1.admin.ApiMigration import blp
from app.utils.api.ApiBaseResponse import create_api_base_response


class FakeCache:
    def __init__(self):
        self.data = {}
        self.set_calls = []

    def get(self, key, as_type=None):
        return self.data.get(key)

    def set(self, key, value, ttl=None):
        self.set_calls.append((key, value, ttl))
        self.data[key] = value


CACHE = FakeCache()


@pytest.fixture(autouse=True)
def _reset_and_patch_cache():
    CACHE.data.clear()
    CACHE.set_calls.clear()
    with mock.patch("app.api.v1.admin.ApiMigration.sogo_cache", return_value=CACHE):
        yield


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(blp)
    return app.test_client()


@pytest.fixture
def seeded_history():
    CACHE.data["migration:history"] = json.dumps([
        {
            "id": "abc12345",
            "source": "dovecot",
            "user_uid": "u1",
            "status": "running",
            "started_at": 100.0,
            "completed_at": None,
            "items_migrated": 12,
            "items_failed": 1,
            "details": "Migration from dovecot for user u1",
        }
    ])


class TestMigrationHistory:
    def test_history_empty(self, client):
        resp = client.get("/migration/history")
        assert resp.status_code == 200
        assert resp.json["data"]["entries"] == []

    def test_history_with_entries(self, client, seeded_history):
        resp = client.get("/migration/history")
        entries = resp.json["data"]["entries"]
        assert len(entries) == 1
        assert entries[0]["id"] == "abc12345"
        assert entries[0]["status"] == "running"


class TestMigrationSources:
    def test_sources_listed(self, client):
        resp = client.get("/migration/sources")
        assert resp.status_code == 200
        sources = resp.json["data"]["sources"]
        ids = [s["id"] for s in sources]
        assert ids == ["gsuite", "m365", "dovecot", "cyrus", "mbox", "csv"]
        gsuite = next(s for s in sources if s["id"] == "gsuite")
        assert gsuite["fields"] == ["client_id", "client_secret", "refresh_token"]
        assert any(s["fields"] == [] for s in sources)


class TestMigrationStart:
    def test_start_creates_pending_job(self, client):
        resp = client.post(
            "/migration/start",
            json={"source": "dovecot", "user_uid": "user@example.org", "options": {"host": "imap"}},
        )
        assert resp.status_code == 200
        entry = resp.json["data"]
        assert re.fullmatch(r"[0-9a-f]{8}", entry["id"])
        assert entry["source"] == "dovecot"
        assert entry["user_uid"] == "user@example.org"
        assert entry["status"] == "pending"
        assert entry["completed_at"] is None
        assert entry["items_migrated"] == 0
        assert entry["items_failed"] == 0
        assert "dovecot" in entry["details"]
        # persisted to cache with 90-day ttl
        assert CACHE.set_calls[-1][0] == "migration:history"
        assert CACHE.set_calls[-1][2] == 86400 * 90
        stored = json.loads(CACHE.data["migration:history"])
        assert stored[0]["id"] == entry["id"]

    def test_start_prepends_new_job(self, client, seeded_history):
        client.post("/migration/start", json={"source": "mbox", "user_uid": "u2"})
        stored = json.loads(CACHE.data["migration:history"])
        assert len(stored) == 2
        assert stored[0]["source"] == "mbox"
        assert stored[1]["id"] == "abc12345"

    def test_start_caps_history_at_50(self, client):
        for i in range(55):
            client.post("/migration/start", json={"source": "csv", "user_uid": f"u{i}"})
        stored = json.loads(CACHE.data["migration:history"])
        assert len(stored) == 50
        assert stored[0]["user_uid"] == "u54"
        assert stored[-1]["user_uid"] == "u5"

    def test_start_requires_source_and_user(self, client):
        resp = client.post("/migration/start", json={})
        assert resp.status_code == 422


class TestMigrationDetail:
    def test_detail_found(self, client, seeded_history):
        resp = client.get("/migration/abc12345")
        assert resp.status_code == 200
        assert resp.json["data"]["id"] == "abc12345"
        assert resp.json["data"]["status"] == "running"

    def test_detail_not_found(self, client):
        resp = client.get("/migration/doesnotexist")
        assert resp.status_code == 404
        assert resp.json["error_code"] == "S000490"


class TestMigrationCancel:
    def test_cancel_found(self, client, seeded_history):
        resp = client.post("/migration/abc12345/cancel")
        assert resp.status_code == 200
        entry = resp.json["data"]
        assert entry["status"] == "cancelled"
        assert entry["completed_at"] is not None
        stored = json.loads(CACHE.data["migration:history"])
        assert stored[0]["status"] == "cancelled"

    def test_cancel_not_found(self, client):
        resp = client.post("/migration/xyz/cancel")
        assert resp.status_code == 404
        assert resp.json["error_code"] == "S000490"
