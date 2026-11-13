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
from typing import TYPE_CHECKING

from base64 import urlsafe_b64encode
from json import dumps as js_dumps, loads as js_loads

from cryptography.fernet import Fernet, InvalidToken
from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate

from app.service import sogo_cache
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import BugException
from app.utils.logger.logger import logger_api, logger_auth

if TYPE_CHECKING:
    from app.auth.User import User
    from app.config.settings.ProcessSetting import ProcessSetting

blp = Blueprint("API Tokens", __name__, url_prefix="/api-tokens")

# Redis key prefix
_API_TOKEN_PREFIX: str = "api_token:"
_API_TOKEN_HASH_PREFIX: str = "api_token_hash:"
_API_TOKEN_INDEX: str = "api_token_index:"
_API_TOKEN_IMP_INDEX: str = "api_token_imp_index:"

# Valid scopes
VALID_SCOPES = ["read", "write", "admin", "mail:read", "mail:send", "calendar:read", "calendar:write", "contacts:read", "contacts:write"]

# Scope classes: the generic grants "read"/"write" cover these module scopes,
# "admin" covers everything.
READ_CLASS_SCOPES = {"mail:read", "calendar:read", "contacts:read"}
WRITE_CLASS_SCOPES = {"mail:send", "calendar:write", "contacts:write"}

# Prefix that distinguishes admin-issued impersonation tokens
IMPERSONATION_PREFIX = "sogoimp_"


def token_scope_satisfies(token_scopes: list, required: str) -> bool:
    """True when the set of token scopes grants the ``required`` module scope.

    ``admin`` grants everything; ``read`` grants every read-class scope;
    ``write`` grants every write-class scope; exact matches always pass.
    """
    if "admin" in token_scopes or required in token_scopes:
        return True
    if "read" in token_scopes and required in READ_CLASS_SCOPES:
        return True
    if "write" in token_scopes and required in WRITE_CLASS_SCOPES:
        return True
    return False


def _session_cipher(process_setting: ProcessSetting) -> Fernet:
    """Fernet cipher derived from the voucher secret (same key material as user sessions)."""
    secret = process_setting.SOGO_P_VOUCHER_SECRET
    if len(secret) != 32:
        raise BugException("SOGO_P_VOUCHER_SECRET is not 32 char long")
    return Fernet(urlsafe_b64encode(secret.encode("utf-8")))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _generate_token() -> str:
    return "sogo_" + secrets.token_hex(32)


