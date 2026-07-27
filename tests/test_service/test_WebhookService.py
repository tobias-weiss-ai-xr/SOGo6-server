"""Real integration tests for WebhookService using real Redis."""
import json
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
        hook = svc.add_webhook("http://localhost:19999/nonexistent", ["mail.received"])
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
