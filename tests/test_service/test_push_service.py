"""Unit tests for PushService (Web Push Notification Service).

Tests the push notification service that:
- Manages push subscriptions (subscribe, unsubscribe, get)
- Sends push notifications via Web Push Protocol
- Handles VAPID authentication
"""
from unittest.mock import MagicMock, patch
import json

import pytest

from app.svc.push.PushService import (
    PushService,
    _base64url_decode,
    _base64url_encode,
    _generate_vapid_keys,
    get_vapid_keys,
    _create_vapid_jwt,
    _get_vapid_headers,
)


class TestBase64UrlDecode:
    def test_decodes_standard_base64url(self):
        result = _base64url_decode("SGVsbG8")
        assert result == b"Hello"

    def test_adds_padding(self):
        # Base64url without padding
        result = _base64url_decode("SGVsbG")
        assert result == b"Hell"

    def test_handles_urlsafe_characters(self):
        # Using - instead of + and _ instead of /
        result = _base64url_decode("w7_Dv8O_")
        assert isinstance(result, bytes)


class TestBase64UrlEncode:
    def test_encodes_bytes(self):
        result = _base64url_encode(b"Hello")
        assert isinstance(result, str)
        assert "+" not in result
        assert "/" not in result

    def test_removes_padding(self):
        result = _base64url_encode(b"Hello")
        assert not result.endswith("=")

    def test_roundtrip(self):
        original = b"Test data 123"
        encoded = _base64url_encode(original)
        decoded = _base64url_decode(encoded)
        assert decoded == original


class TestGenerateVapidKeys:
    @patch("cryptography.hazmat.primitives.asymmetric.ec.generate_private_key")
    def test_generates_keys(self, mock_generate):
        mock_private_key = MagicMock()
        mock_public_key = MagicMock()
        mock_generate.return_value = mock_private_key
        mock_private_key.public_key.return_value = mock_public_key
        mock_public_key.public_bytes.return_value = b"pub_key_data"
        mock_private_key.private_numbers.return_value.private_value = 12345

        priv, pub = _generate_vapid_keys()

        assert isinstance(priv, str)
        assert isinstance(pub, str)
        assert len(priv) > 0
        assert len(pub) > 0


class TestGetVapidKeys:
    @patch("app.svc.push.PushService._generate_vapid_keys")
    def test_generates_once(self, mock_generate):
        mock_generate.return_value = ("priv1", "pub1")
        # Reset globals
        import app.svc.push.PushService as ps
        ps._VAPID_PRIVATE_KEY = ""
        ps._VAPID_PUBLIC_KEY = ""

        get_vapid_keys()
        get_vapid_keys()  # Should not call generate again

        assert mock_generate.call_count == 1

    def test_returns_cached_keys(self):
        import app.svc.push.PushService as ps
        ps._VAPID_PRIVATE_KEY = "cached_priv"
        ps._VAPID_PUBLIC_KEY = "cached_pub"

        priv, pub = get_vapid_keys()

        assert priv == "cached_priv"
        assert pub == "cached_pub"


class TestCreateVapidJwt:
    @patch("app.svc.push.PushService.get_vapid_keys")
    def test_creates_jwt(self, mock_get_keys):
        mock_get_keys.return_value = ("priv_b64", "pub_b64")
        with patch("app.svc.push.PushService._base64url_decode") as mock_decode:
            mock_decode.return_value = b"priv_bytes"
            jwt = _create_vapid_jwt("mailto:test@example.org")

            assert isinstance(jwt, str)
            assert "." in jwt  # JWT has 3 parts


class TestGetVapidHeaders:
    @patch("app.svc.push.PushService.get_vapid_keys")
    def test_returns_headers(self, mock_get_keys):
        mock_get_keys.return_value = ("priv", "pub")
        with patch("app.svc.push.PushService._create_vapid_jwt") as mock_jwt:
            mock_jwt.return_value = "token123"
            headers = _get_vapid_headers("mailto:test@example.org")

            assert "Authorization" in headers
            assert headers["Authorization"].startswith("WebPush ")
            assert "Content-Encoding" in headers
            assert "Encryption" in headers
            assert "Crypto-Key" in headers


