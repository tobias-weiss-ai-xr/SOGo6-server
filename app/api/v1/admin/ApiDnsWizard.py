from __future__ import annotations

from typing import Any

from flask.views import MethodView
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate

from app.module.admin.DnsWizard import DnsWizard
from app.utils.api.ApiBaseResponse import create_api_base_response

blp = Blueprint(
    "DNS Wizard",
    __name__,
    url_prefix="/dns",
    description="DKIM/DMARC/SPF DNS record generator and validator",
)


# ── Schemas ───────────────────────────────────────────────────────────────────


class SpfGenerateSchema(Schema):
    """Request body for SPF record generation."""
    domain = fields.String(required=True, metadata={"example": "example.org"})
    mx_servers = fields.List(fields.String(), load_default=None, metadata={"example": ["mx1.example.org"]})
    ip4_addresses = fields.List(fields.String(), load_default=None, metadata={"example": ["192.0.2.1"]})
    ip6_addresses = fields.List(fields.String(), load_default=None)
    include_domains = fields.List(fields.String(), load_default=None, metadata={"example": ["spf.mailhost.com"]})
    policy = fields.String(load_default="~all", validate=validate.OneOf(["-all", "~all", "+all", "?all"]))


class SpfValidateSchema(Schema):
    """Request body for SPF validation."""
    spf_value = fields.String(required=True, metadata={"example": "v=spf1 mx ~all"})


class DkimGenerateDnsSchema(Schema):
    """Request body for DKIM record generation."""
    domain = fields.String(required=True, metadata={"example": "example.org"})
    selector = fields.String(load_default="sogo", metadata={"example": "sogo"})
    key_type = fields.String(load_default="ed25519", validate=validate.OneOf(["ed25519", "rsa"]))
    public_key = fields.String(load_default=None, allow_none=True)


class DmarcGenerateSchema(Schema):
    """Request body for DMARC record generation."""
    domain = fields.String(required=True, metadata={"example": "example.org"})
    policy = fields.String(load_default="none", validate=validate.OneOf(["none", "quarantine", "reject"]))
    rua_email = fields.String(load_default=None, allow_none=True, metadata={"example": "dmarc@example.org"})
    ruf_email = fields.String(load_default=None, allow_none=True)
    pct = fields.Integer(load_default=100, validate=validate.Range(min=1, max=100))
    subdomain_policy = fields.String(load_default=None, allow_none=True,
                                     validate=validate.OneOf(["none", "quarantine", "reject"]))
    aspf = fields.String(load_default="r", validate=validate.OneOf(["r", "s"]))
    adkim = fields.String(load_default="r", validate=validate.OneOf(["r", "s"]))


class DmarcValidateSchema(Schema):
    """Request body for DMARC validation."""
    dmarc_value = fields.String(required=True, metadata={"example": "v=DMARC1; p=none; pct=100"})


class DnsRecordResponseSchema(Schema):
    """Response schema for a generated DNS record."""
    name = fields.String()
    type = fields.String()
    value = fields.String()
    ttl = fields.Integer()
    selector = fields.String(load_default=None, dump_default=None)
    description = fields.String()


class ValidationResultSchema(Schema):
    """Response schema for validation results."""
    valid = fields.Boolean()
    warnings = fields.List(fields.String())
    errors = fields.List(fields.String())


# ── Endpoints ─────────────────────────────────────────────────────────────────


@blp.route("/spf/generate")
class ApiSpfGenerate(MethodView):
    @blp.arguments(SpfGenerateSchema, error_status_code=400)
    @blp.response(200)
    def post(self, data: dict) -> dict[str, Any]:
        """Generate an SPF TXT record for the given domain."""
        record = DnsWizard.generate_spf_record(
            domain=data["domain"],
            mx_servers=data.get("mx_servers"),
            ip4_addresses=data.get("ip4_addresses"),
            ip6_addresses=data.get("ip6_addresses"),
            include_domains=data.get("include_domains"),
            policy=data.get("policy", "~all"),
        )
        return create_api_base_response({"record": record, "wizard_type": "spf"})


@blp.route("/spf/validate")
class ApiSpfValidate(MethodView):
    @blp.arguments(SpfValidateSchema, error_status_code=400)
    @blp.response(200)
    def post(self, data: dict) -> dict[str, Any]:
        """Validate an SPF record value."""
        result = DnsWizard.validate_spf(data["spf_value"])
        return create_api_base_response(result)


@blp.route("/dkim/generate")
class ApiDkimGenerate(MethodView):
    @blp.arguments(DkimGenerateDnsSchema, error_status_code=400)
    @blp.response(200)
    def post(self, data: dict) -> dict[str, Any]:
        """Generate a DKIM TXT record."""
        record = DnsWizard.generate_dkim_record(
            domain=data["domain"],
            selector=data.get("selector", "sogo"),
            key_type=data.get("key_type", "ed25519"),
            public_key=data.get("public_key"),
        )
        return create_api_base_response({"record": record, "wizard_type": "dkim"})


@blp.route("/dmarc/generate")
class ApiDmarcGenerate(MethodView):
    @blp.arguments(DmarcGenerateSchema, error_status_code=400)
    @blp.response(200)
    def post(self, data: dict) -> dict[str, Any]:
        """Generate a DMARC TXT record."""
        record = DnsWizard.generate_dmarc_record(
            domain=data["domain"],
            policy=data.get("policy", "none"),
            rua_email=data.get("rua_email"),
            ruf_email=data.get("ruf_email"),
            pct=data.get("pct", 100),
            subdomain_policy=data.get("subdomain_policy"),
            aspf=data.get("aspf", "r"),
            adkim=data.get("adkim", "r"),
        )
        return create_api_base_response({"record": record, "wizard_type": "dmarc"})


@blp.route("/dmarc/validate")
class ApiDmarcValidate(MethodView):
    @blp.arguments(DmarcValidateSchema, error_status_code=400)
    @blp.response(200)
    def post(self, data: dict) -> dict[str, Any]:
        """Validate a DMARC record value."""
        result = DnsWizard.validate_dmarc(data["dmarc_value"])
        return create_api_base_response(result)
