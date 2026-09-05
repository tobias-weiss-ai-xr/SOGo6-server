"""Functional tests for ApiSchedulingPolls — poll list/create, respond
(public, capability-secret) and results aggregation.

Uses a fake cache; g.user is provided via a request-context User stub.
"""
import json
from types import SimpleNamespace
from unittest import mock

import pytest
from flask import Flask, g

from app.api.v1.calendar.ApiSchedulingPolls import blp
from app.utils import errors as err


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
USER = SimpleNamespace(uid="user-1")


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    CACHE.data.clear()
    CACHE.set_calls.clear()
    monkeypatch.setattr("app.api.v1.calendar.ApiSchedulingPolls.sogo_cache", lambda: CACHE)
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


def _make_poll(poll_id="abcdef123456", participants=("a@x.org", "b@x.org"), expires_at=None,
               status="open", responses=None):
    poll = {
        "id": poll_id,
        "title": "Lunch",
        "description": "",
        "time_slots": [{"start": "2026-06-01T12:00", "end": "2026-06-01T13:00"}],
        "participants": list(participants),
        "created_by": "user-1",
        "created_at": 100,
        "expires_at": expires_at,
        "token": "tok",
        "responses": responses or [],
        "status": status,
    }
    CACHE.data[f"poll:{poll_id}"] = json.dumps(poll)
    return poll


class TestPollList:
    def test_list_empty(self, client):
        resp = client.get("/polls")
        assert resp.status_code == 200
        assert resp.json["data"]["polls"] == []

    def test_list_includes_creator_polls(self, client):
        _make_poll()
        CACHE.data["poll:index:user-1"] = ["abcdef123456"]
        resp = client.get("/polls")
        polls = resp.json["data"]["polls"]
        assert len(polls) == 1
        assert polls[0]["title"] == "Lunch"
        assert "token" in polls[0]

    def test_list_skips_malformed_poll_entries(self, client):
        CACHE.data["poll:index:user-1"] = ["bad1", "bad2"]
        CACHE.data["poll:bad1"] = "{not-json"
        CACHE.data["poll:bad2"] = None
        resp = client.get("/polls")
        assert resp.json["data"]["polls"] == []


class TestPollCreate:
    def test_create_returns_201_and_persists(self, client):
        resp = client.post("/polls", json={
            "title": "Team lunch",
            "description": "pick a day",
            "time_slots": [
                {"start": "2026-06-01T12:00", "end": "2026-06-01T13:00"},
                {"start": "2026-06-02T12:00", "end": "2026-06-02T13:00"},
            ],
            "participants": ["a@x.org", "b@x.org"],
        })
        assert resp.status_code == 201
        poll = resp.json["data"]
        assert poll["status"] == "open"
        assert poll["created_by"] == "user-1"
        assert len(poll["token"]) == 48
        # index updated
        stored_idx = CACHE.data["poll:index:user-1"]
        assert stored_idx == [poll["id"]]
        # poll persisted with 30-day ttl
        stored = json.loads(CACHE.data[f"poll:{poll['id']}"])
        assert stored["title"] == "Team lunch"
        assert stored["expires_at"] is None
        assert CACHE.set_calls and all(c[2] == 86400 * 30 for c in CACHE.set_calls[-2:])

    def test_create_appends_to_existing_index(self, client):
        _make_poll()
        CACHE.data["poll:index:user-1"] = ["abcdef123456"]
        resp = client.post("/polls", json={
            "title": "Second", "time_slots": [{"start": "S", "end": "E"}],
            "participants": ["a@x.org"],
        })
        assert resp.status_code == 201
        assert CACHE.data["poll:index:user-1"] == ["abcdef123456", resp.json["data"]["id"]]

    def test_create_requires_time_slot(self, client):
        resp = client.post("/polls", json={
            "title": "empty", "time_slots": [], "participants": ["a@x.org"],
        })
        assert resp.status_code == 422


class TestPollRespond:
    def test_respond_unknown_poll(self, client):
        resp = client.post("/polls/nope/respond", json={"participant": "a@x.org"})
        assert resp.status_code == 404
        assert resp.json["error_code"] == err.ERROR_NOT_FOUND.c

    def test_respond_closes_expired_open_poll(self, client):
        _make_poll(expires_at=1)  # already in the past
        resp = client.post("/polls/abcdef123456/respond", json={"participant": "a@x.org", "available_slots": ["0"]})
        assert resp.status_code == 400
        assert resp.json["error_code"] == err.ERROR_POLL_CLOSED.c
        # closure persisted
        assert json.loads(CACHE.data["poll:abcdef123456"])["status"] == "closed"

    def test_respond_closed_poll_returns_closed(self, client):
        _make_poll(expires_at=None, status="closed")
        resp = client.post("/polls/abcdef123456/respond", json={"participant": "a@x.org"})
        assert resp.status_code == 400
        assert resp.json["error_code"] == err.ERROR_POLL_CLOSED.c

    def test_respond_non_participant_rejected(self, client):
        _make_poll()
        resp = client.post("/polls/abcdef123456/respond", json={"participant": "outsider@x.org"})
        assert resp.status_code == 404
        assert resp.json["error_code"] == err.ERROR_POLL_PARTICIPANT_NOT_FOUND.c

    def test_respond_records_and_replaces_prior(self, client):
        _make_poll(responses=[{"participant": "a@x.org", "available_slots": ["0"], "responded_at": 1}])
        resp = client.post("/polls/abcdef123456/respond", json={"participant": "a@x.org", "available_slots": ["1"]})
        assert resp.status_code == 200
        assert resp.json["data"]["status"] == "recorded"
        stored = json.loads(CACHE.data["poll:abcdef123456"])
        assert len(stored["responses"]) == 1  # replaced, not duplicated
        assert stored["responses"][0]["available_slots"] == ["1"]


class TestPollResults:
    def test_results_unknown_poll(self, client):
        resp = client.get("/polls/nope/results")
        assert resp.status_code == 404

    def test_results_aggregates_best_slot(self, client):
        _make_poll(responses=[
            {"participant": "a@x.org", "available_slots": ["0", "1"]},
            {"participant": "b@x.org", "available_slots": ["0"]},
        ])
        resp = client.get("/polls/abcdef123456/results")
        data = resp.json["data"]
        assert data["response_count"] == 2
        assert data["participant_count"] == 2
        assert data["best_slot"] == "0"
        assert data["slot_counts"] == {"0": 2, "1": 1}

    def test_results_no_responses(self, client):
        _make_poll()
        resp = client.get("/polls/abcdef123456/results")
        data = resp.json["data"]
        assert data["response_count"] == 0
        assert data["best_slot"] is None
        assert data["slot_counts"] == {}
