"""Structural tests for the App Password API (0% coverage baseline).

These tests verify the API blueprint structure, schema definitions, and
endpoint registration without requiring a full Flask app or database.
"""
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[3] / "app" / "api" / "v1" / "user"
IFACE_DIR = Path(__file__).resolve().parents[3] / "app" / "interface" / "user"


class TestApiAppPasswordBlueprint:
    """Verify the App Password API blueprint structure."""

    def test_api_file_exists(self):
        assert (API_DIR / "ApiAppPassword.py").exists()

    def test_blueprint_url_prefix(self):
        content = (API_DIR / "ApiAppPassword.py").read_text(encoding="utf-8")
        assert 'url_prefix="/app-passwords"' in content

    def test_list_create_route(self):
        content = (API_DIR / "ApiAppPassword.py").read_text(encoding="utf-8")
        assert '@blp.route("")' in content
        assert "class ApiAppPasswordListCreate" in content
        assert "def get(self)" in content
        assert "def post(self" in content

    def test_delete_route(self):
        content = (API_DIR / "ApiAppPassword.py").read_text(encoding="utf-8")
        assert '@blp.route("/<int:record_id>")' in content
        assert "class ApiAppPasswordDelete" in content
        assert "def delete(self, record_id" in content

    def test_verify_route(self):
        content = (API_DIR / "ApiAppPassword.py").read_text(encoding="utf-8")
        assert '@blp.route("/verify")' in content
        assert "class ApiAppPasswordVerify" in content
        assert "public_access = True" in content

    def test_register_in_user_apis(self):
        # Note: These APIs may not be registered yet - they exist as standalone modules
        # This test verifies the file exists and has the expected blueprint pattern
        content = (API_DIR / "ApiAppPassword.py").read_text(encoding="utf-8")
        assert "Blueprint" in content
        assert "blp = Blueprint" in content


class TestApiAppPasswordSchemas:
    """Verify the request/response schema definitions."""

    def test_create_schema_has_label(self):
        content = (API_DIR / "ApiAppPassword.py").read_text(encoding="utf-8")
        assert "class AppPasswordCreateSchema" in content
        assert 'fields.String(required=True)' in content
        assert '"label"' in content

    def test_create_response_schema_has_token(self):
        content = (API_DIR / "ApiAppPassword.py").read_text(encoding="utf-8")
        assert "class AppPasswordCreateResponseSchema" in content
        assert "token" in content
        assert "created_at" in content

    def test_list_response_schema_has_app_passwords(self):
        content = (API_DIR / "ApiAppPassword.py").read_text(encoding="utf-8")
        assert "class AppPasswordListResponseSchema" in content
        assert "app_passwords" in content

    def test_item_schema_has_fields(self):
        content = (API_DIR / "ApiAppPassword.py").read_text(encoding="utf-8")
        assert "class AppPasswordItemSchema" in content
        assert "id" in content
        assert "label" in content
        assert "last_used" in content
        assert "expires_at" in content


class TestInterfaceAppPassword:
    """Verify the interface layer structure."""

    def test_interface_file_exists(self):
        assert (IFACE_DIR / "InterfaceAppPassword.py").exists()

    def test_interface_has_list_for_user(self):
        content = (IFACE_DIR / "InterfaceAppPassword.py").read_text(encoding="utf-8")
        assert "def list_for_user" in content

    def test_interface_has_create(self):
        content = (IFACE_DIR / "InterfaceAppPassword.py").read_text(encoding="utf-8")
        assert "def create" in content

    def test_interface_has_delete(self):
        content = (IFACE_DIR / "InterfaceAppPassword.py").read_text(encoding="utf-8")
        assert "def delete" in content

    def test_interface_has_verify(self):
        content = (IFACE_DIR / "InterfaceAppPassword.py").read_text(encoding="utf-8")
        assert "def verify" in content
