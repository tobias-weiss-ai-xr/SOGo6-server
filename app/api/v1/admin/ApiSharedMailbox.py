from __future__ import annotations

import csv
import io
from typing import Any

from flask import Response, g
from flask.typing import ResponseReturnValue
from flask.views import MethodView
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate

from app.module.admin.ModuleSharedMailbox import ModuleSharedMailbox, VALID_ROLES
from app.module.admin.ModuleSharedMailboxNotes import ModuleSharedMailboxNotes
from app.module.admin.ModuleSharedMailboxAssignment import ModuleSharedMailboxAssignment, VALID_STATUSES
from app.module.admin.ModuleSharedMailboxAnalytics import ModuleSharedMailboxAnalytics
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.db.Condition import EqualCondition
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
    is_active = fields.Boolean(load_default=True)
    member_uids = fields.List(fields.Email(), load_default=None,
                              metadata={"description": "Initial member email addresses"})
    # Quota
    quota_enabled = fields.Boolean(load_default=False)
    quota_max_size = fields.Integer(load_default=None, validate=validate.Range(min=1))
    quota_max_emails = fields.Integer(load_default=None, validate=validate.Range(min=1))
    # Auto-responder
    auto_respond_enabled = fields.Boolean(load_default=False)
    auto_respond_subject = fields.String(load_default=None)
    auto_respond_message = fields.String(load_default=None)
    # Forwarding
    forward_to = fields.List(fields.Email(), load_default=None)
    forward_keep_copy = fields.Boolean(load_default=True)
    # Signatures
    signature_enabled = fields.Boolean(load_default=False)
    signature_html = fields.String(load_default=None)
    signature_plain = fields.String(load_default=None)


class SharedMailboxUpdateSchema(Schema):
    """Request body for updating a shared mailbox."""
    name = fields.String()
    description = fields.String()
    is_active = fields.Boolean()
    member_uids = fields.List(fields.Email())
    # Quota
    quota_enabled = fields.Boolean()
    quota_max_size = fields.Integer(validate=validate.Range(min=1))
    quota_max_emails = fields.Integer(validate=validate.Range(min=1))
    # Auto-responder
    auto_respond_enabled = fields.Boolean()
    auto_respond_subject = fields.String()
    auto_respond_message = fields.String()
    # Forwarding
    forward_to = fields.List(fields.Email())
    forward_keep_copy = fields.Boolean()
    # Signatures
    signature_enabled = fields.Boolean()
    signature_html = fields.String()
    signature_plain = fields.String()


class SharedMailboxMemberSchema(Schema):
    """Request body for adding a member."""
    user_uid = fields.Email(required=True, metadata={"example": "user@example.org"})
    role = fields.String(load_default="member", validate=validate.OneOf(list(VALID_ROLES)))


class SharedMailboxMemberUpdateSchema(Schema):
    """Request body for updating a member's role."""
    role = fields.String(required=True, validate=validate.OneOf(list(VALID_ROLES)))


class SharedMailboxResponseDataSchema(Schema):
    """Response data for a shared mailbox."""
    id = fields.String()
    email = fields.Email()
    name = fields.String()
    description = fields.String()
    member_uids = fields.List(fields.Email())
    member_roles = fields.List(fields.Dict())
    is_active = fields.Boolean()
    created_at = fields.String()
    updated_at = fields.String()
    quota_enabled = fields.Boolean()
    quota_max_size = fields.Integer(allow_none=True)
    quota_max_emails = fields.Integer(allow_none=True)
    auto_respond_enabled = fields.Boolean()
    auto_respond_subject = fields.String(allow_none=True)
    auto_respond_message = fields.String(allow_none=True)
    forward_to = fields.List(fields.Email())
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


class NoteResponseSchema(Schema):
    """Response for a note."""
    id = fields.String()
    mailbox_id = fields.String()
    email_id = fields.String(allow_none=True)
    author_uid = fields.String()
    content = fields.String()
    is_private = fields.Boolean()
    mentions = fields.List(fields.String())
    created_at = fields.String()
    updated_at = fields.String()


class AssignmentCreateSchema(Schema):
    """Request body for creating an assignment."""
    email_id = fields.String(required=True)
    assigned_to = fields.Email(required=True)
    reason = fields.String(load_default=None)


class AssignmentUpdateSchema(Schema):
    """Request body for updating an assignment."""
    status = fields.String(validate=validate.OneOf(list(VALID_STATUSES)))
    reason = fields.String()
    notified = fields.Boolean()


class AssignmentResponseSchema(Schema):
    """Response for an assignment."""
    id = fields.String()
    mailbox_id = fields.String()
    email_id = fields.String()
    assigned_to = fields.String()
    assigned_by = fields.String()
    reason = fields.String(allow_none=True)
    status = fields.String()
    notified = fields.Boolean()
    created_at = fields.String()
    completed_at = fields.String(allow_none=True)


