"""User Notes API endpoints for CRUD operations."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flask import g, request
from flask.views import MethodView
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.module.user.ModuleUserNotes import ModuleUserNotes
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User
    from app.config.settings.ProcessSetting import ProcessSetting


blp = Blueprint("Notes", __name__, url_prefix="/notes")


# ── Schemas ───────────────────────────────────────────────────────────────────


class NoteSchema(Schema):
    """Schema for note response."""
    id = fields.String()
    user_uid = fields.String()
    title = fields.String()
    content = fields.String()
    created_at = fields.String()
    updated_at = fields.String()


class NoteCreateSchema(Schema):
    """Request body for creating a note."""
    title = fields.String(required=True)
    content = fields.String(required=True)


class NoteUpdateSchema(Schema):
    """Request body for updating a note."""
    title = fields.String(required=True)
    content = fields.String(required=True)


# ── Helpers ───────────────────────────────────────────────────────────────────


def require_user(req: Any) -> User:
    """Extract the authenticated user from the request.
    
    :param req: Flask request object
    :return: The authenticated User object
    :rtype: User
    """
    return g.user


def _get_notes_module() -> ModuleUserNotes:
    """Get or create the ModuleUserNotes instance.
    
    :return: ModuleUserNotes instance
    :rtype: ModuleUserNotes
    """
    if not hasattr(g, "_user_notes_module"):
        from app.utils.module.importManager import import_and_instantiate_manager
        process: ProcessSetting = g.process_settings
        db = import_and_instantiate_manager(
            module_path="app.manager.db",
            module_and_class_name=f"Client{process.SOGO_P_DB_TYPE}",
            module_args=process.get_db_settings(),
        )
        g._user_notes_module = ModuleUserNotes(db)
    return g._user_notes_module


# ── Endpoints ─────────────────────────────────────────────────────────────────


@blp.route("/")
class ApiNotesList(MethodView):
    """List all notes for the current user and create new notes."""

    @blp.response(200, NoteSchema(many=True))
    def get(self) -> list[dict[str, Any]]:
        """List all notes for the current user."""
        user = require_user(request)
        module = _get_notes_module()
        notes = module.list_notes(user.uid)
        logger_api.debug("Listed %d notes for user %s", len(notes), user.uid)
        return notes

    @blp.arguments(NoteCreateSchema, error_status_code=400)
    @blp.response(201, NoteSchema)
    def post(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new note."""
        user = require_user(request)
        module = _get_notes_module()
        note = module.create_note(
            user_uid=user.uid,
            title=data["title"],
            content=data["content"],
        )
        logger_api.info("Created note %s for user %s", note["id"], user.uid)
        return note


@blp.route("/<string:note_id>")
class ApiNotesDetail(MethodView):
    """Get, update, and delete individual notes."""

    @blp.response(200, NoteSchema)
    def get(self, note_id: str) -> dict[str, Any]:
        """Get a specific note by ID."""
        module = _get_notes_module()
        note = module.get_note(note_id)
        logger_api.debug("Retrieved note %s", note_id)
        return note

    @blp.arguments(NoteUpdateSchema, error_status_code=400)
    @blp.response(200, NoteSchema)
    def put(self, data: dict[str, Any], note_id: str) -> dict[str, Any]:
        """Update an existing note."""
        module = _get_notes_module()
        note = module.update_note(
            note_id=note_id,
            title=data["title"],
            content=data["content"],
        )
        logger_api.info("Updated note %s", note_id)
        return note

    @blp.response(200)
    def delete(self, note_id: str) -> dict[str, Any]:
        """Delete a note."""
        module = _get_notes_module()
        module.delete_note(note_id)
        logger_api.info("Deleted note %s", note_id)
        return {"deleted": True, "note_id": note_id}
