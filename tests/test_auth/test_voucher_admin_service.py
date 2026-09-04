"""Unit tests for VoucherAdminService (admin session token generation/validation).

Tests the admin authentication voucher service that:
- Generates admin session vouchers (JWTVoucher with encrypted session key)
- Validates and reads vouchers back
- Generates Admin instances from valid vouchers
"""
from unittest.mock import MagicMock, patch
from base64 import urlsafe_b64encode

import pytest

from app.auth.service.VoucherAdminService import VoucherAdminService
from app.auth.Admin import Admin, AdminAnonymous
from app.utils.exceptions import RequestException, BugException


class FakeProcessSettings:
    SOGO_P_VOUCHER_SECRET = "a" * 32  # valid 32-char secret

    def __getitem__(self, key):
        return getattr(self, key)


class FakeVoucher:
    """Fake JWTVoucher."""

    @classmethod
    def get_needed_parameters_to_instantiate(cls):
        return {"process_settings": ("SOGO_P_VOUCHER_SECRET", "secret")}

    def __init__(self, secret=None):
        self._secret = secret
        self._payload = None

    def create_voucher(self, payload, ttl):
        self._payload = payload
        return {"voucher": "jwt_token", "ttl": ttl}

    def check_voucher_data_type(self, data):
        return isinstance(data, dict)

    def read_voucher(self, data):
        if "expired" in str(data.get("voucher", "")):
            return None
        return self._payload or {"session_key": "encrypted_key", "uid": "admin@example.org"}


@pytest.fixture
def service():
    with patch(
        "app.auth.service.VoucherAdminService.import_and_get_class",
        return_value=FakeVoucher,
    ):
        yield VoucherAdminService(FakeProcessSettings())


class TestInit:
    def test_valid_secret_initializes(self):
        with patch("app.auth.service.VoucherAdminService.import_and_get_class"):
            service = VoucherAdminService(FakeProcessSettings())
            assert service.fernet_session is not None

    def test_short_secret_raises_bug(self):
        settings = FakeProcessSettings()
        settings.SOGO_P_VOUCHER_SECRET = "short"
        with pytest.raises(BugException):
            VoucherAdminService(settings)


class TestGenerateVoucherFromAdmin:
    def test_generates_voucher(self, service):
        with patch("app.auth.service.VoucherAdminService.sogo_cache") as mock_cache:
            mock_cache.return_value = MagicMock()

            result = service.generate_voucher_from_admin("admin@example.org")

            assert isinstance(result, dict)
            assert "voucher" in result

    def test_stores_session_in_redis(self, service):
        mock_cache = MagicMock()
        with patch("app.auth.service.VoucherAdminService.sogo_cache", return_value=mock_cache):
            service.generate_voucher_from_admin("admin@example.org")

            assert mock_cache.hashset.called
            args = mock_cache.hashset.call_args[0]
            assert args[0].startswith("admin_session:")
            assert args[2] == 30 * 60  # 30 min TTL
            mock_cache.close.assert_called_once()

    def test_session_contains_user_uid(self, service):
        mock_cache = MagicMock()
        with patch("app.auth.service.VoucherAdminService.sogo_cache", return_value=mock_cache):
            service.generate_voucher_from_admin("admin@example.org")

            session_data = mock_cache.hashset.call_args[0][1]
            assert session_data["uid"] == "admin@example.org"
            assert "last_activity" in session_data


class TestGetRedisSessionKeyFromVoucher:
    def test_returns_uid_and_redis_key(self, service):
        # Generate a real encrypted session key using the service fernet
        service.fernet_session = MagicMock()
        service.fernet_session.decrypt.return_value = b"session_id:session_key"

        uid, redis_key = service.get_redis_session_key_from_voucher({"voucher": "token"})

        assert uid == "admin@example.org"
        assert redis_key == "admin_session:session_id"


class TestFakeVoucherExpired:
    def test_expired_voucher_returns_none(self):
        assert FakeVoucher().read_voucher({"voucher": "expired_token"}) is None


class TestGenerateAdminFromVoucher:
    def test_returns_admin_for_valid_session(self, service):
        service.fernet_session = MagicMock()
        service.fernet_session.decrypt.return_value = b"session_id:key"

        mock_cache = MagicMock()
        mock_cache.hashget.return_value = {"uid": "admin@example.org"}

        with patch("app.auth.service.VoucherAdminService.sogo_cache", return_value=mock_cache):
            admin = service.generate_admin_from_voucher({"voucher": "jwt"})

            assert isinstance(admin, Admin)
            assert admin.uid == "admin@example.org"

    def test_returns_anonymous_when_no_session(self, service):
        service.fernet_session = MagicMock()
        service.fernet_session.decrypt.return_value = b"session_id:key"

        mock_cache = MagicMock()
        mock_cache.hashget.return_value = None

        with patch("app.auth.service.VoucherAdminService.sogo_cache", return_value=mock_cache):
            admin = service.generate_admin_from_voucher({"voucher": "jwt"})

            assert isinstance(admin, AdminAnonymous)

    def test_returns_anonymous_on_uid_mismatch(self, service):
        service.fernet_session = MagicMock()
        service.fernet_session.decrypt.return_value = b"session_id:key"

        mock_cache = MagicMock()
        mock_cache.hashget.return_value = {"uid": "different@example.org"}

        with patch("app.auth.service.VoucherAdminService.sogo_cache", return_value=mock_cache):
            admin = service.generate_admin_from_voucher({"voucher": "jwt"})

            assert isinstance(admin, AdminAnonymous)

    def test_returns_anonymous_on_request_exception(self, service):
        with patch.object(
            service, "get_redis_session_key_from_voucher",
            side_effect=RequestException("invalid"),
        ):
            admin = service.generate_admin_from_voucher({"voucher": "bad"})

            assert isinstance(admin, AdminAnonymous)

    def test_updates_session_last_seen(self, service):
        service.fernet_session = MagicMock()
        service.fernet_session.decrypt.return_value = b"session_id:key"

        mock_cache = MagicMock()
        mock_cache.hashget.return_value = {"uid": "admin@example.org"}

        with patch("app.auth.service.VoucherAdminService.sogo_cache", return_value=mock_cache):
            service.generate_admin_from_voucher({"voucher": "jwt"})

            hashset_args = mock_cache.hashset.call_args[0]
            assert hashset_args[0] == "admin_session:session_id"
            assert "last_activity" in hashset_args[1]
            hashset_kwargs = mock_cache.hashset.call_args[1]
            assert hashset_kwargs.get("ttl") == 30 * 60
