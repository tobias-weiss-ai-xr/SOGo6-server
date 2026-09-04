"""Structural tests for unregistered API blueprints.

These tests verify the existence and structure of 7 API blueprints that are
NOT registered in app/api/v1/__init__.py. They document the API contracts
and guard against accidental deletion or refactoring.

Blueprints tested:
- ApiCollaborativeDrafts: Collaborative drafts API (66 stmts)
- ApiAppPassword: App password management (66 stmts)
- ApiSmartCalendar: AI meeting suggestions (67 stmts)
- ApiAI: AI service endpoints (78 stmts)
- ApiPGP: PGP encryption (86 stmts)
- ApiSpamFilter: Spam scoring (100 stmts)
- ApiTranscripts: Meeting transcripts (110 stmts)
"""
import ast
import os


# ────────────────────────────────────────────────────────────────────────────
# ApiCollaborativeDrafts
# ────────────────────────────────────────────────────────────────────────────

class TestApiCollaborativeDraftsStructure:
    """Structural tests for ApiCollaborativeDrafts blueprint."""

    @staticmethod
    def test_blueprint_exists():
        path = "app/api/v1/mail/ApiCollaborativeDrafts.py"
        with open(path) as f:
            tree = ast.parse(f.read())

        blueprints = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
        bp_names = []
        for bp in blueprints:
            for target in bp.targets:
                if isinstance(target, ast.Name) and target.id == "blp":
                    bp_names.append(target.id)

        assert "blp" in bp_names

    @staticmethod
    def test_blueprint_has_route_decorator():
        path = "app/api/v1/mail/ApiCollaborativeDrafts.py"
        with open(path) as f:
            content = f.read()

        assert "@blp.route" in content

    @staticmethod
    def test_has_method_view_classes():
        path = "app/api/v1/mail/ApiCollaborativeDrafts.py"
        with open(path) as f:
            tree = ast.parse(f.read())

        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        class_names = [c.name for c in classes]

        assert any("Draft" in name for name in class_names)

    @staticmethod
    def test_uses_cache():
        path = "app/api/v1/mail/ApiCollaborativeDrafts.py"
        with open(path) as f:
            content = f.read()

        assert "sogo_cache" in content

    @staticmethod
    def test_has_schemas():
        path = "app/api/v1/mail/ApiCollaborativeDrafts.py"
        with open(path) as f:
            content = f.read()

        assert "Schema" in content


# ────────────────────────────────────────────────────────────────────────────
# ApiAppPassword
# ────────────────────────────────────────────────────────────────────────────

class TestApiAppPasswordStructure:
    """Structural tests for ApiAppPassword blueprint."""

    @staticmethod
    def test_blueprint_exists():
        path = "app/api/v1/user/ApiAppPassword.py"
        with open(path) as f:
            tree = ast.parse(f.read())

        blueprints = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
        bp_names = []
        for bp in blueprints:
            for target in bp.targets:
                if isinstance(target, ast.Name) and target.id == "blp":
                    bp_names.append(target.id)

        assert "blp" in bp_names

    @staticmethod
    def test_blueprint_prefix():
        path = "app/api/v1/user/ApiAppPassword.py"
        with open(path) as f:
            content = f.read()

        assert 'url_prefix="/app-passwords"' in content

    @staticmethod
    def test_has_list_create_endpoint():
        path = "app/api/v1/user/ApiAppPassword.py"
        with open(path) as f:
            content = f.read()

        assert "ApiAppPasswordListCreate" in content

    @staticmethod
    def test_has_delete_endpoint():
        path = "app/api/v1/user/ApiAppPassword.py"
        with open(path) as f:
            content = f.read()

        assert "ApiAppPasswordDelete" in content

    @staticmethod
    def test_has_verify_endpoint():
        path = "app/api/v1/user/ApiAppPassword.py"
        with open(path) as f:
            content = f.read()

        assert "ApiAppPasswordVerify" in content

    @staticmethod
    def test_has_app_password_schemas():
        path = "app/api/v1/user/ApiAppPassword.py"
        with open(path) as f:
            content = f.read()

        assert "AppPasswordCreateSchema" in content
        assert "AppPasswordListResponseSchema" in content
        assert "AppPasswordItemSchema" in content


