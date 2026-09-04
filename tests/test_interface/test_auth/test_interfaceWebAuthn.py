"""Unit tests for InterfaceWebAuthn (WebAuthn/FIDO2 operations).

Tests the WebAuthn interface layer that wraps ModuleWebAuthn for:
- Registration (begin, complete)
- Authentication (begin, complete)
- Credential management (get, delete, check enabled)
"""
from unittest.mock import MagicMock, patch
import time

import pytest

from app.interface.auth.InterfaceWebAuthn import InterfaceWebAuthn
from app.utils import errors as err
from app.utils.exceptions import RequestException


class FakeUser:
    """Fake User object for testing."""
    def __init__(self, uid="test@example.org", cn="Test User"):
        self.uid = uid
        self.cn = cn


class FakeProcessSettings:
    """Fake process settings for testing."""
    SOGO_P_DB_TYPE = "PostgreSQL"
    
    def get_db_settings(self):
        return {"host": "localhost", "database": "test"}


@pytest.fixture
def interface():
    with patch(
        "app.interface.auth.InterfaceWebAuthn.ModuleWebAuthn",
        return_value=MagicMock(),
    ):
        iface = InterfaceWebAuthn(FakeProcessSettings())
        yield iface


class TestRegistrationBegin:
    def test_generates_registration_options(self, interface):
        interface._module.generate_registration_options.return_value = {
            "challenge": "abc123",
            "rp": {"id": "example.com", "name": "Test"},
        }
        result = interface.registration_begin(
            FakeUser(),
            rp_id="example.com",
            rp_name="Test App",
        )
        assert "publicKey" in result
        assert result["publicKey"]["challenge"] == "abc123"

    def test_stores_challenge(self, interface):
        interface._module.generate_registration_options.return_value = {
            "challenge": "abc123",
        }
        interface.registration_begin(FakeUser(), rp_id="example.com")
        assert interface._challenges["test@example.org"]["type"] == "registration"
        assert interface._challenges["test@example.org"]["challenge"] == "abc123"

    def test_uses_default_rp_name(self, interface):
        interface._module.generate_registration_options.return_value = {
            "challenge": "abc123",
        }
        interface.registration_begin(FakeUser(), rp_id="example.com")
        interface._module.generate_registration_options.assert_called()
        call_kwargs = interface._module.generate_registration_options.call_args[1]
        assert call_kwargs["rp_name"] == "SOGo 6"

    def test_uses_default_origin(self, interface):
        interface._module.generate_registration_options.return_value = {
            "challenge": "abc123",
        }
        interface.registration_begin(FakeUser(), rp_id="example.com")
        assert interface._challenges["test@example.org"]["origin"] == "https://example.com"


class TestRegistrationComplete:
    def test_completes_registration(self, interface):
        interface._challenges["test@example.org"] = {
            "type": "registration",
            "challenge": "abc123",
            "origin": "https://example.com",
            "rp_id": "example.com",
            "created_at": time.time(),
        }
        interface._module.register_credential.return_value = MagicMock(
            to_dict=MagicMock(return_value={"id": "cred123", "other": "data"})
        )
        result = interface.registration_complete(
            FakeUser(),
            {"response": "credential_data"},
            device_name="YubiKey",
        )
        assert result["credential_id"] == "cred123"
        assert result["device_name"] == "YubiKey"

    def test_no_challenge_raises(self, interface):
        with pytest.raises(RequestException) as exc_info:
            interface.registration_complete(FakeUser(), {}, "Device")
        assert exc_info.value.http_status == err.ERROR_WEBAUTHN_CHALLENGE_EXPIRED.h

    def test_expired_challenge_raises(self, interface):
        interface._challenges["test@example.org"] = {
            "type": "registration",
            "challenge": "abc123",
            "created_at": time.time() - 200,  # Expired (TTL=120)
        }
        with pytest.raises(RequestException) as exc_info:
            interface.registration_complete(FakeUser(), {}, "Device")
        assert exc_info.value.http_status == err.ERROR_WEBAUTHN_CHALLENGE_EXPIRED.h

    def test_wrong_challenge_type_raises(self, interface):
        interface._challenges["test@example.org"] = {
            "type": "authentication",  # Wrong type
            "challenge": "abc123",
            "created_at": time.time(),
        }
        with pytest.raises(RequestException) as exc_info:
            interface.registration_complete(FakeUser(), {}, "Device")
        assert exc_info.value.http_status == err.ERROR_WEBAUTHN_CHALLENGE_EXPIRED.h

    def test_verification_failure_raises(self, interface):
        interface._challenges["test@example.org"] = {
            "type": "registration",
            "challenge": "abc123",
            "created_at": time.time(),
        }
        interface._module.register_credential.side_effect = Exception("Verification failed")
        with pytest.raises(RequestException) as exc_info:
            interface.registration_complete(FakeUser(), {"response": "data"}, "Device")
        assert exc_info.value.http_status == err.ERROR_WEBAUTHN_REGISTRATION_FAILED.h


