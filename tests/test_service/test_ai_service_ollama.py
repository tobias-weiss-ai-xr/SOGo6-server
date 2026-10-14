"""Tests for the Ollama LLM backend in AIService.

Covers OllamaBackend behaviour with a mocked HTTP layer: URL handling,
load() reachability probe, LLM method overrides, and graceful fallback
to the rule-based parent when the Ollama server is unreachable.
"""
from unittest import mock

import pytest

from app.service.ai.AIService import (
    AIModelBackend,
    OllamaBackend,
    _get_ollama_config,
    get_model_backend,
)


@pytest.fixture
def ollama():
    return OllamaBackend("http://localhost:11434/", "qwen2.5:1.5b")


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the cached module-level backend between tests."""
    import app.service.ai.AIService as svc
    original = svc._model_backend
    svc._model_backend = None
    yield
    svc._model_backend = original


class TestOllamaConfig:
    def test_get_ollama_config_uses_env(self, monkeypatch):
        monkeypatch.setenv("SOGO_AI_OLLAMA_URL", "http://localhost:11434/")
        monkeypatch.setenv("SOGO_AI_OLLAMA_MODEL", "llama3.2:1b")
        url, model = _get_ollama_config()
        # trailing slash stripped
        assert url == "http://localhost:11434"
        assert model == "llama3.2:1b"

    def test_get_ollama_config_defaults(self, monkeypatch):
        monkeypatch.delenv("SOGO_AI_OLLAMA_URL", raising=False)
        monkeypatch.delenv("SOGO_AI_OLLAMA_MODEL", raising=False)
        url, model = _get_ollama_config()
        assert url is None
        assert model == "qwen2.5:1.5b"


class TestLoad:
    @mock.patch("app.service.ai.AIService.requests.get")
    def test_load_success(self, mock_get, ollama):
        mock_get.return_value.status_code = 200
        assert ollama.load() is True
        assert ollama.is_loaded() is True
        mock_get.assert_called_once_with("http://localhost:11434/api/tags", timeout=5)

    @mock.patch("app.service.ai.AIService.requests.get")
    def test_load_unreachable(self, mock_get, ollama):
        mock_get.side_effect = Exception("connection refused")
        assert ollama.load() is False
        assert ollama.is_loaded() is False

    @mock.patch("app.service.ai.AIService.requests.get")
    def test_load_non_200(self, mock_get, ollama):
        mock_get.return_value.status_code = 500
        assert ollama.load() is False


class TestChat:
    @mock.patch("app.service.ai.AIService.requests.post")
    def test_chat_returns_content(self, mock_post, ollama):
        mock_post.return_value.json.return_value = {
            "message": {"content": "  Hello there  "}
        }
        assert ollama._chat("sys", "user") == "Hello there"
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["model"] == "qwen2.5:1.5b"
        assert kwargs["json"]["stream"] is False
        assert kwargs["json"]["messages"][0] == {"role": "system", "content": "sys"}
        assert kwargs["json"]["messages"][1] == {"role": "user", "content": "user"}

    @mock.patch("app.service.ai.AIService.requests.post")
    def test_chat_error_returns_empty(self, mock_post, ollama):
        mock_post.side_effect = Exception("timeout")
        assert ollama._chat("sys", "user") == ""


class TestSummarize:
    @mock.patch("app.service.ai.AIService.requests.post")
    def test_summarize_uses_llm(self, mock_post, ollama):
        mock_post.return_value.json.return_value = {
            "message": {"content": "Short summary."}
        }
        assert ollama.summarize("A long email body.", 3) == "Short summary."

    @mock.patch("app.service.ai.AIService.requests.post")
    def test_summarize_falls_back_to_rules(self, mock_post, ollama):
        mock_post.return_value.json.return_value = {"message": {"content": ""}}
        result = ollama.summarize("First sentence. Second sentence. Third sentence.")
        # fallback returns extractive tail
        assert isinstance(result, str)
        assert len(result) > 0


class TestClassify:
    @mock.patch("app.service.ai.AIService.requests.post")
    def test_classify_parses_json(self, mock_post, ollama):
        mock_post.return_value.json.return_value = {
            "message": {
                "content": '[{"label": "newsletter", "confidence": 0.9}]'
            }
        }
        assert ollama.classify("unsubscribe now") == [
            {"label": "newsletter", "confidence": 0.9}
        ]

    @mock.patch("app.service.ai.AIService.requests.post")
    def test_classify_invalid_json_falls_back(self, mock_post, ollama):
        mock_post.return_value.json.return_value = {
            "message": {"content": "not json at all"}
        }
        result = ollama.classify("unsubscribe")
        assert isinstance(result, list)
        assert result  # rule-based fallback produces at least one label


class TestSuggestReply:
    @mock.patch("app.service.ai.AIService.requests.post")
    def test_suggest_reply_uses_llm(self, mock_post, ollama):
        mock_post.return_value.json.return_value = {
            "message": {"content": "Happy to help!"}
        }
        assert ollama.suggest_reply("Can you help?", "friendly") == "Happy to help!"

    @mock.patch("app.service.ai.AIService.requests.post")
    def test_suggest_reply_falls_back(self, mock_post, ollama):
        mock_post.return_value.json.return_value = {"message": {"content": ""}}
        result = ollama.suggest_reply("Can you help?")
        assert isinstance(result, str)
        assert result


class TestExtractContactInfo:
    @mock.patch("app.service.ai.AIService.requests.post")
    def test_extract_contact_info_parses_json(self, mock_post, ollama):
        mock_post.return_value.json.return_value = {
            "message": {
                "content": (
                    '{"phone": "+49 111", "title": "Dr.", '
                    '"company": "HRZ", "location": null}'
                )
            }
        }
        assert ollama.extract_contact_info("Dr. X, HRZ") == {
            "phone": "+49 111",
            "title": "Dr.",
            "company": "HRZ",
            "location": None,
        }


class TestModelSelection:
    def test_get_model_backend_uses_ollama_when_configured(self, monkeypatch):
        monkeypatch.setenv("SOGO_AI_OLLAMA_URL", "http://localhost:11434")
        with mock.patch(
            "app.service.ai.AIService.OllamaBackend.load", return_value=True
        ), mock.patch(
            "app.service.ai.AIService._get_ollama_config",
            return_value=("http://localhost:11434", "qwen2.5:1.5b"),
        ):
            backend = get_model_backend()
            assert isinstance(backend, OllamaBackend)

    def test_get_model_backend_falls_back_when_unreachable(self, monkeypatch):
        monkeypatch.setenv("SOGO_AI_OLLAMA_URL", "http://localhost:11434")
        with mock.patch(
            "app.service.ai.AIService.OllamaBackend.load", return_value=False
        ), mock.patch(
            "app.service.ai.AIService._get_ollama_config",
            return_value=("http://localhost:11434", "qwen2.5:1.5b"),
        ):
            backend = get_model_backend()
            assert isinstance(backend, AIModelBackend)
            assert not isinstance(backend, OllamaBackend)

    def test_get_model_backend_fallback_when_no_url(self, monkeypatch):
        monkeypatch.delenv("SOGO_AI_OLLAMA_URL", raising=False)
        with mock.patch(
            "app.service.ai.AIService._get_ollama_config",
            return_value=(None, "qwen2.5:1.5b"),
        ):
            backend = get_model_backend()
            assert isinstance(backend, AIModelBackend)
            assert not isinstance(backend, OllamaBackend)
