"""Coverage tests for auth plumbing + dynamic import utils.

Tests:
- app/auth/User.py: User, UserProfile, ModuleAccess, UserAnonymous (attribute access, serialization)
- app/auth/Admin.py: Admin, AdminAnonymous
- app/auth/voucher/JWTVoucher.py: encode/decode, expiry, bad signature
- app/auth/service/VoucherAdminService: issue/validate with mock signer
- app/auth/service/VoucherUserService: issue/validate with mock signer
- app/utils/module/importManager.py: import_and_instantiate_manager
- app/utils/dynamic_import.py: import_and_get_class

Target: >=90% combined coverage on these modules.
"""
import json
import os
import time
from base64 import urlsafe_b64encode
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Set required environment variables
os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

from app.utils import constants as cs
from app.utils.exceptions import RequestException, AggravatedException, BugException


# =============================================================================
# Fake objects used across multiple test classes
# =============================================================================

class FakeCache:
    """Fake cache that simulates Redis without requiring a running server."""
    
    def __init__(self):
        self.hashes = {}
        self.zsets = {}
        self.closed = False
        self.strings = {}

    def hashset(self, key, mapping, ttl=None, **kwargs):
        h = self.hashes.setdefault(key, {})
        h.update(mapping)
        return True

    def hashget(self, key, field=None):
        h = self.hashes.get(key)
        if h is None:
            return None
        if field is None:
            return h
        return h.get(field)

    def zset_add(self, key, member, score):
        self.zsets.setdefault(key, {})[member] = score
        return 1

    def zset_remove(self, key, *members):
        z = self.zsets.get(key)
        if not z:
            return 0
        n = 0
        for m in members:
            if m in z:
                del z[m]
                n += 1
        return n

    def close(self):
        self.closed = True

    def set(self, key, val, ttl=None, nx=False):
        if nx and key in self.strings:
            return False
        self.strings[key] = val
        return True

    def get(self, key, expected_type=str):
        return self.strings.get(key)

    def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.strings:
                del self.strings[key]
                removed += 1
            if key in self.hashes:
                del self.hashes[key]
                removed += 1
        return removed


# =============================================================================
# Part 1: User and Admin model tests
# =============================================================================


class TestUser:
    """Tests for app.auth.User module - User, UserProfile, ModuleAccess classes."""

    def test_module_access_default_attributes(self):
        """Test ModuleAccess default attribute values."""
        from app.auth.User import ModuleAccess
        
        access = ModuleAccess()
        assert access.calendar is True
        assert access.mail is True
        assert access.contact is True

    def test_user_profile_default_attributes(self):
        """Test UserProfile default attribute values."""
        from app.auth.User import UserProfile
        
        profile = UserProfile()
        assert profile.id == ""
        assert profile.hash == ""
        assert profile.uid == ""
        assert profile.preferences == {}
        assert profile.folders == {}
        assert profile.main_account == {}
        assert profile.external_accounts is None
        assert profile.filters is None
        assert profile.private_salt == ""
        assert profile.acl_given is None
        assert profile.acl_received is None
        assert profile.delegation_given is None
        assert profile.delegation_received is None

    def test_user_profile_repr_with_external_accounts(self):
        """Test UserProfile __repr__ with external accounts."""
        from app.auth.User import UserProfile
        
        profile = UserProfile()
        profile.uid = "testuser"
        profile.external_accounts = {
            "acc1": {"name": "Account1", "type": "imap"},
            "acc2": {"name": "Account2", "type": "caldav"}
        }
        repr_str = repr(profile)
        assert "testuser" in repr_str
        assert "Account1" in repr_str
        assert "Account2" in repr_str

    def test_user_profile_repr_without_external_accounts(self):
        """Test UserProfile __repr__ without external accounts."""
        from app.auth.User import UserProfile
        
        profile = UserProfile()
        profile.uid = "testuser"
        profile.external_accounts = None
        repr_str = repr(profile)
        assert "testuser" in repr_str
        assert "[]" in repr_str

    def test_user_init_default_values(self):
        """Test User __init__ with default values."""
        from app.auth.User import User
        
        user = User(uid="testuser", password="testpass")
        assert user.uid == "testuser"
        assert user.password == "testpass"
        assert user.cn == ""
        assert user.domain == ""
        assert user.is_domainless is False
        assert user.authenticated is False
        assert user.anonymous is False
        assert user.user_class == cs.USER_CLASS_USER
        assert user.auth_method == ""
        assert user.mail == ""
        assert user.source_id == ""
        assert isinstance(user.profile, type(user.profile))
        assert user.extra_mail == []
        assert user.extra_info == {}
        assert isinstance(user.access, type(user.access))
        assert user.imap_host == ""

    def test_user_init_with_domain(self):
        """Test User __init__ with explicit domain."""
        from app.auth.User import User
        
        user = User(uid="testuser", password="testpass", domain="example.com")
        assert user.domain == "example.com"

    def test_user_init_domainless(self):
        """Test User __init__ with domainless=True."""
        from app.auth.User import User
        
        user = User(uid="testuser", password="testpass", is_domainless=True)
        assert user.is_domainless is True

    def test_user_init_from_mail_domain(self):
        """Test User __init__ extracts domain from uid if it's an email."""
        from app.auth.User import User
        
        user = User(uid="user@example.com", password="testpass")
        assert user.domain == "example.com"

    def test_user_init_from_user_session(self):
        """Test User.init_from_user_session factory method."""
        from app.auth.User import User
        
        session = {
            cs.USER_UID: "session_user",
            cs.USER_PWD: "session_pass",
            cs.USER_DOMAIN: "session_domain",
            cs.USER_EMAIL: "user@example.com",
            cs.USER_SRC_ID: "ldap-main",
            cs.USER_AUTH_METHOD: "oidc"
        }
        user = User.init_from_user_session(session)
        
        assert user.uid == "session_user"
        assert user.password == "session_pass"
        assert user.domain == "session_domain"
        assert user.mail == "user@example.com"
        assert user.source_id == "ldap-main"
        assert user.auth_method == "oidc"

    def test_user_init_from_user_session_without_auth_method(self):
        """Test User.init_from_user_session without auth_method."""
        from app.auth.User import User
        
        session = {
            cs.USER_UID: "session_user",
            cs.USER_PWD: "session_pass",
            cs.USER_DOMAIN: "session_domain",
            cs.USER_EMAIL: "user@example.com",
            cs.USER_SRC_ID: "ldap-main"
        }
        user = User.init_from_user_session(session)
        assert user.auth_method == ""

    def test_user_get_user_session(self):
        """Test User.get_user_session serialization."""
        from app.auth.User import User
        
        user = User(uid="testuser", password="testpass", domain="example.com")
        user.mail = "user@example.com"
        user.source_id = "ldap-main"
        user.auth_method = "password"
        
        session = user.get_user_session()
        
        assert session[cs.USER_UID] == "testuser"
        assert session[cs.USER_PWD] == "testpass"
        assert session[cs.USER_DOMAIN] == "example.com"
        assert session[cs.USER_EMAIL] == "user@example.com"
        assert session[cs.USER_SRC_ID] == "ldap-main"
        assert session[cs.USER_AUTH_METHOD] == "password"

    def test_user_get_voucher_payload(self):
        """Test User.get_voucher_payload serialization."""
        from app.auth.User import User
        
        user = User(uid="testuser", cn="Test User", password="testpass", domain="example.com")
        user.mail = "user@example.com"
        
        payload = user.get_voucher_payload()
        
        assert payload[cs.USER_UID] == "testuser"
        assert payload[cs.USER_CN] == "Test User"
        assert payload[cs.USER_EMAIL] == "user@example.com"

    def test_user_repr(self):
        """Test User.__repr__."""
        from app.auth.User import User
        
        user = User(uid="testuser", cn="Test", password="pass", domain="example.com")
        user.mail = "user@example.com"
        user.authenticated = True
        
        repr_str = repr(user)
        assert "testuser" in repr_str
        assert "Test" in repr_str
        assert "user@example.com" in repr_str
        assert "True" in repr_str

    def test_user_anonymous(self):
        """Test UserAnonymous class."""
        from app.auth.User import UserAnonymous
        
        user = UserAnonymous()
        assert user.uid == "anonymous"
        assert user.password == "anonymous"
        assert user.authenticated is False
        assert user.anonymous is True


