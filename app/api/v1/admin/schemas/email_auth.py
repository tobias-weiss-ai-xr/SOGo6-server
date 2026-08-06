"""Request/response schemas for the admin email-auth (DKIM/DMARC/SPF) API."""

from __future__ import annotations

from marshmallow import Schema, fields, validate


class EmailAuthDomainCreateSchema(Schema):
    """Request body for adding a domain."""
    name = fields.String(required=True, metadata={"example": "example.org"})
    description = fields.String(load_default="", metadata={"example": "Primary domain"})
    is_active = fields.Boolean(load_default=True)


class EmailAuthDomainResponseSchema(Schema):
    """A configured domain."""
    name = fields.String()
    description = fields.String()
    is_active = fields.Boolean()
    created_at = fields.String()
    updated_at = fields.String()


class EmailAuthDomainStatusSchema(Schema):
    """Aggregate authentication status for a domain."""
    domain = fields.String()
    dkim_status = fields.String(validate=validate.OneOf(["ok", "warning", "error", "none"]))
    dkim_status_msg = fields.String()
    dmarc_status = fields.String(validate=validate.OneOf(["ok", "warning", "error", "none"]))
    dmarc_status_msg = fields.String()
    spf_status = fields.String(validate=validate.OneOf(["ok", "warning", "error", "none"]))
    spf_status_msg = fields.String()
    overall_status = fields.String(validate=validate.OneOf(["ok", "warning", "error", "none"]))
    overall_recommendations = fields.List(fields.String())


class DkimGenerateSchema(Schema):
    """Request to generate a DKIM key pair."""
    key_length = fields.Integer(load_default=2048, validate=validate.OneOf([1024, 2048, 4096]))


class DkimGenerateResponseSchema(Schema):
    """Generated DKIM key pair (private key included in response only)."""
    private_key = fields.String()
    public_key = fields.String()
    key_type = fields.String()
    key_length = fields.String()
    public_key_fingerprint = fields.String()


class DkimConfigSchema(Schema):
    """DKIM configuration payload."""
    selector = fields.String(load_default="default", metadata={"example": "default"})
    enabled = fields.Boolean(load_default=True)
    key_length = fields.Integer(load_default=2048, validate=validate.OneOf([1024, 2048, 4096]))
    signing_algorithm = fields.String(load_default="rsa-sha256",
                                      validate=validate.OneOf(["rsa-sha1", "rsa-sha256"]))
    headers_to_sign = fields.List(fields.String(), load_default=None)
    notes = fields.String(load_default="")
    public_key = fields.String(load_default=None, allow_none=True)
    dns_record = fields.Dict(load_default=None, allow_none=True)


class DkimConfigResponseSchema(Schema):
    """DKIM configuration for a domain."""
    domain = fields.String()
    selector = fields.String()
    enabled = fields.Boolean()
    key_length = fields.Integer()
    signing_algorithm = fields.String()
    headers_to_sign = fields.List(fields.String(), allow_none=True)
    notes = fields.String()
    public_key = fields.String(allow_none=True)
    dns_record = fields.Dict(allow_none=True)
    created_at = fields.String()
    updated_at = fields.String()


class DkimValidateResponseSchema(Schema):
    """DKIM validation result."""
    domain = fields.String()
    selector = fields.String()
    is_valid = fields.Boolean()
    errors = fields.List(fields.String())
    warnings = fields.List(fields.String())
    dns_record_found = fields.Boolean()
    record_value = fields.String(allow_none=True)
    expected_value = fields.String(allow_none=True)
    dns_lookup_available = fields.Boolean()
    checked_at = fields.String()


class DmarcConfigSchema(Schema):
    """DMARC policy payload."""
    enabled = fields.Boolean(load_default=True)
    policy = fields.String(load_default="none", validate=validate.OneOf(["none", "quarantine", "reject"]))
    subdomain_policy = fields.String(load_default=None, allow_none=True,
                                     validate=validate.OneOf(["none", "quarantine", "reject"]))
    pct = fields.Integer(load_default=100, validate=validate.Range(min=1, max=100))
    aspf = fields.String(load_default="r", validate=validate.OneOf(["r", "s"]))
    adkim = fields.String(load_default="r", validate=validate.OneOf(["r", "s"]))
    rua = fields.List(fields.Email(), load_default=None)
    ruf = fields.List(fields.Email(), load_default=None)
    ri = fields.Integer(load_default=86400, validate=validate.Range(min=1))
    notes = fields.String(load_default="")


