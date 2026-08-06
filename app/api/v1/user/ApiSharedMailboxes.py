from __future__ import annotations

from typing import Any

from flask import g
from flask.views import MethodView
from flask_smorest import Blueprint, Page, paginate
from marshmallow import Schema, fields

from app.module.admin.ModuleSharedMailbox import ModuleSharedMailbox
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.decorators import requires_auth

blp = Blueprint(
    "User Shared Mailboxes",
    __name__,
    url_prefix="/shared-mailboxes",
    description="User access to shared mailboxes they have membership in",
)


class SharedMailboxSchema(Schema):
    """Schema for shared mailbox response (user-facing)"""

    id = fields.String(dump_only=True)
    name = fields.String()
    email = fields.String()
    description = fields.String(allow_none=True)
    is_active = fields.Boolean()
    created_at = fields.DateTime()
    role = fields.String()  # user's role: member, admin


@blp.route("/")
class UserSharedMailboxesList(MethodView):
    """List all shared mailboxes the current user has access to"""

    @requires_auth
    @blp.response(200, SharedMailboxSchema(many=True))
    def get(self) -> list[dict[str, Any]]:
        """Get all shared mailboxes the user can access"""
        from app.module.admin.ModuleSharedMailbox import ModuleSharedMailbox

        shared_mailbox_module = ModuleSharedMailbox(g.db)
        user_uid = g.current_user.uid

        mailboxes = shared_mailbox_module.get_for_user(user_uid)

        result = []
        for mb in mailboxes:
            result.append(
                {
                    "id": mb["id"],
                    "name": mb["name"],
                    "email": mb["email"],
                    "description": mb.get("description"),
                    "is_active": mb["is_active"],
                    "created_at": mb["created_at"],
                    "role": "member",  # For now, all users are members
                }
            )

        return result


@blp.route("/<string:mailbox_id>")
class UserSharedMailbox(MethodView):
    """Get details for a specific shared mailbox"""

    @requires_auth
    @blp.response(200, SharedMailboxSchema)
    def get(self, mailbox_id: str) -> dict[str, Any]:
        """Get details for a shared mailbox the user has access to"""
        from app.module.admin.ModuleSharedMailbox import ModuleSharedMailbox

        shared_mailbox_module = ModuleSharedMailbox(g.db)
        user_uid = g.current_user.uid

        # Get the mailbox
        mailbox = shared_mailbox_module.get_by_id(mailbox_id)
        if not mailbox:
            return create_api_base_response(
                False, "Shared mailbox not found", 404, {"mailbox_id": mailbox_id}
            )

        # Check if user is a member
        if user_uid not in mailbox.get("member_uids", []):
            return create_api_base_response(
                False, "Access denied - you are not a member of this shared mailbox", 403
            )

        return {
            "id": mailbox["id"],
            "name": mailbox["name"],
            "email": mailbox["email"],
            "description": mailbox.get("description"),
            "is_active": mailbox["is_active"],
            "created_at": mailbox["created_at"],
            "role": "member",
        }
