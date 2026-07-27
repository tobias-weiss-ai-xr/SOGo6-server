"""Tests for API token generation and verification (#28)."""
import json
import pytest
from unittest.mock import MagicMock, patch
from app.api.v1.user.ApiApiTokens import verify_api_token, _hash_token, _generate_token


class TestTokenGeneration:
    def test_generate_token_format(self):
        token = _generate_token()
        assert token.startswith("sogo_")
        assert len(token) > 32

    def test_hash_token(self):
        token = "sogo_test_token_123"
        h1 = _hash_token(token)
        h2 = _hash_token(token)
        assert h1 == h2  # Deterministic
        assert len(h1) == 64  # SHA-256 hex

    def test_hash_different_tokens(self):
        h1 = _hash_token("token_a")
        h2 = _hash_token("token_b")
        assert h1 != h2


class TestTokenVerification:
    def test_verify_valid_token(self):
        token = "sogo_valid_test_token"
        token_hash = _hash_token(token)
        with patch("app.api.v1.user.ApiApiTokens.sogo_cache") as mock_cache:
            cache = MagicMock()
            mock_cache.return_value = cache
            cache.get.side_effect = [
                f"user123:{token_hash[:16]}",  # hash lookup
                json.dumps({"scopes": ["read"], "expires_at": None, "last_used_at": None}),  # metadata
            ]
            result = verify_api_token(token)
            assert result is not None
            uid, data = result
            assert uid == "user123"

    def test_verify_expired_token(self):
        import time
        token = "sogo_expired_token"
        token_hash = _hash_token(token)
        with patch("app.api.v1.user.ApiApiTokens.sogo_cache") as mock_cache:
            cache = MagicMock()
            mock_cache.return_value = cache
            cache.get.side_effect = [
                f"user123:{token_hash[:16]}",  # hash lookup
                json.dumps({"scopes": ["read"], "expires_at": 1, "last_used_at": None}),  # expired in 1970
            ]
            result = verify_api_token(token)
            assert result is None  # Expired

    def test_verify_invalid_token(self):
        with patch("app.api.v1.user.ApiApiTokens.sogo_cache") as mock_cache:
            cache = MagicMock()
            mock_cache.return_value = cache
            cache.get.return_value = None
            result = verify_api_token("invalid_token")
            assert result is None