class SharedMailboxSearchQuerySchema(Schema):
    """Query parameters for searching shared mailboxes."""
    q = fields.String(load_default="",
                      metadata={"description": "Search query matching name, email or description"})


class SharedMailboxImportSchema(Schema):
    """Request body for importing shared mailbox configurations."""
    mailboxes = fields.List(
        fields.Nested(SharedMailboxCreateSchema),
        required=True,
        metadata={"description": "List of mailbox configurations to import"},
    )
    dry_run = fields.Boolean(load_default=False,
                             metadata={"description": "Validate only, do not write anything"})


# ── Helpers ────────────────────────────────────────────────────────────────────


def _get_module() -> ModuleSharedMailbox:
    if not hasattr(g, "_shared_mailbox_module"):
        from app.utils.module.importManager import import_and_instantiate_manager
        process = g.process_settings
        db = import_and_instantiate_manager(
            module_path="app.manager.db",
            module_and_class_name="ClientPostgreSQL",
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
            module_and_class_name="ClientPostgreSQL",
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
            module_and_class_name="ClientPostgreSQL",
            module_args=process.get_db_settings(),
        )
        g._shared_mailbox_assignment_module = ModuleSharedMailboxAssignment(db)
    return g._shared_mailbox_assignment_module


def _get_analytics_module() -> ModuleSharedMailboxAnalytics:
    if not hasattr(g, "_shared_mailbox_analytics_module"):
        from app.utils.module.importManager import import_and_instantiate_manager
        process = g.process_settings
        db = import_and_instantiate_manager(
            module_path="app.manager.db",
            module_and_class_name="ClientPostgreSQL",
            module_args=process.get_db_settings(),
        )
        g._shared_mailbox_analytics_module = ModuleSharedMailboxAnalytics(db)
    return g._shared_mailbox_analytics_module


# ── Mailbox CRUD ──────────────────────────────────────────────────────────────


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
        """Create a new shared mailbox with extended fields."""
        module = _get_module()
        try:
            mailbox = module.create(
                email=data["email"],
                name=data["name"],
                description=data.get("description", ""),
                member_uids=data.get("member_uids"),
                is_active=data.get("is_active", True),
                quota_enabled=data.get("quota_enabled", False),
                quota_max_size=data.get("quota_max_size"),
                quota_max_emails=data.get("quota_max_emails"),
                auto_respond_enabled=data.get("auto_respond_enabled", False),
                auto_respond_subject=data.get("auto_respond_subject"),
                auto_respond_message=data.get("auto_respond_message"),
                forward_to=data.get("forward_to"),
                forward_keep_copy=data.get("forward_keep_copy", True),
                signature_enabled=data.get("signature_enabled", False),
                signature_html=data.get("signature_html"),
                signature_plain=data.get("signature_plain"),
            )
            return create_api_base_response(mailbox, code=201)
        except RequestException as ex:
            return create_api_base_response(None, ex.error)


@blp.route("/search")
class ApiSharedMailboxSearch(MethodView):
    """Search shared mailboxes."""

    @blp.arguments(SharedMailboxSearchQuerySchema, location="query")
    @blp.response(200)
    def get(self, query: dict) -> dict[str, Any]:
        """Search mailboxes by name, email or description."""
        module = _get_module()
        mailboxes = module.search(query.get("q", ""))
        return create_api_base_response({"mailboxes": mailboxes, "total_count": len(mailboxes)})


@blp.route("/export")
class ApiSharedMailboxExportAll(MethodView):
    """Export all shared mailboxes as portable configuration."""

    @blp.response(200)
    def get(self) -> dict[str, Any]:
        """Return the configuration of every shared mailbox."""
        module = _get_module()
        configs = module.export_all_configs()
        return create_api_base_response({"mailboxes": configs, "total_count": len(configs)})


@blp.route("/import")
class ApiSharedMailboxImport(MethodView):
    """Import shared mailbox configurations."""

    @blp.arguments(SharedMailboxImportSchema, error_status_code=400)
    @blp.response(200)
    def post(self, data: dict) -> dict[str, Any]:
        """Create/update mailboxes from imported configuration (idempotent)."""
        module = _get_module()
        mailboxes = data["mailboxes"]
        dry_run = data.get("dry_run", False)
        results = []
        for config in mailboxes:
            if dry_run:
                existing = list(module._db.select_from_table(
                    table_name=module.TABLE_NAME,
                    column_tuple=(module.COL_ID,),
                    condition=EqualCondition(module.COL_EMAIL, config["email"]),
                ))
                results.append({
                    "email": config["email"],
                    "action": "update" if existing else "create",
                })
                continue
            try:
                mailbox = module.import_config(config)
                results.append({
                    "email": mailbox.get("email"),
                    "mailbox_id": mailbox.get("id"),
                    "action": "updated",
                })
            except RequestException as ex:
                results.append({
                    "email": config.get("email"),
                    "action": "error",
                    "error_code": ex.error.c,
                    "error_msg": ex.error.m,
                })
        return create_api_base_response({"imported": len(results) if not dry_run else 0, "results": results})


