"""Real integration tests for Push Notifications (#15) using real Redis."""
import json
import pytest
from app.service.push.PushService import PushService, get_vapid_keys


@pytest.fixture
def svc(real_cache):
    return PushService(cache=real_cache)


class TestVAPIDKeys:
    def test_get_vapid_keys_returns_pair(self):
        priv, pub = get_vapid_keys()
        assert len(priv) > 20  # base64url-encoded key
        assert len(pub) > 20
        assert priv != pub

    def test_vapid_keys_are_stable(self):
        priv1, pub1 = get_vapid_keys()
        priv2, pub2 = get_vapid_keys()
        assert priv1 == priv2  # Same keys every call
        assert pub1 == pub2


class TestPushSubscription:
    def test_subscribe(self, svc):
        sub = {"endpoint": "https://fcm.googleapis.com/fcm/send/test123", "keys": {"p256dh": "key123", "auth": "auth456"}}
        svc.subscribe("user@test.com", sub)
        subs = svc.get_subscriptions("user@test.com")
        assert len(subs) == 1
        assert subs[0]["endpoint"] == sub["endpoint"]

    def test_subscribe_multiple_devices(self, svc):
        svc.subscribe("user@test.com", {"endpoint": "https://fcm/test1", "keys": {}})
        svc.subscribe("user@test.com", {"endpoint": "https://fcm/test2", "keys": {}})
        subs = svc.get_subscriptions("user@test.com")
        assert len(subs) == 2

    def test_subscribe_different_users(self, svc):
        svc.subscribe("alice@test.com", {"endpoint": "https://fcm/alice", "keys": {}})
        svc.subscribe("bob@test.com", {"endpoint": "https://fcm/bob", "keys": {}})
        assert len(svc.get_subscriptions("alice@test.com")) == 1
        assert len(svc.get_subscriptions("bob@test.com")) == 1

    def test_unsubscribe(self, svc):
        svc.subscribe("user@test.com", {"endpoint": "https://fcm/test", "keys": {}})
        assert len(svc.get_subscriptions("user@test.com")) == 1
        svc.unsubscribe("user@test.com", "https://fcm/test")
        assert len(svc.get_subscriptions("user@test.com")) == 0

    def test_unsubscribe_nonexistent(self, svc):
        svc.unsubscribe("user@test.com", "https://fcm/nonexistent")  # Should not raise

    def test_subscription_persistence(self, svc):
        svc.subscribe("user@test.com", {"endpoint": "https://fcm/persist", "keys": {}})
        svc2 = PushService(cache=svc.cache)
        subs = svc2.get_subscriptions("user@test.com")
        assert len(subs) == 1
        assert subs[0]["endpoint"] == "https://fcm/persist"

    def test_send_notification_no_subscribers(self, svc):
        sent = svc.send_notification("unknown@test.com", "Test", "No subscribers")
        assert sent == 0

    def test_send_notification_with_subscribers(self, svc):
        svc.subscribe("user@test.com", {"endpoint": "https://fcm/test", "keys": {}})
        # This will fail to deliver (invalid endpoint), but should not crash
        sent = svc.send_notification("user@test.com", "Hello", "Push body")
        assert sent == 0  # Failed to deliver because endpoint is fake
