from __future__ import annotations

from typing import Any

from flask import g
from flask.views import MethodView
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate

from app.module.calendar.ModuleResourceBooking import ModuleResourceBooking
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import RequestException

blp = Blueprint(
    "Resource Booking",
    __name__,
    url_prefix="/resources",
    description="Bookable resource management (rooms, equipment, vehicles)",
)


# ── Schemas ───────────────────────────────────────────────────────────────────


class ResourceCreateSchema(Schema):
    """Request body for creating a resource."""
    name = fields.String(required=True, metadata={"example": "Conference Room A"})
    email = fields.Email(required=True, metadata={"example": "room-a@example.org"})
    resource_type = fields.String(
        load_default="room",
        validate=validate.OneOf(["room", "equipment", "vehicle", "other"]),
        metadata={"example": "room"},
    )
    description = fields.String(load_default="", metadata={"example": "Ground floor, 20 seats"})
    capacity = fields.Integer(load_default=None, validate=validate.Range(min=1))
    location = fields.String(load_default=None, metadata={"example": "Building A, Floor 1"})
    features = fields.List(fields.String(), load_default=None,
                           metadata={"example": ["projector", "video_conferencing", "whiteboard"]})
    booking_policy = fields.String(
        load_default="open",
        validate=validate.OneOf(["open", "moderated", "restricted"]),
        metadata={"example": "open"},
    )
    allowed_groups = fields.List(fields.String(), load_default=None,
                                  metadata={"description": "LDAP groups allowed to book (empty = all)"})
    auto_accept = fields.Boolean(load_default=True)


class ResourceUpdateSchema(Schema):
    """Request body for updating a resource."""
    name = fields.String()
    description = fields.String()
    email = fields.Email()
    resource_type = fields.String(validate=validate.OneOf(["room", "equipment", "vehicle", "other"]))
    capacity = fields.Integer(validate=validate.Range(min=1))
    location = fields.String()
    features = fields.List(fields.String())
    is_active = fields.Boolean()
    booking_policy = fields.String(validate=validate.OneOf(["open", "moderated", "restricted"]))
    allowed_groups = fields.List(fields.String())
    auto_accept = fields.Boolean()


class ResourceListSchema(Schema):
    """Query parameters for listing resources."""
    active_only = fields.Boolean(load_default=False)


class ResourceAvailabilitySchema(Schema):
    """Request body for checking resource availability."""
    resource_id = fields.String(required=True)
    start = fields.String(required=True, metadata={"example": "2025-01-15T09:00:00Z"})
    end = fields.String(required=True, metadata={"example": "2025-01-15T10:00:00Z"})


class ResourceAvailableListSchema(Schema):
    """Query parameters for listing available resources."""
    start = fields.String(required=True, metadata={"example": "2025-01-15T09:00:00Z"})
    end = fields.String(required=True, metadata={"example": "2025-01-15T10:00:00Z"})
    resource_type = fields.String(load_default=None)
    min_capacity = fields.Integer(load_default=None)


# ── Helper ────────────────────────────────────────────────────────────────────


def _get_module() -> ModuleResourceBooking:
    if not hasattr(g, "_resource_booking_module"):
        from app.utils.module.importManager import import_and_instantiate_manager

        process = g.process_settings
        db = import_and_instantiate_manager(
            module_path="app.manager.db",
            module_and_class_name=f"Client{process.SOGO_P_DB_TYPE}",
            module_args=process.get_db_settings(),
        )
        g._resource_booking_module = ModuleResourceBooking(db)
    return g._resource_booking_module


# ── Endpoints ─────────────────────────────────────────────────────────────────


