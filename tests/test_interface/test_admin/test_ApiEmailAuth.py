"""Structural tests for the Email Authentication (DKIM/DMARC/SPF) Admin API.

Fixture-free by design (no client/auth fixtures — those only exist under
``tests/test_integration/conftest.py``), matching the project convention for
``test_interface`` structural tests.
"""
import pytest


class TestEmailAuthSchemas:
    """Verify the request/response schema definitions."""

    def test_domain_create_schema_fields(self):
        from app.api.v1.admin.schemas.email_auth import EmailAuthDomainCreateSchema
        schema = EmailAuthDomainCreateSchema()
        assert "name" in schema.fields
        assert "description" in schema.fields
        assert "is_active" in schema.fields
        assert schema.fields["name"].required is True

    def test_dkim_generate_schema_limits_key_length(self):
        from app.api.v1.admin.schemas.email_auth import DkimGenerateSchema
        schema = DkimGenerateSchema()
        validator = schema.fields["key_length"].validators[0]
        assert validator.choices == [1024, 2048, 4096]

    def test_dmarc_config_schema_policy_choices(self):
        from app.api.v1.admin.schemas.email_auth import DmarcConfigSchema
        schema = DmarcConfigSchema()
        policy = schema.fields["policy"]
        assert policy.validators[0].choices == ["none", "quarantine", "reject"]

    def test_spf_config_schema_all_qualifier_choices(self):
        from app.api.v1.admin.schemas.email_auth import SpfConfigSchema
        schema = SpfConfigSchema()
        assert schema.fields["all_qualifier"].validators[0].choices == ["+all", "-all", "~all", "?all"]

    def test_schemas_load_defaults(self):
        from app.api.v1.admin.schemas.email_auth import (
            DkimGenerateSchema,
            DmarcConfigSchema,
            SpfConfigSchema,
        )
        assert DkimGenerateSchema().load({})["key_length"] == 2048
        assert DmarcConfigSchema().load({})["policy"] == "none"
        assert SpfConfigSchema().load({})["all_qualifier"] == "-all"


class TestEmailAuthBlueprint:
    """Verify blueprint registration and endpoint classes."""

    def test_blueprint_prefix(self):
        from app.api.v1.admin.ApiEmailAuth import blp
        assert blp.url_prefix == "/email-auth"
        assert blp.name == "Email Authentication"

    def test_domains_endpoint_methods(self):
        from app.api.v1.admin.ApiEmailAuth import (
            ApiEmailAuthDomains,
            ApiEmailAuthDomainItem,
            ApiEmailAuthDomainStatus,
        )
        assert hasattr(ApiEmailAuthDomains, "get")
        assert hasattr(ApiEmailAuthDomains, "post")
        assert hasattr(ApiEmailAuthDomainItem, "get")
        assert hasattr(ApiEmailAuthDomainItem, "delete")
        assert hasattr(ApiEmailAuthDomainStatus, "get")

    def test_dkim_endpoint_methods(self):
        from app.api.v1.admin.ApiEmailAuth import (
            ApiEmailAuthDkimList,
            ApiEmailAuthDkimGenerate,
            ApiEmailAuthDkimItem,
            ApiEmailAuthDkimRotate,
            ApiEmailAuthDkimValidate,
        )
        assert hasattr(ApiEmailAuthDkimList, "get")
        assert hasattr(ApiEmailAuthDkimGenerate, "post")
        for method in ("get", "post", "put", "delete"):
            assert hasattr(ApiEmailAuthDkimItem, method)
        assert hasattr(ApiEmailAuthDkimRotate, "post")
        assert hasattr(ApiEmailAuthDkimValidate, "post")

    def test_dmarc_endpoint_methods(self):
        from app.api.v1.admin.ApiEmailAuth import (
            ApiEmailAuthDmarcList,
            ApiEmailAuthDmarcItem,
            ApiEmailAuthDmarcValidate,
            ApiEmailAuthDmarcReports,
        )
        assert hasattr(ApiEmailAuthDmarcList, "get")
        for method in ("get", "post", "put", "delete"):
            assert hasattr(ApiEmailAuthDmarcItem, method)
        assert hasattr(ApiEmailAuthDmarcValidate, "post")
        assert hasattr(ApiEmailAuthDmarcReports, "get")

    def test_spf_endpoint_methods(self):
        from app.api.v1.admin.ApiEmailAuth import (
            ApiEmailAuthSpfList,
            ApiEmailAuthSpfItem,
            ApiEmailAuthSpfValidate,
        )
        assert hasattr(ApiEmailAuthSpfList, "get")
        for method in ("get", "post", "put", "delete"):
            assert hasattr(ApiEmailAuthSpfItem, method)
        assert hasattr(ApiEmailAuthSpfValidate, "post")

    def test_test_and_validate_all_endpoints(self):
        from app.api.v1.admin.ApiEmailAuth import (
            ApiEmailAuthTest,
            ApiEmailAuthValidateAll,
        )
        assert hasattr(ApiEmailAuthTest, "post")
        assert hasattr(ApiEmailAuthValidateAll, "post")


class TestEmailAuthErrors:
    """Verify error constants used by the endpoints."""

    def test_domain_not_found_error(self):
        from app.utils import errors as err
        assert err.ERROR_EMAIL_AUTH_DOMAIN_NOT_FOUND.c == "S000638"
        assert err.ERROR_EMAIL_AUTH_DOMAIN_NOT_FOUND.h == 404

    def test_duplicate_domain_error_conflict(self):
        from app.utils import errors as err
        assert err.ERROR_EMAIL_AUTH_DOMAIN_ALREADY_EXISTS.h == 409

    def test_config_not_found_errors(self):
        from app.utils import errors as err
        assert err.ERROR_EMAIL_AUTH_DKIM_NOT_FOUND.c == "S000640"
        assert err.ERROR_EMAIL_AUTH_DMARC_NOT_FOUND.c == "S000641"
        assert err.ERROR_EMAIL_AUTH_SPF_NOT_FOUND.c == "S000642"

    def test_invalid_key_length_error(self):
        from app.utils import errors as err
        assert err.ERROR_EMAIL_AUTH_INVALID_KEY_LENGTH.h == 400


class TestEmailAuthModuleIntegration:
    """Verify the API module binding works end to end (in-memory)."""

    def test_module_roundtrip(self):
        from app.module.admin.ModuleEmailAuth import ModuleEmailAuth
        module = ModuleEmailAuth()
        module.add_domain("example.org")
        keys = module.generate_key_pair(2048)
        module.set_dkim("example.org", {"public_key": keys["public_key"]})
        module.set_dmarc("example.org", {"policy": "quarantine"})
        module.set_spf("example.org", {"include_mechanisms": ["_spf.google.com"]})
        status = module.get_domain_status("example.org")
        assert status["overall_status"] in ("ok", "warning", "error")
        assert status["dkim_status"] == "ok"