# ────────────────────────────────────────────────────────────────────────────
# ApiSmartCalendar
# ────────────────────────────────────────────────────────────────────────────

class TestApiSmartCalendarStructure:
    """Structural tests for ApiSmartCalendar blueprint."""

    @staticmethod
    def test_blueprint_exists():
        path = "app/api/v1/user/ApiSmartCalendar.py"
        with open(path) as f:
            tree = ast.parse(f.read())

        blueprints = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
        bp_names = []
        for bp in blueprints:
            for target in bp.targets:
                if isinstance(target, ast.Name) and target.id == "blp":
                    bp_names.append(target.id)

        assert "blp" in bp_names

    @staticmethod
    def test_blueprint_prefix():
        path = "app/api/v1/user/ApiSmartCalendar.py"
        with open(path) as f:
            content = f.read()

        assert 'url_prefix="/ai/smart-calendar"' in content

    @staticmethod
    def test_has_suggest_times_endpoint():
        path = "app/api/v1/user/ApiSmartCalendar.py"
        with open(path) as f:
            content = f.read()

        assert "ApiSmartCalendarSuggest" in content
        assert "/suggest-times" in content

    @staticmethod
    def test_has_analyze_pattern_endpoint():
        path = "app/api/v1/user/ApiSmartCalendar.py"
        with open(path) as f:
            content = f.read()

        assert "ApiSmartCalendarAnalyze" in content
        assert "/analyze-patterns" in content

    @staticmethod
    def test_has_schemas():
        path = "app/api/v1/user/ApiSmartCalendar.py"
        with open(path) as f:
            content = f.read()

        assert "SuggestTimesSchema" in content
        assert "AnalyzePatternSchema" in content

    @staticmethod
    def test_uses_cache():
        path = "app/api/v1/user/ApiSmartCalendar.py"
        with open(path) as f:
            content = f.read()

        assert "sogo_cache" in content


# ────────────────────────────────────────────────────────────────────────────
# ApiAI
# ────────────────────────────────────────────────────────────────────────────

class TestApiAIStructure:
    """Structural tests for ApiAI blueprint."""

    @staticmethod
    def test_blueprint_exists():
        path = "app/api/v1/user/ApiAI.py"
        with open(path) as f:
            tree = ast.parse(f.read())

        blueprints = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
        bp_names = []
        for bp in blueprints:
            for target in bp.targets:
                if isinstance(target, ast.Name) and target.id == "blp":
                    bp_names.append(target.id)

        assert "blp" in bp_names

    @staticmethod
    def test_blueprint_prefix():
        path = "app/api/v1/user/ApiAI.py"
        with open(path) as f:
            content = f.read()

        assert 'url_prefix="/ai"' in content

    @staticmethod
    def test_has_summarize_endpoint():
        path = "app/api/v1/user/ApiAI.py"
        with open(path) as f:
            content = f.read()

        assert "ApiAISummarize" in content
        assert "/summarize" in content

    @staticmethod
    def test_has_classify_endpoint():
        path = "app/api/v1/user/ApiAI.py"
        with open(path) as f:
            content = f.read()

        assert "ApiAIClassify" in content
        assert "/classify" in content

    @staticmethod
    def test_has_suggest_reply_endpoint():
        path = "app/api/v1/user/ApiAI.py"
        with open(path) as f:
            content = f.read()

        assert "ApiAISuggestReply" in content
        assert "/suggest-reply" in content

    @staticmethod
    def test_has_natural_search_endpoint():
        path = "app/api/v1/user/ApiAI.py"
        with open(path) as f:
            content = f.read()

        assert "ApiAINaturalSearch" in content
        assert "/natural-search" in content

    @staticmethod
    def test_has_anomaly_endpoint():
        path = "app/api/v1/user/ApiAI.py"
        with open(path) as f:
            content = f.read()

        assert "ApiAIAnomaly" in content
        assert "/detect-anomaly" in content

    @staticmethod
    def test_has_enrich_contact_endpoint():
        path = "app/api/v1/user/ApiAI.py"
        with open(path) as f:
            content = f.read()

        assert "ApiAIEnrichContact" in content
        assert "/enrich-contact" in content

    @staticmethod
    def test_has_classify_attachment_endpoint():
        path = "app/api/v1/user/ApiAI.py"
        with open(path) as f:
            content = f.read()

        assert "ApiAIClassifyAttachment" in content
        assert "/classify-attachment" in content

    @staticmethod
    def test_has_schemas():
        path = "app/api/v1/user/ApiAI.py"
        with open(path) as f:
            content = f.read()

        assert "SummarizeSchema" in content
        assert "ClassifySchema" in content
        assert "SuggestReplySchema" in content
        assert "SearchSchema" in content
        assert "AnomalySchema" in content
        assert "EnrichSchema" in content

    @staticmethod
    def test_uses_ai_service():
        path = "app/api/v1/user/ApiAI.py"
        with open(path) as f:
            content = f.read()

        assert "get_model_backend" in content


