"""Real integration tests for API tokens using real Redis."""
import json
import time
import pytest
from app.api.v1.user.ApiApiTokens import verify_api_token, _hash_token, _generate_token
from app.service import sogo_cache


@pytest.fixture
def cache():
    """Use the default sogo_cache Redis instance (DB 0)."""
    c = sogo_cache()
    try:
        c.redis.flushdb()
    except Exception:
        pass
    yield c
    try:
        c.redis.flushdb()
    except Exception:
        pass


class TestTokenGeneration:
    def test_generate_token_format(self):
        token = _generate_token()
        assert token.startswith("sogo_")
        assert len(token) > 32
        assert len(token) < 100

    def test_hash_token_deterministic(self):
        token = "sogo_test_token_123"
        h1 = _hash_token(token)
        h2 = _hash_token(token)
        assert h1 == h2
        assert len(h1) == 64

    def test_hash_different_tokens(self):
        h1 = _hash_token("token_a")
        h2 = _hash_token("token_b")
        assert h1 != h2

    def test_generate_unique_tokens(self):
        tokens = {_generate_token() for _ in range(100)}
        assert len(tokens) == 100  # No duplicates


class TestTokenVerification:
    def test_verify_valid_token(self, cache):
        # Manually set up a token in Redis like the API would
        token = _generate_token()
        token_hash = _hash_token(token)
        token_id = token_hash[:16]
        
        cache.set(f"api_token:user123:{token_id}", 
                  json.dumps({"scopes": ["read"], "expires_at": None, "last_used_at": None}),
                  ttl=86400 * 365)
        cache.set(f"api_token_hash:{token_hash}", f"user123:{token_id}", ttl=86400 * 365)
        
        result = verify_api_token(token)
        assert result is not None
        uid, data = result
        assert uid == "user123"
        assert data["scopes"] == ["read"]

    def test_verify_expired_token(self, cache):
        token = _generate_token()
        token_hash = _hash_token(token)
        token_id = token_hash[:16]
        
        cache.set(f"api_token:user123:{token_id}",
                  json.dumps({"scopes": ["read"], "expires_at": 1, "last_used_at": None}),
                  ttl=86400 * 365)
        cache.set(f"api_token_hash:{token_hash}", f"user123:{token_id}", ttl=86400 * 365)
        
        result = verify_api_token(token)
        assert result is None  # Expired

    def test_verify_invalid_token(self, cache):
        result = verify_api_token("invalid_token_that_does_not_exist")
        assert result is None

    def test_verify_updates_last_used(self, cache):
        token = _generate_token()
        token_hash = _hash_token(token)
        token_id = token_hash[:16]
        
        cache.set(f"api_token:user123:{token_id}",
                  json.dumps({"scopes": ["admin"], "expires_at": None, "last_used_at": None}),
                  ttl=86400 * 365)
        cache.set(f"api_token_hash:{token_hash}", f"user123:{token_id}", ttl=86400 * 365)
        
        verify_api_token(token)
        
        # Check that last_used_at was updated
        raw = cache.get(f"api_token:user123:{token_id}", str)
        data = json.loads(raw) if raw else {}
        assert data.get("last_used_at") is not None
        assert data["last_used_at"] > 0
