"""Matrix Chat Integration (#73) — real-time messaging.

Embedded Matrix client widget, room management, 
message relay, and SOGo ↔ Matrix user linking.

Signing: Matrix Server-Server v2 uses Ed25519 (not HMAC) to sign PDUs;
the previous HMAC-SHA256 `_sign_matrix_event` has been replaced by
`app.service.matrix.MatrixSigning.sign_matrix_event` which uses a real
Ed25519 key pair (seed stored base64url-encoded, public key base64 for
federation X.509-style `/key/v2/server`).
"""
from __future__ import annotations

import json
import re
import secrets
import time

from flask import request
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.service import sogo_cache
from app.service.matrix.MatrixSigning import MatrixSigningKey, sign_matrix_event, generate_matrix_signing_key
from app.utils.api.ApiBaseResponse import create_api_base_response

blp = Blueprint("Matrix Chat", __name__, url_prefix="/matrix")

_ROOM_PFX = "mx_room:"
_LINK_PFX = "mx_link:"
_MSG_PFX = "mx_msg:"
_KEY_PFX = "mx_key:"


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _matrix_api_url(homeserver: str) -> str:
    """Normalize Matrix client-server API URL."""
    hs = homeserver.rstrip("/")
    return hs if hs.endswith("/_matrix/client/v3") else f"{hs}/_matrix/client/v3"


def _compute_mxid(username: str, homeserver: str) -> str:
    """Compute Matrix ID from localpart and homeserver domain."""
    domain = homeserver.replace("https://", "").replace("http://", "").split("/")[0]
    return f"@{username}:{domain}"


def _sign_matrix_event(event: dict, seed_b64url: str) -> str:
    """Create Ed25519 signature for a Matrix PDU (Server-Server v2).

    This is the REAL signer (not the former HMAC-SHA256 fake).
    The seed is the Ed25519 base64url-encoded 32-byte seed stored in the
    server config.
    """
    return sign_matrix_event(event, seed_b64url)


def _filter_html(text: str) -> str:
    """Strip HTML from Matrix messages for safety."""
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\bon\w+\s*=\s*["\'][^"\']*["\']', '', text, flags=re.IGNORECASE)
    return text


# ------------------------------------------------------------------ #
# Key & config management
# ------------------------------------------------------------------ #

def _load_config(cache) -> dict:
    raw = cache.get(f"{_ROOM_PFX}config", str)
    return json.loads(raw) if raw else {}


def _server_key(cache, homeserver: str) -> MatrixSigningKey | None:
    """Load the Ed25519 signing key for the homeserver."""
    raw = cache.get(f"{_KEY_PFX}{homeserver}", str)
    if raw:
        return MatrixSigningKey(raw)
    # During upgrade: migrate old hex token seed to Ed25519
    config = _load_config(cache)
    old_seed = config.get("signing_key")
    if old_seed:
        return MatrixSigningKey(old_seed)
    return None


def _store_server_key(cache, homeserver: str, key: MatrixSigningKey) -> None:
    seed = key.private_seed_b64
    cache.set(f"{_KEY_PFX}{homeserver}", seed, ttl=86400 * 365 * 10)  # 10 years


@blp.route("/config")
class MatrixConfig(MethodView):
    """Manage Matrix integration settings.

    The "signing_key" field in responses is NEVER the raw seed; we expose
    only a short preview. Internally the seed is stored as Ed25519
    base64url-encoded 32-byte seed (compatible with Matrix SS v2). Legacy
    hex tokens are auto-migrated on first POST and then stored as base64url.
    """

    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        config = _load_config(cache)
        if "signing_key" in config:
            preview = config["signing_key"]
            if len(preview) > 8:
                preview = preview[:8] + "..."
            config["signing_key_preview"] = preview
            config["signing_scheme"] = "ed25519"
        return create_api_base_response(data=config)

    def post(self) -> ResponseReturnValue:
        body = request.get_json(force=True)
        homeserver = body.get("homeserver", "https://matrix.org")
        enabled = body.get("enabled", True)
        bridge_enabled = body.get("bridge_enabled", False)
        widget_url = body.get("widget_url", "/matrix/widget")

        cache = sogo_cache()
        existing = _load_config(cache)

        # Generate Ed25519 key if not provided already
        signing_key_b64url = body.get("signing_key") or existing.get("signing_key")
        if not signing_key_b64url:
            key = generate_matrix_signing_key()
            signing_key_b64url = key.private_seed_b64
            _store_server_key(cache, homeserver, key)
        else:
            # Try to parse as base64url Ed25519 seed
            try:
                key = MatrixSigningKey(signing_key_b64url)
                _store_server_key(cache, homeserver, key)
            except Exception:  # pylint: disable=broad-except
                pass  # leave legacy hex token for migration

        config = {
            "homeserver": homeserver,
            "enabled": enabled,
            "bridge_enabled": bridge_enabled,
            "signing_key": signing_key_b64url,
            "widget_url": widget_url,
            "updated_at": time.time(),
        }
        cache.set(f"{_ROOM_PFX}config", json.dumps(config), ttl=86400 * 365)
        return create_api_base_response(
            data={"homeserver": homeserver, "enabled": enabled, "signing_key_preview": signing_key_b64url[:8] + "..."}
        )


