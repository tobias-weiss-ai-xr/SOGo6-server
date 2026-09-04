"""Structural tests for AuthUserApi (authentication API blueprint).

Tests verify the Blueprint structure, schema definitions, routes, and key
logic patterns without executing code (blueprints are not registered in __init__.py).

Following the Round 18 pattern for unregistered blueprints - these tests document
API contracts and guard against accidental deletion/refactor, even though they
don't move coverage % (structural tests read file content, they don't execute code).
"""
import re

import pytest


@pytest.fixture
def blueprint_content():
    """Read the AuthUserApi blueprint file."""
    with open("app/api/v1/auth/AuthUserApi.py", "r") as f:
        return f.read()


@pytest.fixture
def schema_content():
    """Read the authUser schema file."""
    with open("app/api/v1/auth/schema/authUser.py", "r") as f:
        return f.read()


class TestBlueprintStructure:
    def test_file_contains_blueprint(self, blueprint_content):
        assert "Blueprint" in blueprint_content
        assert "blp = Blueprint" in blueprint_content

    def test_blueprint_has_correct_name(self, blueprint_content):
        assert 'Blueprint("Auth"' in blueprint_content
        assert 'url_prefix="/auth"' in blueprint_content

    def test_file_contains_method_views(self, blueprint_content):
        assert "MethodView" in blueprint_content

    def test_file_imports_interface(self, blueprint_content):
        assert "InterfaceAuthUser" in blueprint_content

    def test_file_imports_errors(self, blueprint_content):
        assert "errors as err" in blueprint_content

    def test_file_imports_logger(self, blueprint_content):
        assert "logger_api" in blueprint_content


class TestRoutes:
    def test_has_mode_route(self, blueprint_content):
        assert '@blp.route("/mode")' in blueprint_content

    def test_has_login_route(self, blueprint_content):
        assert '@blp.route("/login")' in blueprint_content

    def test_has_callback_route(self, blueprint_content):
        assert '@blp.route("/callback/<string:domain>")' in blueprint_content

    def test_has_saml2_discovery_route(self, blueprint_content):
        assert '@blp.route("/saml2/discovery")' in blueprint_content

    def test_has_logout_route(self, blueprint_content):
        assert '@blp.route("/logout")' in blueprint_content


class TestApiAuthUserMode:
    def test_mode_class_exists(self, blueprint_content):
        assert "class ApiAuthUserMode(MethodView):" in blueprint_content

    def test_mode_has_get_method(self, blueprint_content):
        pattern = r'class ApiAuthUserMode\(MethodView\):.*?def get\(self, username:str, redirect:str\)'
        assert re.search(pattern, blueprint_content, re.DOTALL)

    def test_mode_uses_get_login_mech(self, blueprint_content):
        assert "get_login_mech" in blueprint_content

    def test_mode_has_query_arguments(self, blueprint_content):
        assert "AuthUserGetMechSchema" in blueprint_content
        assert "location='query'" in blueprint_content


class TestApiAuthUserLogin:
    def test_login_class_exists(self, blueprint_content):
        assert "class ApiAuthUserLogin(MethodView):" in blueprint_content

    def test_login_has_post_method(self, blueprint_content):
        pattern = r'class ApiAuthUserLogin\(MethodView\):.*?def post\(self, new_data:dict\)'
        assert re.search(pattern, blueprint_content, re.DOTALL)

    def test_login_uses_plain_login(self, blueprint_content):
        assert "plain_login" in blueprint_content

    def test_login_has_rate_limiting(self, blueprint_content):
        assert "LoginRateLimiter" in blueprint_content
        assert "is_ip_rate_limited" in blueprint_content
        assert "SOGO_P_LOGIN_IP_MAX" in blueprint_content
        assert "SOGO_P_LOGIN_IP_WINDOW" in blueprint_content

    def test_login_uses_basic_post_schema(self, blueprint_content):
        assert "AuthUserBasicPostSchema" in blueprint_content

    def test_login_has_content_type_check(self, blueprint_content):
        # POST without body needs Content-Type header
        assert "Content-Type" in blueprint_content or "application/json" in blueprint_content


