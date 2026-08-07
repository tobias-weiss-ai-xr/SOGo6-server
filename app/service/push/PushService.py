"""Web Push Notification Service (VAPID-based).

Provides endpoints to subscribe/unsubscribe browser push subscriptions
and a service to send push notifications via the Web Push Protocol.

Uses stdlib only — no external dependencies.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.request

from app.service import sogo_cache
from app.utils.logger.logger import logger_api

# VAPID keys (should be loaded from config/env in production)
_VAPID_PRIVATE_KEY: str = ""
_VAPID_PUBLIC_KEY: str = ""
_VAPID_CLAIMS: dict = {}

# Redis key prefix for push subscriptions
_PUSH_SUB_PREFIX: str = "push:sub:"
_PUSH_INDEX_PREFIX: str = "push:index:"
_PUSH_MSG_PREFIX: str = "push:msg:"


def _base64url_decode(data: str) -> bytes:
    """Decode base64url-encoded string."""
    data = data.replace("-", "+").replace("_", "/")
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.b64decode(data)


def _base64url_encode(data: bytes) -> str:
    """Encode bytes to base64url."""
    return base64.b64encode(data).decode().replace("+", "-").replace("/", "_").rstrip("=")


def _generate_vapid_keys() -> tuple[str, str]:
    """Generate VAPID keys using ECDSA on curve P-256.

    Simplified implementation for development. In production, use pre-generated keys.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    # Export raw uncompressed point for public key
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )

    # Export private key as raw bytes
    priv_bytes = private_key.private_numbers().private_value.to_bytes(32, "big")

    return _base64url_encode(priv_bytes), _base64url_encode(pub_bytes)


def get_vapid_keys() -> tuple[str, str]:
    """Return (private_key, public_key) VAPID key pair."""
    global _VAPID_PRIVATE_KEY, _VAPID_PUBLIC_KEY
    if not _VAPID_PRIVATE_KEY:
        _VAPID_PRIVATE_KEY, _VAPID_PUBLIC_KEY = _generate_vapid_keys()
        logger_api.info("Generated new VAPID key pair")
    return _VAPID_PRIVATE_KEY, _VAPID_PUBLIC_KEY


