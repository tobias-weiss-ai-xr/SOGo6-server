"""Unit tests for InterfacePasswordReset (API layer for password recovery).

Tests the API-facing wrapper around ModulePasswordReset: domain setting checks,
user lookup, rate limiting, token generation, email sending, and the verify/reset
endpoints. External dependencies (ModuleAdminUser, ModulePasswordReset, domain
settings) are mocked.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.interface.auth.InterfacePasswordReset import (
    InterfacePasswordReset,
    RATE_LIMIT_WINDOW,
    MAX_REQUESTS_PER_WINDOW,
)
from app.utils.exceptions import RequestException
from app.utils import errors as err


class FakeProcessSettings:
    """Fake process settings for testing."""
    SOGO_P_DB_TYPE = "PostgreSQL"
    SOGO_P_PUBLIC_BASE_URL = "http://localhost:3000"
    SOGO_P_SMTP_SERVER = "smtp.example.com"
    SOGO_P_SMTP_PORT = 587
    SOGO_P_SMTP_FROM = "noreply@example.com"

    def get_db_settings(self):
        return {"host": "localhost", "database": "test"}


class FakeModulePasswordReset:
    """Fake ModulePasswordReset for testing."""
    def __init__(self, *a, **kw):
        pass

    def create_reset_token(self, user_uid, ttl=3600):
        return "FAKE_TOKEN_" + user_uid

    def count_recent_tokens(self, user_uid, within_seconds=300):
        return 0  # no rate limit by default

    def validate_token(self, raw_token):
        if raw_token == "valid_token":
            return {"user_uid": "testuser", "id": 42}
        raise RequestException("Invalid token", err.ERROR_PWD_RESET_TOKEN_INVALID)

    def mark_token_used(self, token_id):
        pass

    def reset_password(self, user_uid, new_password):
        # Default: success; can be overridden per-test
        pass


class FakeModuleAdminUser:
    """Fake ModuleAdminUser for testing."""
    def __init__(self, *a, **kw):
        pass

    def list_users(self, query, page, per_page):
        # Default: user found
        return (1, [{"uid": query, "domain": "example.org", "mail": f"{query}@example.org", "cn": query}])


@pytest.fixture
def interface():
    with patch(
        "app.interface.auth.InterfacePasswordReset.ModulePasswordReset",
        FakeModulePasswordReset,
    ):
        iface = InterfacePasswordReset(FakeProcessSettings())
        yield iface


class TestRequestReset:
    def test_user_not_found_returns_requested_true(self, interface, monkeypatch):
        # Patch ModuleAdminUser to return no users
        mock_admin = MagicMock()
        mock_admin.list_users.return_value = (0, [])
        monkeypatch.setattr(
            "app.module.admin.ModuleAdminUser.ModuleAdminUser",
            lambda **kw: mock_admin,
        )
        result, status = interface.request_reset("unknown")
        assert result["data"]["requested"] is True
        assert status == 200

    def test_user_found_creates_token(self, interface, monkeypatch):
        mock_admin = MagicMock()
        mock_admin.list_users.return_value = (1, [
            {"uid": "alice", "domain": "example.org", "mail": "alice@example.org", "cn": "Alice"}
        ])
        monkeypatch.setattr(
            "app.module.admin.ModuleAdminUser.ModuleAdminUser",
            lambda **kw: mock_admin,
        )
        # Patch domain settings to enable password recovery
        monkeypatch.setattr(
            "app.config.init_config.init_get_user_domain_settings",
            lambda user: {"AUTH_SETTINGS": {"SOGO_D_PWD_RECOVERY": True}},
        )
        result, status = interface.request_reset("alice")
        assert result["data"]["requested"] is True
        assert status == 200

    def test_domain_recovery_disabled_returns_requested_true(self, interface, monkeypatch):
        mock_admin = MagicMock()
        mock_admin.list_users.return_value = (1, [
            {"uid": "alice", "domain": "example.org", "mail": "alice@example.org", "cn": "Alice"}
        ])
        monkeypatch.setattr(
            "app.module.admin.ModuleAdminUser.ModuleAdminUser",
            lambda **kw: mock_admin,
        )
        monkeypatch.setattr(
            "app.config.init_config.init_get_user_domain_settings",
            lambda user: {"AUTH_SETTINGS": {"SOGO_D_PWD_RECOVERY": False}},
        )
        result, status = interface.request_reset("alice")
        assert result["data"]["requested"] is True
        assert status == 200

    def test_rate_limited_returns_requested_true(self, interface, monkeypatch):
        mock_admin = MagicMock()
        mock_admin.list_users.return_value = (1, [
            {"uid": "alice", "domain": "example.org", "mail": "alice@example.org", "cn": "Alice"}
        ])
        monkeypatch.setattr(
            "app.module.admin.ModuleAdminUser.ModuleAdminUser",
            lambda **kw: mock_admin,
        )
        monkeypatch.setattr(
            "app.config.init_config.init_get_user_domain_settings",
            lambda user: {"AUTH_SETTINGS": {"SOGO_D_PWD_RECOVERY": True}},
        )
        # Simulate rate limit exceeded
        interface.module.count_recent_tokens = lambda uid, within_seconds: MAX_REQUESTS_PER_WINDOW
        result, status = interface.request_reset("alice")
        assert result["data"]["requested"] is True
        assert status == 200

    def test_builds_reset_link_with_base_url(self, interface, monkeypatch):
        mock_admin = MagicMock()
        mock_admin.list_users.return_value = (1, [
            {"uid": "alice", "domain": "example.org", "mail": "alice@example.org", "cn": "Alice"}
        ])
        monkeypatch.setattr(
            "app.module.admin.ModuleAdminUser.ModuleAdminUser",
            lambda **kw: mock_admin,
        )
        monkeypatch.setattr(
            "app.config.init_config.init_get_user_domain_settings",
            lambda user: {"AUTH_SETTINGS": {"SOGO_D_PWD_RECOVERY": True}},
        )
        # Patch send_reset_email to capture the link
        captured_link = []
        def capture_email(recipient_email, recipient_name, reset_link, **kw):
            captured_link.append(reset_link)
        interface.module.send_reset_email = capture_email
        interface.request_reset("alice")
        assert len(captured_link) == 1
        assert "FAKE_TOKEN_alice" in captured_link[0]
        assert "http://localhost:3000" in captured_link[0]


class TestVerifyToken:
    def test_valid_token_returns_user_uid(self, interface):
        result, status = interface.verify_token("valid_token")
        assert result["data"]["user_uid"] == "testuser"
        assert result["data"]["valid"] is True
        assert status == 200

    def test_invalid_token_returns_error(self, interface):
        result, status = interface.verify_token("invalid_token")
        assert result["data"] is None
        assert result["error_code"] == err.ERROR_PWD_RESET_TOKEN_INVALID.c
        assert status == err.ERROR_PWD_RESET_TOKEN_INVALID.h


class TestResetPassword:
    def test_valid_token_updates_password(self, interface, monkeypatch):
        # Patch ModuleAdminUser to succeed
        mock_admin = MagicMock()
        monkeypatch.setattr(
            "app.module.admin.ModuleAdminUser.ModuleAdminUser",
            lambda **kw: mock_admin,
        )
        result, status = interface.reset_password("valid_token", "newpass123")
        assert result["data"]["reset"] is True
        assert status == 200

    def test_short_password_returns_validation_error(self, interface):
        result, status = interface.reset_password("valid_token", "123")
        assert result["data"] is None
        assert result["error_code"] == err.ERROR_VALIDATION_ERROR.c

    def test_invalid_token_returns_error(self, interface):
        result, status = interface.reset_password("invalid_token", "newpass123")
        assert result["data"] is None
        assert result["error_code"] == err.ERROR_PWD_RESET_TOKEN_INVALID.c

    def test_reset_failure_returns_error(self, interface):
        # Make the fake module raise an error
        interface.module.reset_password = lambda uid, pw: (_ for _ in ()).throw(
            RequestException("LDAP failed", err.ERROR_PWD_RESET_UPDATE_FAILED)
        )
        result, status = interface.reset_password("valid_token", "newpass123")
        assert result["data"] is None
        assert result["error_code"] == err.ERROR_PWD_RESET_UPDATE_FAILED.c

    def test_marks_token_used_after_success(self, interface, monkeypatch):
        mock_admin = MagicMock()
        monkeypatch.setattr(
            "app.module.admin.ModuleAdminUser.ModuleAdminUser",
            lambda **kw: mock_admin,
        )
        mark_used_called = []
        original_mark = interface.module.mark_token_used
        def capture_mark(token_id):
            mark_used_called.append(token_id)
            return original_mark(token_id)
        interface.module.mark_token_used = capture_mark
        interface.reset_password("valid_token", "newpass123")
        assert len(mark_used_called) == 1
        assert mark_used_called[0] == 42  # token id from fake module