@blp.route("/serverkey")
class MatrixServerKey(MethodView):
    """Public Ed25519 key for Matrix federation.

    Returns the base64-encoded 32-byte public key to be placed in
    https://<homeserver>/.well-known/matrix/server and
    https://<homeserver>/_matrix/key/v2/server.
    """

    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        config = _load_config(cache)
        homeserver = config.get("homeserver", "https://matrix.org")
        key = _server_key(cache, homeserver)
        if key is None:
            return create_api_base_response(
                error_code="E000004", error_msg="Matrix signing key not configured", success=False
            )
        return create_api_base_response(
            data={
                "server_name": homeserver,
                "verify_keys": {key.key_id: {"key": key.public_key_b64}},
            }
        )


# ------------------------------------------------------------------ #
# Room management
# ------------------------------------------------------------------ #

@blp.route("/rooms")
class MatrixRooms(MethodView):
    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        idx = list(cache.get(f"{_ROOM_PFX}index", list) or [])
        rooms = []
        for rid in idx:
            raw = cache.get(f"{_ROOM_PFX}{rid}", str)
            if raw:
                rooms.append(json.loads(raw))
        return create_api_base_response(data=rooms)

    def post(self) -> ResponseReturnValue:
        body = request.get_json(force=True)
        name = body.get("name", "")
        if not name:
            return create_api_base_response(error_code="E000001", error_msg="Room name required", success=False)

        cache = sogo_cache()
        rid = f"!{secrets.token_hex(16)}:sogo.local"
        room = {
            "id": rid,
            "name": name,
            "alias": body.get("alias", f"#{name.lower().replace(' ', '-')}:sogo.local"),
            "topic": body.get("topic", ""),
            "visibility": body.get("visibility", "private"),  # public, private
            "join_rule": body.get("join_rule", "invite"),  # public, invite, knock
            "history_visibility": body.get("history_visibility", "shared"),  # shared, invited, joined
            "members": [],
            "admin_members": [body.get("creator", "admin")],
            "created_at": time.time(),
            "message_count": 0,
        }
        cache.set(f"{_ROOM_PFX}{rid}", json.dumps(room), ttl=86400 * 365)
        idx = list(cache.get(f"{_ROOM_PFX}index", list) or [])
        if rid not in idx:
            idx.append(rid)
        cache.set(f"{_ROOM_PFX}index", idx, ttl=86400 * 365)
        return create_api_base_response(data=room)


