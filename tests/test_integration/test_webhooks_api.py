"""Real HTTP integration tests for Webhooks API (#41) using Flask test client."""
import json
import pytest
from app import create_app
from app.utils import constants as cs
from app.config.init_config import process_config


@pytest.fixture
def client():
    """Flask test client with a running app."""
    app = create_app(cs.SOGO_OK)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestWebhooksAPI:
    WEBHOOKS_URL = "/api/admin/v1/webhooks"

    def test_list_webhooks_empty(self, client):
        resp = client.get(self.WEBHOOKS_URL)
        assert resp.status_code == 200

    def test_create_webhook(self, client):
        data = {
            "url": "https://example.com/hook",
            "events": ["mail.received"],
            "name": "Test Webhook",
            "secret": "s3cr3t",
        }
        resp = client.post(
            self.WEBHOOKS_URL,
            data=json.dumps(data),
            content_type="application/json",
        )
        assert resp.status_code == 201
        result = resp.get_json()
        assert result["data"]["url"] == "https://example.com/hook"
        assert result["data"]["events"] == ["mail.received"]

    def test_create_and_list_webhook(self, client):
        client.post(
            self.WEBHOOKS_URL,
            data=json.dumps({"url": "https://example.com/h1", "events": ["mail.received"]}),
            content_type="application/json",
        )
        resp = client.get(self.WEBHOOKS_URL)
        data = resp.get_json()
        assert len(data["data"]["webhooks"]) == 1

    def test_create_webhook_invalid_url_fails(self, client):
        resp = client.post(
            self.WEBHOOKS_URL,
            data=json.dumps({"url": "", "events": []}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_delete_webhook(self, client):
        create_resp = client.post(
            self.WEBHOOKS_URL,
            data=json.dumps({"url": "https://example.com/hook", "events": ["mail.received"]}),
            content_type="application/json",
        )
        hook_id = create_resp.get_json()["data"]["id"]
        delete_resp = client.delete(f"{self.WEBHOOKS_URL}/{hook_id}")
        assert delete_resp.status_code == 200
        # Verify it's gone
        list_resp = client.get(self.WEBHOOKS_URL)
        assert len(list_resp.get_json()["data"]["webhooks"]) == 0

    def test_multiple_events(self, client):
        data = {"url": "https://example.com/hook", "events": ["mail.received", "mail.sent", "calendar.updated"]}
        resp = client.post(self.WEBHOOKS_URL, data=json.dumps(data), content_type="application/json")
        assert resp.status_code == 201
        assert len(resp.get_json()["data"]["events"]) == 3
