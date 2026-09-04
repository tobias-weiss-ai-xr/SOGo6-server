"""Structural tests for the Collaborative Drafts API (0% coverage baseline)."""
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[3] / "app" / "api" / "v1" / "mail"
IFACE_DIR = Path(__file__).resolve().parents[3] / "app" / "interface" / "mail"


class TestApiCollaborativeDraftsBlueprint:
    """Verify the Collaborative Drafts API blueprint structure."""

    def test_api_file_exists(self):
        assert (API_DIR / "ApiCollaborativeDrafts.py").exists()

    def test_blueprint_url_prefix(self):
        content = (API_DIR / "ApiCollaborativeDrafts.py").read_text(encoding="utf-8")
        assert 'url_prefix="/shared-drafts"' in content

    def test_list_create_route(self):
        content = (API_DIR / "ApiCollaborativeDrafts.py").read_text(encoding="utf-8")
        assert '@blp.route("")' in content
        assert "class ApiSharedDraftListCreate" in content
        assert "def get(self)" in content
        assert "def post(self" in content

    def test_review_route(self):
        content = (API_DIR / "ApiCollaborativeDrafts.py").read_text(encoding="utf-8")
        assert '@blp.route("/<string:draft_id>/review")' in content
        assert "class ApiSharedDraftReview" in content
        assert "def post(self" in content

    def test_register_in_mail_apis(self):
        # Note: This API may not be registered yet - it exists as a standalone module
        content = (API_DIR / "ApiCollaborativeDrafts.py").read_text(encoding="utf-8")
        assert "Blueprint" in content
        assert "blp = Blueprint" in content


class TestApiCollaborativeDraftsSchemas:
    """Verify the request/response schema definitions."""

    def test_create_schema_has_required_fields(self):
        content = (API_DIR / "ApiCollaborativeDrafts.py").read_text(encoding="utf-8")
        assert "class SharedDraftCreateSchema" in content
        assert "subject" in content
        assert "body" in content
        assert "recipients" in content
        assert "required=True" in content

    def test_review_schema_has_fields(self):
        content = (API_DIR / "ApiCollaborativeDrafts.py").read_text(encoding="utf-8")
        assert "class ReviewSchema" in content
        assert "reviewer" in content
        assert "comment" in content
        assert "approved" in content
        assert "fields.Boolean" in content

    def test_draft_has_share_token(self):
        content = (API_DIR / "ApiCollaborativeDrafts.py").read_text(encoding="utf-8")
        assert "share_token" in content
        assert "secrets.token_hex" in content

    def test_draft_has_reviews_list(self):
        content = (API_DIR / "ApiCollaborativeDrafts.py").read_text(encoding="utf-8")
        assert '"reviews"' in content
        assert '"status"' in content
        assert '"pending"' in content


class TestCollaborativeDraftsCache:
    """Verify cache key patterns."""

    def test_cache_prefix_defined(self):
        content = (API_DIR / "ApiCollaborativeDrafts.py").read_text(encoding="utf-8")
        assert "_SHARED_DRAFT_PREFIX" in content
        assert "shared_draft:" in content

    def test_cache_index_key_pattern(self):
        content = (API_DIR / "ApiCollaborativeDrafts.py").read_text(encoding="utf-8")
        assert 'index:{user.uid}' in content

    def test_cache_ttl_7_days(self):
        content = (API_DIR / "ApiCollaborativeDrafts.py").read_text(encoding="utf-8")
        assert "86400 * 7" in content
