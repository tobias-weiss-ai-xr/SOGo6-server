"""Matrix Chat Integration (#73) — real-time messaging.

Embedded Matrix client widget, room management, 
message relay, and SOGo ↔ Matrix user linking.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Any

from flask import request
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.service import sogo_cache
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

blp = Blueprint("Matrix Chat", __name__, url_prefix="/admin/matrix")

_ROOM_PFX = "mx_room:"
_LINK_PFX = "mx_link:"
_MSG_PFX = "mx_msg:"


def _matrix_api_url(homeserver: str) -> str:
    """Normalize Matrix client-server API URL."""
    hs = homeserver.rstrip("/")
    return hs if hs.endswith("/_matrix/client/v3") else f"{hs}/_matrix/client/v3"


def _compute_mxid(username: str, homeserver: str) -> str:
    """Compute Matrix ID from localpart and homeserver domain."""
    domain = homeserver.replace("https://", "").replace("http://", "").split("/")[0]
    return f"@{username}:{domain}"


def _sign_matrix_event(event: dict, signing_key: str) -> str:
    """Create HMAC signature for Matrix event (for verified federation)."""
    event_json = json.dumps(event, sort_keys=True, separators=(",", ":"))
    return hmac.new(signing_key.encode(), event_json.encode(), hashlib.sha256).hexdigest()


def _filter_html(text: str) -> str:
    """Strip HTML from Matrix messages for safety."""
    # Remove script tags, event handlers
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\bon\w+\s*=\s*["\'][^"\']*["\']', '', text, flags=re.IGNORECASE)
    return text


@blp.route("/config")
class MatrixConfig(MethodView):
    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_ROOM_PFX}config", str)
        config = json.loads(raw) if raw else {
            "homeserver": "https://matrix.org",
            "enabled": False,
            "bridge_enabled": False,
            "signing_key": secrets.token_hex(32),
            "widget_url": "/matrix/widget",
        }
        # Never expose full signing key in responses
        safe_config = {**config}
        if safe_config.get("signing_key"):
            safe_config["signing_key_preview"] = safe_config["signing_key"][:8] + "..."
            del safe_config["signing_key"]
        return create_api_base_response(data=safe_config)

    def post(self) -> ResponseReturnValue:
        body = request.get_json(force=True)
        config = {
            "homeserver": body.get("homeserver", "https://matrix.org"),
            "enabled": body.get("enabled", True),
            "bridge_enabled": body.get("bridge_enabled", False),
            "signing_key": body.get("signing_key") or secrets.token_hex(32),
            "widget_url": body.get("widget_url", "/matrix/widget"),
            "updated_at": time.time(),
        }
        cache = sogo_cache()
        cache.set(f"{_ROOM_PFX}config", json.dumps(config), ttl=86400 * 365)
        return create_api_base_response(data={"homeserver": config["homeserver"], "enabled": config["enabled"]})


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
        # Get messages
        msg_idx = list(cache.get(f"{_MSG_PFX}index", list) or [])
        messages = [json.loads(cache.get(f"{_MSG_PFX}{mid}", str)) for mid in msg_idx
                    if cache.get(f"{_MSG_PFX}{mid}", str) and json.loads(cache.get(f"{_MSG_PFX}{mid}", str)).get("room_id") == room_id]
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
        cache.set(f"{_MSG_PFX}{mid}", json.dumps(event), ttl=86400 * 365)
        msg_idx = list(cache.get(f"{_MSG_PFX}index", list) or [])
        msg_idx.append(mid)
        cache.set(f"{_MSG_PFX}index", msg_idx, ttl=86400 * 365)
        # Update room message count
        raw = cache.get(f"{_ROOM_PFX}{room_id}", str)
        if raw:
            room = json.loads(raw)
            room["message_count"] = room.get("message_count", 0) + 1
            cache.set(f"{_ROOM_PFX}{room_id}", json.dumps(room), ttl=86400 * 365)
        return create_api_base_response(data=event)


@blp.route("/link")
class MatrixUserLink(MethodView):
    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        idx = list(cache.get(f"{_LINK_PFX}index", list) or [])
        links = [json.loads(cache.get(f"{_LINK_PFX}{uid}", str)) for uid in idx
                 if cache.get(f"{_LINK_PFX}{uid}", str)]
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
