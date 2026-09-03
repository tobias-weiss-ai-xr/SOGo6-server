"""Admin Email Authentication API — DKIM/DMARC/SPF wizard.

Blueprint prefix: ``/admin/v1/email-auth`` (registered by the admin API
package with the global ``/admin/v1`` prefix).
"""

from __future__ import annotations


from flask.views import MethodView
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.module.admin.ModuleEmailAuth import ModuleEmailAuth
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import RequestException

from .schemas.email_auth import (
    DkimConfigSchema,
    DkimGenerateSchema,
    DmarcConfigSchema,
    EmailAuthDomainCreateSchema,
    EmailAuthTestSchema,
    SpfConfigSchema,
)

blp = Blueprint(
    "Email Authentication",
    __name__,
    url_prefix="/email-auth",
    description="DKIM/DMARC/SPF email authentication wizard",
)


def _module() -> ModuleEmailAuth:
    """Return a per-request module instance (in-memory store per process)."""
    return ModuleEmailAuth()


class _BaseResource(MethodView):
    """Shared error translation for the email-auth endpoints."""

    @staticmethod
    def _not_found(kind: str) -> RequestException:
        mapping = {
            "domain": err.ERROR_EMAIL_AUTH_DOMAIN_NOT_FOUND,
            "dkim": err.ERROR_EMAIL_AUTH_DKIM_NOT_FOUND,
            "dmarc": err.ERROR_EMAIL_AUTH_DMARC_NOT_FOUND,
            "spf": err.ERROR_EMAIL_AUTH_SPF_NOT_FOUND,
        }
        e = mapping.get(kind, err.ERROR_EMAIL_AUTH_DOMAIN_NOT_FOUND)
        return RequestException(error=e)


# ── Domains ───────────────────────────────────────────────────────────────────


@blp.route("/domains")
class ApiEmailAuthDomains(MethodView):
    @blp.response(200)
    def get(self) -> tuple[dict, int]:
        """List all configured domains."""
        domains = _module().list_domains()
        return create_api_base_response({"domains": domains, "total_count": len(domains)})

    @blp.arguments(EmailAuthDomainCreateSchema, error_status_code=400)
    @blp.response(201)
    def post(self, data: dict) -> tuple[dict, int]:
        """Add a domain."""
        try:
            domain = _module().add_domain(data["name"], data.get("description", ""), data.get("is_active", True))
        except KeyError:
            raise RequestException(
                error=err.ERROR_EMAIL_AUTH_DOMAIN_ALREADY_EXISTS,
                http_status=err.ERROR_EMAIL_AUTH_DOMAIN_ALREADY_EXISTS.h,
            ) from None
        return create_api_base_response({"domain": domain})


@blp.route("/domains/<string:domain>")
class ApiEmailAuthDomainItem(MethodView):
    @blp.response(200)
    def get(self, domain: str) -> tuple[dict, int]:
        """Get a single domain."""
        found = _module().get_domain(domain)
        if not found:
            raise _BaseResource._not_found("domain")
        return create_api_base_response({"domain": found})

    @blp.response(200)
    def delete(self, domain: str) -> tuple[dict, int]:
        """Remove a domain and its configurations."""
        if not _module().remove_domain(domain):
            raise _BaseResource._not_found("domain")
        return create_api_base_response({"deleted": domain})


@blp.route("/domains/<string:domain>/status")
class ApiEmailAuthDomainStatus(MethodView):
    @blp.response(200)
    def get(self, domain: str) -> tuple[dict, int]:
        """Get aggregate DKIM/DMARC/SPF status for a domain."""
        try:
            status = _module().get_domain_status(domain)
        except KeyError:
            raise _BaseResource._not_found("domain") from None
        return create_api_base_response({"status": status})


# ── DKIM ──────────────────────────────────────────────────────────────────────


@blp.route("/dkim")
class ApiEmailAuthDkimList(MethodView):
    @blp.response(200)
    def get(self) -> tuple[dict, int]:
        """List all DKIM configurations."""
        configs = _module().list_dkim()
        return create_api_base_response({"dkim_configs": configs, "total_count": len(configs)})


