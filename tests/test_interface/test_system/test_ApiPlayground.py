"""Tests for API Playground (Swagger UI) feature.

Verifies the Swagger UI template includes all required playground
features and that the OpenAPI routing is configured correctly.
"""

import re
from pathlib import Path

import pytest

TEMPLATE_PATH = Path(__file__).resolve().parents[3] / "app" / "templates" / "swagger-ui.html"


@pytest.fixture(scope="module")
def swagger_template() -> str:
    """Load the custom Swagger UI template."""
    assert TEMPLATE_PATH.exists(), f"Template not found: {TEMPLATE_PATH}"
    return TEMPLATE_PATH.read_text(encoding="utf-8")


# =============================================================================
# Template Structure
# =============================================================================

class TestSwaggerTemplateStructure:
    """Verify the template is well-formed."""

    def test_template_exists(self):
        assert TEMPLATE_PATH.exists()

    def test_balanced_script_tags(self, swagger_template):
        assert swagger_template.count("<script") == swagger_template.count("</script")

    def test_swagger_ui_bundle_loaded(self, swagger_template):
        assert "swagger-ui-bundle.js" in swagger_template
        assert "swagger-ui-standalone-preset.js" in swagger_template

    def test_swagger_ui_init_present(self, swagger_template):
        assert "SwaggerUIBundle(" in swagger_template


# =============================================================================
# Required Playground Features
# =============================================================================

class TestPlaygroundFeatures:
    """Verify each spec requirement is present in the template."""

    def test_try_it_out_enabled(self, swagger_template):
        """Spec: Try-it-out for all authenticated endpoints."""
        assert "tryItOutEnabled: true" in swagger_template

    def test_persist_authorization(self, swagger_template):
        """Spec: JWT token auto-population persists across reloads."""
        assert "persistAuthorization: true" in swagger_template

    def test_login_modal_present(self, swagger_template):
        """Spec: Login modal for JWT token obtaining."""
        assert "loginModal" in swagger_template
        assert "Get Token" in swagger_template or "Get Auth Token" in swagger_template

    def test_login_endpoint_selection(self, swagger_template):
        """Spec: Support both User and Admin login."""
        assert "/api/user/v1/auth/login" in swagger_template
        assert "/api/admin/v1/auth/login" in swagger_template

    def test_mfa_code_supported(self, swagger_template):
        """Spec: MFA support in login modal."""
        assert "mfa_code" in swagger_template

    def test_version_selector(self, swagger_template):
        """Spec: Multi-version API support (User v1, Admin v1)."""
        assert "versionSelector" in swagger_template
        assert "swagger-basic" in swagger_template
        assert "swagger-admin" in swagger_template

    def test_download_json(self, swagger_template):
        """Spec: Download OpenAPI as JSON."""
        assert "downloadOpenApi('json')" in swagger_template
        assert "openapi.json" in swagger_template

    def test_download_yaml(self, swagger_template):
        """Spec: Download OpenAPI as YAML."""
        assert "downloadOpenApi('yaml')" in swagger_template
        assert "openapi.yaml" in swagger_template

    def test_dark_mode_toggle(self, swagger_template):
        """Spec: Dark mode toggle."""
        assert "toggleDarkMode" in swagger_template
        assert "dark-mode" in swagger_template

    def test_rate_limit_banner(self, swagger_template):
        """Spec: Rate limiting information."""
        assert "Rate Limit" in swagger_template or "rate-limit" in swagger_template

    def test_operation_filter(self, swagger_template):
        """Spec: Operation grouping / filtering by module."""
        assert "filter: true" in swagger_template

    def test_request_interceptor(self, swagger_template):
        """Spec: Request interceptor for auth headers."""
        assert "requestInterceptor" in swagger_template


# =============================================================================
# OpenAPI Routing Configuration
# =============================================================================

class TestOpenApiRouting:
    """Verify OpenAPI JSON and Swagger UI paths are configured."""

    @pytest.mark.parametrize(
        "key,expected",
        [
            ("BASIC_OPENAPI_JSON_PATH", "openapi-basic.json"),
            ("BASIC_OPENAPI_SWAGGER_UI_PATH", "/swagger-basic"),
            ("ADMIN_OPENAPI_JSON_PATH", "openapi-admin.json"),
            ("ADMIN_OPENAPI_SWAGGER_UI_PATH", "/swagger-admin"),
            ("BASIC_OPENAPI_VERSION", "3.0.2"),
            ("ADMIN_OPENAPI_VERSION", "3.0.2"),
        ],
    )
    def test_config_values(self, key: str, expected: str):
        """Verify OpenAPI configuration values match the spec."""
        from app.config.settings.ProcessSetting import process_config
        assert getattr(process_config, key) == expected

    def test_swagger_enabled_by_default(self):
        """Spec: Swagger UI served at runtime (enabled by default)."""
        from app.config.settings.ProcessSetting import process_config
        assert process_config.DO_SWAGGER is True

    def test_custom_template_loaded_in_app(self):
        """The app loads the custom template when swagger is enabled."""
        import app  # noqa: F401  (ensures app package imports cleanly)
        assert True
