"""API Token Management — scoped, expiring bearer tokens for automation.

Tokens can be created with:
- A label for identification
- An optional expiration date
- Scoped permissions (read, write, admin)

Tokens are stored as SHA-256 hashes in Redis. The raw token is shown once
on creation.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate

from app.service import sogo_cache
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User

blp = Blueprint("API Tokens", __name__, url_prefix="/api-tokens")

# Redis key prefix
_API_TOKEN_PREFIX: str = "api_token:"
_API_TOKEN_HASH_PREFIX: str = "api_token_hash:"
_API_TOKEN_INDEX: str = "api_token_index:"

# Valid scopes
VALID_SCOPES = ["read", "write", "admin", "mail:read", "mail:send", "calendar:read", "calendar:write", "contacts:read", "contacts:write"]


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _generate_token() -> str:
    return "sogo_" + secrets.token_hex(32)


# ── Schemas ──────────────────────────────────────────────────────────────────

class ApiTokenCreateSchema(Schema):
    label = fields.String(required=True, metadata={"description": "Human-readable label for the token"})
    scopes = fields.List(
        fields.String(validate=validate.OneOf(VALID_SCOPES)),
        load_default=["read"],
        metadata={"description": f"Scopes: {', '.join(VALID_SCOPES)}"},
    )
    expires_at = fields.Integer(
        load_default=None, allow_none=True,
        metadata={"description": "Unix timestamp when the token expires. null = never expires."},
    )


class ApiTokenCreateResponseSchema(Schema):
    id = fields.String()
    label = fields.String()
    token = fields.String()
    scopes = fields.List(fields.String())
    created_at = fields.Integer()
    expires_at = fields.Integer(allow_none=True)


class ApiTokenItemSchema(Schema):
    id = fields.String()
    label = fields.String()
    scopes = fields.List(fields.String())
    created_at = fields.Integer()
    expires_at = fields.Integer(allow_none=True)
    last_used_at = fields.Integer(allow_none=True)


class ApiTokenListResponseSchema(Schema):
    tokens = fields.List(fields.Nested(ApiTokenItemSchema()))


# ── API Endpoints ────────────────────────────────────────────────────────────

@blp.route("")
class ApiTokenListCreate(MethodView):
    """List or create API tokens."""

    def get(self) -> ResponseReturnValue:
        """List all API tokens for the current user (without secrets)."""
        user: User = g.user
        cache = sogo_cache()
        index_raw = cache.get(f"{_API_TOKEN_INDEX}{user.uid}", list)
        index: list = index_raw if isinstance(index_raw, list) else []
        tokens = []
        for token_id in index:
            raw = cache.get(f"{_API_TOKEN_PREFIX}{user.uid}:{token_id}", str)
            if raw:
                try:
                    import json
                    data = json.loads(raw)
                    tokens.append({
                        "id": token_id,
                        "label": data.get("label", ""),
                        "scopes": data.get("scopes", []),
                        "created_at": data.get("created_at", 0),
                        "expires_at": data.get("expires_at"),
                        "last_used_at": data.get("last_used_at"),
                    })
                except Exception:
                    pass
        return create_api_base_response({"tokens": tokens})

    @blp.arguments(ApiTokenCreateSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """Create a new API token. The raw token is returned once."""
        user: User = g.user
        cache = sogo_cache()
        token = _generate_token()
        token_hash = _hash_token(token)
        token_id = token_hash[:16]

        data = {
            "label": body["label"],
            "scopes": body.get("scopes", ["read"]),
            "created_at": int(time.time()),
            "expires_at": body.get("expires_at"),
            "last_used_at": None,
            "hash": token_hash,
        }

        # Store metadata by ID
        cache.set(
            f"{_API_TOKEN_PREFIX}{user.uid}:{token_id}",
            __import__("json").dumps({k: v for k, v in data.items() if k != "hash"}),
            ttl=86400 * 365,
        )
        # Store hash lookup (for verification)
        cache.set(
            f"{_API_TOKEN_HASH_PREFIX}{token_hash}",
            f"{user.uid}:{token_id}",
            ttl=86400 * 365,
        )
        # Add to user's token index
        index_raw = cache.get(f"{_API_TOKEN_INDEX}{user.uid}", list)
        index: list = index_raw if isinstance(index_raw, list) else []
        index.append(token_id)
        cache.set(f"{_API_TOKEN_INDEX}{user.uid}", index, ttl=86400 * 365)

        logger_api.info("API token created for user %s: %s", user.uid, token_id[:8])

        return create_api_base_response({
            "id": token_id,
            "label": data["label"],
            "token": token,
            "scopes": data["scopes"],
            "created_at": data["created_at"],
            "expires_at": data["expires_at"],
        }, code=201)


@blp.route("/<string:token_id>")
class ApiTokenDetail(MethodView):
    """Get or revoke a specific API token."""

    def get(self, token_id: str) -> ResponseReturnValue:
        """Get token metadata (not the secret)."""
        user: User = g.user
        cache = sogo_cache()
        raw = cache.get(f"{_API_TOKEN_PREFIX}{user.uid}:{token_id}", str)
        if not raw:
            return create_api_base_response(None, err.ERROR_API_TOKEN_NOT_FOUND)
        try:
            data = __import__("json").loads(raw)
        except Exception:
            return create_api_base_response(None, err.ERROR_API_TOKEN_NOT_FOUND)
        return create_api_base_response({
            "id": token_id,
            "label": data.get("label", ""),
            "scopes": data.get("scopes", []),
            "created_at": data.get("created_at", 0),
            "expires_at": data.get("expires_at"),
            "last_used_at": data.get("last_used_at"),
        })

    def delete(self, token_id: str) -> ResponseReturnValue:
        """Revoke an API token."""
        user: User = g.user
        cache = sogo_cache()
        key = f"{_API_TOKEN_PREFIX}{user.uid}:{token_id}"
        raw = cache.get(key, str)
        if not raw:
            return create_api_base_response(None, err.ERROR_API_TOKEN_NOT_FOUND)
        try:
            data = __import__("json").loads(raw)
        except Exception:
            data = {}
        # Clean up hash lookup and index
        cache.delete(f"{_API_TOKEN_HASH_PREFIX}{data.get('hash', '')}")
        cache.delete(key)
        index_raw = cache.get(f"{_API_TOKEN_INDEX}{user.uid}", list)
        index: list = index_raw if isinstance(index_raw, list) else []
        if token_id in index:
            index.remove(token_id)
            cache.set(f"{_API_TOKEN_INDEX}{user.uid}", index, ttl=86400 * 365)
        logger_api.info("API token revoked for user %s: %s", user.uid, token_id[:8])
        return create_api_base_response({"status": "revoked"})


# ── Token verification helper (used by auth middleware) ──────────────────────

def verify_api_token(token: str) -> tuple[str, dict] | None:
    """Verify an API token and return (user_uid, token_data) or None.

    Called by the auth middleware to authenticate requests using API tokens.
    """
    cache = sogo_cache()
    token_hash = _hash_token(token)
    raw = cache.get(f"{_API_TOKEN_HASH_PREFIX}{token_hash}", str)
    if not raw:
        return None
    try:
        user_uid, token_id = raw.split(":", 1)
    except ValueError:
        return None

    # Fetch token metadata
    meta_raw = cache.get(f"{_API_TOKEN_PREFIX}{user_uid}:{token_id}", str)
    if not meta_raw:
        return None

    try:
        data = __import__("json").loads(meta_raw)
    except Exception:
        return None

    # Check expiration
    expires_at = data.get("expires_at")
    if expires_at and time.time() > expires_at:
        cache.delete(f"{_API_TOKEN_HASH_PREFIX}{token_hash}")
        cache.delete(f"{_API_TOKEN_PREFIX}{user_uid}:{token_id}")
        return None

    # Update last used
    data["last_used_at"] = int(time.time())
    cache.set(
        f"{_API_TOKEN_PREFIX}{user_uid}:{token_id}",
        __import__("json").dumps({k: v for k, v in data.items() if k != "hash"}),
        ttl=86400 * 365,
    )

    return user_uid, data