def _generate_impersonation_token() -> str:
    return IMPERSONATION_PREFIX + secrets.token_hex(32)


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
                    continue
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

        # Store the encrypted user session so requests authenticated with this
        # token can rebuild a full User (mail operations need the IMAP password).
        # Same key material as voucher sessions — no new secret introduced.
        try:
            data["user_session"] = _session_cipher(g.process_settings).encrypt(
                js_dumps(user.get_user_session()).encode("utf-8")
            ).decode("utf-8")
        except Exception:  # pragma: no cover - cipher misconfiguration is a BugException
            logger_api.warning("Could not encrypt user session for API token of %s", user.uid)

        # Store metadata by ID (includes the encrypted user_session so token
        # requests can rebuild a full User; the read paths strip it)
        cache.set(
            f"{_API_TOKEN_PREFIX}{user.uid}:{token_id}",
            js_dumps({k: v for k, v in data.items() if k != "hash"}),
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

def verify_api_token(token: str, process_setting: ProcessSetting | None = None) -> tuple[str, dict] | None:
    """Verify an API token and return (user_uid, token_data) or None.

    Called by the auth middleware to authenticate requests using API tokens.
    For ``sogo_`` tokens ``user_uid`` is the owning user; for ``sogoimp_``
    tokens it is the impersonation target (the issuing admin is in
    ``token_data["issuer_uid"]``).

    When ``process_setting`` is provided and the token metadata carries an
    encrypted ``user_session``, the decrypted session is attached as
    ``token_data["_user"]`` (a full ``User`` instance incl. mail password).
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
        data = js_loads(meta_raw)
    except Exception:
        return None

    # Check expiration
    expires_at = data.get("expires_at")
    if expires_at and time.time() > expires_at:
        cache.delete(f"{_API_TOKEN_HASH_PREFIX}{token_hash}")
        cache.delete(f"{_API_TOKEN_PREFIX}{user_uid}:{token_id}")
        return None

    # Rebuild the full User when the encrypted session blob is available
    if process_setting is not None and data.get("user_session"):
        try:
            session = js_loads(
                _session_cipher(process_setting).decrypt(data["user_session"].encode("utf-8")).decode("utf-8")
            )
            from app.auth.User import User
            data["_user"] = User.init_from_user_session(session)
        except Exception:
            logger_api.warning("API token user_session for %s could not be decrypted", user_uid)

    # Update last used (keep the encrypted session blob intact for next use)
    data["last_used_at"] = int(time.time())
    cache.set(
        f"{_API_TOKEN_PREFIX}{user_uid}:{token_id}",
        js_dumps({k: v for k, v in data.items() if k not in ("hash", "_user")}),
        ttl=86400 * 365,
    )

    return user_uid, data


# ── Impersonation token management (admin tier) ─────────────────────────────

def log_impersonation_use(issuer_uid: str, target_uid: str, endpoint: str | None, request_id: str | None = None) -> None:
    """Audit line for every request executed under a sogoimp_ token.

    Spec contract (agent-auth: Impersonation audit trail): the line records
    the issuing admin, the acted-as user, the endpoint and the request id.
    """
    logger_auth.info(
        "API-token impersonation: admin=%s acted_as=%s endpoint=%s request_id=%s",
        issuer_uid, target_uid, endpoint, request_id,
    )


def create_impersonation_token(
    admin_uid: str,
    target_user: User,
    scopes: list,
    label: str,
    expires_at: int | None = None,
) -> tuple[str, dict]:
    """Issue a ``sogoimp_`` token bound to (admin, target user).

    The token acts as the *target* user (target's ACLs apply); every use is
    expected to be audit-logged with the issuing admin. Returns the raw token
    (shown once) and its metadata.
    """
    cache = sogo_cache()
    token = _generate_impersonation_token()
    token_hash = _hash_token(token)
    token_id = token_hash[:16]

    data = {
        "label": label,
        "scopes": scopes,
        "created_at": int(time.time()),
        "expires_at": expires_at,
        "last_used_at": None,
        "hash": token_hash,
        "issuer_uid": admin_uid,
        "target_uid": target_user.uid,
    }

    # Hash lookup maps to the TARGET user: requests act as the target.
    cache.set(f"{_API_TOKEN_PREFIX}{target_user.uid}:{token_id}", js_dumps(data), ttl=86400 * 365)
    cache.set(f"{_API_TOKEN_HASH_PREFIX}{token_hash}", f"{target_user.uid}:{token_id}", ttl=86400 * 365)

    # Index under the issuing admin (token_id -> target_uid) so admins can
    # list and revoke the tokens they issued.
    imp_index_raw = cache.get(f"{_API_TOKEN_IMP_INDEX}{admin_uid}", dict)
    imp_index: dict = imp_index_raw if isinstance(imp_index_raw, dict) else {}
    imp_index[token_id] = target_user.uid
    cache.set(f"{_API_TOKEN_IMP_INDEX}{admin_uid}", imp_index, ttl=86400 * 365)

    logger_api.info(
        "Impersonation token created: admin=%s target=%s token=%s**",
        admin_uid, target_user.uid, token_id[:8],
    )
    return token, data


def list_impersonation_tokens(admin_uid: str) -> list[dict]:
    """List impersonation tokens issued by an admin (metadata, never secrets)."""
    cache = sogo_cache()
    imp_index_raw = cache.get(f"{_API_TOKEN_IMP_INDEX}{admin_uid}", dict)
    imp_index: dict = imp_index_raw if isinstance(imp_index_raw, dict) else {}
    tokens = []
    for token_id, target_uid in imp_index.items():
        raw = cache.get(f"{_API_TOKEN_PREFIX}{target_uid}:{token_id}", str)
        if not raw:
            continue
        try:
            data = js_loads(raw)
        except Exception:
            continue
        data.pop("hash", None)
        data["id"] = token_id
        tokens.append(data)
    return tokens


def revoke_impersonation_token(admin_uid: str, token_id: str) -> bool:
    """Revoke an impersonation token issued by the admin. Returns True on success."""
    cache = sogo_cache()
    imp_index_raw = cache.get(f"{_API_TOKEN_IMP_INDEX}{admin_uid}", dict)
    imp_index: dict = imp_index_raw if isinstance(imp_index_raw, dict) else {}
    target_uid = imp_index.get(token_id)
    if not target_uid:
        return False
    raw = cache.get(f"{_API_TOKEN_PREFIX}{target_uid}:{token_id}", str)
    if not raw:
        return False
    try:
        data = js_loads(raw)
    except Exception:
        return False
    cache.delete(f"{_API_TOKEN_HASH_PREFIX}{data.get('hash', '')}")
    cache.delete(f"{_API_TOKEN_PREFIX}{target_uid}:{token_id}")
    imp_index.pop(token_id, None)
    cache.set(f"{_API_TOKEN_IMP_INDEX}{admin_uid}", imp_index, ttl=86400 * 365)
    logger_api.info("Impersonation token revoked: admin=%s token=%s**", admin_uid, token_id[:8])
    return True
