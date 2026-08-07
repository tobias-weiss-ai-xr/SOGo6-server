"""
Unit tests for crypto_utils module (AES-256 encryption/decryption)
"""
import os
import base64
import pytest
from unittest.mock import patch

import app.utils.maths.crypto_utils as crypto_utils
from app.utils.maths.crypto_utils import (
    encrypt_password,
    decrypt_password
)


@pytest.fixture
def mock_encryption_key():
    """Fixture to provide a valid 32-byte encryption key"""
    return base64.b64encode(os.urandom(32)).decode('utf-8')


@pytest.fixture
def setup_encryption_key(mock_encryption_key):
    """Fixture to set up encryption key in environment"""
    with patch.object(crypto_utils, 'SOGO_AES_ENC_KEY', mock_encryption_key):
        yield mock_encryption_key


class TestEncryptDecryptIntegration:
    """Integration tests for encrypt and decrypt functions"""

    def test_encrypt_decrypt(self, setup_encryption_key):
        """Test full encryption-decryption round trip"""
        passwords = [
            "simple",
            "Complex!P@ssw0rd#123",
            "Пароль",
            "日本語パスワード",
            "a" * 100,
            "!@#$%^&*()_+-=[]{}|;':\",./<>?",
            " leading",
            "trailing ",
            " both ",
            "middle   spaces",
            "\ttabs\t",
            "\nnewlines\n",
        ]

        for password in passwords:
            encrypted = encrypt_password(password)
            decrypted = decrypt_password(encrypted)
            assert decrypted == password, f"Failed for password: {password}"


class TestGcmAtRestEncryption:
    """Tests for authenticated AES-256-GCM at-rest encryption (HIPAA)."""

    def test_gcm_roundtrip(self, setup_encryption_key):
        """Full encrypt/decrypt round trip with per-recipient context."""
        plaintext = "Confidential PHI: patient John Doe, SSN 123-45-6789"
        encrypted = crypto_utils.encrypt_gcm(plaintext, context="patient@example.org")
        assert encrypted != plaintext
        assert "patient" not in encrypted  # ciphertext must not leak plaintext
        assert crypto_utils.decrypt_gcm(encrypted, context="patient@example.org") == plaintext

    def test_gcm_empty_input(self, setup_encryption_key):
        """Empty input returns empty output without errors."""
        assert crypto_utils.encrypt_gcm("", context="x") == ""
        assert crypto_utils.decrypt_gcm("", context="x") == ""

    def test_gcm_wrong_recipient_rejected(self, setup_encryption_key):
        """A different HKDF context must not decrypt the payload."""
        encrypted = crypto_utils.encrypt_gcm("PHI body", context="patient@example.org")
        with pytest.raises(ValueError):
            crypto_utils.decrypt_gcm(encrypted, context="other@example.org")

    def test_gcm_tamper_detection(self, setup_encryption_key):
        """GCM authentication tag must reject tampered ciphertext."""
        encrypted = crypto_utils.encrypt_gcm("PHI body to protect", context="patient@example.org")
        tampered = encrypted[:-4] + ("AAAA" if encrypted[-4] != "A" else "BBBB")
        with pytest.raises(ValueError):
            crypto_utils.decrypt_gcm(tampered, context="patient@example.org")

    def test_gcm_unique_ciphertext(self, setup_encryption_key):
        """Random nonce produces a unique ciphertext for identical plaintext."""
        first = crypto_utils.encrypt_gcm("same text", context="ctx")
        second = crypto_utils.encrypt_gcm("same text", context="ctx")
        assert first != second

    def test_gcm_multibyte_unicode(self, setup_encryption_key):
        """Unicode and long payloads round-trip correctly."""
        for text in ("PHI: 患者名 山田太郎", "x" * 100_000):
            encrypted = crypto_utils.encrypt_gcm(text, context="ctx")
            assert crypto_utils.decrypt_gcm(encrypted, context="ctx") == text

    def test_gcm_invalid_payload(self, setup_encryption_key):
        """Malformed payloads raise ValueError instead of crashing."""
        for bad in ("not-base64!!", base64.b64encode(b"\x01short").decode()):
            with pytest.raises(ValueError):
                crypto_utils.decrypt_gcm(bad, context="ctx")
