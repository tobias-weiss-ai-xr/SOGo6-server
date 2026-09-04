"""Unit tests for ModuleAdminConfig security warnings (_warn_insecure_domain_settings).

Tests the security warning function that checks domain settings for common
misconfigurations and logs warnings to help administrators identify issues.

Note: Full integration tests for the ModuleAdminConfig class require a database
connection. This test file focuses on the pure function _warn_insecure_domain_settings
which can be tested in isolation.
"""
import pytest
import logging

from app.module.admin.ModuleAdminConfig import _warn_insecure_domain_settings


@pytest.fixture
def caplog_handler():
    """Capture log messages."""
    handler = logging.Handler()
    handler.messages = []
    handler.emit = lambda record: handler.messages.append(record.getMessage())
    logger = logging.getLogger("sogolog")
    logger.addHandler(handler)
    yield handler
    logger.removeHandler(handler)


class TestWarnInsecureDomainSettings:
    def test_plain_auth_without_rate_limiting_warns(self, caplog_handler):
        settings = {
            "SOGO_D_AUTH_TYPE": "plain",
            "SOGO_D_LOGIN_CHECK_MAX_ATTEMPT": 0,
        }
        _warn_insecure_domain_settings(settings)
        messages = " ".join(caplog_handler.messages)
        assert "SECURITY WARNING" in messages
        assert "plain" in messages
        assert "rate limiting" in messages

    def test_plain_auth_with_rate_limiting_no_warning(self, caplog_handler):
        settings = {
            "SOGO_D_AUTH_TYPE": "plain",
            "SOGO_D_LOGIN_CHECK_MAX_ATTEMPT": 5,
        }
        _warn_insecure_domain_settings(settings)
        messages = " ".join(caplog_handler.messages)
        # No warning about plain auth with rate limiting
        assert "plain" not in messages or "rate limiting" not in messages

    def test_password_change_disabled_warns(self, caplog_handler):
        settings = {"SOGO_D_PWD_CHANGE_ENABLED": False}
        _warn_insecure_domain_settings(settings)
        messages = " ".join(caplog_handler.messages)
        assert "SECURITY WARNING" in messages
        assert "Password change is disabled" in messages

    def test_mfa_not_enforced_false_warns(self, caplog_handler):
        settings = {"SOGO_D_LOGIN_MFA_FORCE": False}
        _warn_insecure_domain_settings(settings)
        messages = " ".join(caplog_handler.messages)
        assert "SECURITY WARNING" in messages
        assert "MFA" in messages

    def test_mfa_not_enforced_none_warns(self, caplog_handler):
        settings = {"SOGO_D_LOGIN_MFA_FORCE": None}
        _warn_insecure_domain_settings(settings)
        messages = " ".join(caplog_handler.messages)
        assert "SECURITY WARNING" in messages
        assert "MFA" in messages

    def test_mfa_enforced_no_warning(self, caplog_handler):
        settings = {"SOGO_D_LOGIN_MFA_FORCE": True}
        _warn_insecure_domain_settings(settings)
        messages = " ".join(caplog_handler.messages)
        assert "MFA" not in messages

    def test_weak_rate_limiting_warns(self, caplog_handler):
        settings = {
            "SOGO_D_LOGIN_IP_MAX_ATTEMPT": 5,
            "SOGO_D_LOGIN_IP_TIME_SPAN": 60,
        }
        _warn_insecure_domain_settings(settings)
        messages = " ".join(caplog_handler.messages)
        assert "SECURITY WARNING" in messages
        assert "rate limiting" in messages
        assert "5 attempts per 60 seconds" in messages

    def test_strong_rate_limiting_no_warning(self, caplog_handler):
        settings = {
            "SOGO_D_LOGIN_IP_MAX_ATTEMPT": 20,
            "SOGO_D_LOGIN_IP_TIME_SPAN": 300,
        }
        _warn_insecure_domain_settings(settings)
        messages = " ".join(caplog_handler.messages)
        # No warning about rate limiting
        assert "rate limiting may be too lenient" not in messages

    def test_openid_without_secret_errors(self, caplog_handler):
        settings = {
            "SOGO_D_AUTH_TYPE": "openid",
            "SOGO_D_OPENID_CLIENT_SECRET": "",
        }
        _warn_insecure_domain_settings(settings)
        messages = " ".join(caplog_handler.messages)
        assert "SECURITY ERROR" in messages
        assert "OpenID" in messages
        assert "CLIENT_SECRET" in messages

    def test_openid_with_secret_no_error(self, caplog_handler):
        settings = {
            "SOGO_D_AUTH_TYPE": "openid",
            "SOGO_D_OPENID_CLIENT_SECRET": "secret123",
        }
        _warn_insecure_domain_settings(settings)
        messages = " ".join(caplog_handler.messages)
        assert "SECURITY ERROR" not in messages

    def test_secure_settings_no_warnings(self, caplog_handler):
        settings = {
            "SOGO_D_AUTH_TYPE": "plain",
            "SOGO_D_LOGIN_CHECK_MAX_ATTEMPT": 5,
            "SOGO_D_PWD_CHANGE_ENABLED": True,
            "SOGO_D_LOGIN_MFA_FORCE": True,
            "SOGO_D_LOGIN_IP_MAX_ATTEMPT": 20,
            "SOGO_D_LOGIN_IP_TIME_SPAN": 300,
        }
        _warn_insecure_domain_settings(settings)
        messages = " ".join(caplog_handler.messages)
        assert "SECURITY WARNING" not in messages
        assert "SECURITY ERROR" not in messages

    def test_empty_settings_mfa_warning_still_logs(self, caplog_handler):
        settings = {}
        _warn_insecure_domain_settings(settings)
        messages = " ".join(caplog_handler.messages)
        assert "SECURITY WARNING" in messages  # MFA warning always logged for None
        assert "SECURITY ERROR" not in messages

    def test_multiple_warnings_logged(self, caplog_handler):
        settings = {
            "SOGO_D_AUTH_TYPE": "plain",
            "SOGO_D_LOGIN_CHECK_MAX_ATTEMPT": 0,
            "SOGO_D_PWD_CHANGE_ENABLED": False,
            "SOGO_D_LOGIN_MFA_FORCE": False,
        }
        _warn_insecure_domain_settings(settings)
        messages = " ".join(caplog_handler.messages)
        # Should have multiple warnings
        assert messages.count("SECURITY WARNING") >= 3