@blp.route("/dkim/generate")
class ApiEmailAuthDkimGenerate(MethodView):
    @blp.arguments(DkimGenerateSchema, error_status_code=400)
    @blp.response(200)
    def post(self, data: dict) -> tuple[dict, int]:
        """Generate a DKIM RSA key pair."""
        module = _module()
        try:
            keys = module.generate_key_pair(data.get("key_length", 2048))
        except ValueError:
            raise RequestException(
                error=err.ERROR_EMAIL_AUTH_INVALID_KEY_LENGTH,
                http_status=err.ERROR_EMAIL_AUTH_INVALID_KEY_LENGTH.h,
            ) from None
        return create_api_base_response({"key_pair": keys})


@blp.route("/dkim/<string:domain>")
class ApiEmailAuthDkimItem(MethodView):
    @blp.response(200)
    def get(self, domain: str) -> tuple[dict, int]:
        """Get DKIM config for a domain."""
        config = _module().get_dkim(domain)
        if not config:
            raise _BaseResource._not_found("dkim")
        return create_api_base_response({"dkim": config})

    @blp.arguments(DkimConfigSchema, error_status_code=400)
    @blp.response(201)
    def post(self, data: dict, domain: str) -> tuple[dict, int]:
        """Configure DKIM for a domain."""
        module = _module()
        try:
            config = module.set_dkim(domain, data)
        except KeyError:
            raise _BaseResource._not_found("domain") from None
        return create_api_base_response({"dkim": config})

    @blp.arguments(DkimConfigSchema, error_status_code=400)
    @blp.response(200)
    def put(self, data: dict, domain: str) -> tuple[dict, int]:
        """Update DKIM config for a domain."""
        module = _module()
        try:
            config = module.update_dkim(domain, data)
        except KeyError:
            raise _BaseResource._not_found("dkim") from None
        return create_api_base_response({"dkim": config})

    @blp.response(200)
    def delete(self, domain: str) -> tuple[dict, int]:
        """Remove DKIM config for a domain."""
        if not _module().remove_dkim(domain):
            raise _BaseResource._not_found("dkim")
        return create_api_base_response({"deleted": domain})


@blp.route("/dkim/<string:domain>/rotate")
class ApiEmailAuthDkimRotate(MethodView):
    @blp.arguments(Schema.from_dict({"key_length": fields.Integer(load_default=None, allow_none=True)}), error_status_code=400)
    @blp.response(200)
    def post(self, data: dict, domain: str) -> tuple[dict, int]:
        """Rotate DKIM keys for a domain (generate fresh pair)."""
        module = _module()
        try:
            config = module.rotate_dkim(domain, data.get("key_length"))
        except KeyError:
            raise _BaseResource._not_found("dkim") from None
        return create_api_base_response({"dkim": config})


@blp.route("/dkim/<string:domain>/validate")
class ApiEmailAuthDkimValidate(MethodView):
    @blp.response(200)
    def post(self, domain: str) -> tuple[dict, int]:
        """Validate DKIM DNS record for a domain."""
        result = _module().validate_dkim(domain)
        return create_api_base_response({"validation": result})


# ── DMARC ─────────────────────────────────────────────────────────────────────


@blp.route("/dmarc")
class ApiEmailAuthDmarcList(MethodView):
    @blp.response(200)
    def get(self) -> tuple[dict, int]:
        """List all DMARC policies."""
        configs = _module().list_dmarc()
        return create_api_base_response({"dmarc_policies": configs, "total_count": len(configs)})


@blp.route("/dmarc/<string:domain>")
class ApiEmailAuthDmarcItem(MethodView):
    @blp.response(200)
    def get(self, domain: str) -> tuple[dict, int]:
        """Get DMARC policy for a domain."""
        config = _module().get_dmarc(domain)
        if not config:
            raise _BaseResource._not_found("dmarc")
        return create_api_base_response({"dmarc": config})

    @blp.arguments(DmarcConfigSchema, error_status_code=400)
    @blp.response(201)
    def post(self, data: dict, domain: str) -> tuple[dict, int]:
        """Configure DMARC for a domain."""
        module = _module()
        try:
            config = module.set_dmarc(domain, data)
        except KeyError:
            raise _BaseResource._not_found("domain") from None
        return create_api_base_response({"dmarc": config})

    @blp.arguments(DmarcConfigSchema, error_status_code=400)
    @blp.response(200)
    def put(self, data: dict, domain: str) -> tuple[dict, int]:
        """Update DMARC policy for a domain."""
        module = _module()
        try:
            config = module.update_dmarc(domain, data)
        except KeyError:
            raise _BaseResource._not_found("dmarc") from None
        return create_api_base_response({"dmarc": config})

    @blp.response(200)
    def delete(self, domain: str) -> tuple[dict, int]:
        """Remove DMARC policy for a domain."""
        if not _module().remove_dmarc(domain):
            raise _BaseResource._not_found("dmarc")
        return create_api_base_response({"deleted": domain})