@blp.route("/<string:mailbox_id>")
class ApiSharedMailboxDetail(MethodView):
    @blp.response(200)
    def get(self, mailbox_id: str) -> dict[str, Any]:
        """Get a shared mailbox by ID."""
        module = _get_module()
        mailbox = module.get_by_id(mailbox_id)
        if not mailbox:
            return create_api_base_response(None, err.ERROR_SHARED_MAILBOX_NOT_FOUND)
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
        """Delete a shared mailbox (and its notes and assignments)."""
        module = _get_module()
        try:
            # Clean up notes and assignments
            notes_mod = _get_notes_module()
            assignment_mod = _get_assignment_module()
            notes_mod.delete_notes_for_mailbox(mailbox_id)
            assignment_mod.delete_assignments_for_mailbox(mailbox_id)
            module.delete(mailbox_id)
            return create_api_base_response({"deleted": True})
        except RequestException as ex:
            return create_api_base_response(None, ex.error)


# ── Member Management (with roles) ───────────────────────────────────────────


@blp.route("/<string:mailbox_id>/members")
class ApiSharedMailboxMembers(MethodView):
    @blp.response(200)
    def get(self, mailbox_id: str) -> dict[str, Any]:
        """List members of a shared mailbox (with roles)."""
        module = _get_module()
        mailbox = module.get_by_id(mailbox_id)
        if not mailbox:
            return create_api_base_response(None, err.ERROR_SHARED_MAILBOX_NOT_FOUND)
        return create_api_base_response({
            "members": mailbox.get("member_uids", []),
            "member_roles": mailbox.get("member_roles", []),
        })

    @blp.arguments(SharedMailboxMemberSchema, error_status_code=400)
    @blp.response(200)
    def post(self, data: dict, mailbox_id: str) -> dict[str, Any]:
        """Add a member to a shared mailbox (with role)."""
        module = _get_module()
        try:
            mailbox = module.add_member(mailbox_id, data["user_uid"], data.get("role", "member"))
            return create_api_base_response(mailbox)
        except RequestException as ex:
            return create_api_base_response(None, ex.error)


@blp.route("/<string:mailbox_id>/members/<string:user_uid>")
class ApiSharedMailboxMemberDetail(MethodView):
    @blp.arguments(SharedMailboxMemberUpdateSchema, error_status_code=400)
    @blp.response(200)
    def put(self, data: dict, mailbox_id: str, user_uid: str) -> dict[str, Any]:
        """Update a member's role."""
        module = _get_module()
        try:
            mailbox = module.update_member_role(mailbox_id, user_uid, data["role"])
            return create_api_base_response(mailbox)
        except RequestException as ex:
            return create_api_base_response(None, ex.error)

    @blp.response(200)
    def delete(self, mailbox_id: str, user_uid: str) -> dict[str, Any]:
        """Remove a member from a shared mailbox."""
        module = _get_module()
        try:
            mailbox = module.remove_member(mailbox_id, user_uid)
            return create_api_base_response(mailbox)
        except RequestException as ex:
            return create_api_base_response(None, ex.error)


# ── Analytics ─────────────────────────────────────────────────────────────────


@blp.route("/<string:mailbox_id>/analytics")
class ApiSharedMailboxAnalytics(MethodView):
    @blp.response(200)
    def get(self, mailbox_id: str) -> dict[str, Any]:
        """Get analytics for a shared mailbox."""
        module = _get_module()
        mailbox = module.get_by_id(mailbox_id)
        if not mailbox:
            return create_api_base_response(None, err.ERROR_SHARED_MAILBOX_NOT_FOUND)
        analytics = _get_analytics_module().get_analytics(mailbox_id)
        return create_api_base_response(analytics)


@blp.route("/<string:mailbox_id>/analytics/export")
class ApiSharedMailboxAnalyticsExport(MethodView):
    """Export shared mailbox analytics as CSV."""

    def get(self, mailbox_id: str) -> ResponseReturnValue:
        """Return notes/assignment analytics as a CSV download."""
        module = _get_module()
        mailbox = module.get_by_id(mailbox_id)
        if not mailbox:
            return create_api_base_response(None, err.ERROR_SHARED_MAILBOX_NOT_FOUND)
        analytics = _get_analytics_module().get_analytics(mailbox_id)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["metric", "category", "value"])
        for category, stat in (
            ("notes", "total"), ("notes", "public"), ("notes", "private"),
            ("notes", "last_7_days"), ("notes", "last_30_days"),
        ):
            writer.writerow([stat, category, analytics.get("notes", {}).get(stat, 0)])
        for stat in ("total", "pending", "accepted", "completed", "cancelled",
                     "last_7_days", "last_30_days", "completion_rate", "avg_completion_seconds"):
            writer.writerow([stat, "assignments", analytics.get("assignments", {}).get(stat, 0)])

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=shared-mailbox-{mailbox_id}-analytics.csv"},
        )


