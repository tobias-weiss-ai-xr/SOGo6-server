"""Web Push Notification API — subscribe/unsubscribe + VAPID public key."""
from __future__ import annotations

from typing import TYPE_CHECKING

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.svc.push.PushService import PushService
from app.svc.push.PushService import get_vapid_keys
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User

blp = Blueprint("Push Notifications", __name__, url_prefix="/push")


class PushSubscriptionSchema(Schema):
    """Schema for push subscription."""
    endpoint = fields.String(required=True)
    keys = fields.Dict(required=True, keys=fields.String(), values=fields.String())


@blp.route("/vapid-public-key")
class ApiVapidPublicKey(MethodView):
    """Return the VAPID public key for push subscription."""

    def get(self) -> ResponseReturnValue:
        """Return the application's VAPID public key."""
        _, public_key = get_vapid_keys()
        return {"public_key": public_key}


@blp.route("/subscribe")
class ApiPushSubscribe(MethodView):
    """Subscribe to push notifications."""

    @blp.arguments(PushSubscriptionSchema)
    def post(self, subscription: dict) -> ResponseReturnValue:
        """Store a push subscription for the current user."""
        user: User = g.user
        service = PushService()
        service.subscribe(user.uid, subscription)
        logger_api.info("Push subscribed for user %s", user.uid)
        return {"status": "subscribed"}


@blp.route("/unsubscribe")
class ApiPushUnsubscribe(MethodView):
    """Unsubscribe from push notifications."""

    @blp.arguments(PushSubscriptionSchema(only=("endpoint",)))
    def post(self, data: dict) -> ResponseReturnValue:
        """Remove a push subscription."""
        user: User = g.user
        service = PushService()
        service.unsubscribe(user.uid, data["endpoint"])
        logger_api.info("Push unsubscribed for user %s", user.uid)
        return {"status": "unsubscribed"}