class TestAdmin:
    """Tests for app.auth.Admin module - Admin, AdminAnonymous classes."""

    def test_admin_init_default(self):
        """Test Admin __init__ with default values."""
        from app.auth.Admin import Admin
        
        admin = Admin()
        assert admin.uid == ""
        assert admin.authenticated is True
        assert admin.anonymous is False

    def test_admin_init_with_uid(self):
        """Test Admin __init__ with uid."""
        from app.auth.Admin import Admin
        
        admin = Admin(uid="admin@example.com")
        assert admin.uid == "admin@example.com"

    def test_admin_repr(self):
        """Test Admin.__repr__."""
        from app.auth.Admin import Admin
        
        admin = Admin(uid="admin@example.com")
        repr_str = repr(admin)
        assert "admin@example.com" in repr_str

    def test_admin_anonymous(self):
        """Test AdminAnonymous class."""
        from app.auth.Admin import AdminAnonymous
        
        admin = AdminAnonymous()
        assert admin.uid == "anonymous"
        assert admin.authenticated is False
        assert admin.anonymous is True


# =============================================================================
# Part 2: JWTVoucher tests
# =============================================================================


class TestJWTVoucher:
    """Tests for app.auth.voucher.JWTVoucher."""

    @pytest.fixture
    def voucher(self):
        """Create a JWTVoucher with the test secret."""
        from app.auth.voucher.JWTVoucher import JWTVoucher
        secret = "0123456789abcdef0123456789abcdef"
        return JWTVoucher(secret)

    def test_get_needed_parameters_to_instantiate(self):
        """Test get_needed_parameters_to_instantiate returns correct dict."""
        from app.auth.voucher.JWTVoucher import JWTVoucher
        
        result = JWTVoucher.get_needed_parameters_to_instantiate()
        assert isinstance(result, dict)
        assert "process_settings" in result
        assert result["process_settings"] == ("SOGO_P_VOUCHER_SECRET", "secret")

    def test_create_voucher_success(self, voucher):
        """Test create_voucher returns a valid JWT token."""
        import jwt
        
        payload = {"uid": "testuser", "mail": "user@example.com"}
        secret = "0123456789abcdef0123456789abcdef"
        token = voucher.create_voucher(payload, validity=3600)
        
        assert isinstance(token, str)
        # Verify we can decode it
        decoded = jwt.decode(token, secret, algorithms=["HS256"])
        assert decoded["uid"] == "testuser"
        assert decoded["mail"] == "user@example.com"
        assert decoded[cs.JWT_ISS] == "SOGo6"
        assert decoded[cs.JWT_EXP] > int(time.time())

    def test_create_voucher_adds_issuer_and_expiry(self, voucher):
        """Test that create_voucher adds issuer and expiry to payload."""
        import jwt
        
        payload = {"sub": "test"}
        secret = "0123456789abcdef0123456789abcdef"
        token = voucher.create_voucher(payload, validity=60)
        decoded = jwt.decode(token, secret, algorithms=["HS256"])
        
        assert decoded[cs.JWT_ISS] == "SOGo6"
        assert cs.JWT_EXP in decoded

    def test_create_voucher_zero_validity_raises(self, voucher):
        """Test create_voucher with validity <= 0 raises BugException."""
        payload = {"uid": "testuser"}
        
        with pytest.raises(BugException):
            voucher.create_voucher(payload, validity=0)

    def test_create_voucher_negative_validity_raises(self, voucher):
        """Test create_voucher with negative validity raises BugException."""
        payload = {"uid": "testuser"}
        
        with pytest.raises(BugException):
            voucher.create_voucher(payload, validity=-1)

    def test_check_voucher_data_type_string(self, voucher):
        """Test check_voucher_data_type returns True for strings."""
        assert voucher.check_voucher_data_type("some_string") is True

    def test_check_voucher_data_type_non_string(self, voucher):
        """Test check_voucher_data_type returns False for non-strings."""
        assert voucher.check_voucher_data_type(123) is False
        assert voucher.check_voucher_data_type({}) is False
        assert voucher.check_voucher_data_type([]) is False
        assert voucher.check_voucher_data_type(None) is False

    def test_read_voucher_success(self, voucher):
        """Test read_voucher successfully decodes a valid token."""
        import jwt
        
        secret = "0123456789abcdef0123456789abcdef"
        payload = {"uid": "testuser", "mail": "user@example.com"}
        token = jwt.encode(payload, secret, algorithm="HS256")
        
        result = voucher.read_voucher(token)
        
        assert result is not None
        assert result["uid"] == "testuser"
        assert result["mail"] == "user@example.com"

    def test_read_voucher_expired_signature(self, voucher):
        """Test read_voucher returns None for expired token."""
        import jwt
        
        secret = "0123456789abcdef0123456789abcdef"
        payload = {
            "uid": "testuser",
            "exp": int(time.time()) - 100  # Expired 100 seconds ago
        }
        token = jwt.encode(payload, secret, algorithm="HS256")
        
        result = voucher.read_voucher(token)
        assert result is None

    def test_read_voucher_invalid_signature(self, voucher):
        """Test read_voucher returns None for invalid signature."""
        import jwt
        
        payload = {"uid": "testuser"}
        # Use a different secret to create invalid signature
        token = jwt.encode(payload, "wrong_secret", algorithm="HS256")
        
        result = voucher.read_voucher(token)
        assert result is None

    def test_read_voucher_decode_error(self, voucher):
        """Test read_voucher returns None for decode errors."""
        result = voucher.read_voucher("not.a.valid.jwt.token")
        assert result is None

    def test_read_voucher_empty_string(self, voucher):
        """Test read_voucher with empty string."""
        result = voucher.read_voucher("")
        assert result is None

    def test_read_voucher_none(self, voucher):
        """Test read_voucher with None."""
        result = voucher.read_voucher(None)
        assert result is None

    def test_read_voucher_int(self, voucher):
        """Test read_voucher with wrong type."""
        result = voucher.read_voucher(123)
        assert result is None

    def test_read_voucher_invalid_signature_error(self, voucher):
        """Test read_voucher handles InvalidSignatureError."""
        import jwt
        token = jwt.encode({"uid": "test"}, "wrong_secret", algorithm="HS256")
        result = voucher.read_voucher(token)
        assert result is None

    def test_read_voucher_decode_error(self, voucher):
        """Test read_voucher returns None for decode errors."""
        result = voucher.read_voucher("not.a.valid.jwt.token")
        assert result is None


