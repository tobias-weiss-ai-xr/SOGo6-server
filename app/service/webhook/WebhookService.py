"""Webhook System (#41) — outbound webhooks for n8n/Make/automation.

Events trigger HTTP POST requests to configured URLs with JSON payloads.
Supports:
- Secret-based HMAC signing (X-Signature-256)
- Retry with exponential backoff (foreground ``dispatch`` for scripts,
  background daemon threads for ``dispatch_event`` — never blocks a request)
- Event filtering by type
- Per-webhook enable/disable
- Delivery stats (last status, timestamps, counters) surfaced by the API
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import urllib.parse
import urllib.request

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

    # ------------------------------------------------------------------ #
    # persistence helpers
    # ------------------------------------------------------------------ #

    def list_webhooks(self) -> list[dict]:
        """List all configured webhooks."""
        raw = self.cache.get(_WEBHOOK_CONFIG_KEY, list)
        return list(raw) if isinstance(raw, list) else []

    def save_webhooks(self, webhooks: list[dict]) -> None:
        """Persist webhook list."""
        self.cache.set(_WEBHOOK_CONFIG_KEY, webhooks, ttl=86400 * 365)

    def get_webhook(self, hook_id: str) -> dict | None:
        """Return one webhook (with delivery stats) or None."""
        for hook in self.list_webhooks():
            if hook.get("id") == hook_id:
                return hook
        return None

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #

    def add_webhook(self, url: str, events: list[str], secret: str = "", name: str = "") -> dict:
        """Register a new webhook."""
        if not self._validate_url(url):
            raise ValueError(f"Webhook URL is not http(s): {url!r}")
        webhooks = self.list_webhooks()
        hook = {
            "id": hashlib.sha256(f"{url}:{time.time()}".encode()).hexdigest()[:16],
            "name": name or url,
            "url": url,
            "events": events,
            "secret": secret,
            "enabled": True,
            "created_at": int(time.time()),
            "delivery_count": 0,
            "success_count": 0,
            "last_status": None,
            "last_attempted_at": None,
        }
        webhooks.append(hook)
        self.save_webhooks(webhooks)
        logger_api.info("Webhook added: %s (%d events)", url, len(events))
        return hook

    def update_webhook(self, hook_id: str, url: str | None = None, events: list[str] | None = None,
                       secret: str | None = None, name: str | None = None,
                       enabled: bool | None = None) -> dict | None:
        """Update mutable fields of an existing webhook; return updated hook or None."""
        webhooks = self.list_webhooks()
        for hook in webhooks:
            if hook.get("id") != hook_id:
                continue
            if url is not None:
                if not self._validate_url(url):
                    raise ValueError(f"Webhook URL is not http(s): {url!r}")
                hook["url"] = url
            if events is not None:
                hook["events"] = events
            if secret is not None:
                hook["secret"] = secret
            if name is not None:
                hook["name"] = name
            if enabled is not None:
                hook["enabled"] = bool(enabled)
            self.save_webhooks(webhooks)
            return hook
        return None

    def remove_webhook(self, hook_id: str) -> bool:
        """Remove a webhook by ID."""
        webhooks = self.list_webhooks()
        filtered = [h for h in webhooks if h.get("id") != hook_id]
        if len(filtered) == len(webhooks):
            return False
        self.save_webhooks(filtered)
        logger_api.info("Webhook removed: %s", hook_id)
        return True

    @staticmethod
    def _validate_url(url: str) -> bool:
        try:
            parsed = urllib.parse.urlparse(url)
        except ValueError:
            return False
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    # ------------------------------------------------------------------ #
    # delivery
    # ------------------------------------------------------------------ #

    def dispatch(self, event: str, payload: dict) -> int:
        """Send an event to all subscribed webhooks, synchronously.

        Blocks until every matching delivery attempt finished (used by
        callers that want the count, e.g. tests / admin test-buttons).
        """
        return self._deliver(event, payload, async_deliveries=False)

    def dispatch_event(self, event: str, payload: dict) -> int:
        """Fire an event without blocking the caller (background threads).

        Returns the number of matching webhooks, not delivery results —
        deliveries complete asynchronously and update per-hook stats.
        """
        return self._deliver(event, payload, async_deliveries=True)

    def _deliver(self, event: str, payload: dict, async_deliveries: bool) -> int:
        webhooks = self.list_webhooks()
        matched = 0

        for hook in webhooks:
            if not hook.get("enabled"):
                continue
            if hook.get("events") and event not in hook["events"]:
                continue
            url = hook.get("url", "")
            if not url:
                continue
            matched += 1
            if async_deliveries:
                threading.Thread(
                    target=self._deliver_to_hook,
                    args=(hook, event, payload),
                    daemon=True,
                    name=f"webhook-{event}-{hook.get('id', '')[:6]}",
                ).start()
            else:
                self._deliver_to_hook(hook, event, payload)

        if async_deliveries:
            logger_api.info("Webhook %s: dispatched to %d webhooks", event, matched)
        return matched

    def _deliver_to_hook(self, hook: dict, event: str, payload: dict) -> bool:
        """One delivery attempt chain for one webhook; records stats."""
        body = json.dumps({
            "event": event,
            "timestamp": int(time.time()),
            "data": payload,
        })
        url = hook.get("url", "")
        secret = hook.get("secret", "")
        ok = self._send(url, body, secret)

        hook["delivery_count"] = int(hook.get("delivery_count") or 0) + 1
        hook["last_attempted_at"] = int(time.time())
        if ok:
            hook["success_count"] = int(hook.get("success_count") or 0) + 1
            hook["last_status"] = 200
        else:
            hook["last_status"] = 0
        # persist stats (best-effort; the registered list stays authoritative)
        try:
            hooks = self.list_webhooks()
            for stored in hooks:
                if stored.get("id") == hook.get("id"):
                    stored.update({k: hook[k] for k in (
                        "delivery_count", "success_count", "last_status", "last_attempted_at",
                    ) if k in hook})
                    break
            self.save_webhooks(hooks)
        except Exception as exc:  # pragma: no cover - stats must never break delivery
            logger_api.debug("Webhook stat persistence failed: %s", exc)
        return ok

    def _send(self, url: str, body: str, secret: str) -> bool:
        """Send a webhook with retry logic."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "SOGo6-Webhook/1.0",
            "X-Sogo-Webhook": "1",
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
                logger_api.warning("Webhook %s returned HTTP %d (attempt %d)", url[:40], resp.status, attempt + 1)
            except Exception as e:
                logger_api.warning("Webhook %s failed (attempt %d): %s", url[:40], attempt + 1, e)
                if attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_DELAYS[attempt] if attempt < len(_RETRY_DELAYS) else 60
                    time.sleep(delay)
        return False


_emitter: WebhookService | None = None


def emit_event(event: str, payload: dict) -> None:
    """Module-level best-effort event emitter used by domain modules.

    Never raises and never blocks the caller: deliveries run in daemon
    threads inside the shared WebhookService so a slow target endpoint can
    not stall a user request.
    """
    global _emitter
    try:
        if _emitter is None:
            _emitter = WebhookService()
        _emitter.dispatch_event(event, payload)
    except Exception as exc:  # pragma: no cover - emissions must never break the main op
        logger_api.debug("Webhook emit failed for %s: %s", event, exc)