class DmarcConfigResponseSchema(Schema):
    """DMARC policy for a domain."""
    domain = fields.String()
    enabled = fields.Boolean()
    policy = fields.String()
    subdomain_policy = fields.String(allow_none=True)
    pct = fields.Integer()
    aspf = fields.String()
    adkim = fields.String()
    rua = fields.List(fields.String())
    ruf = fields.List(fields.String())
    ri = fields.Integer()
    notes = fields.String()
    record_value = fields.String(allow_none=True)
    created_at = fields.String()
    updated_at = fields.String()


class DmarcValidateResponseSchema(Schema):
    """DMARC validation result."""
    domain = fields.String()
    is_valid = fields.Boolean()
    errors = fields.List(fields.String())
    warnings = fields.List(fields.String())
    dns_record_found = fields.Boolean()
    record_value = fields.String(allow_none=True)
    expected_record = fields.String(allow_none=True)
    dns_lookup_available = fields.Boolean()
    checked_at = fields.String()


class SpfConfigSchema(Schema):
    """SPF record payload."""
    enabled = fields.Boolean(load_default=True)
    include_mechanisms = fields.List(fields.String(), load_default=None)
    ip4_mechanisms = fields.List(fields.String(), load_default=None)
    ip6_mechanisms = fields.List(fields.String(), load_default=None)
    a_mechanisms = fields.List(fields.String(), load_default=None)
    mx_mechanisms = fields.List(fields.String(), load_default=None)
    exists_mechanisms = fields.List(fields.String(), load_default=None)
    raw_mail_servers = fields.String(load_default=None, allow_none=True)
    all_qualifier = fields.String(load_default="-all", validate=validate.OneOf(["+all", "-all", "~all", "?all"]))
    redirect_modifier = fields.String(load_default=None, allow_none=True)
    explanation_modifier = fields.String(load_default=None, allow_none=True)
    notes = fields.String(load_default="")


class SpfConfigResponseSchema(Schema):
    """SPF record for a domain."""
    domain = fields.String()
    enabled = fields.Boolean()
    include_mechanisms = fields.List(fields.String())
    ip4_mechanisms = fields.List(fields.String())
    ip6_mechanisms = fields.List(fields.String())
    a_mechanisms = fields.List(fields.String())
    mx_mechanisms = fields.List(fields.String())
    exists_mechanisms = fields.List(fields.String())
    raw_mail_servers = fields.String(allow_none=True)
    all_qualifier = fields.String()
    redirect_modifier = fields.String(allow_none=True)
    explanation_modifier = fields.String(allow_none=True)
    notes = fields.String()
    record_value = fields.String(allow_none=True)
    created_at = fields.String()
    updated_at = fields.String()


class SpfValidateResponseSchema(Schema):
    """SPF validation result."""
    domain = fields.String()
    is_valid = fields.Boolean()
    errors = fields.List(fields.String())
    warnings = fields.List(fields.String())
    dns_record_found = fields.Boolean()
    record_value = fields.String(allow_none=True)
    expected_record = fields.String(allow_none=True)
    mechanism_count = fields.Integer()
    dns_lookup_count = fields.Integer()
    over_lookup_limit = fields.Boolean()
    dns_lookup_available = fields.Boolean()
    checked_at = fields.String()


class EmailAuthTestSchema(Schema):
    """Request to test email authentication."""
    from_address = fields.Email(required=True)
    smtp_server = fields.String(load_default="localhost")
    smtp_port = fields.Integer(load_default=25)


class EmailAuthTestResultSchema(Schema):
    """Result of an email authentication test."""
    sent = fields.Boolean()
    smtp_response = fields.String()
    domain = fields.String()
    from_address = fields.String()
    timestamp = fields.String()
