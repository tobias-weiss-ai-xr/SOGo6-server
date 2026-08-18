"""
API endpoints for application-password management.

Provides:
  - GET  /auth/app-passwords           — list all app passwords for the user
  - POST /auth/app-passwords           — create a new app password (returns token shown once)
  - POST /auth/app-passwords/delete    — revoke (delete) an app password by ID
"""

from __future__ import annotations

from typing import Any

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.auth.User import User
from app.interface.auth.InterfaceAppPassword import InterfaceAppPassword
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import RequestException

blp = Blueprint("AppPassword", __name__, url_prefix="/auth/app-passwords")


# ── Schemas ──────────────────────────────────────────────────────────────────


class AppPasswordRecordSchema(Schema):
    """App-password metadata (no token)."""

    id = fields.Integer()
    label = fields.String()
    created_at = fields.Integer()
    last_used = fields.Integer()
    expires_at = fields.Integer(allow_none=True)


class CreateRequestSchema(Schema):
    """Request body for creating an app password."""

    label = fields.String(required=True, metadata={"description": "e.g. Thunderbird on Laptop"})


class CreateResponseSchema(Schema):
    """Response after creating an app password (token shown once)."""

    token = fields.String(
        metadata={"description": "Raw app-password token — show to user once, never stored"},
    )
    app_password = fields.Nested(AppPasswordRecordSchema)


class DeleteRequestSchema(Schema):
    """Request body for revoking an app password."""

    id = fields.Integer(required=True, metadata={"description": "App-password ID to revoke"})


# ── Before request: inject interface ─────────────────────────────────────────


@blp.before_request
def init_app_password_interface() -> None:
    """Initialise the app-password interface on every request."""
    if "app_pw_inter" not in g:
        from app.manager.db.ClientSQL import ClientSQL
        from app.config.settings.ProcessSetting import process_config

        db = ClientSQL(
            process_config.SOGO_P_DB_HOST,
            process_config.SOGO_P_DB_PORT,
            process_config.SOGO_P_DB_USER,
            process_config.SOGO_P_DB_PWD,
            process_config.SOGO_P_DB_NAME,
        )
        g.app_pw_inter = InterfaceAppPassword(db)


# ── Endpoints ────────────────────────────────────────────────────────────────


@blp.route("/")
class ApiAppPasswordList(MethodView):
    """(Authenticated) List and create app passwords."""

    @blp.response(200, AppPasswordRecordSchema(many=True))
    def get(self) -> list[dict[str, Any]]:
        """Return all app passwords for the authenticated user."""
        user: User = g.user
        inter: InterfaceAppPassword = g.app_pw_inter
        return inter.list(user.uid)

    @blp.arguments(CreateRequestSchema, error_status_code=400)
    @blp.response(200, CreateResponseSchema)
    def post(self, new_data: dict[str, Any]) -> ResponseReturnValue:
        """Create a new app password. The token is returned once."""
        user: User = g.user
        inter: InterfaceAppPassword = g.app_pw_inter
        try:
            result = inter.create(user.uid, new_data["label"])
        except RequestException as exc:
            return create_api_base_response(None, exc.error)
        return create_api_base_response(result)


@blp.route("/delete")
class ApiAppPasswordDelete(MethodView):
    """(Authenticated) Revoke an app password by ID."""

    @blp.arguments(DeleteRequestSchema, error_status_code=400)
    @blp.response(200)
    def post(self, new_data: dict[str, Any]) -> ResponseReturnValue:
        """Revoke (delete) an app password."""
        user: User = g.user
        inter: InterfaceAppPassword = g.app_pw_inter
        try:
            inter.delete(new_data["id"], user.uid)
        except RequestException as exc:
            return create_api_base_response(None, exc.error)
        return create_api_base_response(None)