@blp.route("/<string:mailbox_id>/export")
class ApiSharedMailboxExport(MethodView):
    """Export a single shared mailbox configuration."""

    @blp.response(200)
    def get(self, mailbox_id: str) -> dict[str, Any]:
        """Return the portable configuration for one mailbox."""
        module = _get_module()
        try:
            config = module.export_config(mailbox_id)
            return create_api_base_response(config)
        except RequestException as ex:
            return create_api_base_response(None, ex.error)


# ── Notes ─────────────────────────────────────────────────────────────────────


@blp.route("/<string:mailbox_id>/notes")
class ApiSharedMailboxNotes(MethodView):
    @blp.response(200)
    def get(self, mailbox_id: str) -> dict[str, Any]:
        """List notes for a shared mailbox."""
        notes_mod = _get_notes_module()
        email_id = None
        notes = notes_mod.list_notes(mailbox_id, email_id=email_id, include_private=True)
        return create_api_base_response({"notes": notes, "total_count": len(notes)})

    @blp.arguments(NoteCreateSchema, error_status_code=400)
    @blp.response(201)
    def post(self, data: dict, mailbox_id: str) -> dict[str, Any]:
        """Add a note to a shared mailbox."""
        module = _get_module()
        mailbox = module.get_by_id(mailbox_id)
        if not mailbox:
            return create_api_base_response(None, err.ERROR_SHARED_MAILBOX_NOT_FOUND)
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
class ApiSharedMailboxNoteDetail(MethodView):
    @blp.response(200)
    def delete(self, mailbox_id: str, note_id: str) -> dict[str, Any]:
        """Delete a note."""
        notes_mod = _get_notes_module()
        try:
            notes_mod.delete_note(note_id)
            return create_api_base_response({"deleted": True})
        except RequestException as ex:
            return create_api_base_response(None, ex.error)


# ── Assignments ───────────────────────────────────────────────────────────────


@blp.route("/<string:mailbox_id>/assignments")
class ApiSharedMailboxAssignments(MethodView):
    @blp.response(200)
    def get(self, mailbox_id: str) -> dict[str, Any]:
        """List assignments for a shared mailbox."""
        assignment_mod = _get_assignment_module()
        assignments = assignment_mod.list_assignments(mailbox_id=mailbox_id)
        return create_api_base_response({"assignments": assignments, "total_count": len(assignments)})

    @blp.arguments(AssignmentCreateSchema, error_status_code=400)
    @blp.response(201)
    def post(self, data: dict, mailbox_id: str) -> dict[str, Any]:
        """Create an assignment for an email in a shared mailbox."""
        module = _get_module()
        mailbox = module.get_by_id(mailbox_id)
        if not mailbox:
            return create_api_base_response(None, err.ERROR_SHARED_MAILBOX_NOT_FOUND)
        assignment_mod = _get_assignment_module()
        try:
            assignment = assignment_mod.create_assignment(
                mailbox_id=mailbox_id,
                email_id=data["email_id"],
                assigned_to=data["assigned_to"],
                assigned_by=g.user.uid,
                reason=data.get("reason"),
            )
            return create_api_base_response(assignment, code=201)
        except RequestException as ex:
            return create_api_base_response(None, ex.error)


@blp.route("/<string:mailbox_id>/assignments/<string:assignment_id>")
class ApiSharedMailboxAssignmentDetail(MethodView):
    @blp.arguments(AssignmentUpdateSchema, error_status_code=400)
    @blp.response(200)
    def put(self, data: dict, mailbox_id: str, assignment_id: str) -> dict[str, Any]:
        """Update an assignment (status, reason, notified)."""
        assignment_mod = _get_assignment_module()
        try:
            assignment = assignment_mod.update_assignment(
                assignment_id,
                status=data.get("status"),
                reason=data.get("reason"),
                notified=data.get("notified"),
            )
            return create_api_base_response(assignment)
        except RequestException as ex:
            return create_api_base_response(None, ex.error)

    @blp.response(200)
    def delete(self, mailbox_id: str, assignment_id: str) -> dict[str, Any]:
        """Delete an assignment."""
        assignment_mod = _get_assignment_module()
        try:
            assignment_mod.delete_assignment(assignment_id)
            return create_api_base_response({"deleted": True})
        except RequestException as ex:
            return create_api_base_response(None, ex.error)
