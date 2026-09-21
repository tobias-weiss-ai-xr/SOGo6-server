"""
Test for admin S/MIME certificate inventory endpoint
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key


def _create_test_cert(days_valid=365):
    """Create a test X.509 certificate for testing"""
    key = generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Test User"),
        x509.NameAttribute(NameOID.EMAIL_ADDRESS, "test@example.com"),
    ])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days_valid))
        .add_extension(
            x509.SubjectAlternativeName([x509.RFC822Name("test@example.com")]),
            critical=False,
        )
        .sign(key, __import__(
            "cryptography.hazmat.primitives.hashes", fromlist=["SHA256"]
        ).SHA256())
    )
    return cert, key


class TestSMimeKeyManagerGetAllCertificates:
    """Test the get_all_certificates method in SMimeKeyManager"""

    def test_get_all_certificates_empty(self):
        """Test get_all_certificates with empty store"""
        from app.service.smime.SMimeKeyManager import SMimeKeyManager
        
        smime_manager = SMimeKeyManager()
        
        # Mock the redis scan to return no keys
        mock_redis = MagicMock()
        mock_redis.scan.return_value = (0, [])
        smime_manager.cache.redis = mock_redis
        
        result = smime_manager.get_all_certificates()
        assert result == []

    def test_get_all_certificates_with_data(self):
        """Test get_all_certificates with actual certificates"""
        from app.service.smime.SMimeKeyManager import SMimeKeyManager, _SMIME_CERT_PREFIX, _SMIME_KEY_PREFIX
        
        cert, key = _create_test_cert()
        
        smime_manager = SMimeKeyManager()
        
        # Mock the redis client
        mock_redis = MagicMock()
        # scan returns cursor and keys - for first call return cursor and a key, then cursor=0
        # Note: In Python 3, cursor is bytes or int depending on Redis version
        # The key is the full key name including prefix
        user_uid = "test-user"
        cert_key = f"{_SMIME_CERT_PREFIX}{user_uid}"
        key_key = f"{_SMIME_KEY_PREFIX}{user_uid}"
        
        mock_redis.scan.side_effect = [
            (0, [cert_key.encode()]),  # Single scan call with cursor=0 (no more results)
        ]
        smime_manager.cache.redis = mock_redis
        
        # Mock exists to return True for private key
        def mock_exists(key):
            if key == key_key:
                return 1  # Redis returns 1 for exists
            return 0
        mock_redis.exists.side_effect = mock_exists
        
        # Mock get to return the cert PEM
        mock_redis.get.return_value = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
        
        result = smime_manager.get_all_certificates()
        
        assert len(result) == 1
        assert result[0]['user_uid'] == user_uid
        assert result[0]['has_private_key'] is True
        assert 'test@example.com' in result[0]['emails']
        assert 'not_before' in result[0]
        assert 'not_after' in result[0]

    def test_get_all_certificates_no_private_key(self):
        """Test get_all_certificates when user has cert but no private key"""
        from app.service.smime.SMimeKeyManager import SMimeKeyManager, _SMIME_CERT_PREFIX, _SMIME_KEY_PREFIX
        
        cert, key = _create_test_cert()
        
        smime_manager = SMimeKeyManager()
        
        # Mock the redis client
        mock_redis = MagicMock()
        user_uid = "user-no-key"
        cert_key = f"{_SMIME_CERT_PREFIX}{user_uid}"
        key_key = f"{_SMIME_KEY_PREFIX}{user_uid}"
        
        mock_redis.scan.side_effect = [
            (0, [cert_key.encode()]),
        ]
        smime_manager.cache.redis = mock_redis
        
        # Mock exists to return False for private key
        mock_redis.exists.return_value = 0  # Redis returns 0 for not exists
        
        # Mock get to return the cert PEM
        mock_redis.get.return_value = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
        
        result = smime_manager.get_all_certificates()
        
        assert len(result) == 1
        assert result[0]['has_private_key'] is False

    def test_get_all_certificates_multiple_users(self):
        """Test get_all_certificates with multiple users"""
        from app.service.smime.SMimeKeyManager import SMimeKeyManager, _SMIME_CERT_PREFIX, _SMIME_KEY_PREFIX
        
        cert1, _ = _create_test_cert()
        cert2, _ = _create_test_cert()
        
        smime_manager = SMimeKeyManager()
        
        # Mock the redis client
        mock_redis = MagicMock()
        user1_uid = "user-1"
        user2_uid = "user-2"
        cert1_key = f"{_SMIME_CERT_PREFIX}{user1_uid}"
        cert2_key = f"{_SMIME_CERT_PREFIX}{user2_uid}"
        key1_key = f"{_SMIME_KEY_PREFIX}{user1_uid}"
        key2_key = f"{_SMIME_KEY_PREFIX}{user2_uid}"
        
        # Return both certs in one scan
        mock_redis.scan.side_effect = [
            (0, [cert1_key.encode(), cert2_key.encode()]),
        ]
        smime_manager.cache.redis = mock_redis
        
        # Mock exists to return True for both private keys
        def mock_exists(key):
            if key in [key1_key, key2_key]:
                return 1
            return 0
        mock_redis.exists.side_effect = mock_exists
        
        # Mock get to return the appropriate cert PEM
        def mock_get(key):
            if key == cert1_key:
                return cert1.public_bytes(serialization.Encoding.PEM).decode("ascii")
            elif key == cert2_key:
                return cert2.public_bytes(serialization.Encoding.PEM).decode("ascii")
            return None
        mock_redis.get.side_effect = mock_get
        
        result = smime_manager.get_all_certificates()
        
        assert len(result) == 2
        user_uids = [r['user_uid'] for r in result]
        assert user1_uid in user_uids
        assert user2_uid in user_uids

    def test_get_all_certificates_scan_pagination(self):
        """Test get_all_certificates with multiple scan calls (pagination)"""
        from app.service.smime.SMimeKeyManager import SMimeKeyManager, _SMIME_CERT_PREFIX, _SMIME_KEY_PREFIX
        
        cert1, _ = _create_test_cert()
        cert2, _ = _create_test_cert()
        
        smime_manager = SMimeKeyManager()
        
        # Mock the redis client
        mock_redis = MagicMock()
        user1_uid = "user-1"
        user2_uid = "user-2"
        cert1_key = f"{_SMIME_CERT_PREFIX}{user1_uid}"
        cert2_key = f"{_SMIME_CERT_PREFIX}{user2_uid}"
        
        # Return certs across multiple scan calls (pagination)
        mock_redis.scan.side_effect = [
            (b'100', [cert1_key.encode()]),  # First call with non-zero cursor
            (0, [cert2_key.encode()]),        # Second call with cursor=0 (done)
        ]
        smime_manager.cache.redis = mock_redis
        
        # Mock exists to return True for both private keys
        mock_redis.exists.return_value = 1
        
        # Mock get to return the appropriate cert PEM
        def mock_get(key):
            if key == cert1_key:
                return cert1.public_bytes(serialization.Encoding.PEM).decode("ascii")
            elif key == cert2_key:
                return cert2.public_bytes(serialization.Encoding.PEM).decode("ascii")
            return None
        mock_redis.get.side_effect = mock_get
        
        result = smime_manager.get_all_certificates()
        
        # Should collect results from both scan calls
        assert len(result) == 2
        user_uids = [r['user_uid'] for r in result]
        assert user1_uid in user_uids
        assert user2_uid in user_uids
