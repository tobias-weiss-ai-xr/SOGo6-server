"""Functional tests for ApiCollaborativeDrafts — list/create/review shared draft
emails, backed by a fake cache.
"""
import json
from types import SimpleNamespace
from unittest import mock

import pytest
from flask import Flask, g

from app.api.v1.mail.ApiCollaborativeDrafts import blp
from app.utils import errors as err

MOD = "app.api.v1.mail.ApiCollaborativeDrafts"

USER = SimpleNamespace(uid="user-1")


class FakeCache:
    def __init__(self):
        self.data = {}
        self.sets = []

    def get(self, key, as_type=None):
        return self.data.get(key)

    def set(self, key, value, ttl=None):
        self.sets.append((key, value, ttl))
        self.data[key] = value


CACHE = FakeCache()


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    CACHE.data.clear()
    CACHE.sets.clear()
    monkeypatch.setattr(f"{MOD}.sogo_cache", lambda: CACHE)
    yield


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.before_request
    def _set_user():
        g.user = USER

    app.register_blueprint(blp)
    return app.test_client()


def _seed_draft(draft_id, subject="Review me", recipients=None):
    draft = {
        "id": draft_id,
        "subject": subject,
        "body": "body",
        "author": "user-1",
        "recipients": recipients or ["r@x.org"],
        "message": "",
        "share_token": "tok",
        "status": "pending",
        "reviews": [],
        "created_at": 100,
    }
    CACHE.data[f"shared_draft:{draft_id}"] = json.dumps(draft)
    return draft


class TestList:
    def test_list_empty(self, client):
        resp = client.get("/shared-drafts")
        assert resp.status_code == 200
        assert resp.json["data"]["drafts"] == []

    def test_list_returns_drafts(self, client):
        _seed_draft("abc")
        _seed_draft("def", subject="Second")
        idx = ["abc", "def"]
        CACHE.data["shared_draft:index:user-1"] = idx
        resp = client.get("/shared-drafts")
        assert resp.status_code == 200
        titles = [d["subject"] for d in resp.json["data"]["drafts"]]
        assert titles == ["Review me", "Second"]

    def test_list_skips_corrupt_entries(self, client):
        CACHE.data["shared_draft:index:user-1"] = ["good", "broken"]
        _seed_draft("good")
        CACHE.data["shared_draft:broken"] = "{not json"
        resp = client.get("/shared-drafts")
        assert resp.status_code == 200
        assert [d["id"] for d in resp.json["data"]["drafts"]] == ["good"]


class TestCreate:
    def test_create_ok(self, client):
        resp = client.post(
            "/shared-drafts",
            json={"subject": "Review", "body": "Hi", "recipients": ["r@x.org"], "message": "pls"},
        )
        assert resp.status_code == 201
        data = resp.json["data"]
        assert data["subject"] == "Review"
        assert data["author"] == "user-1"
        assert data["recipients"] == ["r@x.org"]
        assert data["status"] == "pending"
        assert data["reviews"] == []
        assert data["share_token"]
        # persisted: draft + index
        assert f"shared_draft:{data['id']}" in CACHE.data
        assert "shared_draft:index:user-1" in CACHE.data

    def test_create_validation(self, client):
        resp = client.post("/shared-drafts", json={"subject": "x"})
        assert resp.status_code == 422


class TestReview:
    def test_review_ok(self, client):
        _seed_draft("abc")
        resp = client.post(
            "/shared-drafts/abc/review",
            json={"reviewer": "r@x.org", "comment": "looks good", "approved": True},
        )
        assert resp.status_code == 200
        assert resp.json["data"]["status"] == "review_recorded"
        stored = json.loads(CACHE.data["shared_draft:abc"])
        assert stored["reviews"][0]["reviewer"] == "r@x.org"
        assert stored["reviews"][0]["approved"] is True

    def test_review_not_found(self, client):
        resp = client.post(
            "/shared-drafts/nope/review",
            json={"reviewer": "r@x.org", "approved": False},
        )
        assert resp.status_code == err.ERROR_NOT_FOUND.h
        assert resp.json["error_code"] == err.ERROR_NOT_FOUND.c

    def test_review_validation(self, client):
        resp = client.post("/shared-drafts/abc/review", json={})
        assert resp.status_code == 422
