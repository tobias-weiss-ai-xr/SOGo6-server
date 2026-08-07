"""Webhook management API for admins."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate

from app.service.webhook.WebhookService import WebhookService
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User

blp = Blueprint("Webhooks", __name__, url_prefix="/webhooks")

VALID_EVENTS = [
    "mail.received", "mail.sent", "mail.deleted",
    "calendar.created", "calendar.updated", "calendar.deleted",
    "contact.created", "contact.updated", "contact.deleted",
    "user.created", "user.updated", "user.deleted",
]


class WebhookSchema(Schema):
    url = fields.String(required=True, metadata={"description": "Target URL for the webhook"})
    events = fields.List(fields.String(validate=validate.OneOf(VALID_EVENTS)), required=True, metadata={"description": "Event types to subscribe to"})
    secret = fields.String(load_default="", metadata={"description": "Secret for HMAC signing"})
    name = fields.String(load_default="", metadata={"description": "Human-readable name"})


@blp.route("")
class ApiWebhookListCreate(MethodView):
    """List or create webhooks."""

    def get(self) -> ResponseReturnValue:
        svc = WebhookService()
        return create_api_base_response({"webhooks": svc.list_webhooks()})

    @blp.arguments(WebhookSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        svc = WebhookService()
        hook = svc.add_webhook(
            url=body["url"],
            events=body["events"],
            secret=body.get("secret", ""),
            name=body.get("name", ""),
        )
        return create_api_base_response(hook, code=201)


@blp.route("/<string:hook_id>")
class ApiWebhookDetail(MethodView):
    """Get, update, or delete a webhook."""

    def delete(self, hook_id: str) -> ResponseReturnValue:
        svc = WebhookService()
        if svc.remove_webhook(hook_id):
            return create_api_base_response({"status": "deleted"})
        return create_api_base_response(None, err.ERROR_NOT_FOUND)