# =============================================================================
# Part 3: VoucherAdminService tests
# =============================================================================


class TestVoucherAdminService:
    """Tests for app.auth.service.VoucherAdminService."""

    @pytest.fixture
    def fake_process_settings(self):
        """Create a fake ProcessSetting with the required values."""
        # Use a valid 32-char secret regardless of environment
        secret = "0123456789abcdef0123456789abcdef"  # 32 chars
        
        class FakeSettings:
            SOGO_P_VOUCHER_SECRET = secret
            def __getitem__(self, key):
                return getattr(self, key)
        
        return FakeSettings()

    @pytest.fixture
    def fake_cache(self):
        """Create a fresh FakeCache for each test."""
        return FakeCache()

    @pytest.fixture
    def admin_service(self, fake_process_settings, fake_cache):
        """Create a VoucherAdminService with mocked dependencies."""
        from app.auth.service.VoucherAdminService import VoucherAdminService
        from app.auth.voucher.JWTVoucher import JWTVoucher
        
        with patch("app.auth.service.VoucherAdminService.sogo_cache", return_value=fake_cache):
            with patch("app.auth.service.VoucherAdminService.import_and_get_class", return_value=JWTVoucher):
                service = VoucherAdminService(fake_process_settings)
                yield service, fake_cache

    def test_init_valid_secret(self, fake_process_settings):
        """Test VoucherAdminService init with valid 32-char secret."""
        from app.auth.service.VoucherAdminService import VoucherAdminService
        
        with patch("app.auth.service.VoucherAdminService.sogo_cache"):
            with patch("app.auth.service.VoucherAdminService.import_and_get_class"):
                service = VoucherAdminService(fake_process_settings)
                assert service.fernet_session is not None

    def test_init_short_secret_raises(self):
        """Test VoucherAdminService init with short secret raises BugException."""
        from app.auth.service.VoucherAdminService import VoucherAdminService
        from app.config.settings.ProcessSetting import ProcessSetting
        
        settings = MagicMock(spec=ProcessSetting)
        settings.SOGO_P_VOUCHER_SECRET = "short"
        
        with pytest.raises(BugException):
            VoucherAdminService(settings)

    def test_generate_voucher_from_admin_stores_session(self, admin_service):
        """Test generate_voucher_from_admin stores admin session in cache."""
        service, fake_cache = admin_service
        
        voucher = service.generate_voucher_from_admin("admin@example.com")
        
        assert isinstance(voucher, str)
        # Check session was stored in cache
        assert len(fake_cache.hashes) == 1
        session_key = list(fake_cache.hashes.keys())[0]
        assert session_key.startswith("admin_session:")
        session_data = fake_cache.hashes[session_key]
        assert session_data[cs.USER_UID] == "admin@example.com"
        assert cs.SESSION_LAST_SEEN in session_data

    def test_generate_voucher_from_admin_sets_ttl(self, admin_service):
        """Test generate_voucher_from_admin sets 30 min TTL on session."""
        service, fake_cache = admin_service
        
        with patch.object(fake_cache, 'hashset', wraps=fake_cache.hashset) as mock_hashset:
            service.generate_voucher_from_admin("admin@example.com")
            # Check TTL was passed as 30*60 = 1800
            args = mock_hashset.call_args[0]
            assert args[2] == 30 * 60

    def test_generate_voucher_from_admin_closes_cache(self, admin_service):
        """Test generate_voucher_from_admin closes the cache."""
        service, fake_cache = admin_service
        
        service.generate_voucher_from_admin("admin@example.com")
        assert fake_cache.closed is True

    def test_get_redis_session_key_from_voucher_wrong_type(self, admin_service):
        """Test get_redis_session_key_from_voucher raises for wrong data type."""
        service, _ = admin_service
        
        with pytest.raises(RequestException):
            service.get_redis_session_key_from_voucher(12345)

    def test_get_redis_session_key_from_voucher_expired(self, admin_service):
        """Test get_redis_session_key_from_voucher raises for expired voucher."""
        import jwt
        secret = "0123456789abcdef0123456789abcdef"
        
        service, _ = admin_service
        
        # Create an expired JWT
        expired_payload = {
            "uid": "admin@example.com",
            cs.SESSION_KEY: "crypted_session_key",
            "exp": int(time.time()) - 100
        }
        expired_token = jwt.encode(expired_payload, secret, algorithm="HS256")
        
        with pytest.raises(RequestException):
            service.get_redis_session_key_from_voucher(expired_token)

    def test_generate_admin_from_voucher_missing_session(self, fake_process_settings, fake_cache):
        """Test generate_admin_from_voucher returns AdminAnonymous when session is missing."""
        from app.auth.service.VoucherAdminService import VoucherAdminService
        from app.auth.Admin import AdminAnonymous
        import jwt
        
        secret = "0123456789abcdef0123456789abcdef"
        
        with patch("app.auth.service.VoucherAdminService.sogo_cache", return_value=fake_cache):
            with patch("app.auth.service.VoucherAdminService.import_and_get_class") as mock_import:
                from app.auth.voucher.JWTVoucher import JWTVoucher
                mock_import.return_value = JWTVoucher
                service = VoucherAdminService(fake_process_settings)
                
                # Create a valid token but don't store session
                from cryptography.fernet import Fernet
                crypted = service.fernet_session.encrypt(b"session_id:session_key").decode("utf-8")
                payload = {cs.USER_UID: "admin@example.com", cs.SESSION_KEY: crypted}
                token = jwt.encode(payload, secret, algorithm="HS256")
                
                admin = service.generate_admin_from_voucher(token)
                assert isinstance(admin, AdminAnonymous)

    def test_generate_admin_from_voucher_uid_mismatch(self, fake_process_settings, fake_cache):
        """Test generate_admin_from_voucher returns AdminAnonymous on uid mismatch."""
        from app.auth.service.VoucherAdminService import VoucherAdminService
        from app.auth.Admin import AdminAnonymous
        import jwt
        
        secret = "0123456789abcdef0123456789abcdef"
        
        with patch("app.auth.service.VoucherAdminService.sogo_cache", return_value=fake_cache):
            with patch("app.auth.service.VoucherAdminService.import_and_get_class") as mock_import:
                from app.auth.voucher.JWTVoucher import JWTVoucher
                mock_import.return_value = JWTVoucher
                service = VoucherAdminService(fake_process_settings)
                
                # Create session with one uid
                fake_cache.hashes["admin_session:test_session"] = {
                    cs.USER_UID: "stored_admin@example.com"
                }
                
                # Create token with different uid
                crypted = service.fernet_session.encrypt(b"test_session:session_key").decode("utf-8")
                payload = {cs.USER_UID: "different_admin@example.com", cs.SESSION_KEY: crypted}
                token = jwt.encode(payload, secret, algorithm="HS256")
                
                admin = service.generate_admin_from_voucher(token)
                assert isinstance(admin, AdminAnonymous)

    def test_generate_admin_from_voucher_success(self, fake_process_settings, fake_cache):
        """Test generate_admin_from_voucher returns Admin for valid session."""
        from app.auth.service.VoucherAdminService import VoucherAdminService
        from app.auth.Admin import Admin
        import jwt
        
        secret = "0123456789abcdef0123456789abcdef"
        
        with patch("app.auth.service.VoucherAdminService.sogo_cache", return_value=fake_cache):
            with patch("app.auth.service.VoucherAdminService.import_and_get_class") as mock_import:
                from app.auth.voucher.JWTVoucher import JWTVoucher
                mock_import.return_value = JWTVoucher
                service = VoucherAdminService(fake_process_settings)
                
                # Create session
                fake_cache.hashes["admin_session:test_session"] = {
                    cs.USER_UID: "admin@example.com",
                    cs.SESSION_LAST_SEEN: int(time.time()) - 100
                }
                
                # Create valid token
                crypted = service.fernet_session.encrypt(b"test_session:session_key").decode("utf-8")
                payload = {cs.USER_UID: "admin@example.com", cs.SESSION_KEY: crypted}
                token = jwt.encode(payload, secret, algorithm="HS256")
                
                admin = service.generate_admin_from_voucher(token)
                assert isinstance(admin, Admin)
                assert admin.uid == "admin@example.com"
                assert admin.authenticated is True

    def test_generate_admin_from_voucher_updates_last_seen(self, fake_process_settings, fake_cache):
        """Test generate_admin_from_voucher updates last_seen in session."""
        from app.auth.service.VoucherAdminService import VoucherAdminService
        import jwt
        
        secret = "0123456789abcdef0123456789abcdef"
        
        with patch("app.auth.service.VoucherAdminService.sogo_cache", return_value=fake_cache):
            with patch("app.auth.service.VoucherAdminService.import_and_get_class") as mock_import:
                from app.auth.voucher.JWTVoucher import JWTVoucher
                mock_import.return_value = JWTVoucher
                service = VoucherAdminService(fake_process_settings)
                
                old_time = int(time.time()) - 100
                fake_cache.hashes["admin_session:test_session"] = {
                    cs.USER_UID: "admin@example.com",
                    cs.SESSION_LAST_SEEN: old_time
                }
                
                crypted = service.fernet_session.encrypt(b"test_session:session_key").decode("utf-8")
                payload = {cs.USER_UID: "admin@example.com", cs.SESSION_KEY: crypted}
                token = jwt.encode(payload, secret, algorithm="HS256")
                
                service.generate_admin_from_voucher(token)
                
                assert fake_cache.hashes["admin_session:test_session"][cs.SESSION_LAST_SEEN] > old_time

    def test_generate_voucher_encrypt_failure(self, fake_process_settings, fake_cache):
        """Test generate_voucher_from_admin raises BugException on encrypt failure."""
        from app.auth.service.VoucherAdminService import VoucherAdminService
        from app.utils.exceptions import BugException
        from cryptography.fernet import InvalidToken
        
        with patch("app.auth.service.VoucherAdminService.sogo_cache", return_value=fake_cache):
            with patch("app.auth.service.VoucherAdminService.import_and_get_class") as mock_import:
                from app.auth.voucher.JWTVoucher import JWTVoucher
                mock_import.return_value = JWTVoucher
                service = VoucherAdminService(fake_process_settings)
                
                # Make encrypt raise an exception
                service.fernet_session.encrypt = MagicMock(side_effect=InvalidToken("test"))
                
                with pytest.raises(BugException):
                    service.generate_voucher_from_admin("admin@example.com")

    def test_get_redis_session_key_cannot_decrypt(self, fake_process_settings):
        """Test get_redis_session_key_from_voucher raises RequestException on decrypt failure."""
        from app.auth.service.VoucherAdminService import VoucherAdminService
        from cryptography.fernet import InvalidToken
        import jwt
        
        secret = "0123456789abcdef0123456789abcdef"
        fake_cache = FakeCache()
        
        with patch("app.auth.service.VoucherAdminService.sogo_cache", return_value=fake_cache):
            with patch("app.auth.service.VoucherAdminService.import_and_get_class") as mock_import:
                from app.auth.voucher.JWTVoucher import JWTVoucher
                mock_import.return_value = JWTVoucher
                service = VoucherAdminService(fake_process_settings)
                
                # Create a token with invalid ciphertext
                payload = {cs.USER_UID: "admin@example.com", cs.SESSION_KEY: "invalid_ciphertext"}
                token = jwt.encode(payload, secret, algorithm="HS256")
                
                # Make decrypt raise
                service.fernet_session.decrypt = MagicMock(side_effect=InvalidToken("test"))
                
                with pytest.raises(RequestException):
                    service.get_redis_session_key_from_voucher(token)

    def test_get_redis_session_key_invalid_format(self, fake_process_settings):
        """Test get_redis_session_key_from_voucher raises RequestException for invalid session key format."""
        from app.auth.service.VoucherAdminService import VoucherAdminService
        from app.auth.Admin import AdminAnonymous
        import jwt
        
        secret = "0123456789abcdef0123456789abcdef"
        fake_cache = FakeCache()
        
        with patch("app.auth.service.VoucherAdminService.sogo_cache", return_value=fake_cache):
            with patch("app.auth.service.VoucherAdminService.import_and_get_class") as mock_import:
                from app.auth.voucher.JWTVoucher import JWTVoucher
                mock_import.return_value = JWTVoucher
                service = VoucherAdminService(fake_process_settings)
                
                # Create a token with session_key without colon - this will raise RequestException in get_redis_session_key_from_voucher
                # which should be caught by generate_admin_from_voucher
                crypted = service.fernet_session.encrypt(b"nocolon").decode("utf-8")
                payload = {cs.USER_UID: "admin@example.com", cs.SESSION_KEY: crypted}
                token = jwt.encode(payload, secret, algorithm="HS256")
                
                # Call generate_admin_from_voucher which should catch the RequestException
                admin = service.generate_admin_from_voucher(token)
                assert isinstance(admin, AdminAnonymous)


