"""File Sharing (#52) — MinIO-based secure link sharing.

Users can upload files and generate shareable links with expiration,
password protection, and download tracking.
"""
from __future__ import annotations

import json
import secrets
import time
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.service import sogo_cache
from app.utils.api.ApiBaseResponse import create_api_base_response

blp = Blueprint("File Sharing", __name__, url_prefix="/files")


class FileShareCreateSchema(Schema):
    filename = fields.String(required=True)
    size = fields.Integer(required=True)
    expires_in_days = fields.Integer(load_default=7)
    password = fields.String(load_default="", metadata={"description": "Optional password protection"})


@blp.route("/shares")
class ApiFileShareListCreate(MethodView):
    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get("file_shares:index", list)
        index = raw if isinstance(raw, list) else []
        shares = []
        for sid in index:
            raw_s = cache.get(f"file_share:{sid}", str)
            if raw_s:
                try:
                    s = json.loads(raw_s)
                    s.pop("password", None)  # Never expose password
                    shares.append(s)
                except Exception:
                    continue
        return create_api_base_response({"shares": shares})

    @blp.arguments(FileShareCreateSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        cache = sogo_cache()
        share_id = secrets.token_hex(10)
        token = secrets.token_hex(20)
        expires_at = int(time.time()) + body.get("expires_in_days", 7) * 86400
        share = {
            "id": share_id,
            "filename": body["filename"],
            "size": body["size"],
            "token": token,
            "password": body.get("password", ""),
            "downloads": 0,
            "expires_at": expires_at,
            "created_at": int(time.time()),
        }
        cache.set(f"file_share:{share_id}", json.dumps(share), ttl=86400 * (body.get("expires_in_days", 7) + 1))
        idx = list(cache.get("file_shares:index", list) or [])
        idx.append(share_id)
        cache.set("file_shares:index", idx, ttl=86400 * 365)
        return create_api_base_response({
            "id": share_id,
            "token": token,
            "url": f"/files/share/{share_id}?token={token}",
            "expires_at": expires_at,
        }, code=201)
