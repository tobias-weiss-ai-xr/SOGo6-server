"""Functional tests for ApiTranscripts — list/create/detail/summary plus the
pure summary/action-item extractors. sogo_cache is faked, g.user logged in.
"""
import json
from types import SimpleNamespace

import pytest
from flask import Flask, g

from app.api.v1.user.ApiTranscripts import (
    blp,
    _extract_action_items,
    _extract_summary,
)
from app.utils import errors as err

MOD = "app.api.v1.user.ApiTranscripts"

USER = SimpleNamespace(uid="user-1")


class FakeCache:
    def __init__(self):
        self.data = {}

    def get(self, key, as_type=None):
        return self.data.get(key)

    def set(self, key, value, ttl=None):
        self.data[key] = value


CACHE = FakeCache()


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    CACHE.data.clear()
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


def _seed_transcript(tid="abc123", text="We need to ship it. What's the deadline? Follow up on the API."):
    tr = {
        "id": tid,
        "event_id": "",
        "title": "Planning",
        "text": text,
        "summary": "summary",
        "action_items": [],
        "language": "en",
        "duration_minutes": 60,
        "attendees": ["a@x.org", "b@x.org"],
        "created_by": "user-1",
        "created_at": 100,
    }
    CACHE.data[f"transcript:{tid}"] = json.dumps(tr)
    return tr


class TestExtractSummary:
    def test_short_text_kept(self):
        text = "One. Two. Three."
        assert _extract_summary(text) == text

    def test_long_text_scores_action_items_first(self):
        text = (
            "We should fix the bug next week. " * 3
            + "Also, follow up on the invoice, then what about the logo? " * 3
            + "Random filler sentence number one. " * 6
        )
        out = _extract_summary(text, max_lines=4)
        assert len(out.split(". ")) <= 5
        assert "fix the bug" in out or "follow up" in out


class TestExtractActionItems:
    def test_extracts_declarative_actions(self):
        items = _extract_action_items(
            "I should call the client tomorrow. We need to review the PR. TODO: write docs."
        )
        assert len(items) >= 2
        assert all(i["type"] == "action_item" for i in items)

    def test_no_action_items(self):
        assert _extract_action_items("The weather is nice today. The sky is blue.") == []


class TestList:
    def test_list_empty(self, client):
        resp = client.get("/ai/transcripts")
        assert resp.status_code == 200
        assert resp.json["data"]["transcripts"] == []

    def test_list_returns_transcripts(self, client):
        _seed_transcript("abc")
        _seed_transcript("def")
        CACHE.data["transcript:index:user-1"] = ["abc", "def"]
        resp = client.get("/ai/transcripts")
        assert resp.status_code == 200
        assert [t["id"] for t in resp.json["data"]["transcripts"]] == ["abc", "def"]

    def test_list_skips_corrupt(self, client):
        CACHE.data["transcript:index:user-1"] = ["abc", "broken"]
        _seed_transcript("abc")
        CACHE.data["transcript:broken"] = "{oops"
        resp = client.get("/ai/transcripts")
        assert resp.status_code == 200
        assert [t["id"] for t in resp.json["data"]["transcripts"]] == ["abc"]


class TestCreate:
    def test_create_ok(self, client):
        resp = client.post(
            "/ai/transcripts",
            json={
                "event_id": "evt-1",
                "title": "Planning",
                "text": "We should finalize the roadmap. What about the budget?",
                "duration_minutes": 45,
                "attendees": ["a@x.org"],
            },
        )
        assert resp.status_code == 201
        data = resp.json["data"]
        assert data["title"] == "Planning"
        assert data["created_by"] == "user-1"
        assert data["duration_minutes"] == 45
        assert data["attendees"] == ["a@x.org"]
        assert data["summary"]
        assert data["action_items"], "text contains action triggers"
        assert f"transcript:{data['id']}" in CACHE.data
        assert "transcript:index:user-1" in CACHE.data

    def test_create_minimal_body(self, client):
        resp = client.post("/ai/transcripts", json={"title": "T", "text": "Just notes."})
        assert resp.status_code == 201
        data = resp.json["data"]
        assert data["language"] == "en"
        assert data["duration_minutes"] == 60
        assert data["attendees"] == []

    def test_create_validation(self, client):
        resp = client.post("/ai/transcripts", json={"title": "x"})
        assert resp.status_code == 422


class TestDetail:
    def test_detail_ok(self, client):
        _seed_transcript("abc")
        resp = client.get("/ai/transcripts/abc")
        assert resp.status_code == 200
        assert resp.json["data"]["title"] == "Planning"

    def test_detail_not_found(self, client):
        resp = client.get("/ai/transcripts/nope")
        assert resp.status_code == err.ERROR_NOT_FOUND.h
        assert resp.json["error_code"] == err.ERROR_NOT_FOUND.c


class TestSummary:
    def test_summary_ok(self, client):
        _seed_transcript(
            "abc",
            text="We should fix the bug. I will send the report tomorrow. Any questions?",
        )
        resp = client.get("/ai/transcripts/abc/summary")
        assert resp.status_code == 200
        data = resp.json["data"]
        assert data["transcript_id"] == "abc"
        assert data["summary"]
        assert data["attendee_count"] == 2
        assert data["duration_minutes"] == 60

    def test_summary_not_found(self, client):
        resp = client.get("/ai/transcripts/nope/summary")
        assert resp.status_code == err.ERROR_NOT_FOUND.h
        assert resp.json["error_code"] == err.ERROR_NOT_FOUND.c