# =============================================================================
# Part 4: VoucherUserService tests
# =============================================================================


class TestVoucherUserService:
    """Tests for app.auth.service.VoucherUserService."""

    @pytest.fixture
    def fake_process_settings(self):
        """Create a fake ProcessSetting with the required values."""
        # Use a valid 32-char secret regardless of environment
        secret = "0123456789abcdef0123456789abcdef"  # 32 chars
        
        class FakeSettings:
            SOGO_P_VOUCHER_SECRET = secret
            def __getitem__(self, key):
                return getattr(self, key)
        
        return FakeSettings()

    @pytest.fixture
    def fake_cache(self):
        """Create a fresh FakeCache for each test."""
        return FakeCache()

    @pytest.fixture
    def user_service(self, fake_process_settings, fake_cache):
        """Create a VoucherUserService with mocked dependencies."""
        from app.auth.service.VoucherUserService import VoucherUserService
        from app.auth.voucher.JWTVoucher import JWTVoucher
        
        with patch("app.auth.service.VoucherUserService.sogo_cache", return_value=fake_cache):
            with patch("app.auth.service.VoucherUserService.import_and_get_class", return_value=JWTVoucher):
                service = VoucherUserService(fake_process_settings)
                yield service, fake_cache

    def test_init_valid_secret(self, fake_process_settings):
        """Test VoucherUserService init with valid 32-char secret."""
        from app.auth.service.VoucherUserService import VoucherUserService
        
        with patch("app.auth.service.VoucherUserService.sogo_cache"):
            with patch("app.auth.service.VoucherUserService.import_and_get_class"):
                service = VoucherUserService(fake_process_settings)
                assert service.fernet_session is not None

    def test_init_short_secret_raises(self):
        """Test VoucherUserService init with short secret raises AggravatedException."""
        from app.auth.service.VoucherUserService import VoucherUserService
        from app.config.settings.ProcessSetting import ProcessSetting
        
        settings = MagicMock(spec=ProcessSetting)
        settings.SOGO_P_VOUCHER_SECRET = "short"
        
        with pytest.raises(AggravatedException):
            VoucherUserService(settings)

    def test_generate_voucher_from_user_stores_session(self, user_service):
        """Test generate_voucher_from_user stores user session in cache."""
        from app.auth.User import User
        
        service, fake_cache = user_service
        user = User(uid="user@example.com", password="testpass", domain="example.com")
        user.mail = "user@example.com"
        user.source_id = "ldap-main"
        
        voucher = service.generate_voucher_from_user(user)
        
        assert isinstance(voucher, str)
        # Check session was stored in cache
        session_keys = [k for k in fake_cache.hashes.keys() if k.startswith("user_session:")]
        assert len(session_keys) == 1
        session_data = fake_cache.hashes[session_keys[0]]
        assert session_data[cs.USER_UID] == "user@example.com"
        assert session_data[cs.USER_DOMAIN] == "example.com"
        assert cs.SESSION_SENSITIVE in session_data
        assert cs.SESSION_LAST_SEEN in session_data

    def test_generate_voucher_from_user_indexes_in_zsets(self, user_service):
        """Test generate_voucher_from_user indexes session in sorted sets."""
        from app.auth.User import User
        
        service, fake_cache = user_service
        user = User(uid="user@example.com", password="testpass", domain="example.com")
        user.mail = "user@example.com"
        
        service.generate_voucher_from_user(user)
        
        # Check session is indexed in all three zsets
        assert cs.ZSET_USER_SESSIONS_ACTIVITY in fake_cache.zsets
        assert cs.ZSET_USER_SESSIONS_UID in fake_cache.zsets
        assert cs.ZSET_USER_SESSIONS_DOMAIN in fake_cache.zsets

    def test_generate_voucher_from_user_closes_cache(self, user_service):
        """Test generate_voucher_from_user closes the cache."""
        from app.auth.User import User
        
        service, fake_cache = user_service
        user = User(uid="user@example.com", password="testpass")
        
        service.generate_voucher_from_user(user)
        assert fake_cache.closed is True

    def test_get_redis_session_key_from_voucher_wrong_type(self, user_service):
        """Test get_redis_session_key_from_voucher raises for wrong data type."""
        service, _ = user_service
        
        with pytest.raises(RequestException):
            service.get_redis_session_key_from_voucher(12345)

    def test_get_redis_session_key_from_voucher_expired(self, user_service):
        """Test get_redis_session_key_from_voucher raises for expired voucher."""
        import jwt
        secret = "0123456789abcdef0123456789abcdef"
        
        service, _ = user_service
        
        expired_payload = {
            "uid": "user@example.com",
            cs.SESSION_KEY: "crypted_session_key",
            "exp": int(time.time()) - 100
        }
        expired_token = jwt.encode(expired_payload, secret, algorithm="HS256")
        
        with pytest.raises(RequestException):
            service.get_redis_session_key_from_voucher(expired_token)

    def test_generate_user_from_voucher_wrong_type(self, user_service):
        """Test generate_user_from_voucher raises for wrong data type."""
        service, _ = user_service
        
        with pytest.raises(RequestException):
            service.generate_user_from_voucher({"not": "a string"})

    def test_generate_user_from_voucher_success(self, user_service):
        """Test generate_user_from_voucher successfully generates a user from a valid voucher."""
        from app.auth.User import User
        import json
        from uuid import uuid4
        
        service, fake_cache = user_service
        
        # Create a user and generate a voucher
        user = User(uid="user@example.com", password="testpass", domain="example.com")
        user.mail = "user@example.com"
        user.source_id = "ldap-main"
        
        # Generate voucher which will store session in cache
        voucher = service.generate_voucher_from_user(user)
        
        # Now try to get user from voucher
        retrieved_user = service.generate_user_from_voucher(voucher)
        
        assert isinstance(retrieved_user, User)
        assert retrieved_user.uid == "user@example.com"

    def test_generate_user_from_voucher_expired(self, user_service):
        """Test generate_user_from_voucher raises for expired voucher."""
        import jwt
        secret = "0123456789abcdef0123456789abcdef"
        
        service, _ = user_service
        
        expired_payload = {
            "uid": "user@example.com",
            cs.SESSION_KEY: "crypted_session_key",
            "exp": int(time.time()) - 100
        }
        expired_token = jwt.encode(expired_payload, secret, algorithm="HS256")
        
        with pytest.raises(RequestException):
            service.generate_user_from_voucher(expired_token)

    def test_generate_mfa_voucher_success(self, user_service):
        """Test generate_mfa_voucher returns a valid JWT."""
        import jwt
        
        service, _ = user_service
        secret = "0123456789abcdef0123456789abcdef"
        
        token = service.generate_mfa_voucher("user@example.com")
        
        assert isinstance(token, str)
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        assert payload["sub"] == "user@example.com"
        assert payload["uid"] == "user@example.com"
        assert payload["scope"] == "mfa_challenge"
        assert "exp" in payload
        assert "iat" in payload
        assert "jti" in payload

    def test_generate_mfa_voucher_has_5min_ttl(self, user_service):
        """Test generate_mfa_voucher has 5 minute TTL."""
        import jwt
        
        service, _ = user_service
        current_time = int(time.time())
        secret = "0123456789abcdef0123456789abcdef"
        
        token = service.generate_mfa_voucher("user@example.com")
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        
        # TTL should be 5 minutes = 300 seconds
        assert payload["exp"] - payload["iat"] == 300

    def test_decode_mfa_voucher_success(self, user_service):
        """Test decode_mfa_voucher successfully decodes a valid MFA voucher."""
        import jwt
        
        service, _ = user_service
        
        token = service.generate_mfa_voucher("user@example.com")
        payload = service.decode_mfa_voucher(token)
        
        assert payload is not None
        assert payload["sub"] == "user@example.com"
        assert payload["scope"] == "mfa_challenge"

    def test_decode_mfa_voucher_wrong_scope(self, user_service):
        """Test decode_mfa_voucher returns None for wrong scope."""
        import jwt
        
        service, _ = user_service
        secret = "0123456789abcdef0123456789abcdef"
        
        token = jwt.encode(
            {"sub": "user@example.com", "scope": "wrong_scope", "exp": int(time.time()) + 100},
            secret, algorithm="HS256"
        )
        
        payload = service.decode_mfa_voucher(token)
        assert payload is None

    def test_decode_mfa_voucher_invalid_signature(self, user_service):
        """Test decode_mfa_voucher returns None for invalid signature."""
        import jwt
        
        service, _ = user_service
        
        token = jwt.encode(
            {"sub": "user@example.com", "scope": "mfa_challenge", "exp": int(time.time()) + 100},
            "wrong_secret", algorithm="HS256"
        )
        
        payload = service.decode_mfa_voucher(token)
        assert payload is None

    def test_decode_mfa_voucher_expired(self, user_service):
        """Test decode_mfa_voucher returns None for expired token."""
        import jwt
        
        service, _ = user_service
        secret = "0123456789abcdef0123456789abcdef"
        
        token = jwt.encode(
            {"sub": "user@example.com", "scope": "mfa_challenge", "exp": int(time.time()) - 10},
            secret, algorithm="HS256"
        )
        
        payload = service.decode_mfa_voucher(token)
        assert payload is None

    def test_decode_mfa_voucher_garbage(self, user_service):
        """Test decode_mfa_voucher returns None for garbage input."""
        service, _ = user_service
        
        payload = service.decode_mfa_voucher("not.a.valid.jwt")
        assert payload is None

    def test_generate_voucher_user_session_encrypt_failure(self, fake_process_settings):
        """Test generate_voucher_from_user raises BugException on user session encrypt failure."""
        from app.auth.service.VoucherUserService import VoucherUserService
        from app.utils.exceptions import BugException
        from cryptography.fernet import InvalidToken
        from app.auth.User import User
        fake_cache = FakeCache()
        
        with patch("app.auth.service.VoucherUserService.sogo_cache", return_value=fake_cache):
            with patch("app.auth.service.VoucherUserService.import_and_get_class") as mock_import:
                from app.auth.voucher.JWTVoucher import JWTVoucher
                mock_import.return_value = JWTVoucher
                service = VoucherUserService(fake_process_settings)
                
                user = User(uid="user@example.com", password="testpass")
                # Make Fernet constructor or encrypt fail by patching at the right place
                with patch("app.auth.service.VoucherUserService.Fernet") as mock_fernet:
                    mock_fernet_instance = MagicMock()
                    mock_fernet_instance.encrypt = MagicMock(side_effect=InvalidToken("test"))
                    mock_fernet.return_value = mock_fernet_instance
                    
                    with pytest.raises(BugException):
                        service.generate_voucher_from_user(user)

    def test_generate_voucher_voucher_encrypt_failure(self, fake_process_settings):
        """Test generate_voucher_from_user raises BugException on voucher token encrypt failure."""
        from app.auth.service.VoucherUserService import VoucherUserService
        from app.utils.exceptions import BugException
        from cryptography.fernet import InvalidToken
        from app.auth.User import User
        fake_cache = FakeCache()
        
        with patch("app.auth.service.VoucherUserService.sogo_cache", return_value=fake_cache):
            with patch("app.auth.service.VoucherUserService.import_and_get_class") as mock_import:
                from app.auth.voucher.JWTVoucher import JWTVoucher
                mock_import.return_value = JWTVoucher
                service = VoucherUserService(fake_process_settings)
                
                user = User(uid="user@example.com", password="testpass")
                # Make the service's own fernet_session.encrypt fail
                service.fernet_session.encrypt = MagicMock(side_effect=InvalidToken("test"))
                
                with pytest.raises(BugException):
                    service.generate_voucher_from_user(user)

    def test_get_redis_session_key_cannot_decrypt(self, fake_process_settings):
        """Test get_redis_session_key_from_voucher raises RequestException on decrypt failure."""
        from app.auth.service.VoucherUserService import VoucherUserService
        from cryptography.fernet import InvalidToken
        import jwt
        
        secret = "0123456789abcdef0123456789abcdef"
        fake_cache = FakeCache()
        
        with patch("app.auth.service.VoucherUserService.sogo_cache", return_value=fake_cache):
            with patch("app.auth.service.VoucherUserService.import_and_get_class") as mock_import:
                from app.auth.voucher.JWTVoucher import JWTVoucher
                mock_import.return_value = JWTVoucher
                service = VoucherUserService(fake_process_settings)
                
                # Create a token with invalid ciphertext
                payload = {cs.USER_UID: "user@example.com", cs.SESSION_KEY: "invalid_ciphertext"}
                token = jwt.encode(payload, secret, algorithm="HS256")
                
                # Make decrypt raise
                service.fernet_session.decrypt = MagicMock(side_effect=InvalidToken("test"))
                
                with pytest.raises(RequestException):
                    service.get_redis_session_key_from_voucher(token)

    def test_get_redis_session_key_success(self, user_service):
        """Test get_redis_session_key_from_voucher returns session key for valid voucher."""
        import jwt
        
        service, _ = user_service
        secret = "0123456789abcdef0123456789abcdef"
        
        # Create a token with valid session_key (with colon)
        crypted = service.fernet_session.encrypt(b"session_id:session_token").decode("utf-8")
        payload = {"uid": "user@example.com", cs.SESSION_KEY: crypted}
        token = jwt.encode(payload, secret, algorithm="HS256")
        
        result = service.get_redis_session_key_from_voucher(token)
        assert result == "user_session:session_id"

    def test_get_redis_session_key_invalid_format(self, user_service):
        """Test get_redis_session_key_from_voucher raises RequestException for invalid session key format."""
        import jwt
        
        service, _ = user_service
        secret = "0123456789abcdef0123456789abcdef"
        
        # Create a token with session_key without colon
        crypted = service.fernet_session.encrypt(b"nocolon").decode("utf-8")
        payload = {"uid": "user@example.com", cs.SESSION_KEY: crypted}
        token = jwt.encode(payload, secret, algorithm="HS256")
        
        with pytest.raises(RequestException):
            service.get_redis_session_key_from_voucher(token)

    def test_get_user_session_from_payload_invalid_session_key(self, fake_process_settings):
        """Test _get_user_session_from_payload raises RequestException for invalid session key."""
        from app.auth.service.VoucherUserService import VoucherUserService
        
        fake_cache = FakeCache()
        
        with patch("app.auth.service.VoucherUserService.sogo_cache", return_value=fake_cache):
            with patch("app.auth.service.VoucherUserService.import_and_get_class") as mock_import:
                from app.auth.voucher.JWTVoucher import JWTVoucher
                mock_import.return_value = JWTVoucher
                service = VoucherUserService(fake_process_settings)
                
                from cryptography.fernet import Fernet
                from base64 import urlsafe_b64encode
                secret = "0123456789abcdef0123456789abcdef"
                # Create ciphertext without colon in plaintext
                f = Fernet(urlsafe_b64encode(secret.encode("utf-8")))
                crypted = f.encrypt(b"nocolon").decode("utf-8")
                payload = {cs.SESSION_KEY: crypted, cs.USER_UID: "user@example.org"}
                
                with pytest.raises(RequestException):
                    service._get_user_session_from_payload(payload)

    def test_get_user_session_from_payload_decrypt_failure(self, fake_process_settings):
        """Test _get_user_session_from_payload raises RequestException on decrypt failure."""
        from app.auth.service.VoucherUserService import VoucherUserService
        
        fake_cache = FakeCache()
        
        with patch("app.auth.service.VoucherUserService.sogo_cache", return_value=fake_cache):
            with patch("app.auth.service.VoucherUserService.import_and_get_class") as mock_import:
                from app.auth.voucher.JWTVoucher import JWTVoucher
                mock_import.return_value = JWTVoucher
                service = VoucherUserService(fake_process_settings)
                
                from cryptography.fernet import Fernet
                from base64 import urlsafe_b64encode
                secret = "0123456789abcdef0123456789abcdef"
                session_token = "wrongtoken"  # This won't decrypt correctly
                sid = "test_session"
                f = Fernet(urlsafe_b64encode(secret.encode("utf-8")))
                crypted = f.encrypt(f"{sid}:{session_token}".encode("utf-8")).decode("utf-8")
                
                fake_cache.hashes[f"user_session:{sid}"] = {
                    cs.USER_UID: "user@example.org",
                    cs.SESSION_SENSITIVE: b"garbage_encrypted_data",
                }
                payload = {cs.SESSION_KEY: crypted, cs.USER_UID: "user@example.org"}
                
                with pytest.raises(RequestException):
                    service._get_user_session_from_payload(payload)

    def test_get_user_session_from_payload_json_decode_failure(self, fake_process_settings):
        """Test _get_user_session_from_payload raises BugException on JSON decode failure."""
        from app.auth.service.VoucherUserService import VoucherUserService
        from app.utils.exceptions import BugException
        
        fake_cache = FakeCache()
        
        with patch("app.auth.service.VoucherUserService.sogo_cache", return_value=fake_cache):
            with patch("app.auth.service.VoucherUserService.import_and_get_class") as mock_import:
                from app.auth.voucher.JWTVoucher import JWTVoucher
                mock_import.return_value = JWTVoucher
                service = VoucherUserService(fake_process_settings)
                
                from cryptography.fernet import Fernet
                from base64 import urlsafe_b64encode
                secret = "0123456789abcdef0123456789abcdef"
                session_token = "abcdefghijklmnopqrstuvwxyzabcdef"
                sid = "test_session"
                
                # Create sensitive data that is not valid JSON
                session_fernet = Fernet(urlsafe_b64encode(session_token.encode("utf-8")))
                sensitive_data_encrypted = session_fernet.encrypt(b"not-json")
                
                fake_cache.hashes[f"user_session:{sid}"] = {
                    cs.USER_UID: "user@example.org",
                    cs.SESSION_SENSITIVE: sensitive_data_encrypted,
                }
                
                f = Fernet(urlsafe_b64encode(secret.encode("utf-8")))
                crypted = f.encrypt(f"{sid}:{session_token}".encode("utf-8")).decode("utf-8")
                payload = {cs.SESSION_KEY: crypted, cs.USER_UID: "user@example.org"}
                
                with pytest.raises(BugException):
                    service._get_user_session_from_payload(payload)

    def test_get_user_session_from_payload_missing_session(self, fake_process_settings):
        """Test _get_user_session_from_payload returns UserAnonymous for missing session."""
        from app.auth.service.VoucherUserService import VoucherUserService
        from app.auth.User import UserAnonymous
        
        fake_cache = FakeCache()
        
        with patch("app.auth.service.VoucherUserService.sogo_cache", return_value=fake_cache):
            with patch("app.auth.service.VoucherUserService.import_and_get_class") as mock_import:
                from app.auth.voucher.JWTVoucher import JWTVoucher
                mock_import.return_value = JWTVoucher
                service = VoucherUserService(fake_process_settings)
                
                from cryptography.fernet import Fernet
                from base64 import urlsafe_b64encode
                secret = "0123456789abcdef0123456789abcdef"
                crypted = Fernet(urlsafe_b64encode(secret.encode("utf-8"))).encrypt(b"deadbeef-deadbeef:tokentokentokentokentokentokentokentoken").decode("utf-8")
                payload = {cs.SESSION_KEY: crypted, cs.USER_UID: "ghost@example.org"}
                user = service._get_user_session_from_payload(payload)
                assert isinstance(user, UserAnonymous)

    def test_get_user_session_from_payload_uid_mismatch(self, fake_process_settings):
        """Test _get_user_session_from_payload returns UserAnonymous on uid mismatch."""
        from app.auth.service.VoucherUserService import VoucherUserService
        from app.auth.User import UserAnonymous
        from uuid import uuid4
        
        fake_cache = FakeCache()
        
        with patch("app.auth.service.VoucherUserService.sogo_cache", return_value=fake_cache):
            with patch("app.auth.service.VoucherUserService.import_and_get_class") as mock_import:
                from app.auth.voucher.JWTVoucher import JWTVoucher
                mock_import.return_value = JWTVoucher
                service = VoucherUserService(fake_process_settings)
                
                from cryptography.fernet import Fernet
                from base64 import urlsafe_b64encode
                secret = "0123456789abcdef0123456789abcdef"
                sid = str(uuid4())
                session_token = "abcdefghijklmnopqrstuvwxyzabcdef"
                f = Fernet(urlsafe_b64encode(secret.encode("utf-8")))
                crypted = f.encrypt(f"{sid}:{session_token}".encode("utf-8")).decode("utf-8")
                # store a session with a DIFFERENT uid
                fake_cache.hashes[f"user_session:{sid}"] = {
                    cs.USER_UID: "other@example.org",
                    cs.SESSION_SENSITIVE: "irrelevant",
                }
                payload = {cs.SESSION_KEY: crypted, cs.USER_UID: "wanted@example.org"}
                user = service._get_user_session_from_payload(payload)
                assert isinstance(user, UserAnonymous)

    def test_get_user_session_from_payload_success(self, fake_process_settings):
        """Test _get_user_session_from_payload successfully rehydrates user."""
        from app.auth.service.VoucherUserService import VoucherUserService
        from app.auth.User import User
        from uuid import uuid4
        import json
        
        fake_cache = FakeCache()
        
        with patch("app.auth.service.VoucherUserService.sogo_cache", return_value=fake_cache):
            with patch("app.auth.service.VoucherUserService.import_and_get_class") as mock_import:
                from app.auth.voucher.JWTVoucher import JWTVoucher
                mock_import.return_value = JWTVoucher
                service = VoucherUserService(fake_process_settings)
                
                from cryptography.fernet import Fernet
                from base64 import urlsafe_b64encode
                secret = "0123456789abcdef0123456789abcdef"
                sid = str(uuid4())
                session_token = "abcdefghijklmnopqrstuvwxyzabcdef"
                
                # Create sensitive data that can be decrypted
                session_fernet = Fernet(urlsafe_b64encode(session_token.encode("utf-8")))
                sensitive_json = {
                    cs.USER_UID: "user@example.org",
                    cs.USER_PWD: "testpass",
                    cs.USER_DOMAIN: "example.com",
                    cs.USER_EMAIL: "user@example.com",
                    cs.USER_SRC_ID: "ldap-main"
                }
                sensitive_data_encrypted = session_fernet.encrypt(json.dumps(sensitive_json).encode("utf-8"))
                
                fake_cache.hashes[f"user_session:{sid}"] = {
                    cs.USER_UID: "user@example.org",
                    cs.SESSION_SENSITIVE: sensitive_data_encrypted,
                    cs.SESSION_LAST_SEEN: 1234,
                }
                
                # Encrypt the session key
                f = Fernet(urlsafe_b64encode(secret.encode("utf-8")))
                crypted = f.encrypt(f"{sid}:{session_token}".encode("utf-8")).decode("utf-8")
                payload = {cs.SESSION_KEY: crypted, cs.USER_UID: "user@example.org"}
                user = service._get_user_session_from_payload(payload)
                
                assert isinstance(user, User)
                assert user.uid == "user@example.org"
                assert user.mail == "user@example.com"
                # Verify cache was updated
                assert fake_cache.hashes[f"user_session:{sid}"][cs.SESSION_LAST_SEEN] > 1234


