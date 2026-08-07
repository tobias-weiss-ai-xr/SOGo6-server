"""Admin SAML2 Provider Management API.

Blueprint prefix: ``/admin/v1/auth/saml2`` (registered by the admin API
package with the global ``/admin/v1`` prefix).

Endpoints:
  - GET    /providers           — list all SAML2 providers
  - GET    /providers/<id>      — get a single provider
  - POST   /providers           — create a new provider
  - PUT    /providers/<id>      — update an existing provider
  - DELETE /providers/<id>      — delete a provider
  - POST   /providers/<id>/refresh — refresh metadata from the provider's metadata_url
"""

from __future__ import annotations


from flask.views import MethodView
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.config.settings.ProcessSetting import process_config
from app.module.auth.ModuleSaml2Provider import ModuleSaml2Provider
from app.module.auth.Saml2Metadata import Saml2Metadata
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api

blp = Blueprint(
    "SAML2 Provider Management",
    __name__,
    url_prefix="/auth/saml2",
    description="Admin CRUD for SAML2 IdP providers",
)


# ── Schemas ───────────────────────────────────────────────────────────────────


class Saml2ProviderCreateSchema(Schema):
    """Schema for creating a SAML2 provider."""

    id = fields.String(required=True, metadata={"description": "Unique provider ID (slug)"})
    name = fields.String(required=True, metadata={"description": "Human-readable name"})
    entity_id = fields.String(required=True, metadata={"description": "IdP entityID"})
    sso_url = fields.Url(required=True, schemes={"http", "https"}, require_tld=False)
    sso_binding = fields.String(load_default="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect")
    sls_url = fields.Url(required=False, allow_none=True, schemes={"http", "https"}, require_tld=False)
    sls_binding = fields.String(required=False, allow_none=True)
    certificate = fields.String(required=False, allow_none=True, metadata={"description": "IdP X.509 cert (PEM)"})
    fingerprint = fields.String(required=False, allow_none=True)
    metadata_url = fields.Url(required=False, allow_none=True, schemes={"http", "https"}, require_tld=False)
    metadata_xml = fields.String(required=False, allow_none=True)
    nameid_format = fields.String(
        load_default="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
    )
    attribute_map = fields.Dict(required=False, allow_none=True)
    acs_url = fields.Url(required=False, allow_none=True, schemes={"http", "https"}, require_tld=False)
    is_active = fields.Boolean(load_default=True)


class Saml2ProviderUpdateSchema(Schema):
    """Schema for updating a SAML2 provider."""

    name = fields.String(required=False)
    entity_id = fields.String(required=False)
    sso_url = fields.Url(required=False, schemes={"http", "https"}, require_tld=False)
    sso_binding = fields.String(required=False)
    sls_url = fields.Url(required=False, allow_none=True, schemes={"http", "https"}, require_tld=False)
    sls_binding = fields.String(required=False, allow_none=True)
    certificate = fields.String(required=False, allow_none=True)
    fingerprint = fields.String(required=False, allow_none=True)
    metadata_url = fields.Url(required=False, allow_none=True, schemes={"http", "https"}, require_tld=False)
    metadata_xml = fields.String(required=False, allow_none=True)
    nameid_format = fields.String(required=False)
    attribute_map = fields.Dict(required=False, allow_none=True)
    acs_url = fields.Url(required=False, allow_none=True, schemes={"http", "https"}, require_tld=False)
    is_active = fields.Boolean(required=False)


def _module() -> ModuleSaml2Provider:
    """Return a per-request module instance."""
    return ModuleSaml2Provider(process_config)


# ── CRUD endpoints ────────────────────────────────────────────────────────────


@blp.route("/providers")
class ApiSaml2Providers(MethodView):
    @blp.response(200)
    def get(self) -> tuple[dict, int]:
        """List all SAML2 providers."""
        active_only = False
        providers = _module().list_providers(active_only=active_only)
        return create_api_base_response({"providers": providers, "total": len(providers)})

    @blp.arguments(Saml2ProviderCreateSchema, error_status_code=400)
    @blp.response(201)
    def post(self, data: dict) -> tuple[dict, int]:
        """Create a new SAML2 provider."""
        try:
            provider = _module().create_provider(data)
            return create_api_base_response(provider, status_code=201)
        except RequestException:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            logger_api.error("Failed to create SAML2 provider: %s", exc)
            return create_api_base_response(str(exc), err.ERROR_SAML_NOT_CONFIGURED)


@blp.route("/providers/<string:provider_id>")
class ApiSaml2ProviderById(MethodView):
    @blp.response(200)
    def get(self, provider_id: str) -> tuple[dict, int]:
        """Get a single SAML2 provider by ID."""
        provider = _module().get_provider(provider_id)
        if not provider:
            return create_api_base_response(
                f"SAML2 provider '{provider_id}' not found",
                err.ERROR_SAML_PROVIDER_NOT_FOUND,
            )
        return create_api_base_response(provider)

    @blp.arguments(Saml2ProviderUpdateSchema, error_status_code=400)
    @blp.response(200)
    def put(self, data: dict, provider_id: str) -> tuple[dict, int]:
        """Update a SAML2 provider."""
        try:
            provider = _module().update_provider(provider_id, data)
            return create_api_base_response(provider)
        except RequestException:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            logger_api.error("Failed to update SAML2 provider '%s': %s", provider_id, exc)
            return create_api_base_response(str(exc), err.ERROR_SAML_PROVIDER_NOT_FOUND)

    @blp.response(200)
    def delete(self, provider_id: str) -> tuple[dict, int]:
        """Delete a SAML2 provider."""
        try:
            _module().delete_provider(provider_id)
            return create_api_base_response({"deleted": True, "id": provider_id})
        except RequestException:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            logger_api.error("Failed to delete SAML2 provider '%s': %s", provider_id, exc)
            return create_api_base_response(str(exc), err.ERROR_SAML_PROVIDER_NOT_FOUND)


@blp.route("/providers/<string:provider_id>/refresh")
class ApiSaml2ProviderRefresh(MethodView):
    @blp.response(200)
    def post(self, provider_id: str) -> tuple[dict, int]:
        """Refresh a provider's metadata from its metadata_url."""
        try:
            provider = _module().get_provider(provider_id)
            if not provider:
                return create_api_base_response(
                    f"SAML2 provider '{provider_id}' not found",
                    err.ERROR_SAML_PROVIDER_NOT_FOUND,
                )

            metadata_url = provider.get("metadata_url", "")
            if not metadata_url:
                return create_api_base_response(
                    f"SAML2 provider '{provider_id}' has no metadata_url configured",
                    err.ERROR_SAML_METADATA_FETCH_FAILED,
                )

            # Fetch and parse the metadata
            metadata_fetcher = Saml2Metadata(process_config)
            idp_config = metadata_fetcher.fetch_idp_metadata(metadata_url)

            # Update the provider with refreshed metadata
            updated = _module().refresh_provider_metadata(
                provider_id,
                metadata_xml="",  # Will be set from the raw fetch
                sso_url=idp_config.get("sso_url", ""),
                certificate=idp_config.get("certificate", ""),
                fingerprint=idp_config.get("fingerprint", ""),
            )
            return create_api_base_response(updated)
        except RequestException:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            logger_api.error("Failed to refresh SAML2 provider '%s': %s", provider_id, exc)
            return create_api_base_response(str(exc), err.ERROR_SAML_METADATA_FETCH_FAILED)
