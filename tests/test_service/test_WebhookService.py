"""Real integration tests for WebhookService using real Redis."""
import json
import time

import pytest

from app.service.webhook.WebhookService import WebhookService


@pytest.fixture
def svc(real_cache):
    return WebhookService(cache=real_cache)


class TestWebhookCRUD:
    def test_add_webhook(self, svc):
        hook = svc.add_webhook("https://example.com/hook", ["mail.received"], secret="s3cr3t", name="Test Hook")
        assert hook["url"] == "https://example.com/hook"
        assert hook["events"] == ["mail.received"]
        assert hook["secret"] == "s3cr3t"
        assert hook["name"] == "Test Hook"
        assert hook["enabled"] is True
        assert "id" in hook

    def test_list_webhooks_empty(self, svc):
        hooks = svc.list_webhooks()
        assert hooks == []

    def test_list_webhooks_after_add(self, svc):
        svc.add_webhook("https://example.com/hook1", ["mail.received"])
        svc.add_webhook("https://example.com/hook2", ["calendar.updated"])
        hooks = svc.list_webhooks()
        assert len(hooks) == 2

    def test_remove_webhook(self, svc):
        hook = svc.add_webhook("https://example.com/hook", ["mail.received"])
        assert svc.remove_webhook(hook["id"]) is True
        assert svc.list_webhooks() == []

    def test_remove_nonexistent(self, svc):
        assert svc.remove_webhook("nonexistent") is False

    def test_dispatch_no_webhooks(self, svc):
        sent = svc.dispatch("mail.received", {"subject": "Test"})
        assert sent == 0

    def test_dispatch_disabled_webhook(self, svc):
        _ = svc.add_webhook("http://localhost:19999/nonexistent", ["mail.received"])
        # Manually disable
        hooks = svc.list_webhooks()
        hooks[0]["enabled"] = False
        svc.save_webhooks(hooks)
        sent = svc.dispatch("mail.received", {"subject": "Test"})
        assert sent == 0

    def test_persistence_across_instances(self, svc):
        svc.add_webhook("https://persist-test.com/hook", ["mail.received"])
        svc2 = WebhookService(cache=svc.cache)
        hooks = svc2.list_webhooks()
        assert len(hooks) == 1
        assert hooks[0]["url"] == "https://persist-test.com/hook"

    def test_multiple_events_same_webhook(self, svc):
        hook = svc.add_webhook("https://example.com/hook", ["mail.received", "mail.sent", "calendar.updated"])
        assert len(hook["events"]) == 3


class FakeUrlResponse:
    def __init__(self, status=200):
        self.status = status


class TestWebhookDelivery:
    def _capture(self, monkeypatch):
        calls = {}

        def fake_urlopen(req, timeout=10):
            calls["url"] = req.full_url
            calls["headers"] = {k: v for k, v in req.header_items()}
            calls["body"] = req.data.decode() if req.data else ""
            calls["timeout"] = timeout
            return FakeUrlResponse(200)

        monkeypatch.setattr("app.service.webhook.WebhookService.urllib.request.urlopen", fake_urlopen)
        return calls

    def test_dispatch_sync_delivers_and_records_stats(self, svc, monkeypatch):
        calls = self._capture(monkeypatch)
        hook = svc.add_webhook("https://example.com/hook", ["mail.received"], secret="s3cr3t")
        events = svc.dispatch("mail.received", {"subject": "Hello"})

        assert events == 1
        assert calls["url"] == "https://example.com/hook"
        body = json.loads(calls["body"])
        assert body["event"] == "mail.received"
        assert body["data"] == {"subject": "Hello"}
        assert calls["timeout"] == 10
        lower = {k.lower(): v for k, v in calls["headers"].items()}
        assert "x-signature-256" in lower
        assert "x-sogo-webhook" in lower

        stored = svc.get_webhook(hook["id"])
        assert stored["last_status"] == 200
        assert stored["delivery_count"] == 1
        assert stored["success_count"] == 1

    def test_events_mismatched_not_delivered(self, svc, monkeypatch):
        calls = self._capture(monkeypatch)
        _ = svc.add_webhook("https://example.com/hook", ["calendar.updated"])
        n = svc.dispatch("mail.received", {})
        assert n == 0
        assert "url" not in calls

    def test_async_dispatch_does_not_block_and_matches(self, svc, monkeypatch):
        calls = self._capture(monkeypatch)
        svc.add_webhook("https://example.com/hook", ["contact.created"])
        matched = svc.dispatch_event("contact.created", {"uid": "u1"})
        assert matched == 1
        # give the daemon thread a moment to deliver
        for _ in range(100):
            if calls.get("url"):
                break
            time.sleep(0.02)
        assert calls["url"] == "https://example.com/hook"


class TestWebhookUpdate:
    def test_update_fields_and_toggle(self, svc):
        hook = svc.add_webhook("https://example.com/hook", ["mail.received"], secret="a")
        updated = svc.update_webhook(hook["id"], enabled=False, secret="b", events=["calendar.deleted"])
        assert updated is not None
        assert updated["enabled"] is False
        assert updated["secret"] == "b"
        assert updated["events"] == ["calendar.deleted"]
        assert svc.get_webhook(hook["id"])["enabled"] is False

    def test_update_missing_hook_returns_none(self, svc):
        assert svc.update_webhook("does-not-exist", enabled=False) is None

    def test_invalid_url_scheme_rejected(self, svc):
        import pytest as _pytest
        with _pytest.raises(ValueError):
            svc.add_webhook("ftp://example.com/hook", ["mail.received"])
        with _pytest.raises(ValueError):
            svc.add_webhook("javascript:alert(1)", ["mail.received"])