# =============================================================================
# Part 5: Dynamic import tests
# =============================================================================


class TestDynamicImport:
    """Tests for app.utils.dynamic_import module."""

    def test_import_and_get_class_success(self):
        """Test import_and_get_class successfully imports and returns a class."""
        from app.utils.dynamic_import import import_and_get_class
        
        imported_class = import_and_get_class("app.auth.voucher", "JWTVoucher")
        
        assert imported_class is not None
        assert hasattr(imported_class, "get_needed_parameters_to_instantiate")

    def test_import_and_get_class_module_not_found(self):
        """Test import_and_get_class raises AggravatedException for missing module."""
        from app.utils.dynamic_import import import_and_get_class
        
        with pytest.raises(AggravatedException):
            import_and_get_class("nonexistent.module", "SomeClass")

    def test_import_and_get_class_name_error(self):
        """Test import_and_get_class raises AggravatedException for missing class name."""
        from app.utils.dynamic_import import import_and_get_class
        
        with pytest.raises(AggravatedException):
            import_and_get_class("app.auth", "NonExistentClass")

    def test_import_and_get_class_generic_exception(self):
        """Test import_and_get_class handles generic Exception."""
        from app.utils.dynamic_import import import_and_get_class
        
        with patch("app.utils.dynamic_import.import_module") as mock_import:
            # Raise a generic exception
            mock_import.side_effect = RuntimeError("Unexpected error")
            with pytest.raises(AggravatedException):
                import_and_get_class("app.auth", "User")


