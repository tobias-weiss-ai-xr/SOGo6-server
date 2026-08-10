from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from flask import g
from flask.views import MethodView
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate

from app.module.mail.ModuleSnooze import ModuleSnooze
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import RequestException

blp = Blueprint(
    "Mail Snooze",
    __name__,
    url_prefix="/snooze",
    description="Temporarily remove emails from inbox and restore them later",
)


# ── Schemas ───────────────────────────────────────────────────────────────────


class SnoozeCreateSchema(Schema):
    """Request body to snooze one or more emails."""
    account_id = fields.String(required=True, metadata={"example": "0"})
    mail_uids = fields.List(fields.String(), required=True, metadata={"example": ["12345"]})
    folder = fields.String(required=True, metadata={"example": "INBOX"})
    snooze_until = fields.String(
        load_default=None, allow_none=True,
        metadata={"example": "2025-01-16T09:00:00Z", "description": "ISO 8601 datetime. Mutually exclusive with preset."},
    )
    preset = fields.String(
        load_default=None, allow_none=True,
        validate=validate.OneOf(["later_today", "tomorrow", "this_weekend", "next_week"]),
        metadata={"description": "Preset snooze duration. Mutually exclusive with snooze_until."},
    )


class SnoozeUnsnoozeSchema(Schema):
    """Request body to unsnooze (restore) a snoozed email."""
    snooze_id = fields.Integer(required=True)


# ── Helper ────────────────────────────────────────────────────────────────────


def _get_module() -> ModuleSnooze:
    if not hasattr(g, "_snooze_module"):
        from app.utils.module.importManager import import_and_instantiate_manager

        process = g.process_settings
        db = import_and_instantiate_manager(
            module_path="app.manager.db",
            module_and_class_name=f"Client{process.SOGO_P_DB_TYPE}",
            module_args=process.get_db_settings(),
        )
        g._snooze_module = ModuleSnooze(db)
    return g._snooze_module


def _resolve_snooze_time(data: dict) -> datetime:
    """Resolve snooze_until from either a direct datetime or a preset."""
    now = datetime.now(timezone.utc)

    if data.get("preset"):
        delta_dict = ModuleSnooze.parse_preset(data["preset"])
        if delta_dict:
            if "days" in delta_dict:
                return now + timedelta(days=delta_dict["days"])
            if "hours" in delta_dict:
                return now + timedelta(hours=delta_dict["hours"])

    if data.get("snooze_until"):
        try:
            return datetime.fromisoformat(data["snooze_until"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise RequestException(
                error=err.ERROR_VALIDATION_FAILED,
                message="Invalid snooze_until datetime. Use ISO 8601 format.",
            ) from exc

    raise RequestException(
        error=err.ERROR_VALIDATION_FAILED,
        message="Either snooze_until or preset must be provided.",
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@blp.route("/")
class ApiSnoozeList(MethodView):
    @blp.response(200)
    def get(self) -> dict[str, Any]:
        """List all snoozed emails for the current user."""
        module = _get_module()
        user = g.user
        snoozed = module.list_snoozed(user.uid)
        return create_api_base_response({"snoozed": snoozed})

    @blp.arguments(SnoozeCreateSchema, error_status_code=400)
    @blp.response(201)
    def post(self, data: dict) -> dict[str, Any]:
        """Snooze one or more emails.

        The snooze_until is resolved from either the ``snooze_until`` field
        (ISO 8601 datetime) or a ``preset`` key (``later_today``, ``tomorrow``,
        ``this_weekend``, ``next_week``).

        The mail metadata is stored in the database. The caller (UI) should
        then move the mail to a hidden folder or apply a visual filter.
        """
        module = _get_module()
        user = g.user

        snooze_until = _resolve_snooze_time(data)
        results = []

        for mail_uid in data["mail_uids"]:
            record = module.snooze(
                user_uid=user.uid,
                account_id=data["account_id"],
                mail_uid=mail_uid,
                folder=data["folder"],
                snooze_until=snooze_until,
            )
            results.append(record)

        return create_api_base_response({"snoozed": results})


@blp.route("/<int:snooze_id>")
class ApiSnoozeDetail(MethodView):
    @blp.response(200)
    def delete(self, snooze_id: int) -> dict[str, Any]:
        """Unsnooze (restore) a snoozed email.

        Returns the snooze record including the original folder, so the
        caller can move the mail back.
        """
        module = _get_module()
        user = g.user
        record = module.unsnooze(user.uid, snooze_id)
        return create_api_base_response({"restored": record})
