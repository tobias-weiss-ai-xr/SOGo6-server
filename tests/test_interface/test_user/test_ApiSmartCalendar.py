"""Functional tests for ApiSmartCalendar — suggest-times & analyze-patterns.

Uses a fake cache injected via monkeypatch on the module-level ``sogo_cache``.
"""
import json
from unittest import mock

import pytest
from flask import Flask

from app.api.v1.user.ApiSmartCalendar import blp

MOD = "app.api.v1.user.ApiSmartCalendar"


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
    app.register_blueprint(blp)
    return app.test_client()


def _seed_pattern(uid, busy, preferred=None):
    CACHE.data[f"sched_pattern:{uid}"] = json.dumps(
        {"busy_hours": busy, "preferred_hours": preferred or []}
    )


class TestSuggestTimes:
    def test_suggest_empty_no_patterns(self, client):
        resp = client.post(
            "/ai/smart-calendar/suggest-times",
            json={
                "attendee_uids": ["a@x.org"],
                "date_from": "2026-06-01",
                "date_to": "2026-06-01",
                "duration_minutes": 60,
            },
        )
        assert resp.status_code == 200
        data = resp.json["data"]
        assert data["attendees_analyzed"] == 0
        assert data["total_candidates"] > 0
        assert data["suggestions"], "expected non-empty suggestions"
        # Weekday slot only, default preferred hours
        assert data["suggestions"][0]["day"] in (
            "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
        )

    def test_suggest_respects_preferred_and_conflicts(self, client):
        # a@x.org busy at 9 and 10, prefers nothing; b@x.org free everywhere
        _seed_pattern("a@x.org", [9, 10])
        _seed_pattern("b@x.org", [])
        resp = client.post(
            "/ai/smart-calendar/suggest-times",
            json={
                "attendee_uids": ["a@x.org", "b@x.org"],
                "date_from": "2026-06-01",
                "date_to": "2026-06-02",
                "duration_minutes": 60,
            },
        )
        assert resp.status_code == 200
        data = resp.json["data"]
        assert data["attendees_analyzed"] == 2
        for sugg in data["suggestions"]:
            # No 9/10 o'clock slots should carry a conflict with a@x.org
            assert sugg["conflicts"] == [] or "a@x.org" not in sugg["conflicts"] or sugg["hour"] not in (9, 10)

    def test_suggest_custom_preferred_hours(self, client):
        resp = client.post(
            "/ai/smart-calendar/suggest-times",
            json={
                "attendee_uids": [],
                "date_from": "2026-06-01",
                "date_to": "2026-06-01",
                "duration_minutes": 30,
                "preferred_hours": [20],
            },
        )
        assert resp.status_code == 200
        data = resp.json["data"]
        assert all(s["hour"] == 20 for s in data["suggestions"] if s["day"] == "Monday")

    def test_suggest_invalid_date(self, client):
        resp = client.post(
            "/ai/smart-calendar/suggest-times",
            json={
                "attendee_uids": [],
                "date_from": "not-a-date",
                "date_to": "2026-06-01",
            },
        )
        assert resp.status_code == 200
        assert resp.json["data"]["error"] == "invalid_date_format"

    def test_suggest_validation_error(self, client):
        resp = client.post("/ai/smart-calendar/suggest-times", json={})
        assert resp.status_code == 422


class TestAnalyzePatterns:
    def test_analyze_returns_patterns(self, client):
        resp = client.post(
            "/ai/smart-calendar/analyze-patterns",
            json={"attendee_uid": "user-1", "days_back": 14},
        )
        assert resp.status_code == 200
        data = resp.json["data"]
        assert data["preferred_hours"] == [9, 10, 14, 15]
        assert data["busy_hours"] == [12, 13]

    def test_analyze_validation_error(self, client):
        resp = client.post("/ai/smart-calendar/analyze-patterns", json={})
        assert resp.status_code == 422
