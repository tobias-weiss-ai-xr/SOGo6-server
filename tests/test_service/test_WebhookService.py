"""Tests for WebhookService (#41)."""
import json
import pytest
from unittest.mock import patch, MagicMock
from app.service.webhook.WebhookService import WebhookService


@pytest.fixture
def svc():
    return WebhookService(cache=MagicMock())


class TestWebhookCRUD:
    def test_add_webhook(self, svc):
        svc.cache.get.return_value = []
        hook = svc.add_webhook("https://example.com/hook", ["mail.received"], secret="s3cr3t", name="Test")
        assert hook["url"] == "https://example.com/hook"
        assert hook["events"] == ["mail.received"]
        assert hook["secret"] == "s3cr3t"
        assert hook["name"] == "Test"
        svc.cache.set.assert_called_once()

    def test_list_webhooks_empty(self, svc):
        svc.cache.get.return_value = []
        hooks = svc.list_webhooks()
        assert hooks == []

    def test_list_webhooks_with_data(self, svc):
        svc.cache.get.return_value = [{"id": "abc", "url": "https://example.com/hook", "events": ["mail.received"], "enabled": True}]
        hooks = svc.list_webhooks()
        assert len(hooks) == 1
        assert hooks[0]["id"] == "abc"

    def test_remove_webhook_exists(self, svc):
        svc.cache.get.return_value = [{"id": "abc", "url": "https://example.com/hook", "events": ["mail.received"], "enabled": True}]
        result = svc.remove_webhook("abc")
        assert result is True

    def test_remove_webhook_not_found(self, svc):
        svc.cache.get.return_value = []
        result = svc.remove_webhook("nonexistent")
        assert result is False

    def test_dispatch_no_webhooks(self, svc):
        svc.cache.get.return_value = []
        sent = svc.dispatch("mail.received", {"subject": "Test"})
        assert sent == 0

    def test_dispatch_skips_disabled(self, svc):
        svc.cache.get.return_value = [{"id": "abc", "url": "https://example.com/hook", "events": ["mail.received"], "enabled": False}]
        sent = svc.dispatch("mail.received", {"subject": "Test"})
        assert sent == 0

    def test_dispatch_skips_unmatched_event(self, svc):
        svc.cache.get.return_value = [{"id": "abc", "url": "https://example.com/hook", "events": ["calendar.updated"], "enabled": True}]
        sent = svc.dispatch("mail.received", {"subject": "Test"})
        assert sent == 0

    @patch("app.service.webhook.WebhookService.WebhookService._send")
    def test_dispatch_sends_to_matched(self, mock_send, svc):
        mock_send.return_value = True
        svc.cache.get.return_value = [{"id": "abc", "url": "https://example.com/hook", "events": ["mail.received"], "enabled": True, "secret": ""}]
        sent = svc.dispatch("mail.received", {"subject": "Test"})
        assert sent == 1