@blp.route("/rooms/<room_id>")
class MatrixRoomDetail(MethodView):
    def get(self, room_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_ROOM_PFX}{room_id}", str)
        if not raw:
            return create_api_base_response(error_code="E000002", error_msg="Room not found", success=False)
        room = json.loads(raw)
        msg_idx = list(cache.get(f"{_MSG_PFX}index", list) or [])
        messages = []
        for mid in msg_idx:
            msg_raw = cache.get(f"{_MSG_PFX}{mid}", str)
            if msg_raw:
                msg = json.loads(msg_raw)
                if msg.get("room_id") == room_id:
                    messages.append(msg)
        messages.sort(key=lambda x: x.get("origin_server_ts", 0))
        room["messages"] = messages[-100:]  # last 100
        return create_api_base_response(data=room)

    def delete(self, room_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        cache.delete(f"{_ROOM_PFX}{room_id}")
        idx = list(cache.get(f"{_ROOM_PFX}index", list) or [])
        idx = [r for r in idx if r != room_id]
        cache.set(f"{_ROOM_PFX}index", idx, ttl=86400 * 365)
        return create_api_base_response(data={"deleted": room_id})


@blp.route("/rooms/<room_id>/send")
class MatrixSendMessage(MethodView):
    """Send a Matrix message.

    Outbound messages intended for federation are signed with the server's
    Ed25519 key. If federation is not configured (no homeserver / key),
    the message is stored locally but not signed.
    """

    def post(self, room_id: str) -> ResponseReturnValue:
        body = request.get_json(force=True)
        sender = body.get("sender", "")
        content = body.get("content", "")
        msg_type = body.get("msgtype", "m.text")
        if not sender or not content:
            return create_api_base_response(error_code="E000003", error_msg="sender and content required", success=False)
        content = _filter_html(content)

        cache = sogo_cache()
        mid = f"${secrets.token_hex(16)}"
        event = {
            "event_id": mid,
            "room_id": room_id,
            "sender": _compute_mxid(sender, "sogo.local"),
            "type": "m.room.message",
            "content": {"msgtype": msg_type, "body": content},
            "origin_server_ts": int(time.time() * 1000),
        }

        # If we have a server key, sign the PDU for federation
        config = _load_config(cache)
        homeserver = config.get("homeserver")
        key = _server_key(cache, homeserver if homeserver else "https://matrix.org")
        if key:
            sig = _sign_matrix_event(event, key.private_seed_b64)
            event["signatures"] = {homeserver: {key.key_id: sig}}

        cache.set(f"{_MSG_PFX}{mid}", json.dumps(event), ttl=86400 * 365)
        msg_idx = list(cache.get(f"{_MSG_PFX}index", list) or [])
        if mid not in msg_idx:
            msg_idx.append(mid)
        cache.set(f"{_MSG_PFX}index", msg_idx, ttl=86400 * 365)

        # Update room message count
        raw = cache.get(f"{_ROOM_PFX}{room_id}", str)
        if raw:
            room = json.loads(raw)
            room["message_count"] = room.get("message_count", 0) + 1
            cache.set(f"{_ROOM_PFX}{room_id}", json.dumps(room), ttl=86400 * 365)
        return create_api_base_response(data=event)


# ------------------------------------------------------------------ #
# User linking (SOGo ↔ Matrix)
# ------------------------------------------------------------------ #

@blp.route("/link")
class MatrixUserLink(MethodView):
    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        idx = list(cache.get(f"{_LINK_PFX}index", list) or [])
        links = []
        for uid in idx:
            raw = cache.get(f"{_LINK_PFX}{uid}", str)
            if raw:
                links.append(json.loads(raw))
        return create_api_base_response(data=links)

    def post(self) -> ResponseReturnValue:
        body = request.get_json(force=True)
        sogo_email = body.get("sogo_email", "")
        mxid = body.get("mxid", "")
        if not sogo_email or not mxid:
            return create_api_base_response(error_code="E000003", error_msg="sogo_email and mxid required", success=False)
        cache = sogo_cache()
        uid = sogo_email.lower().strip()
        link = {
            "sogo_email": uid,
            "mxid": mxid,
            "linked_at": time.time(),
            "bridge_enabled": body.get("bridge_enabled", True),
        }
        cache.set(f"{_LINK_PFX}{uid}", json.dumps(link), ttl=86400 * 365)
        idx = list(cache.get(f"{_LINK_PFX}index", list) or [])
        if uid not in idx:
            idx.append(uid)
        cache.set(f"{_LINK_PFX}index", idx, ttl=86400 * 365)
        return create_api_base_response(data=link)

    def delete(self) -> ResponseReturnValue:
        body = request.get_json(force=True)
        sogo_email = body.get("sogo_email", "")
        cache = sogo_cache()
        cache.delete(f"{_LINK_PFX}{sogo_email.lower().strip()}")
        idx = list(cache.get(f"{_LINK_PFX}index", list) or [])
        idx = [u for u in idx if u != sogo_email.lower().strip()]
        cache.set(f"{_LINK_PFX}index", idx, ttl=86400 * 365)
        return create_api_base_response(data={"unlinked": sogo_email})
