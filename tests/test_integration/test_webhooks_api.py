"""Real HTTP integration tests for Webhooks API (#41) with JWT auth."""
import json
import pytest


class TestWebhooksAPI:
    WEBHOOKS_URL = "/api/admin/v1/webhooks"

    def test_list_webhooks_empty(self, client, auth_headers):
        resp = client.get(self.WEBHOOKS_URL, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["error_code"] == "S000000"

    def test_create_webhook(self, client, auth_headers):
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
            headers=auth_headers,
        )
        assert resp.status_code == 201
        result = resp.get_json()
        assert result["data"]["url"] == "https://example.com/hook"
        assert result["data"]["events"] == ["mail.received"]

    def test_create_and_list_webhook(self, client, auth_headers):
        client.post(
            self.WEBHOOKS_URL,
            data=json.dumps({"url": "https://example.com/h1", "events": ["mail.received"]}),
            content_type="application/json",
            headers=auth_headers,
        )
        resp = client.get(self.WEBHOOKS_URL, headers=auth_headers)
        data = resp.get_json()
        assert len(data["data"]["webhooks"]) == 1

    def test_create_webhook_invalid_data(self, client, auth_headers):
        resp = client.post(
            self.WEBHOOKS_URL,
            data=json.dumps({"events": []}),
            content_type="application/json",
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_delete_webhook(self, client, auth_headers):
        create_resp = client.post(
            self.WEBHOOKS_URL,
            data=json.dumps({"url": "https://example.com/hook", "events": ["mail.received"]}),
            content_type="application/json",
            headers=auth_headers,
        )
        hook_id = create_resp.get_json()["data"]["id"]
        delete_resp = client.delete(f"{self.WEBHOOKS_URL}/{hook_id}", headers=auth_headers)
        assert delete_resp.status_code == 200
        list_resp = client.get(self.WEBHOOKS_URL, headers=auth_headers)
        assert len(list_resp.get_json()["data"]["webhooks"]) == 0

    def test_multiple_events(self, client, auth_headers):
        data = {"url": "https://example.com/hook", "events": ["mail.received", "mail.sent", "calendar.updated"]}
        resp = client.post(self.WEBHOOKS_URL, data=json.dumps(data), content_type="application/json", headers=auth_headers)
        assert resp.status_code == 201
        assert len(resp.get_json()["data"]["events"]) == 3

    def test_unauthorized_without_token(self, client):
        resp = client.get(self.WEBHOOKS_URL)
        assert resp.status_code == 401