class TestApiAuthUserCallback:
    def test_callback_class_exists(self, blueprint_content):
        assert "class ApiAuthUserCallback(MethodView):" in blueprint_content

    def test_callback_has_get_method(self, blueprint_content):
        assert "def get(self, domain: str)" in blueprint_content

    def test_callback_has_post_method(self, blueprint_content):
        assert "def post(self, domain: str)" in blueprint_content

    def test_callback_accepts_both_get_and_post(self, blueprint_content):
        # Should handle both OIDC (GET) and SAML (POST) callbacks
        assert "InterfaceAuthSSO" in blueprint_content
        assert "handle_callback" in blueprint_content

    def test_callback_handles_saml_response(self, blueprint_content):
        assert "SAMLResponse" in blueprint_content

    def test_callback_handles_oidc_code(self, blueprint_content):
        assert "authorization code" in blueprint_content.lower() or "code:" in blueprint_content

    def test_callback_redirects_on_jwt_token(self, blueprint_content):
        assert "jwt_token" in blueprint_content
        assert "redirect" in blueprint_content.lower()

    def test_callback_loads_domain_settings(self, blueprint_content):
        assert "domain_settings" in blueprint_content
        assert "AuthSettingsObj" in blueprint_content


class TestApiAuthSaml2Discovery:
    def test_discovery_class_exists(self, blueprint_content):
        assert "class ApiAuthSaml2Discovery(MethodView):" in blueprint_content

    def test_discovery_has_get_method(self, blueprint_content):
        assert "def get(self)" in blueprint_content

    def test_discovery_has_post_method(self, blueprint_content):
        assert "def post(self)" in blueprint_content

    def test_discovery_returns_idp_list(self, blueprint_content):
        assert "idps" in blueprint_content
        assert "entity_id" in blueprint_content
        assert "sso_url" in blueprint_content

    def test_discovery_handles_federation_metadata(self, blueprint_content):
        assert "SAML2_FEDERATION_METADATA_URL" in blueprint_content
        assert "Saml2Metadata" in blueprint_content
        assert "get_federation_idps" in blueprint_content

    def test_discovery_loads_providers_from_db(self, blueprint_content):
        assert "ModuleSaml2Provider" in blueprint_content
        assert "list_providers" in blueprint_content

    def test_discovery_handles_external_wayf(self, blueprint_content):
        assert "SAML2_DISCOVERY_SERVICE_URL" in blueprint_content

    def test_discovery_post_builds_authnrequest(self, blueprint_content):
        assert "AuthnRequest" in blueprint_content
        assert "create_login_request" in blueprint_content

    def test_discovery_post_validates_entity_id(self, blueprint_content):
        assert "entity_id is required" in blueprint_content

    def test_discovery_handles_provider_not_found(self, blueprint_content):
        assert "SAML_PROVIDER_NOT_FOUND" in blueprint_content


class TestApiAuthUserLogout:
    def test_logout_class_exists(self, blueprint_content):
        assert "class ApiAuthUserLogout(MethodView):" in blueprint_content

    def test_logout_has_post_method(self, blueprint_content):
        assert "def post(self)" in blueprint_content

    def test_logout_revs_session(self, blueprint_content):
        assert "logout" in blueprint_content
        assert "revoke" in blueprint_content.lower() or "session" in blueprint_content

    def test_logout_uses_authorization_header(self, blueprint_content):
        assert "request.authorization" in blueprint_content
        assert "Authorization" in blueprint_content


class TestSchemas:
    def test_auth_user_get_mech_schema_exists(self, schema_content):
        assert "class AuthUserGetMechSchema(Schema):" in schema_content

    def test_auth_user_get_mech_has_username_field(self, schema_content):
        assert "username = fields.String(required=True)" in schema_content

    def test_auth_user_get_mech_has_redirect_field(self, schema_content):
        assert "redirect = fields.String" in schema_content

    def test_auth_user_basic_post_schema_exists(self, schema_content):
        assert "class AuthUserBasicPostSchema(Schema):" in schema_content

    def test_auth_user_basic_post_has_username_field(self, schema_content):
        assert "username = fields.String(required=True)" in schema_content

    def test_auth_user_basic_post_has_password_field(self, schema_content):
        assert "password = fields.String(required=True)" in schema_content

    def test_auth_user_basic_post_has_mfa_code_field(self, schema_content):
        assert "mfa_code = fields.String" in schema_content

    def test_auth_user_basic_post_has_example_method(self, schema_content):
        assert "def example(cls)" in schema_content


class TestBeforeRequest:
    def test_has_before_request_decorator(self, blueprint_content):
        assert "@blp.before_request" in blueprint_content

    def test_before_request_initializes_interface(self, blueprint_content):
        assert "init_admin_config" in blueprint_content
        assert "InterfaceAuthUser" in blueprint_content

    def test_before_request_sets_g_inter(self, blueprint_content):
        assert "g.inter = interface_api" in blueprint_content

    def test_before_request_accesses_g_settings(self, blueprint_content):
        assert "g.process_settings" in blueprint_content
        assert "g.system_settings" in blueprint_content
        assert "g.default_domain_settings" in blueprint_content
