"""Unit tests for InterfaceMFA (MFA/TOTP operations).

Tests the MFA interface layer that wraps ModuleTOTP for:
- TOTP setup (secret generation, QR code)
- TOTP enable (code verification, activation)
- TOTP disable
"""
from unittest.mock import MagicMock, patch

import pytest

from app.interface.auth.InterfaceMFA import InterfaceMFA
from app.utils import errors as err
from app.utils.exceptions import RequestException


class FakeUser:
    """Fake User object for testing."""
    def __init__(self, uid="test@example.org"):
        self.uid = uid


class FakeProcessSettings:
    """Fake process settings for testing."""
    SOGO_P_DB_TYPE = "PostgreSQL"
    
    def get_db_settings(self):
        return {"host": "localhost", "database": "test"}


@pytest.fixture
def interface():
    with patch(
        "app.interface.auth.InterfaceMFA.ModuleTOTP",
        return_value=MagicMock(),
    ):
        iface = InterfaceMFA(FakeProcessSettings())
        yield iface


class TestSetup:
    def test_generates_secret(self, interface):
        interface._module.generate_secret.return_value = "JBSWY3DPEHPK3PXP"
        result = interface.setup(FakeUser())
        assert "secret" in result
        assert result["secret"] == "JBSWY3DPEHPK3PXP"

    def test_returns_provisioning_uri(self, interface):
        interface._module.generate_secret.return_value = "SECRET"
        interface._module.get_provisioning_uri.return_value = "otpauth://totp/test@example.org?secret=SECRET"
        result = interface.setup(FakeUser())
        assert "provisioning_uri" in result
        assert "otpauth://" in result["provisioning_uri"]

    def test_returns_qr_svg(self, interface):
        interface._module.generate_secret.return_value = "SECRET"
        interface._module.get_provisioning_uri.return_value = "otpauth://totp/test@example.org?secret=SECRET"
        result = interface.setup(FakeUser())
        assert "qr_svg" in result

    def test_creates_or_updates_secret(self, interface):
        interface._module.generate_secret.return_value = "SECRET"
        interface._module.get_provisioning_uri.return_value = "otpauth://totp/test@example.org?secret=SECRET"
        interface.setup(FakeUser())
        interface._module.create_or_update_secret.assert_called_once()


class TestEnable:
    def test_enables_totp(self, interface):
        interface._module.get_secret.return_value = "SECRET"
        interface._module.is_enabled.return_value = False
        interface._module.verify_code.return_value = True
        interface.enable(FakeUser(), "123456")
        interface._module.enable.assert_called_once()

    def test_setup_not_started_raises(self, interface):
        interface._module.get_secret.return_value = None
        with pytest.raises(RequestException) as exc_info:
            interface.enable(FakeUser(), "123456")
        assert exc_info.value.http_status == err.ERROR_MFA_TOTP_SETUP_REQUIRED.h

    def test_already_enabled_raises(self, interface):
        interface._module.get_secret.return_value = "SECRET"
        interface._module.is_enabled.return_value = True
        with pytest.raises(RequestException) as exc_info:
            interface.enable(FakeUser(), "123456")
        assert exc_info.value.http_status == err.ERROR_MFA_TOTP_ALREADY_ENABLED.h

    def test_invalid_code_raises(self, interface):
        interface._module.get_secret.return_value = "SECRET"
        interface._module.is_enabled.return_value = False
        interface._module.verify_code.return_value = False
        with pytest.raises(RequestException) as exc_info:
            interface.enable(FakeUser(), "123456")
        assert exc_info.value.http_status == err.ERROR_MFA_TOTP_INVALID_CODE.h


class TestDisable:
    def test_disables_totp(self, interface):
        interface._module.is_enabled.return_value = True
        interface.disable(FakeUser())
        interface._module.disable.assert_called_once()

    def test_not_enabled_raises(self, interface):
        interface._module.is_enabled.return_value = False
        with pytest.raises(RequestException) as exc_info:
            interface.disable(FakeUser())
        assert exc_info.value.http_status == err.ERROR_MFA_TOTP_NOT_ENABLED.h


class TestValidateMfaVoucher:
    def test_valid_voucher_returns_uid(self, interface):
        with patch(
            "app.auth.service.VoucherUserService.VoucherUserService",
            return_value=MagicMock(decode_mfa_voucher=MagicMock(return_value={"sub": "test@example.org"})),
        ):
            result = interface._validate_mfa_voucher("valid_voucher")
            assert result == "test@example.org"

    def test_invalid_voucher_returns_none(self, interface):
        with patch(
            "app.auth.service.VoucherUserService.VoucherUserService",
            return_value=MagicMock(decode_mfa_voucher=MagicMock(return_value=None)),
        ):
            result = interface._validate_mfa_voucher("invalid_voucher")
            assert result is None

    def test_exception_returns_none(self, interface):
        with patch(
            "app.auth.service.VoucherUserService.VoucherUserService",
            side_effect=Exception("test"),
        ):
            result = interface._validate_mfa_voucher("invalid_voucher")
            assert result is None


class TestGenerateMfaVoucher:
    def test_generates_voucher(self, interface):
        with patch(
            "app.auth.service.VoucherUserService.VoucherUserService",
            return_value=MagicMock(generate_mfa_voucher=MagicMock(return_value="MFA_JWT")),
        ):
            result = interface.generate_mfa_voucher("test@example.org")
            assert result == "MFA_JWT"
