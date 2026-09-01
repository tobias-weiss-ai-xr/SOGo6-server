from __future__ import annotations

from typing import Any

from flask import g
from flask.views import MethodView
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.module.admin.ModuleSharedMailbox import ModuleSharedMailbox
from app.module.admin.ModuleSharedMailboxNotes import ModuleSharedMailboxNotes
from app.module.admin.ModuleSharedMailboxAssignment import ModuleSharedMailboxAssignment
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import RequestException

blp = Blueprint(
    "User Shared Mailboxes",
    __name__,
    url_prefix="/shared-mailboxes",
    description="User access to shared mailboxes they have membership in",
)


# ── Schemas ───────────────────────────────────────────────────────────────────


class SharedMailboxSchema(Schema):
    """Schema for shared mailbox response (user-facing)."""
    id = fields.String()
    name = fields.String()
    email = fields.String()
    description = fields.String(allow_none=True)
    is_active = fields.Boolean()
    # The module returns created_at/updated_at as strings (SQL str() or the
    # create payload); DateTime() would call .isoformat on them and 500.
    created_at = fields.String()
    updated_at = fields.String(allow_none=True)
    role = fields.String()
    member_uids = fields.List(fields.String())
    member_roles = fields.List(fields.Dict())
    quota_enabled = fields.Boolean()
    quota_max_size = fields.Integer(allow_none=True)
    quota_max_emails = fields.Integer(allow_none=True)
    auto_respond_enabled = fields.Boolean()
    auto_respond_subject = fields.String(allow_none=True)
    auto_respond_message = fields.String(allow_none=True)
    forward_to = fields.List(fields.String())
    forward_keep_copy = fields.Boolean()
    signature_enabled = fields.Boolean()
    signature_html = fields.String(allow_none=True)
    signature_plain = fields.String(allow_none=True)


class NoteCreateSchema(Schema):
    """Request body for creating a note."""
    content = fields.String(required=True)
    email_id = fields.String(load_default=None)
    is_private = fields.Boolean(load_default=False)
    mentions = fields.List(fields.String(), load_default=None)


class AssignmentAcceptSchema(Schema):
    """Empty schema for accepting an assignment."""


# ── Helpers ────────────────────────────────────────────────────────────────────


def _get_module() -> ModuleSharedMailbox:
    if not hasattr(g, "_shared_mailbox_module"):
        from app.utils.module.importManager import import_and_instantiate_manager
        process = g.process_settings
        db = import_and_instantiate_manager(
            module_path="app.manager.db",
            module_and_class_name=f"Client{process.SOGO_P_DB_TYPE}",
            module_args=process.get_db_settings(),
        )
        g._shared_mailbox_module = ModuleSharedMailbox(db)
    return g._shared_mailbox_module


def _get_notes_module() -> ModuleSharedMailboxNotes:
    if not hasattr(g, "_shared_mailbox_notes_module"):
        from app.utils.module.importManager import import_and_instantiate_manager
        process = g.process_settings
        db = import_and_instantiate_manager(
            module_path="app.manager.db",
            module_and_class_name=f"Client{process.SOGO_P_DB_TYPE}",
            module_args=process.get_db_settings(),
        )
        g._shared_mailbox_notes_module = ModuleSharedMailboxNotes(db)
    return g._shared_mailbox_notes_module


def _get_assignment_module() -> ModuleSharedMailboxAssignment:
    if not hasattr(g, "_shared_mailbox_assignment_module"):
        from app.utils.module.importManager import import_and_instantiate_manager
        process = g.process_settings
        db = import_and_instantiate_manager(
            module_path="app.manager.db",
            module_and_class_name=f"Client{process.SOGO_P_DB_TYPE}",
            module_args=process.get_db_settings(),
        )
        g._shared_mailbox_assignment_module = ModuleSharedMailboxAssignment(db)
    return g._shared_mailbox_assignment_module