class TestImportManager:
    """Tests for app.utils.module.importManager module."""

    def test_import_and_instantiate_manager_success(self):
        """Test import_and_instantiate_manager successfully imports and instantiates."""
        from app.utils.module.importManager import import_and_instantiate_manager
        
        # Use a simple mock module for testing
        with patch("app.utils.module.importManager.import_module") as mock_import:
            # Create a mock module with a mock class
            mock_module = MagicMock()
            mock_class = MagicMock()
            mock_instance = MagicMock()
            mock_class.return_value = mock_instance
            mock_module.MockClass = mock_class
            mock_import.return_value = mock_module
            
            result = import_and_instantiate_manager(
                "test.module",
                "MockClass",
                {"arg1": "value1"}
            )
            
            assert result == mock_instance
            mock_class.assert_called_once_with(arg1="value1")

    def test_import_and_instantiate_manager_module_not_found(self):
        """Test import_and_instantiate_manager raises AggravatedException for missing module."""
        from app.utils.module.importManager import import_and_instantiate_manager
        
        with pytest.raises(AggravatedException):
            import_and_instantiate_manager(
                "nonexistent.module",
                "SomeClass",
                {}
            )

    def test_import_and_instantiate_manager_invalid_class(self):
        """Test import_and_instantiate_manager raises AggravatedException for invalid class."""
        from app.utils.module.importManager import import_and_instantiate_manager
        
        # Create a module that doesn't have the class
        with patch("app.utils.module.importManager.import_module") as mock_import:
            mock_module = MagicMock(spec=type("module", (), {}))
            # Don't set MockClass attribute
            mock_import.return_value = mock_module
            
            with pytest.raises(AggravatedException):
                import_and_instantiate_manager(
                    "test.module",
                    "NonExistentClass",
                    {}
                )
