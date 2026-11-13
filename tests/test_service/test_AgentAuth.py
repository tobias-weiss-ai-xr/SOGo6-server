"""Unit tests for the agent auth foundation (API tokens, scopes, impersonation)."""
import json
import time

import pytest

from app.api.v1.user import ApiApiTokens as tokens


class _StubSetting:
    """Minimal ProcessSetting stand-in for the session cipher."""

    SOGO_P_VOUCHER_SECRET = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def cache(monkeypatch):
    """Hermetic in-memory cache injected into the token module."""
    class FakeCache:
        def __init__(self):
            self._store = {}

        def get(self, key, expected_type=str):
            raw = self._store.get(key)
            if raw is None:
                return None
            if expected_type == str:
                return raw
            try:
                return json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                return raw

        def set(self, key, val, ttl=None, nx=False):
            if not isinstance(val, str):
                val = json.dumps(val)
            self._store[key] = val
            return True

        def delete(self, *keys):
            for key in keys:
                self._store.pop(key, None)

    fake = FakeCache()
    monkeypatch.setattr(tokens, "sogo_cache", lambda: fake)
    return fake


class TestScopeGrants:
    """token_scope_satisfies — the scope matrix."""

    def test_exact_scope_matches(self):
        assert tokens.token_scope_satisfies(["mail:read"], "mail:read")

    def test_missing_scope_rejected(self):
        assert not tokens.token_scope_satisfies(["mail:read"], "mail:send")

    def test_read_grants_all_read_class(self):
        for scope in ("mail:read", "calendar:read", "contacts:read"):
            assert tokens.token_scope_satisfies(["read"], scope)

    def test_read_does_not_grant_write_class(self):
        assert not tokens.token_scope_satisfies(["read"], "mail:send")

    def test_write_grants_all_write_class(self):
        for scope in ("mail:send", "calendar:write", "contacts:write"):
            assert tokens.token_scope_satisfies(["write"], scope)

    def test_admin_grants_everything(self):
        for scope in tokens.READ_CLASS_SCOPES | tokens.WRITE_CLASS_SCOPES:
            assert tokens.token_scope_satisfies(["admin"], scope)


class TestVerifyApiToken:
    def _store_token(self, cache, token, meta_overrides=None):
        token_hash = tokens._hash_token(token)
        token_id = token_hash[:16]
        meta = {
            "scopes": ["read"],
            "expires_at": None,
            "last_used_at": None,
            "hash": token_hash,
        }
        meta.update(meta_overrides or {})
        cache.set(f"api_token:user1:{token_id}", json.dumps(meta), ttl=3600)
        cache.set(f"api_token_hash:{token_hash}", f"user1:{token_id}", ttl=3600)
        return token_id

    def test_valid_token_returns_metadata(self, cache):
        token = tokens._generate_token()
        self._store_token(cache, token)
        result = tokens.verify_api_token(token)
        assert result is not None
        user_uid, data = result
        assert user_uid == "user1"
        assert data["last_used_at"] >= int(time.time()) - 5

    def test_unknown_token_rejected(self, cache):
        assert tokens.verify_api_token(tokens._generate_token()) is None

    def test_expired_token_rejected_and_deleted(self, cache):
        token = tokens._generate_token()
        self._store_token(cache, token, {"expires_at": int(time.time()) - 10})
        assert tokens.verify_api_token(token) is None

    def test_user_session_rebuilt_into_full_user(self, cache):
        from app.auth.User import User

        user = User("user1@example.org", "pw123", domain="example.org")
        cipher = tokens._session_cipher(_StubSetting())
        session_blob = cipher.encrypt(json.dumps(user.get_user_session()).encode()).decode()

        token = tokens._generate_token()
        self._store_token(cache, token, {"user_session": session_blob})

        result = tokens.verify_api_token(token, process_setting=_StubSetting())
        assert result is not None
        _, data = result
        rebuilt = data.get("_user")
        assert rebuilt is not None
        assert rebuilt.uid == "user1@example.org"
        assert rebuilt.password == "pw123"

    def test_session_blob_survives_last_used_update(self, cache):
        from app.auth.User import User

        user = User("user1@example.org", "pw123", domain="example.org")
        cipher = tokens._session_cipher(_StubSetting())
        session_blob = cipher.encrypt(json.dumps(user.get_user_session()).encode()).decode()

        token = tokens._generate_token()
        token_id = self._store_token(cache, token, {"user_session": session_blob})

        tokens.verify_api_token(token, process_setting=_StubSetting())
        # Second use must still resolve the full user (blob not dropped)
        result = tokens.verify_api_token(token, process_setting=_StubSetting())
        assert result is not None
        assert result[1].get("_user") is not None
        stored = json.loads(cache.get(f"api_token:user1:{token_id}", str))
        assert "user_session" in stored


class TestImpersonationTokens:
    def _target(self):
        from app.auth.User import User
        return User("target@example.org", domain="example.org")

    def test_create_sets_target_and_issuer(self, cache):
        token, data = tokens.create_impersonation_token(
            admin_uid="admin@example.org",
            target_user=self._target(),
            scopes=["calendar:write"],
            label="bot",
        )
        assert token.startswith("sogoimp_")
        assert data["issuer_uid"] == "admin@example.org"
        assert data["target_uid"] == "target@example.org"

    def test_verify_resolves_to_target(self, cache):
        token, _ = tokens.create_impersonation_token(
            "admin@example.org", self._target(), ["calendar:read"], "bot",
        )
        result = tokens.verify_api_token(token)
        assert result is not None
        user_uid, data = result
        assert user_uid == "target@example.org"  # acts as the target
        assert data["issuer_uid"] == "admin@example.org"

    def test_list_and_revoke_cycle(self, cache):
        token, data = tokens.create_impersonation_token(
            "admin@example.org", self._target(), ["read"], "bot",
        )
        token_id = data["hash"][:16]

        listed = tokens.list_impersonation_tokens("admin@example.org")
        assert [t["id"] for t in listed] == [token_id]
        assert listed[0]["target_uid"] == "target@example.org"

        assert tokens.verify_api_token(token) is not None
        assert tokens.revoke_impersonation_token("admin@example.org", token_id) is True
        assert tokens.verify_api_token(token) is None
        assert tokens.revoke_impersonation_token("admin@example.org", token_id) is False
        assert tokens.list_impersonation_tokens("admin@example.org") == []

    def test_revoke_is_scoped_to_issuing_admin(self, cache):
        token, data = tokens.create_impersonation_token(
            "admin1@example.org", self._target(), ["read"], "bot",
        )
        token_id = data["hash"][:16]
        # Another admin cannot revoke or even see the token
        assert tokens.revoke_impersonation_token("admin2@example.org", token_id) is False
        assert tokens.verify_api_token(token) is not None