@blp.route("/")
class ApiResourceList(MethodView):
    @blp.arguments(ResourceListSchema, location="query", error_status_code=400)
    @blp.response(200)
    def get(self, args: dict) -> dict[str, Any]:
        """List all bookable resources."""
        module = _get_module()
        resources = module.get_all(active_only=args.get("active_only", False))
        return create_api_base_response({"resources": resources})

    @blp.arguments(ResourceCreateSchema, error_status_code=400)
    @blp.response(201)
    def post(self, data: dict) -> dict[str, Any]:
        """Create a new bookable resource."""
        module = _get_module()
        resource = module.create(
            name=data["name"],
            email=data["email"],
            resource_type=data.get("resource_type", "room"),
            description=data.get("description", ""),
            capacity=data.get("capacity"),
            location=data.get("location"),
            features=data.get("features"),
            booking_policy=data.get("booking_policy", "open"),
            allowed_groups=data.get("allowed_groups"),
            auto_accept=data.get("auto_accept", True),
        )
        return create_api_base_response({"resource": resource})


@blp.route("/available")
class ApiResourceAvailableList(MethodView):
    @blp.arguments(ResourceAvailableListSchema, location="query", error_status_code=400)
    @blp.response(200)
    def get(self, args: dict) -> dict[str, Any]:
        """List resources available during a time window."""
        from datetime import datetime

        module = _get_module()

        try:
            start = datetime.fromisoformat(args["start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(args["end"].replace("Z", "+00:00"))
        except (ValueError, KeyError) as exc:
            raise RequestException(
                error=err.ERROR_VALIDATION_FAILED,
                message="Invalid start/end datetime. Use ISO 8601 format.",
            ) from exc

        resources = module.list_available(
            start=start,
            end=end,
            resource_type=args.get("resource_type"),
            min_capacity=args.get("min_capacity"),
        )
        return create_api_base_response({"resources": resources})


@blp.route("/<string:resource_id>")
class ApiResourceDetail(MethodView):
    @blp.response(200)
    def get(self, resource_id: str) -> dict[str, Any]:
        """Get a single resource by ID."""
        module = _get_module()
        resource = module.get_by_id(resource_id)
        if not resource:
            raise RequestException(
                error=err.ERROR_RESOURCE_NOT_FOUND,
                message=f"Resource '{resource_id}' not found.",
            )
        return create_api_base_response({"resource": resource})

    @blp.arguments(ResourceUpdateSchema, error_status_code=400)
    @blp.response(200)
    def patch(self, data: dict, resource_id: str) -> dict[str, Any]:
        """Update an existing resource."""
        module = _get_module()
        resource = module.update(
            resource_id=resource_id,
            name=data.get("name"),
            description=data.get("description"),
            email=data.get("email"),
            resource_type=data.get("resource_type"),
            capacity=data.get("capacity"),
            location=data.get("location"),
            features=data.get("features"),
            is_active=data.get("is_active"),
            booking_policy=data.get("booking_policy"),
            allowed_groups=data.get("allowed_groups"),
            auto_accept=data.get("auto_accept"),
        )
        return create_api_base_response({"resource": resource})

    @blp.response(200)
    def delete(self, resource_id: str) -> dict[str, Any]:
        """Delete a resource."""
        module = _get_module()
        module.delete(resource_id)
        return create_api_base_response({"deleted": resource_id})


@blp.route("/<string:resource_id>/availability")
class ApiResourceAvailability(MethodView):
    @blp.arguments(ResourceAvailabilitySchema, error_status_code=400)
    @blp.response(200)
    def post(self, data: dict, resource_id: str) -> dict[str, Any]:
        """Check resource availability for a time window."""
        from datetime import datetime

        module = _get_module()

        try:
            start = datetime.fromisoformat(data["start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(data["end"].replace("Z", "+00:00"))
        except (ValueError, KeyError) as exc:
            raise RequestException(
                error=err.ERROR_VALIDATION_FAILED,
                message="Invalid start/end datetime. Use ISO 8601 format.",
            ) from exc

        result = module.check_availability(resource_id=resource_id, start=start, end=end)
        return create_api_base_response(result)
