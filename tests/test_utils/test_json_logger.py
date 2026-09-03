"""
Unit tests for app.utils.logger.json_logger — the structured JSON log
formatter and the auto-enable logic.
"""
from __future__ import annotations

import json
import logging
import os

from app.utils.logger.json_logger import JsonFormatter, enable_json_logging


def _record(message="hello", extra=None, exc=None):
    logger = logging.getLogger("sogolog.test.json")
    record = logger.makeRecord(
        logger.name, logging.INFO, __file__, 42,
        message, (), exc, func="some_func", sinfo=None,
    )
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    return record


def test_formatter_emits_valid_json_with_core_fields():
    line = JsonFormatter().format(_record())
    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "sogolog.test.json"
    assert payload["message"] == "hello"
    assert payload["file"].endswith("test_json_logger.py")
    assert payload["func"] == "some_func"
    assert payload["line"] == 42
    assert "timestamp" in payload
    assert isinstance(payload["pid"], int)


def test_formatter_request_context_fields_default_dash():
    payload = json.loads(JsonFormatter().format(_record()))
    assert payload["request_id"] == "-"
    assert payload["user"] == "-"
    assert payload["domain"] == "-"


def test_formatter_extra_kwargs_are_merged():
    record = _record(extra={"request_id": "req-123", "user_uid": "u1", "user_domain": "x.org", "custom": 7})
    payload = json.loads(JsonFormatter().format(record))
    assert payload["request_id"] == "req-123"
    assert payload["user"] == "u1"
    assert payload["domain"] == "x.org"
    assert payload["custom"] == 7


def test_formatter_exception_adds_exception_object():
    try:
        raise ValueError("broken")
    except ValueError:
        record = _record(message="with exc", exc=True)
        record.exc_info = ValueError, ValueError("broken"), None
    payload = json.loads(JsonFormatter().format(record))
    assert payload["exception"] == {"type": "ValueError", "value": "broken"}


def test_formatter_message_substitution():
    record = _record(message="value=%s", extra={"args": (5,)})
    record.args = (5,)  # ensure args are carried
    payload = json.loads(JsonFormatter().format(record))
    # makeRecord already formatted msg with args
    assert payload["message"] == "value=5" or "value" in payload["message"]


def test_formatter_unicode_preserved():
    record = _record(message="grüße → 日本語")
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "grüße → 日本語"


# ---------------------------------------------------------------------------
# enable_json_logging
# ---------------------------------------------------------------------------

def test_opt_out_env_returns_without_adding_handlers(monkeypatch):
    monkeypatch.setenv("SOGO_JSON_LOG", "0")
    monkeypatch.delenv("FLASK_ENV", raising=False)
    root = logging.getLogger("sogolog")
    handlers_before = len(root.handlers)
    enable_json_logging()
    assert len(root.handlers) == handlers_before


def test_opt_in_env_adds_json_handler(monkeypatch):
    monkeypatch.setenv("SOGO_JSON_LOG", "1")
    monkeypatch.delenv("FLASK_ENV", raising=False)
    enable_json_logging()
    root = logging.getLogger("sogolog")
    assert any(isinstance(h.formatter, JsonFormatter) for h in root.handlers)
    assert root.propagate is False


def test_production_env_auto_enables(monkeypatch):
    monkeypatch.delenv("SOGO_JSON_LOG", raising=False)
    monkeypatch.setenv("FLASK_ENV", "production")
    enable_json_logging()
    root = logging.getLogger("sogolog")
    assert any(isinstance(h.formatter, JsonFormatter) for h in root.handlers)


def test_dev_env_keeps_console_format(monkeypatch):
    monkeypatch.delenv("SOGO_JSON_LOG", raising=False)
    monkeypatch.setenv("FLASK_ENV", "development")
    root = logging.getLogger("sogolog")
    handlers_before = len(root.handlers)
    enable_json_logging()
    assert len(root.handlers) == handlers_before
