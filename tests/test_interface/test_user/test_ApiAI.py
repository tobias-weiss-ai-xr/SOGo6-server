"""Functional tests for ApiAI — summarize/classify/suggest-reply/natural-search/
detect-anomaly/enrich-contact/classify-attachment with a mocked model backend.
"""
from unittest import mock

import pytest
from flask import Flask

from app.api.v1.user.ApiAI import blp

MOD = "app.api.v1.user.ApiAI"


@pytest.fixture
def model():
    with mock.patch(f"{MOD}.get_model_backend") as get_backend:
        m = get_backend.return_value
        yield m


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(blp)
    return app.test_client()


class TestSummarize:
    def test_summarize_ok(self, client, model):
        model.summarize.return_value = "Short summary."
        resp = client.post("/ai/summarize", json={"text": "A very long text."})
        assert resp.status_code == 200
        assert resp.json["data"]["summary"] == "Short summary."
        model.summarize.assert_called_once_with("A very long text.", 3)

    def test_summarize_custom_max_sentences(self, client, model):
        model.summarize.return_value = "s"
        client.post("/ai/summarize", json={"text": "T", "max_sentences": 5})
        model.summarize.assert_called_once_with("T", 5)

    def test_summarize_validation(self, client, model):
        resp = client.post("/ai/summarize", json={})
        assert resp.status_code == 422


class TestClassify:
    def test_classify_ok(self, client, model):
        model.classify.return_value = ["spam"]
        resp = client.post("/ai/classify", json={"text": "buy now"})
        assert resp.status_code == 200
        assert resp.json["data"]["labels"] == ["spam"]
        model.classify.assert_called_once_with("buy now", "", "")

    def test_classify_with_metadata(self, client, model):
        model.classify.return_value = ["ok"]
        client.post("/ai/classify", json={"text": "hi", "subject": "greeting", "sender": "a@x.org"})
        model.classify.assert_called_once_with("hi", "greeting", "a@x.org")


class TestSuggestReply:
    def test_suggest_reply_default_tone(self, client, model):
        model.suggest_reply.return_value = "Thanks!"
        resp = client.post("/ai/suggest-reply", json={"email_text": "Can you help?"})
        assert resp.status_code == 200
        assert resp.json["data"]["suggestion"] == "Thanks!"
        model.suggest_reply.assert_called_once_with("Can you help?", "professional")

    def test_suggest_reply_friendly(self, client, model):
        model.suggest_reply.return_value = "Hey!"
        client.post("/ai/suggest-reply", json={"email_text": "hi", "tone": "friendly"})
        model.suggest_reply.assert_called_once_with("hi", "friendly")

    def test_suggest_reply_invalid_tone(self, client, model):
        resp = client.post("/ai/suggest-reply", json={"email_text": "hi", "tone": "rude"})
        assert resp.status_code == 422


class TestNaturalSearch:
    def test_natural_search(self, client, model):
        model.nl_to_search.return_value = {"query": "q"}
        resp = client.post("/ai/natural-search", json={"query": "mails from bob"})
        assert resp.status_code == 200
        assert resp.json["data"] == {"query": "q"}
        model.nl_to_search.assert_called_once_with("mails from bob")

    def test_natural_search_validation(self, client, model):
        resp = client.post("/ai/natural-search", json={})
        assert resp.status_code == 422


class TestAnomaly:
    def test_anomaly_defaults(self, client, model):
        model.detect_anomaly.return_value = {"anomalous": False}
        resp = client.post("/ai/detect-anomaly", json={})
        assert resp.status_code == 200
        assert resp.json["data"] == {"anomalous": False}
        model.detect_anomaly.assert_called_once_with(
            {"recipient_count": 0, "hour": 12, "new_recipient_ratio": 0}
        )

    def test_anomaly_values(self, client, model):
        model.detect_anomaly.return_value = {"anomalous": True}
        client.post(
            "/ai/detect-anomaly",
            json={"recipient_count": 40, "hour": 3, "new_recipient_ratio": 0.9},
        )
        model.detect_anomaly.assert_called_once_with(
            {"recipient_count": 40, "hour": 3, "new_recipient_ratio": 0.9}
        )


class TestEnrich:
    def test_enrich_contact(self, client, model):
        model.extract_contact_info.return_value = {"name": "Bob"}
        resp = client.post("/ai/enrich-contact", json={"text": "Bob, bob@x.org"})
        assert resp.status_code == 200
        assert resp.json["data"] == {"name": "Bob"}
        model.extract_contact_info.assert_called_once_with("Bob, bob@x.org")

    def test_enrich_validation(self, client, model):
        resp = client.post("/ai/enrich-contact", json={})
        assert resp.status_code == 422


class TestClassifyAttachment:
    def test_classify_attachment(self, client, model):
        model.classify_attachment.return_value = {"category": "invoice"}
        resp = client.post(
            "/ai/classify-attachment",
            json={"filename": "inv.pdf", "content_type": "application/pdf"},
        )
        assert resp.status_code == 200
        assert resp.json["data"] == {"category": "invoice"}
        model.classify_attachment.assert_called_once_with("inv.pdf", "application/pdf")

    def test_classify_attachment_default_type(self, client, model):
        model.classify_attachment.return_value = {"category": "other"}
        client.post("/ai/classify-attachment", json={"filename": "x.bin"})
        model.classify_attachment.assert_called_once_with("x.bin", "")

    def test_classify_attachment_validation(self, client, model):
        resp = client.post("/ai/classify-attachment", json={})
        assert resp.status_code == 422
