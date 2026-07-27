from __future__ import annotations

from typing import Any

from flask import g
from flask.views import MethodView
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate

from app.module.admin.ModuleSharedMailbox import ModuleSharedMailbox
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import RequestException

blp = Blueprint(
    "Shared Mailboxes",
    __name__,
    url_prefix="/shared-mailboxes",
    description="Team/shared mailbox management (e.g., support@, info@)",
)


# ── Schemas ───────────────────────────────────────────────────────────────────


class SharedMailboxCreateSchema(Schema):
    """Request body for creating a shared mailbox."""
    email = fields.Email(required=True, metadata={"example": "support@example.org"})
    name = fields.String(required=True, metadata={"example": "Support Team"})
    description = fields.String(load_default="", metadata={"example": "Customer support shared inbox"})
    member_uids = fields.List(fields.Email(), load_default=None,
                              metadata={"description": "Initial member email addresses"})


class SharedMailboxUpdateSchema(Schema):
    """Request body for updating a shared mailbox."""
    name = fields.String()
    description = fields.String()
    is_active = fields.Boolean()
    member_uids = fields.List(fields.Email())


class SharedMailboxMemberSchema(Schema):
    """Request body for adding/removing a member."""
    user_uid = fields.Email(required=True, metadata={"example": "user@example.org"})


class SharedMailboxResponseDataSchema(Schema):
    """Response data for a shared mailbox."""
    id = fields.String()
    email = fields.Email()
    name = fields.String()
    description = fields.String()
    member_uids = fields.List(fields.Email())
    is_active = fields.Boolean()
    created_at = fields.String()
    updated_at = fields.String()


# ── Helper ────────────────────────────────────────────────────────────────────


def _get_module() -> ModuleSharedMailbox:
    if not hasattr(g, "_shared_mailbox_module"):
        from app.manager.db.ClientPostgreSQL import ClientPostgreSQL

        process = g.process_settings
        db = ClientPostgreSQL(process.get_db_settings())
        g._shared_mailbox_module = ModuleSharedMailbox(db)
    return g._shared_mailbox_module


# ── Endpoints ─────────────────────────────────────────────────────────────────


@blp.route("")
class ApiSharedMailboxList(MethodView):
    @blp.response(200)
    def get(self) -> dict[str, Any]:
        """List all shared mailboxes."""
        module = _get_module()
        mailboxes = module.get_all()
        return create_api_base_response({"mailboxes": mailboxes, "total_count": len(mailboxes)})

    @blp.arguments(SharedMailboxCreateSchema, error_status_code=400)
    @blp.response(201)
    def post(self, data: dict) -> dict[str, Any]:
        """Create a new shared mailbox."""
        module = _get_module()
        try:
            mailbox = module.create(
                email=data["email"],
                name=data["name"],
                description=data.get("description", ""),
                member_uids=data.get("member_uids"),
            )
            return create_api_base_response(mailbox, code=201)
        except RequestException as ex:
            return create_api_base_response(None, ex.error)


@blp.route("/<string:mailbox_id>")
class ApiSharedMailboxDetail(MethodView):
    @blp.response(200)
    def get(self, mailbox_id: str) -> dict[str, Any]:
        """Get a shared mailbox by ID."""
        module = _get_module()
        mailbox = module.get_by_id(mailbox_id)
        if not mailbox:
            return create_api_base_response(None, {"code": "S000314", "msg": "Shared Mailbox Not Found"})
        return create_api_base_response(mailbox)

    @blp.arguments(SharedMailboxUpdateSchema, error_status_code=400)
    @blp.response(200)
    def put(self, data: dict, mailbox_id: str) -> dict[str, Any]:
        """Update a shared mailbox."""
        module = _get_module()
        try:
            mailbox = module.update(mailbox_id, data)
            return create_api_base_response(mailbox)
        except RequestException as ex:
            return create_api_base_response(None, ex.error)

    @blp.response(200)
    def delete(self, mailbox_id: str) -> dict[str, Any]:
        """Delete a shared mailbox."""
        module = _get_module()
        try:
            module.delete(mailbox_id)
            return create_api_base_response({"deleted": True})
        except RequestException as ex:
            return create_api_base_response(None, ex.error)


@blp.route("/<string:mailbox_id>/members")
class ApiSharedMailboxMembers(MethodView):
    @blp.response(200)
    def get(self, mailbox_id: str) -> dict[str, Any]:
        """List members of a shared mailbox."""
        module = _get_module()
        mailbox = module.get_by_id(mailbox_id)
        if not mailbox:
            return create_api_base_response(None, {"code": "S000314", "msg": "Shared Mailbox Not Found"})
        return create_api_base_response({"members": mailbox.get("member_uids", [])})

    @blp.arguments(SharedMailboxMemberSchema, error_status_code=400)
    @blp.response(200)
    def post(self, data: dict, mailbox_id: str) -> dict[str, Any]:
        """Add a member to a shared mailbox."""
        module = _get_module()
        try:
            mailbox = module.add_member(mailbox_id, data["user_uid"])
            return create_api_base_response(mailbox)
        except RequestException as ex:
            return create_api_base_response(None, ex.error)


@blp.route("/<string:mailbox_id>/members/<string:user_uid>")
class ApiSharedMailboxMemberDelete(MethodView):
    @blp.response(200)
    def delete(self, mailbox_id: str, user_uid: str) -> dict[str, Any]:
        """Remove a member from a shared mailbox."""
        module = _get_module()
        try:
            mailbox = module.remove_member(mailbox_id, user_uid)
            return create_api_base_response(mailbox)
        except RequestException as ex:
            return create_api_base_response(None, ex.error)
