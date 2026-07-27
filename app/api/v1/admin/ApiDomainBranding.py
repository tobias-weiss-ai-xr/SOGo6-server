"""Multi-Tenant Branding — per-domain login page customization.

Each domain can have:
- Logo image (uploaded, stored as base64)
- Primary color
- Custom CSS
- Login page header/footer text
- Favicon
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
from flask import g, request
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api
from app.service import sogo_cache

if TYPE_CHECKING:
    from app.auth.User import User

blp = Blueprint("Domain Branding", __name__, url_prefix="/branding")

_BRANDING_PREFIX: str = "branding:"


class BrandingSchema(Schema):
    logo = fields.String(allow_none=True, metadata={"description": "Base64-encoded logo image (PNG/SVG, max 500KB)"})
    primary_color = fields.String(allow_none=True, metadata={"description": "Primary color hex code (e.g. #3B82F6)"})
    custom_css = fields.String(allow_none=True, metadata={"description": "Custom CSS injected into login page"})
    login_header = fields.String(allow_none=True, metadata={"description": "Header text shown on login page"})
    login_footer = fields.String(allow_none=True, metadata={"description": "Footer text shown on login page"})
    favicon = fields.String(allow_none=True, metadata={"description": "Base64-encoded favicon image"})


class PublicBrandingSchema(Schema):
    logo = fields.String(allow_none=True)
    primary_color = fields.String(allow_none=True)
    custom_css = fields.String(allow_none=True)
    login_header = fields.String(allow_none=True)
    login_footer = fields.String(allow_none=True)
    favicon = fields.String(allow_none=True)


@blp.route("/<string:domain>")
class ApiDomainBranding(MethodView):
    """Manage branding for a domain (admin only)."""

    @blp.response(200, BrandingSchema)
    def get(self, domain: str) -> ResponseReturnValue:
        """Get the current branding config for a domain."""
        cache = sogo_cache()
        raw = cache.get(f"{_BRANDING_PREFIX}{domain}", str)
        if not raw:
            return create_api_base_response({})
        try:
            import json
            return create_api_base_response(json.loads(raw))
        except Exception:
            return create_api_base_response({})

    @blp.arguments(BrandingSchema)
    @blp.response(200, BrandingSchema)
    def put(self, body: dict, domain: str) -> ResponseReturnValue:
        """Set branding config for a domain."""
        cache = sogo_cache()
        import json
        cache.set(f"{_BRANDING_PREFIX}{domain}", json.dumps(body), ttl=86400 * 365)
        logger_api.info("Branding updated for domain %s", domain)
        return create_api_base_response(body)


@blp.route("/<string:domain>/public")
class ApiPublicBranding(MethodView):
    """Public branding endpoint (no auth required)."""

    @blp.response(200, PublicBrandingSchema)
    def get(self, domain: str) -> ResponseReturnValue:
        """Get public branding info for a domain (logo, colors, CSS)."""
        cache = sogo_cache()
        raw = cache.get(f"{_BRANDING_PREFIX}{domain}", str)
        if not raw:
            return create_api_base_response({})
        try:
            import json
            data = json.loads(raw)
            # Only return public-safe fields
            safe = {k: data[k] for k in PublicBrandingSchema._declared_fields if k in data}
            return create_api_base_response(safe)
        except Exception:
            return create_api_base_response({})
