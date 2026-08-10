"""Webhook management API for admins."""
from __future__ import annotations

from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate

from app.service.webhook.WebhookService import WebhookService
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response

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


class WebhookUpdateSchema(Schema):
    url = fields.String(required=False, metadata={"description": "New target URL"})
    events = fields.List(fields.String(validate=validate.OneOf(VALID_EVENTS)), required=False, metadata={"description": "Event types to subscribe to"})
    secret = fields.String(required=False, metadata={"description": "New HMAC secret"})
    name = fields.String(required=False, metadata={"description": "New human-readable name"})
    enabled = fields.Boolean(required=False, metadata={"description": "Pause/resume delivery"})


class TestWebhookSchema(Schema):
    event = fields.String(
        validate=validate.OneOf(VALID_EVENTS),
        load_default="calendar.updated",
        metadata={"description": "Event type to simulate for the test delivery"},
    )


def _public_hook(hook: dict) -> dict:
    """Strip nothing for now; webhooks are admin-owned by construction."""
    return hook


@blp.route("")
class ApiWebhookListCreate(MethodView):
    """List or create webhooks."""

    def get(self) -> ResponseReturnValue:
        svc = WebhookService()
        return create_api_base_response({"webhooks": [_public_hook(h) for h in svc.list_webhooks()]})

    @blp.arguments(WebhookSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        svc = WebhookService()
        try:
            hook = svc.add_webhook(
                url=body["url"],
                events=body["events"],
                secret=body.get("secret", ""),
                name=body.get("name", ""),
            )
        except ValueError as exc:  # bad URL scheme
            return create_api_base_response(None, err.ERROR_VALIDATION_ERROR, error_msg=str(exc))
        return create_api_base_response(_public_hook(hook), code=201)


@blp.route("/<string:hook_id>")
class ApiWebhookDetail(MethodView):
    """Get, update, or delete a webhook."""

    def get(self, hook_id: str) -> ResponseReturnValue:
        svc = WebhookService()
        hook = svc.get_webhook(hook_id)
        if hook is None:
            return create_api_base_response(None, err.ERROR_RESOURCE_NOT_FOUND)
        return create_api_base_response(_public_hook(hook))

    @blp.arguments(WebhookUpdateSchema)
    def patch(self, body: dict, hook_id: str) -> ResponseReturnValue:
        svc = WebhookService()
        try:
            hook = svc.update_webhook(hook_id, **body)
        except ValueError as exc:
            return create_api_base_response(None, err.ERROR_VALIDATION_ERROR, error_msg=str(exc))
        if hook is None:
            return create_api_base_response(None, err.ERROR_RESOURCE_NOT_FOUND)
        return create_api_base_response(_public_hook(hook))

    @blp.arguments(TestWebhookSchema, location="json")
    def post(self, body: dict, hook_id: str) -> ResponseReturnValue:
        """Deliver a real test event to this webhook now (sync)."""
        svc = WebhookService()
        hook = svc.get_webhook(hook_id)
        if hook is None:
            return create_api_base_response(None, err.ERROR_RESOURCE_NOT_FOUND)
        event = body.get("event", "calendar.updated")
        delivered = svc.dispatch(event, {"test": True, "hook_id": hook_id})
        hook = svc.get_webhook(hook_id)  # refreshed stats
        return create_api_base_response({
            "event": event,
            "delivered": delivered > 0,
            "last_status": hook.get("last_status") if hook else None,
        })

    def delete(self, hook_id: str) -> ResponseReturnValue:
        svc = WebhookService()
        if svc.remove_webhook(hook_id):
            return create_api_base_response({"status": "deleted"})
        return create_api_base_response(None, err.ERROR_RESOURCE_NOT_FOUND)