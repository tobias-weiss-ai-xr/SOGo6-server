"""Functional tests for ApiSpamFilter — /score, /report, /stats + the pure
heuristic scorer itself. sogo_cache is faked.
"""
import json

import pytest
from flask import Flask

from app.api.v1.user.ApiSpamFilter import blp, _compute_spam_score

MOD = "app.api.v1.user.ApiSpamFilter"


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


class TestScoreEndpoint:
    def test_score_ham(self, client):
        resp = client.post(
            "/ai/spam/score",
            json={
                "subject": "Meeting tomorrow",
                "body": "Hi, let's schedule the meeting. Regards, Bob",
                "sender": "bob@company.com",
            },
        )
        assert resp.status_code == 200
        data = resp.json["data"]
        assert data["classification"] == "ham"
        assert data["is_spam"] is False
        assert data["model"] == "heuristic"

    def test_score_spam(self, client):
        resp = client.post(
            "/ai/spam/score",
            json={
                "subject": "YOU HAVE WON!!!",
                "body": "Click here now to claim your $10 MILLION prize. "
                        "Get FREE viagra and casino bonus. Act now!",
                "sender": "n0t1f1cat10n.s3rv1ce@x.xyz",
            },
        )
        assert resp.status_code == 200
        data = resp.json["data"]
        assert data["is_spam"] is True
        assert data["classification"] == "spam"
        assert data["is_suspicious"] is False
        assert data["signals"], "expected signals to be reported"

    def test_score_validation(self, client):
        resp = client.post("/ai/spam/score", json={})
        assert resp.status_code == 422


class TestSpamScoreHeuristic:
    """Direct assertions on the pure scorer (fast + thorough)."""

    def test_benign_discounts(self):
        result = _compute_spam_score(
            subject="Weekly standup",
            body="Meeting notes attached, unsubscribe at any time. Thanks!",
            sender="a@company.com",
            has_attachments=True,
        )
        assert result["is_spam"] is False

    def test_numeric_sender_and_suspicious_tld(self):
        result = _compute_spam_score(
            subject="hi", body="hello friend", sender="12345@telegram.top"
        )
        signals = {s["signal"] for s in result["signals"]}
        assert "numeric_heavy_local" in signals
        assert any(s.startswith("suspicious_tld_") for s in signals)

    def test_high_caps_ratio(self):
        result = _compute_spam_score(
            subject="REMINDER", body="THIS IS A REMINDER THAT PAYMENT IS DUE NOW.", sender=""
        )
        assert any(s["signal"] == "high_caps_ratio" for s in result["signals"])

    def test_excessive_links(self):
        body = " ".join(["https://example.com/page" for _ in range(8)])
        result = _compute_spam_score(subject="links", body=body, sender="")
        assert any(s["signal"] == "excessive_links" for s in result["signals"])

    def test_score_clamped_0_10(self):
        result = _compute_spam_score(
            subject="URGENT ACTION REQUIRED!! YOU WON $1 MILLION CASINO LOTTERY",
            body="Click here immediately, act now, wire transfer $10 million. " * 5,
            sender="",
        )
        assert 0.0 <= result["score"] <= 10.0


class TestReport:
    def test_report_with_sender(self, client):
        resp = client.post(
            "/ai/spam/report",
            json={"message_id": "m1", "is_spam": True, "sender": "spam@x.xyz"},
        )
        assert resp.status_code == 200
        assert resp.json["data"]["status"] == "recorded"
        assert "spam:report:m1" in CACHE.data
        stats = json.loads(CACHE.data["spam:stats:spam@x.xyz"])
        assert stats == {"total": 1, "spam": 1}

    def test_report_ham_updates_stats(self, client):
        CACHE.data["spam:stats:a@x.org"] = json.dumps({"total": 5, "spam": 3})
        resp = client.post(
            "/ai/spam/report",
            json={"message_id": "m2", "is_spam": False, "sender": "a@x.org"},
        )
        assert resp.status_code == 200
        stats = json.loads(CACHE.data["spam:stats:a@x.org"])
        assert stats == {"total": 6, "spam": 3}

    def test_report_without_sender(self, client):
        resp = client.post("/ai/spam/report", json={"message_id": "m3", "is_spam": False})
        assert resp.status_code == 200
        assert "spam:report:m3" in CACHE.data

    def test_report_validation(self, client):
        resp = client.post("/ai/spam/report", json={})
        assert resp.status_code == 422


class TestStats:
    def test_stats_defaults(self, client):
        resp = client.get("/ai/spam/stats")
        assert resp.status_code == 200
        data = resp.json["data"]
        assert data["total_scored"] == 0
        assert data["classified_spam"] == 0

    def test_stats_stored(self, client):
        CACHE.data["spam:global_stats"] = json.dumps(
            {"total_scored": 42, "classified_spam": 10, "classified_ham": 30,
             "classified_suspicious": 2, "false_positive_reports": 1}
        )
        resp = client.get("/ai/spam/stats")
        assert resp.status_code == 200
        assert resp.json["data"]["total_scored"] == 42