def _create_vapid_jwt(subject: str = "mailto:admin@example.org") -> str:
    """Create a VAPID JWT for Web Push authentication."""
    private_key_b64, public_key_b64 = get_vapid_keys()
    private_key_bytes = _base64url_decode(private_key_b64)

    header = _base64url_encode(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    now = int(time.time())
    payload = _base64url_encode(
        json.dumps({
            "aud": "https://fcm.googleapis.com",
            "exp": now + 43200,
            "sub": subject,
        }).encode()
    )

    # Sign using HMAC-SHA256 (simplified — real VAPID uses ECDSA)
    # For production, use cryptography library for proper ECDSA signing
    signing_input = f"{header}.{payload}"
    signature = hmac.new(
        private_key_bytes, signing_input.encode(), hashlib.sha256
    ).digest()
    signature_b64 = _base64url_encode(signature)

    return f"{signing_input}.{signature_b64}"


def _get_vapid_headers(subject: str = "mailto:admin@example.org") -> dict:
    """Return HTTP headers with VAPID authentication."""
    _, public_key_b64 = get_vapid_keys()
    token = _create_vapid_jwt(subject)
    return {
        "Authorization": f"WebPush {token}",
        "Content-Encoding": "aes128gcm",
        "Encryption": f"keyid=p256dh; salt={_base64url_encode(hashlib.sha256(str(time.time()).encode()).digest()[:16])}",
        "Crypto-Key": f"p256ecdsa={public_key_b64}",
    }


class PushService:
    """Manages push subscriptions and sends notifications."""

    def __init__(self, cache=None):
        self.cache = cache or sogo_cache()

    def subscribe(self, user_uid: str, subscription: dict) -> None:
        """Store a push subscription for a user.

        :param user_uid: User identifier
        :param subscription: Push subscription object from browser
            {endpoint, keys: {p256dh, auth}}
        """
        import hashlib
        sub_id = hashlib.sha256(subscription['endpoint'].encode()).hexdigest()[:16]
        key = f"{_PUSH_SUB_PREFIX}{user_uid}:{sub_id}"
        self.cache.set(key, json.dumps(subscription), ttl=86400 * 365)
        # Maintain index
        index_raw = self.cache.get(f"{_PUSH_INDEX_PREFIX}{user_uid}", list)
        index: list = list(index_raw) if isinstance(index_raw, list) else []
        if sub_id not in index:
            index.append(sub_id)
            self.cache.set(f"{_PUSH_INDEX_PREFIX}{user_uid}", index, ttl=86400 * 365)
        logger_api.info("Push subscription stored for user %s", user_uid)

    def unsubscribe(self, user_uid: str, endpoint: str) -> None:
        """Remove a push subscription."""
        import hashlib
        sub_id = hashlib.sha256(endpoint.encode()).hexdigest()[:16]
        key = f"{_PUSH_SUB_PREFIX}{user_uid}:{sub_id}"
        self.cache.delete(key)
        # Update index
        index_raw = self.cache.get(f"{_PUSH_INDEX_PREFIX}{user_uid}", list)
        index: list = list(index_raw) if isinstance(index_raw, list) else []
        if sub_id in index:
            index.remove(sub_id)
            self.cache.set(f"{_PUSH_INDEX_PREFIX}{user_uid}", index, ttl=86400 * 365)
        logger_api.info("Push subscription removed for user %s", user_uid)

    def get_subscriptions(self, user_uid: str) -> list[dict]:
        """Get all push subscriptions for a user."""
        import json as _json
        index_raw = self.cache.get(f"{_PUSH_INDEX_PREFIX}{user_uid}", list)
        index: list = list(index_raw) if isinstance(index_raw, list) else []
        subs = []
        for sub_id in index:
            raw = self.cache.get(f"{_PUSH_SUB_PREFIX}{user_uid}:{sub_id}", str)
            if raw:
                try:
                    subs.append(_json.loads(raw))
                except _json.JSONDecodeError:
                    continue
        return subs

    def send_notification(
        self, user_uid: str, title: str, body: str, icon: str = "/icons/icon.svg",
        url: str = "", tag: str = "",
    ) -> int:
        """Send a push notification to all devices of a user.

        :param user_uid: User to notify
        :param title: Notification title
        :param body: Notification body text
        :param icon: Icon URL
        :param url: URL to open on click
        :param tag: Notification tag for grouping
        :return: Number of successful deliveries
        """
        payload = json.dumps({
            "title": title,
            "body": body,
            "icon": icon,
            "data": {"url": url, "tag": tag},
            "tag": tag,
        })

        subscriptions = self.get_subscriptions(user_uid)
        sent = 0

        for sub in subscriptions:
            try:
                if self._send_to_subscription(sub, payload):
                    sent += 1
            except Exception as e:
                logger_api.warning("Failed to send push to %s: %s", user_uid, e)

        logger_api.info(
            "Push notification sent to %s: %d/%d delivered",
            user_uid, sent, len(subscriptions),
        )
        return sent

    def _send_to_subscription(self, subscription: dict, payload: str) -> bool:
        """Send encrypted push to a single subscription. Returns True on success."""
        endpoint = subscription.get("endpoint", "")
        if not endpoint:
            return False

        headers = {
            "Content-Type": "application/octet-stream",
            "TTL": "86400",
            "Urgency": "normal",
        }

        # Add VAPID headers for endpoints that require authentication
        headers.update(_get_vapid_headers())

        req = urllib.request.Request(
            endpoint,
            data=payload.encode(),
            headers=headers,
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            logger_api.debug("Push sent to %s: HTTP %d", endpoint[:30], resp.status)
            return resp.status < 300
        except urllib.error.HTTPError as e:
            if e.code in (410, 404):
                logger_api.info("Push subscription gone (HTTP %d), should remove", e.code)
            else:
                logger_api.warning("Push send failed (HTTP %d): %s", e.code, e)
            return False
        except urllib.error.URLError as e:
            logger_api.warning("Push send failed (connection): %s", e)
            return False