@blp.route("/dmarc/<string:domain>/validate")
class ApiEmailAuthDmarcValidate(MethodView):
    @blp.response(200)
    def post(self, domain: str) -> tuple[dict, int]:
        """Validate DMARC DNS record for a domain."""
        result = _module().validate_dmarc(domain)
        return create_api_base_response({"validation": result})


@blp.route("/dmarc/<string:domain>/reports")
class ApiEmailAuthDmarcReports(MethodView):
    @blp.response(200)
    def get(self, domain: str) -> tuple[dict, int]:
        """Get stored DMARC aggregate reports for a domain."""
        reports = _module().get_dmarc_reports(domain)
        return create_api_base_response({"reports": reports, "total_count": len(reports)})


# ── SPF ───────────────────────────────────────────────────────────────────────


@blp.route("/spf")
class ApiEmailAuthSpfList(MethodView):
    @blp.response(200)
    def get(self) -> tuple[dict, int]:
        """List all SPF records."""
        configs = _module().list_spf()
        return create_api_base_response({"spf_records": configs, "total_count": len(configs)})


@blp.route("/spf/<string:domain>")
class ApiEmailAuthSpfItem(MethodView):
    @blp.response(200)
    def get(self, domain: str) -> tuple[dict, int]:
        """Get SPF record for a domain."""
        config = _module().get_spf(domain)
        if not config:
            raise _BaseResource._not_found("spf")
        return create_api_base_response({"spf": config})

    @blp.arguments(SpfConfigSchema, error_status_code=400)
    @blp.response(201)
    def post(self, data: dict, domain: str) -> tuple[dict, int]:
        """Configure SPF for a domain."""
        module = _module()
        try:
            config = module.set_spf(domain, data)
        except KeyError:
            raise _BaseResource._not_found("domain") from None
        return create_api_base_response({"spf": config})

    @blp.arguments(SpfConfigSchema, error_status_code=400)
    @blp.response(200)
    def put(self, data: dict, domain: str) -> tuple[dict, int]:
        """Update SPF record for a domain."""
        module = _module()
        try:
            config = module.update_spf(domain, data)
        except KeyError:
            raise _BaseResource._not_found("spf") from None
        return create_api_base_response({"spf": config})

    @blp.response(200)
    def delete(self, domain: str) -> tuple[dict, int]:
        """Remove SPF record for a domain."""
        if not _module().remove_spf(domain):
            raise _BaseResource._not_found("spf")
        return create_api_base_response({"deleted": domain})


@blp.route("/spf/<string:domain>/validate")
class ApiEmailAuthSpfValidate(MethodView):
    @blp.response(200)
    def post(self, domain: str) -> tuple[dict, int]:
        """Validate SPF DNS record for a domain."""
        result = _module().validate_spf(domain)
        return create_api_base_response({"validation": result})


# ── Testing / bulk ────────────────────────────────────────────────────────────


@blp.route("/test")
class ApiEmailAuthTest(MethodView):
    @blp.arguments(EmailAuthTestSchema, error_status_code=400)
    @blp.response(200)
    def post(self, data: dict) -> tuple[dict, int]:
        """Test email authentication (SMTP connectivity)."""
        result = ModuleEmailAuth.test_email_auth(
            data["from_address"],
            data.get("smtp_server", "localhost"),
            data.get("smtp_port", 25),
        )
        return create_api_base_response({"test": result})


@blp.route("/validate-all")
class ApiEmailAuthValidateAll(MethodView):
    @blp.response(200)
    def post(self) -> tuple[dict, int]:
        """Validate all configured domains."""
        statuses = _module().validate_all()
        return create_api_base_response({"statuses": statuses, "total_count": len(statuses)})