def _check_access(mailbox_id: str, required_role: str = "member") -> dict[str, Any] | None:
    """Check if the current user has access to a shared mailbox.

    Returns the mailbox dict if access is granted, None otherwise.
    Sets g._shared_mailbox_access_denied if access is denied.
    """
    module = _get_module()
    mailbox = module.get_by_id(mailbox_id)
    if not mailbox:
        return None

    user_uid = g.user.uid
    if not module.check_permission(mailbox_id, user_uid, required_role):
        return None

    return mailbox


# ── Endpoints ─────────────────────────────────────────────────────────────────


@blp.route("/")
class UserSharedMailboxesList(MethodView):
    """List all shared mailboxes the current user has access to."""

    @blp.response(200, SharedMailboxSchema(many=True))
    def get(self) -> list[dict[str, Any]]:
        """Get all shared mailboxes the user can access"""
        module = _get_module()
        user_uid = g.user.uid
        mailboxes = module.get_for_user(user_uid)
        return mailboxes


@blp.route("/<string:mailbox_id>")
class UserSharedMailbox(MethodView):
    """Get details for a specific shared mailbox"""

    @blp.response(200)
    def get(self, mailbox_id: str) -> dict[str, Any]:
        """Get details for a shared mailbox the user has access to"""
        module = _get_module()
        mailbox = module.get_by_id(mailbox_id)
        if not mailbox:
            return create_api_base_response(None, err.ERROR_SHARED_MAILBOX_NOT_FOUND)

        user_uid = g.user.uid
        role = module.get_member_role(mailbox_id, user_uid)
        if not role:
            return create_api_base_response(None, err.ERROR_SHARED_MAILBOX_ACCESS_DENIED)

        # Update member activity
        module.update_member_activity(mailbox_id, user_uid)

        mailbox["role"] = role
        return create_api_base_response(mailbox)


@blp.route("/<string:mailbox_id>/activity")
class UserSharedMailboxActivity(MethodView):
    """Get the current user's activity in a shared mailbox."""

    @blp.response(200)
    def get(self, mailbox_id: str) -> dict[str, Any]:
        """Get user activity for a shared mailbox"""
        mailbox = _check_access(mailbox_id)
        if not mailbox:
            return create_api_base_response(None, err.ERROR_SHARED_MAILBOX_ACCESS_DENIED)

        module = _get_module()
        user_uid = g.user.uid
        role = module.get_member_role(mailbox_id, user_uid)

        # Get user's notes and assignments
        notes_mod = _get_notes_module()
        assignment_mod = _get_assignment_module()

        notes = notes_mod.list_notes(mailbox_id, user_uid=user_uid, include_private=True)
        user_notes = [n for n in notes if n.get("author_uid") == user_uid]
        assignments = assignment_mod.list_assignments(assigned_to=user_uid)
        user_assignments = [a for a in assignments if a.get("mailbox_id") == mailbox_id]

        return create_api_base_response({
            "mailbox_id": mailbox_id,
            "role": role,
            "notes_count": len(user_notes),
            "assignments_count": len(user_assignments),
            "assignments_pending": len([a for a in user_assignments if a.get("status") == "pending"]),
            "assignments_accepted": len([a for a in user_assignments if a.get("status") == "accepted"]),
            "assignments_completed": len([a for a in user_assignments if a.get("status") == "completed"]),
        })


@blp.route("/<string:mailbox_id>/notes")
class UserSharedMailboxNotes(MethodView):
    """List and create notes in a shared mailbox."""

    @blp.response(200)
    def get(self, mailbox_id: str) -> dict[str, Any]:
        """List notes (public + own private)"""
        mailbox = _check_access(mailbox_id)
        if not mailbox:
            return create_api_base_response(None, err.ERROR_SHARED_MAILBOX_ACCESS_DENIED)

        notes_mod = _get_notes_module()
        user_uid = g.user.uid
        notes = notes_mod.list_notes(mailbox_id, user_uid=user_uid, include_private=True)
        return create_api_base_response({"notes": notes, "total_count": len(notes)})

    @blp.arguments(NoteCreateSchema, error_status_code=400)
    @blp.response(201)
    def post(self, data: dict, mailbox_id: str) -> dict[str, Any]:
        """Add a note"""
        mailbox = _check_access(mailbox_id)
        if not mailbox:
            return create_api_base_response(None, err.ERROR_SHARED_MAILBOX_ACCESS_DENIED)

        notes_mod = _get_notes_module()
        note = notes_mod.create_note(
            mailbox_id=mailbox_id,
            author_uid=g.user.uid,
            content=data["content"],
            email_id=data.get("email_id"),
            is_private=data.get("is_private", False),
            mentions=data.get("mentions"),
        )
        return create_api_base_response(note, code=201)