# ────────────────────────────────────────────────────────────────────────────
# ApiPGP
# ────────────────────────────────────────────────────────────────────────────

class TestApiPGPStructure:
    """Structural tests for ApiPGP blueprint."""

    @staticmethod
    def test_blueprint_exists():
        path = "app/api/v1/user/ApiPGP.py"
        with open(path) as f:
            tree = ast.parse(f.read())

        blueprints = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
        bp_names = []
        for bp in blueprints:
            for target in bp.targets:
                if isinstance(target, ast.Name) and target.id == "blp":
                    bp_names.append(target.id)

        assert "blp" in bp_names

    @staticmethod
    def test_blueprint_prefix():
        path = "app/api/v1/user/ApiPGP.py"
        with open(path) as f:
            content = f.read()

        assert 'url_prefix="/pgp"' in content

    @staticmethod
    def test_has_generate_key_endpoint():
        path = "app/api/v1/user/ApiPGP.py"
        with open(path) as f:
            content = f.read()

        assert "ApiPGPGenerate" in content
        assert "/key/generate" in content

    @staticmethod
    def test_has_get_key_endpoint():
        path = "app/api/v1/user/ApiPGP.py"
        with open(path) as f:
            content = f.read()

        assert "ApiPGPGetKey" in content
        assert 'route("/key")' in content or '@blp.route("/key")' in content

    @staticmethod
    def test_has_delete_key_endpoint():
        path = "app/api/v1/user/ApiPGP.py"
        with open(path) as f:
            content = f.read()

        assert "ApiPGPDeleteKey" in content

    @staticmethod
    def test_has_encrypt_endpoint():
        path = "app/api/v1/user/ApiPGP.py"
        with open(path) as f:
            content = f.read()

        assert "ApiPGPEncrypt" in content
        assert "/encrypt" in content

    @staticmethod
    def test_has_decrypt_endpoint():
        path = "app/api/v1/user/ApiPGP.py"
        with open(path) as f:
            content = f.read()

        assert "ApiPGPDecrypt" in content
        assert "/decrypt" in content

    @staticmethod
    def test_has_schemas():
        path = "app/api/v1/user/ApiPGP.py"
        with open(path) as f:
            content = f.read()

        assert "PGPKeyResponseSchema" in content
        assert "PGPKeyGenerateSchema" in content
        assert "PGPEncryptSchema" in content
        assert "PGPDecryptSchema" in content

    @staticmethod
    def test_uses_pgp_manager():
        path = "app/api/v1/user/ApiPGP.py"
        with open(path) as f:
            content = f.read()

        assert "PGPKeyManager" in content


# ────────────────────────────────────────────────────────────────────────────
# ApiSpamFilter
# ────────────────────────────────────────────────────────────────────────────