class TestAuthenticationBegin:
    def test_generates_authentication_options(self, interface):
        interface._module.generate_authentication_options.return_value = {
            "challenge": "xyz789",
            "rpId": "example.com",
        }
        result = interface.authentication_begin(rp_id="example.com", user_uid="test@example.org")
        assert "publicKey" in result
        assert result["publicKey"]["challenge"] == "xyz789"

    def test_stores_authentication_challenge(self, interface):
        interface._module.generate_authentication_options.return_value = {
            "challenge": "xyz789",
        }
        interface.authentication_begin(rp_id="example.com", user_uid="test@example.org")
        assert interface._challenges["test@example.org"]["type"] == "authentication"

    def test_anonymous_user_uses_special_key(self, interface):
        interface._module.generate_authentication_options.return_value = {
            "challenge": "xyz789",
        }
        interface.authentication_begin(rp_id="example.com")
        assert "__anonymous__" in interface._challenges


class TestAuthenticationComplete:
    def test_completes_authentication(self, interface):
        interface._challenges["test@example.org"] = {
            "type": "authentication",
            "challenge": "xyz789",
            "origin": "https://example.com",
            "rp_id": "example.com",
            "created_at": time.time(),
        }
        with patch("app.interface.auth.InterfaceWebAuthn.ModuleWebAuthn") as mock_module:
            mock_challenge = MagicMock()
            mock_challenge.id = "challenge123"
            mock_module.create_challenge.return_value = mock_challenge
            mock_module.authenticate.return_value = (
                MagicMock(id="cred456"),
                "test@example.org",
            )
            result = interface.authentication_complete({"response": "auth_data"})
            assert result["user_uid"] == "test@example.org"
            assert result["credential_id"] == "cred456"

    def test_no_challenge_raises(self, interface):
        with pytest.raises(RequestException) as exc_info:
            interface.authentication_complete({"response": "data"})
        assert exc_info.value.http_status == err.ERROR_WEBAUTHN_CHALLENGE_EXPIRED.h

    def test_expired_challenge_raises(self, interface):
        interface._challenges["__anonymous__"] = {
            "type": "authentication",
            "challenge": "xyz789",
            "created_at": time.time() - 200,  # Expired
        }
        with pytest.raises(RequestException) as exc_info:
            interface.authentication_complete({"response": "data"})
        assert exc_info.value.http_status == err.ERROR_WEBAUTHN_CHALLENGE_EXPIRED.h

    def test_verification_failure_raises(self, interface):
        interface._challenges["test@example.org"] = {
            "type": "authentication",
            "challenge": "xyz789",
            "created_at": time.time(),
            "rp_id": "example.com",
        }
        with patch("app.interface.auth.InterfaceWebAuthn.ModuleWebAuthn") as mock_module:
            mock_challenge = MagicMock()
            mock_challenge.id = "challenge123"
            mock_module.create_challenge.return_value = mock_challenge
            mock_module.authenticate.side_effect = Exception("Verification failed")
            with pytest.raises(RequestException) as exc_info:
                interface.authentication_complete({"response": "data"})
            assert exc_info.value.http_status == err.ERROR_WEBAUTHN_AUTHENTICATION_FAILED.h


class TestGetCredentials:
    def test_returns_credentials(self, interface):
        mock_cred = MagicMock(to_dict=MagicMock(return_value={"id": "c1", "name": "Device1"}))
        interface._module.get_credentials_by_user.return_value = [mock_cred]
        result = interface.get_credentials("test@example.org")
        assert len(result) == 1
        assert result[0]["id"] == "c1"

    def test_empty_list_when_no_credentials(self, interface):
        interface._module.get_credentials_by_user.return_value = []
        result = interface.get_credentials("test@example.org")
        assert result == []


class TestDeleteCredential:
    def test_deletes_credential(self, interface):
        interface.delete_credential("cred123", "test@example.org")
        interface._module.remove_credential.assert_called_once_with("cred123", "test@example.org")


class TestHasEnabledCredentials:
    def test_returns_true(self, interface):
        interface._module.get_user_has_passkeys.return_value = True
        result = interface.has_enabled_credentials("test@example.org")
        assert result is True

    def test_returns_false(self, interface):
        interface._module.get_user_has_passkeys.return_value = False
        result = interface.has_enabled_credentials("test@example.org")
        assert result is False
