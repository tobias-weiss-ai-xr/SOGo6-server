"""API tests for the webhook management endpoints.

Covers the full lifecycle now that detail/update/test endpoints exist:
create, list, detail, patch (toggle/fields), test delivery, delete — plus
the URL-scheme validation gate.  Uses a fake-admin client (SOGO_NOT_INIT so
no database is touched) and the real Redis cache the service persists to.
"""
from __future__ import annotations

import json

import pytest

from app import create_app
from app.service import sogo_cache
from app.utils import constants as cs

WEBHOOKS_BASE = "/api/admin/v1/webhooks"


@pytest.fixture()
def authed_client(monkeypatch):
    from app.auth.Admin import Admin

    app = create_app(cs.SOGO_NOT_INIT)
    app.config["TESTING"] = True

    monkeypatch.setattr("app.VoucherAdminService.__init__", lambda self, ps: None)
    monkeypatch.setattr(
        "app.VoucherAdminService.generate_admin_from_voucher",
        staticmethod(lambda token: Admin("smoke-admin")),
    )
    client = app.test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = "Bearer test-token"
    return client


@pytest.fixture()
def clean_hooks():
    cache = sogo_cache()
    cache.set("webhook:config", [], ttl=60)
    try:
        yield
    finally:
        cache.set("webhook:config", [], ttl=60)


def _create(authed_client, url="https://example.com/hook", events=None, secret="s3"):
    resp = authed_client.post(
        WEBHOOKS_BASE,
        json={"url": url, "events": events or ["mail.received"], "secret": secret, "name": "n"},
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["data"]


class TestWebhookApiLifecycle:
    def test_create_list_detail_delete(self, authed_client, clean_hooks):
        hook = _create(authed_client)
        hook_id = hook["id"]

        listed = authed_client.get(WEBHOOKS_BASE).get_json()["data"]["webhooks"]
        assert [h["id"] for h in listed] == [hook_id]

        detail = authed_client.get(f"{WEBHOOKS_BASE}/{hook_id}").get_json()["data"]
        assert detail["url"] == "https://example.com/hook"
        assert detail["enabled"] is True

        missing = authed_client.get(f"{WEBHOOKS_BASE}/nope")
        assert missing.status_code == 404

        deleted = authed_client.delete(f"{WEBHOOKS_BASE}/{hook_id}")
        assert deleted.get_json()["data"]["status"] == "deleted"
        assert authed_client.get(WEBHOOKS_BASE).get_json()["data"]["webhooks"] == []

    def test_patch_toggle_and_update(self, authed_client, clean_hooks):
        hook = _create(authed_client)
        patched = authed_client.patch(
            f"{WEBHOOKS_BASE}/{hook['id']}",
            json={"enabled": False, "secret": "new-secret", "events": ["calendar.deleted"]},
        )
        assert patched.status_code == 200, patched.get_data(as_text=True)
        body = patched.get_json()["data"]
        assert body["enabled"] is False
        assert body["events"] == ["calendar.deleted"]

        # re-enabled and detail reflects it
        authed_client.patch(f"{WEBHOOKS_BASE}/{hook['id']}", json={"enabled": True})
        detail = authed_client.get(f"{WEBHOOKS_BASE}/{hook['id']}").get_json()["data"]
        assert detail["enabled"] is True

    def test_invalid_url_scheme_rejected(self, authed_client, clean_hooks):
        resp = authed_client.post(
            WEBHOOKS_BASE,
            json={"url": "ftp://example.com/hook", "events": ["mail.received"]},
        )
        assert resp.status_code == 400
        assert resp.get_json()["error_code"] in {"S000300", "E000005"} or "http" in json.dumps(resp.get_json())

    def test_test_endpoint_delivers_and_records_stats(self, authed_client, clean_hooks, monkeypatch):
        import app.service.webhook.WebhookService as wsvc

        calls = {}

        class FakeUrlResponse:
            status = 200

        def fake_urlopen(req, timeout=10):
            calls["url"] = req.full_url
            calls["body"] = req.data.decode() if req.data else ""
            return FakeUrlResponse()

        monkeypatch.setattr(wsvc.urllib.request, "urlopen", fake_urlopen)

        hook = _create(authed_client, events=["calendar.updated"])
        resp = authed_client.post(
            f"{WEBHOOKS_BASE}/{hook['id']}",
            json={"event": "calendar.updated"},
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()["data"]
        assert body["delivered"] is True
        assert calls["url"] == "https://example.com/hook"
        payload = json.loads(calls["body"])
        assert payload["data"]["test"] is True

        detail = authed_client.get(f"{WEBHOOKS_BASE}/{hook['id']}").get_json()["data"]
        assert detail["delivery_count"] == 1
        assert detail["last_status"] == 200