@blp.route("/<string:mailbox_id>/notes/<string:note_id>")
class UserSharedMailboxNoteDetail(MethodView):
    """Delete a note (author only)."""

    @blp.response(200)
    def delete(self, mailbox_id: str, note_id: str) -> dict[str, Any]:
        """Delete a note (only the author can delete)"""
        mailbox = _check_access(mailbox_id)
        if not mailbox:
            return create_api_base_response(None, err.ERROR_SHARED_MAILBOX_ACCESS_DENIED)

        notes_mod = _get_notes_module()
        note = notes_mod.get_note(note_id)
        if not note:
            return create_api_base_response(None, err.ERROR_SHARED_MAILBOX_NOTE_NOT_FOUND)

        # Only the author can delete their notes
        if note.get("author_uid") != g.user.uid:
            return create_api_base_response(None, err.ERROR_SHARED_MAILBOX_ACCESS_DENIED)

        try:
            notes_mod.delete_note(note_id)
            return create_api_base_response({"deleted": True})
        except RequestException as ex:
            return create_api_base_response(None, ex.error)


@blp.route("/<string:mailbox_id>/assignments")
class UserSharedMailboxAssignments(MethodView):
    """List assignments for the current user in a shared mailbox."""

    @blp.response(200)
    def get(self, mailbox_id: str) -> dict[str, Any]:
        """List assignments assigned to the current user"""
        mailbox = _check_access(mailbox_id)
        if not mailbox:
            return create_api_base_response(None, err.ERROR_SHARED_MAILBOX_ACCESS_DENIED)

        assignment_mod = _get_assignment_module()
        user_uid = g.user.uid
        assignments = assignment_mod.list_assignments(mailbox_id=mailbox_id)
        user_assignments = [a for a in assignments if a.get("assigned_to") == user_uid]
        return create_api_base_response({"assignments": user_assignments, "total_count": len(user_assignments)})


@blp.route("/<string:mailbox_id>/assignments/<string:assignment_id>/accept")
class UserSharedMailboxAssignmentAccept(MethodView):
    """Accept an assignment."""

    @blp.response(200)
    def post(self, mailbox_id: str, assignment_id: str) -> dict[str, Any]:
        """Accept an assignment assigned to the current user"""
        mailbox = _check_access(mailbox_id)
        if not mailbox:
            return create_api_base_response(None, err.ERROR_SHARED_MAILBOX_ACCESS_DENIED)

        assignment_mod = _get_assignment_module()
        try:
            assignment = assignment_mod.accept_assignment(assignment_id, g.user.uid)
            return create_api_base_response(assignment)
        except RequestException as ex:
            return create_api_base_response(None, ex.error)


@blp.route("/<string:mailbox_id>/assignments/<string:assignment_id>/complete")
class UserSharedMailboxAssignmentComplete(MethodView):
    """Complete an assignment."""

    @blp.response(200)
    def post(self, mailbox_id: str, assignment_id: str) -> dict[str, Any]:
        """Mark an assignment as completed"""
        mailbox = _check_access(mailbox_id)
        if not mailbox:
            return create_api_base_response(None, err.ERROR_SHARED_MAILBOX_ACCESS_DENIED)

        assignment_mod = _get_assignment_module()
        try:
            assignment = assignment_mod.complete_assignment(assignment_id, g.user.uid)
            return create_api_base_response(assignment)
        except RequestException as ex:
            return create_api_base_response(None, ex.error)
