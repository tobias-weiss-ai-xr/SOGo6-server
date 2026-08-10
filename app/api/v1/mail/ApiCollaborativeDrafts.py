"""Collaborative Drafts (#49) — share draft emails for review before sending."""
from __future__ import annotations

import json
import secrets
import time
from typing import TYPE_CHECKING

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.service import sogo_cache
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User

blp = Blueprint("Collaborative Drafts", __name__, url_prefix="/shared-drafts")

_SHARED_DRAFT_PREFIX: str = "shared_draft:"


class SharedDraftCreateSchema(Schema):
    subject = fields.String(required=True)
    body = fields.String(required=True)
    recipients = fields.List(fields.String(), required=True, metadata={"description": "Email addresses of reviewers"})
    message = fields.String(load_default="", metadata={"description": "Message to reviewers"})


@blp.route("")
class ApiSharedDraftListCreate(MethodView):
    def get(self) -> ResponseReturnValue:
        user: User = g.user
        cache = sogo_cache()
        raw = cache.get(f"{_SHARED_DRAFT_PREFIX}index:{user.uid}", list)
        index = raw if isinstance(raw, list) else []
        drafts = []
        for did in index:
            raw_d = cache.get(f"{_SHARED_DRAFT_PREFIX}{did}", str)
            if raw_d:
                try:
                    drafts.append(json.loads(raw_d))
                except Exception:
                    continue
        return create_api_base_response({"drafts": drafts})

    @blp.arguments(SharedDraftCreateSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        user: User = g.user
        cache = sogo_cache()
        draft_id = secrets.token_hex(12)
        share_token = secrets.token_hex(20)
        draft = {
            "id": draft_id,
            "subject": body["subject"],
            "body": body["body"],
            "author": user.uid,
            "recipients": body["recipients"],
            "message": body.get("message", ""),
            "share_token": share_token,
            "status": "pending",
            "reviews": [],
            "created_at": int(time.time()),
        }
        cache.set(f"{_SHARED_DRAFT_PREFIX}{draft_id}", json.dumps(draft), ttl=86400 * 7)
        idx = list(cache.get(f"{_SHARED_DRAFT_PREFIX}index:{user.uid}", list) or [])
        idx.append(draft_id)
        cache.set(f"{_SHARED_DRAFT_PREFIX}index:{user.uid}", idx, ttl=86400 * 7)
        logger_api.info("Shared draft created: %s by %s", draft_id[:8], user.uid)
        return create_api_base_response(draft, code=201)


@blp.route("/<string:draft_id>/review")
class ApiSharedDraftReview(MethodView):
    """Review a shared draft (via share token)."""

    class ReviewSchema(Schema):
        reviewer = fields.String(required=True)
        comment = fields.String(load_default="")
        approved = fields.Boolean(required=True)

    @blp.arguments(ReviewSchema)
    def post(self, body: dict, draft_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_SHARED_DRAFT_PREFIX}{draft_id}", str)
        if not raw:
            return create_api_base_response(None, err.ERROR_NOT_FOUND)
        draft = json.loads(raw)
        draft["reviews"].append({
            "reviewer": body["reviewer"],
            "comment": body.get("comment", ""),
            "approved": body["approved"],
            "reviewed_at": int(time.time()),
        })
        cache.set(f"{_SHARED_DRAFT_PREFIX}{draft_id}", json.dumps(draft), ttl=86400 * 7)
        return create_api_base_response({"status": "review_recorded"})
