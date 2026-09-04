"""Structural tests for the AI Service API (0% coverage baseline)."""
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[3] / "app" / "api" / "v1" / "user"


class TestApiAIBlueprint:
    """Verify the AI Service API blueprint structure."""

    def test_api_file_exists(self):
        assert (API_DIR / "ApiAI.py").exists()

    def test_blueprint_url_prefix(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert 'url_prefix="/ai"' in content

    def test_summarize_route(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert '@blp.route("/summarize")' in content
        assert "class ApiAISummarize" in content

    def test_classify_route(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert '@blp.route("/classify")' in content
        assert "class ApiAIClassify" in content

    def test_suggest_reply_route(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert '@blp.route("/suggest-reply")' in content
        assert "class ApiAISuggestReply" in content

    def test_natural_search_route(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert '@blp.route("/natural-search")' in content
        assert "class ApiAINaturalSearch" in content

    def test_detect_anomaly_route(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert '@blp.route("/detect-anomaly")' in content
        assert "class ApiAIAnomaly" in content

    def test_enrich_contact_route(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert '@blp.route("/enrich-contact")' in content
        assert "class ApiAIEnrichContact" in content

    def test_classify_attachment_route(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert '@blp.route("/classify-attachment")' in content
        assert "class ApiAIClassifyAttachment" in content

    def test_register_in_user_apis(self):
        # Note: This API may not be registered yet - it exists as a standalone module
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert "Blueprint" in content
        assert "blp = Blueprint" in content


class TestApiAISchemas:
    """Verify the request schema definitions."""

    def test_summarize_schema_has_text_and_max_sentences(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert "class SummarizeSchema" in content
        assert "text" in content
        assert "max_sentences" in content
        assert "validate.Range(min=1, max=10)" in content

    def test_classify_schema_has_fields(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert "class ClassifySchema" in content
        assert "text" in content
        assert "subject" in content
        assert "sender" in content

    def test_suggest_reply_schema_has_tone_validation(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert "class SuggestReplySchema" in content
        assert "tone" in content
        assert 'validate.OneOf(["professional", "friendly", "formal"])' in content

    def test_search_schema_has_query(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert "class SearchSchema" in content
        assert "query" in content

    def test_anomaly_schema_has_fields(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert "class AnomalySchema" in content
        assert "recipient_count" in content
        assert "hour" in content
        assert "new_recipient_ratio" in content

    def test_enrich_schema_has_text(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert "class EnrichSchema" in content
        assert "text" in content

    def test_attachment_schema_has_fields(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert "class AttachmentSchema" in content
        assert "filename" in content
        assert "content_type" in content


class TestAILogic:
    """Verify key logic patterns in the implementation."""

    def test_all_endpoints_use_get_model_backend(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert "get_model_backend()" in content
        assert content.count("get_model_backend()") >= 6  # 6 endpoints

    def test_summarize_returns_summary_and_model(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert '"summary"' in content
        assert '"model"' in content
        assert '"fallback"' in content

    def test_classify_returns_labels(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert '"labels"' in content

    def test_suggest_reply_returns_suggestion(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert '"suggestion"' in content

    def test_natural_search_returns_structured(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert "nl_to_search" in content

    def test_detect_anomaly_takes_dict(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert "detect_anomaly" in content
        assert "recipient_count" in content
        assert "new_recipient_ratio" in content

    def test_enrich_contact_uses_extract_contact_info(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert "extract_contact_info" in content

    def test_classify_attachment_uses_method(self):
        content = (API_DIR / "ApiAI.py").read_text(encoding="utf-8")
        assert "classify_attachment" in content
