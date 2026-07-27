"""Webhook System (#41) — outbound webhooks for n8n/Make/automation.

Events trigger HTTP POST requests to configured URLs with JSON payloads.
Supports:
- Secret-based HMAC signing
- Retry with exponential backoff
- Event filtering by type
- Per-webhook enable/disable
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.request
from typing import Any, Callable

from app.service import sogo_cache
from app.utils.logger.logger import logger_api

_WEBHOOK_PREFIX: str = "webhook:"
_WEBHOOK_CONFIG_KEY: str = "webhook:config"
_MAX_RETRIES: int = 3
_RETRY_DELAYS: list[int] = [5, 30, 120]  # seconds


class WebhookService:
    """Manages webhook subscriptions and dispatches events."""

    def __init__(self, cache=None):
        self.cache = cache or sogo_cache()

    def list_webhooks(self) -> list[dict]:
        """List all configured webhooks."""
        raw = self.cache.get(_WEBHOOK_CONFIG_KEY, list)
        return list(raw) if isinstance(raw, list) else []

    def save_webhooks(self, webhooks: list[dict]) -> None:
        """Persist webhook list."""
        self.cache.set(_WEBHOOK_CONFIG_KEY, webhooks, ttl=86400 * 365)

    def add_webhook(self, url: str, events: list[str], secret: str = "", name: str = "") -> dict:
        """Register a new webhook."""
        webhooks = self.list_webhooks()
        hook = {
            "id": hashlib.sha256(f"{url}:{time.time()}".encode()).hexdigest()[:16],
            "name": name or url,
            "url": url,
            "events": events,
            "secret": secret,
            "enabled": True,
            "created_at": int(time.time()),
        }
        webhooks.append(hook)
        self.save_webhooks(webhooks)
        logger_api.info("Webhook added: %s (%d events)", url, len(events))
        return hook

    def remove_webhook(self, hook_id: str) -> bool:
        """Remove a webhook by ID."""
        webhooks = self.list_webhooks()
        filtered = [h for h in webhooks if h.get("id") != hook_id]
        if len(filtered) == len(webhooks):
            return False
        self.save_webhooks(filtered)
        logger_api.info("Webhook removed: %s", hook_id)
        return True

    def dispatch(self, event: str, payload: dict) -> int:
        """Send an event to all subscribed webhooks.

        :param event: Event type (e.g. "mail.received", "calendar.updated")
        :param payload: Event data
        :return: Number of successful deliveries
        """
        webhooks = self.list_webhooks()
        sent = 0
        body = json.dumps({
            "event": event,
            "timestamp": int(time.time()),
            "data": payload,
        })

        for hook in webhooks:
            if not hook.get("enabled"):
                continue
            if hook.get("events") and event not in hook["events"]:
                continue

            url = hook.get("url", "")
            secret = hook.get("secret", "")
            if not url:
                continue

            if self._send(url, body, secret):
                sent += 1

        logger_api.info("Webhook %s: %d/%d delivered", event, sent, len(webhooks))
        return sent

    def _send(self, url: str, body: str, secret: str) -> bool:
        """Send a webhook with retry logic."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "SOGo6-Webhook/1.0",
        }
        if secret:
            signature = hmac.new(
                secret.encode(), body.encode(), hashlib.sha256
            ).hexdigest()
            headers["X-Signature-256"] = signature

        for attempt in range(_MAX_RETRIES):
            try:
                req = urllib.request.Request(url, data=body.encode(), headers=headers, method="POST")
                resp = urllib.request.urlopen(req, timeout=10)
                if resp.status < 300:
                    return True
                logger_api.warning("Webhook %s returned HTTP %d (attempt %d)", url[:30], resp.status, attempt + 1)
            except Exception as e:
                logger_api.warning("Webhook %s failed (attempt %d): %s", url[:30], attempt + 1, e)
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAYS[attempt] if attempt < len(_RETRY_DELAYS) else 60)
        return False
