"""Admin-issued impersonation tokens — scoped ``sogoimp_`` bearer tokens.

An authenticated admin can issue a token bound to a target user; requests
presenting it execute as the target user under the target's ACLs. Every use
is audit-logged (issuer + acted-as) by the auth middleware. The raw token is
shown once on creation; only its SHA-256 hash is stored.
"""
from __future__ import annotations

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate

from app.api.v1.user.ApiApiTokens import (
    VALID_SCOPES,
    create_impersonation_token,
    list_impersonation_tokens,
    revoke_impersonation_token,
)
from app.auth.Admin import AdminAnonymous
from app.interface.admin.InterfaceApiAdminUser import InterfaceApiAdminUser
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import ApiBaseResponse, create_api_base_response

blp = Blueprint(
    "Impersonation Tokens",
    __name__,
    url_prefix="/impersonation-tokens",
    description="Admin-issued tokens that act as a target user (audited)",
)


# ── Schemas ──────────────────────────────────────────────────────────────────

class ImpersonationTokenCreateSchema(Schema):
    target_uid = fields.String(required=True, metadata={"description": "UID (mail) of the user to act as"})
    scopes = fields.List(
        fields.String(validate=validate.OneOf(VALID_SCOPES)),
        load_default=["read"],
        metadata={"description": f"Scopes: {', '.join(VALID_SCOPES)}"},
    )
    label = fields.String(required=True, metadata={"description": "Human-readable label for the token"})
    expires_at = fields.Integer(
        load_default=None, allow_none=True,
        metadata={"description": "Unix timestamp when the token expires. null = never expires."},
    )


class ImpersonationTokenCreateResponseSchema(Schema):
    id = fields.String()
    label = fields.String()
    token = fields.String()
    target_uid = fields.String()
    scopes = fields.List(fields.String())
    created_at = fields.Integer()
    expires_at = fields.Integer(allow_none=True)


class ImpersonationTokenItemSchema(Schema):
    id = fields.String()
    label = fields.String()
    target_uid = fields.String()
    scopes = fields.List(fields.String())
    created_at = fields.Integer()
    expires_at = fields.Integer(allow_none=True)
    last_used_at = fields.Integer(allow_none=True)


class ImpersonationTokenListDataSchema(Schema):
    tokens = fields.List(fields.Nested(ImpersonationTokenItemSchema()))


class ImpersonationTokenListResponseSchema(ApiBaseResponse):
    """Envelope-wrapped token list (matches create + user-token convention).

    The ``data` field carries ``{tokens: [...]}``; serializing through this
    schema keeps ``error_code``/``error_msg``/``data`` in the body instead of
    truncating the envelope to ``{}`` (the bare-``tokens`` shape previously
    declared here silently dropped every field).
    """

    data = fields.Nested(ImpersonationTokenListDataSchema())


# ── Endpoints ────────────────────────────────────────────────────────────────

@blp.before_request
def _require_admin() -> ResponseReturnValue | None:
    """Impersonation management is strictly admin-tier."""
    admin = getattr(g, "admin", None)
    if admin is None or isinstance(admin, AdminAnonymous):
        return create_api_base_response(error=err.ERROR_AUTHENTICATED_ROUTE)
    return None


@blp.route("")
class ImpersonationTokenListCreate(MethodView):
    """List or create impersonation tokens."""

    @blp.response(200, ImpersonationTokenListResponseSchema)
    def get(self) -> ResponseReturnValue:
        """List impersonation tokens issued by the current admin."""
        tokens = list_impersonation_tokens(g.admin.uid)
        return create_api_base_response({"tokens": tokens})

    @blp.arguments(ImpersonationTokenCreateSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """Issue an impersonation token acting as the target user. Raw token shown once."""
        from app.auth.User import User
        from app.utils.strings import get_domain_from_mail

        target_uid = body["target_uid"]

        # The target must resolve to a real directory user.
        interface = InterfaceApiAdminUser(process_setting=g.process_settings)
        _, status = interface.get_user(target_uid)
        if status >= 400:
            return create_api_base_response(None, err.ERROR_IMPERSONATION_TARGET_INVALID)

        target_user = User(target_uid, domain=get_domain_from_mail(target_uid))
        token, data = create_impersonation_token(
            admin_uid=g.admin.uid,
            target_user=target_user,
            scopes=body["scopes"],
            label=body["label"],
            expires_at=body.get("expires_at"),
        )
        return create_api_base_response({
            "id": data["hash"][:16],
            "label": data["label"],
            "token": token,
            "target_uid": target_uid,
            "scopes": data["scopes"],
            "created_at": data["created_at"],
            "expires_at": data["expires_at"],
        }, code=201)


@blp.route("/<string:token_id>")
class ImpersonationTokenDetail(MethodView):
    """Revoke an impersonation token."""

    def delete(self, token_id: str) -> ResponseReturnValue:
        """Revoke an impersonation token issued by the current admin."""
        if not revoke_impersonation_token(g.admin.uid, token_id):
            return create_api_base_response(None, err.ERROR_API_TOKEN_NOT_FOUND)
        return create_api_base_response({"status": "revoked"})