class TestApiSpamFilterStructure:
    """Structural tests for ApiSpamFilter blueprint."""

    @staticmethod
    def test_blueprint_exists():
        path = "app/api/v1/user/ApiSpamFilter.py"
        with open(path) as f:
            tree = ast.parse(f.read())

        blueprints = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
        bp_names = []
        for bp in blueprints:
            for target in bp.targets:
                if isinstance(target, ast.Name) and target.id == "blp":
                    bp_names.append(target.id)

        assert "blp" in bp_names

    @staticmethod
    def test_blueprint_prefix():
        path = "app/api/v1/user/ApiSpamFilter.py"
        with open(path) as f:
            content = f.read()

        assert 'url_prefix="/ai/spam"' in content

    @staticmethod
    def test_has_score_endpoint():
        path = "app/api/v1/user/ApiSpamFilter.py"
        with open(path) as f:
            content = f.read()

        assert "ApiSpamScore" in content
        assert "/score" in content

    @staticmethod
    def test_has_report_endpoint():
        path = "app/api/v1/user/ApiSpamFilter.py"
        with open(path) as f:
            content = f.read()

        assert "ApiSpamReport" in content
        assert "/report" in content

    @staticmethod
    def test_has_stats_endpoint():
        path = "app/api/v1/user/ApiSpamFilter.py"
        with open(path) as f:
            content = f.read()

        assert "ApiSpamStats" in content
        assert "/stats" in content

    @staticmethod
    def test_has_schemas():
        path = "app/api/v1/user/ApiSpamFilter.py"
        with open(path) as f:
            content = f.read()

        assert "SpamScoreSchema" in content
        assert "SpamReportSchema" in content

    @staticmethod
    def test_has_spam_patterns():
        path = "app/api/v1/user/ApiSpamFilter.py"
        with open(path) as f:
            content = f.read()

        assert "_SPAM_PATTERNS" in content
        assert "_BENIGN_PATTERNS" in content

    @staticmethod
    def test_has_compute_spam_score_function():
        path = "app/api/v1/user/ApiSpamFilter.py"
        with open(path) as f:
            content = f.read()

        assert "_compute_spam_score" in content


# ────────────────────────────────────────────────────────────────────────────
# ApiTranscripts
# ────────────────────────────────────────────────────────────────────────────

class TestApiTranscriptsStructure:
    """Structural tests for ApiTranscripts blueprint."""

    @staticmethod
    def test_blueprint_exists():
        path = "app/api/v1/user/ApiTranscripts.py"
        with open(path) as f:
            tree = ast.parse(f.read())

        blueprints = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
        bp_names = []
        for bp in blueprints:
            for target in bp.targets:
                if isinstance(target, ast.Name) and target.id == "blp":
                    bp_names.append(target.id)

        assert "blp" in bp_names

    @staticmethod
    def test_blueprint_prefix():
        path = "app/api/v1/user/ApiTranscripts.py"
        with open(path) as f:
            content = f.read()

        assert 'url_prefix="/ai/transcripts"' in content

    @staticmethod
    def test_has_list_create_endpoint():
        path = "app/api/v1/user/ApiTranscripts.py"
        with open(path) as f:
            content = f.read()

        assert "ApiTranscriptListCreate" in content

    @staticmethod
    def test_has_detail_endpoint():
        path = "app/api/v1/user/ApiTranscripts.py"
        with open(path) as f:
            content = f.read()

        assert "ApiTranscriptDetail" in content

    @staticmethod
    def test_has_summary_endpoint():
        path = "app/api/v1/user/ApiTranscripts.py"
        with open(path) as f:
            content = f.read()

        assert "ApiTranscriptSummary" in content
        assert "/summary" in content

    @staticmethod
    def test_has_schemas():
        path = "app/api/v1/user/ApiTranscripts.py"
        with open(path) as f:
            content = f.read()

        assert "TranscriptCreateSchema" in content
        assert "TranscriptUpdateSchema" in content

    @staticmethod
    def test_has_extract_summary_function():
        path = "app/api/v1/user/ApiTranscripts.py"
        with open(path) as f:
            content = f.read()

        assert "_extract_summary" in content

    @staticmethod
    def test_has_extract_action_items_function():
        path = "app/api/v1/user/ApiTranscripts.py"
        with open(path) as f:
            content = f.read()

        assert "_extract_action_items" in content