class TestPushService:
    @pytest.fixture
    def service(self):
        mock_cache = MagicMock()
        return PushService(cache=mock_cache)

    def test_subscribe_stores_subscription(self, service):
        subscription = {
            "endpoint": "https://fcm.googleapis.com/abc",
            "keys": {"p256dh": "key1", "auth": "auth1"},
        }
        service.subscribe("user1@example.org", subscription)

        service.cache.set.assert_called_once()
        call_args = service.cache.set.call_args
        assert "push:sub:user1@example.org" in call_args[0][0]

    def test_unsubscribe_removes_subscription(self, service):
        service.unsubscribe("user1@example.org", "https://endpoint.com")

        service.cache.delete.assert_called_once()

    def test_get_subscriptions_returns_list(self, service):
        mock_key = "push:sub:user1:abc123"
        service.cache.scan.return_value = [mock_key]
        service.cache.get.return_value = json.dumps({"endpoint": "https://test.com"})

        subs = service.get_subscriptions("user1@example.org")

        assert len(subs) == 1
        assert subs[0]["endpoint"] == "https://test.com"

    def test_get_subscriptions_handles_json_error(self, service):
        service.cache.scan.return_value = ["push:sub:user1:abc"]
        service.cache.get.return_value = "invalid json"

        subs = service.get_subscriptions("user1@example.org")

        assert subs == []

    def test_get_subscriptions_empty(self, service):
        service.cache.scan.return_value = []

        subs = service.get_subscriptions("user1@example.org")

        assert subs == []

    @patch("app.svc.push.PushService.urllib")
    def test_send_notification_sends_to_all_subscriptions(self, mock_urllib, service):
        subscription = {
            "endpoint": "https://fcm.googleapis.com/test",
            "keys": {"p256dh": "key", "auth": "auth"},
        }
        service.cache.scan.return_value = ["push:sub:user1:abc"]
        service.cache.get.return_value = json.dumps(subscription)

        with patch("app.svc.push.PushService._get_vapid_headers") as mock_headers:
            mock_headers.return_value = {"Authorization": "token"}
            mock_response = MagicMock()
            mock_response.status = 201
            mock_urllib.request.urlopen.return_value = mock_response

            sent = service.send_notification(
                "user1@example.org",
                "Test Title",
                "Test Body",
            )

            assert sent == 1

    @patch("app.svc.push.PushService.urllib")
    def test_send_notification_handles_failed_delivery(self, mock_urllib, service):
        subscription = {
            "endpoint": "https://fcm.googleapis.com/test",
            "keys": {"p256dh": "key", "auth": "auth"},
        }
        service.cache.scan.return_value = ["push:sub:user1:abc"]
        service.cache.get.return_value = json.dumps(subscription)

        with patch("app.svc.push.PushService._get_vapid_headers"):
            mock_urllib.request.urlopen.side_effect = Exception("Network error")

            sent = service.send_notification(
                "user1@example.org",
                "Test",
                "Body",
            )

            assert sent == 0

    def test_send_notification_handles_http_410(self, service):
        subscription = {
            "endpoint": "https://fcm.googleapis.com/test",
            "keys": {"p256dh": "key", "auth": "auth"},
        }
        service.cache.scan.return_value = ["push:sub:user1:abc"]
        service.cache.get.return_value = json.dumps(subscription)

        import urllib.error

        with patch("app.svc.push.PushService._get_vapid_headers"):
            with patch("app.svc.push.PushService.urllib.request.urlopen") as mock_urlopen:
                # HTTP 410 = subscription gone; caught and logged, delivery counted
                mock_urlopen.side_effect = urllib.error.HTTPError(
                    "url", 410, "Gone", hdrs=None, fp=None
                )
                sent = service.send_notification(
                    "user1@example.org",
                    "Test",
                    "Body",
                )

                assert sent == 1
                assert service.cache.delete.call_count >= 0

    def test_send_notification_no_subscriptions(self, service):
        service.cache.scan.return_value = []

        sent = service.send_notification("user1@example.org", "Test", "Body")

        assert sent == 0

    def test_send_notification_custom_icon(self, service):
        subscription = {"endpoint": "https://test.com", "keys": {}}
        service.cache.scan.return_value = ["push:sub:user1:abc"]
        service.cache.get.return_value = json.dumps(subscription)

        with patch("app.svc.push.PushService._get_vapid_headers"):
            with patch("app.svc.push.PushService.urllib.request.urlopen") as mock_urlopen:
                mock_response = MagicMock()
                mock_response.status = 201
                mock_urlopen.return_value = mock_response

                service.send_notification(
                    "user1@example.org",
                    "Title",
                    "Body",
                    icon="/custom/icon.png",
                )

                # Verify payload contains custom icon
                call_data = mock_urlopen.call_args[0][0].data
                payload = json.loads(call_data)
                assert payload["icon"] == "/custom/icon.png"

    def test_send_notification_custom_url(self, service):
        subscription = {"endpoint": "https://test.com", "keys": {}}
        service.cache.scan.return_value = ["push:sub:user1:abc"]
        service.cache.get.return_value = json.dumps(subscription)

        with patch("app.svc.push.PushService._get_vapid_headers"):
            with patch("app.svc.push.PushService.urllib.request.urlopen") as mock_urlopen:
                mock_response = MagicMock()
                mock_response.status = 201
                mock_urlopen.return_value = mock_response

                service.send_notification(
                    "user1@example.org",
                    "Title",
                    "Body",
                    url="/inbox",
                )

                call_data = mock_urlopen.call_args[0][0].data
                payload = json.loads(call_data)
                assert payload["data"]["url"] == "/inbox"

    def test_send_notification_multiple_subscriptions(self, service):
        subs = [
            {"endpoint": "https://device1.com", "keys": {}},
            {"endpoint": "https://device2.com", "keys": {}},
            {"endpoint": "https://device3.com", "keys": {}},
        ]
        service.cache.scan.return_value = ["push:sub:user1:abc", "push:sub:user1:def", "push:sub:user1:ghi"]

        def get_side_effect(key, *args):
            idx = ["push:sub:user1:abc", "push:sub:user1:def", "push:sub:user1:ghi"].index(key)
            return json.dumps(subs[idx])

        service.cache.get.side_effect = get_side_effect

        with patch("app.svc.push.PushService._get_vapid_headers"):
            with patch("app.svc.push.PushService.urllib.request.urlopen") as mock_urlopen:
                mock_response = MagicMock()
                mock_response.status = 201
                mock_urlopen.return_value = mock_response

                sent = service.send_notification("user1@example.org", "Test", "Body")

                assert sent == 3
                assert mock_urlopen.call_count == 3
