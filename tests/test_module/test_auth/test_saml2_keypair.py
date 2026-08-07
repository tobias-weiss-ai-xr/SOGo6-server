"""Unit tests for Saml2Keypair — SP X.509 certificate and private key loading.

Tests cover:
  - Loading valid PEM files
  - Handling missing files
  - Handling invalid PEM content
  - is_configured() check
  - get_cert_b64() extraction
"""
from __future__ import annotations

import os
import tempfile

import pytest

from app.module.auth.Saml2Keypair import Saml2Keypair


# ── Fixtures ───────────────────────────────────────────────────────────────────


VALID_CERT_PEM = """-----BEGIN CERTIFICATE-----
MIIDfzCCAmegAwIBAgIUfakecertbase64==
-----END CERTIFICATE-----"""

VALID_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIIEfakekeybase64==
-----END PRIVATE KEY-----"""


@pytest.fixture
def fake_process_with_keypair(tmp_path):
    """Fake ProcessSetting with cert/key file paths in tmp_path."""
    cert_file = tmp_path / "sp-cert.pem"
    key_file = tmp_path / "sp-key.pem"
    cert_file.write_text(VALID_CERT_PEM)
    key_file.write_text(VALID_KEY_PEM)

    process = type("FakeProcess", (), {})()
    process.SOGO_SAML2_SP_CERT_FILE = str(cert_file)
    process.SOGO_SAML2_SP_KEY_FILE = str(key_file)
    return process


@pytest.fixture
def fake_process_no_keypair(tmp_path):
    """Fake ProcessSetting with non-existent cert/key files."""
    process = type("FakeProcess", (), {})()
    process.SOGO_SAML2_SP_CERT_FILE = str(tmp_path / "nonexistent-cert.pem")
    process.SOGO_SAML2_SP_KEY_FILE = str(tmp_path / "nonexistent-key.pem")
    return process


@pytest.fixture
def fake_process_invalid_pem(tmp_path):
    """Fake ProcessSetting with invalid PEM content."""
    cert_file = tmp_path / "bad-cert.pem"
    key_file = tmp_path / "bad-key.pem"
    cert_file.write_text("this is not a PEM certificate")
    key_file.write_text("this is not a PEM key")

    process = type("FakeProcess", (), {})()
    process.SOGO_SAML2_SP_CERT_FILE = str(cert_file)
    process.SOGO_SAML2_SP_KEY_FILE = str(key_file)
    return process


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestSaml2Keypair:
    """Tests for Saml2Keypair."""

    def test_load_valid_keypair(self, fake_process_with_keypair):
        """Should load valid PEM cert and key."""
        keypair = Saml2Keypair(fake_process_with_keypair)
        cert, key = keypair.load_keypair()
        assert cert is not None
        assert key is not None
        assert "BEGIN CERTIFICATE" in cert
        assert "PRIVATE KEY" in key

    def test_is_configured_true_with_valid_keypair(self, fake_process_with_keypair):
        """is_configured() should return True with valid files."""
        keypair = Saml2Keypair(fake_process_with_keypair)
        assert keypair.is_configured() is True

    def test_is_configured_false_with_missing_files(self, fake_process_no_keypair):
        """is_configured() should return False with missing files."""
        keypair = Saml2Keypair(fake_process_no_keypair)
        assert keypair.is_configured() is False

    def test_cert_property_returns_pem(self, fake_process_with_keypair):
        """cert property should return the PEM string."""
        keypair = Saml2Keypair(fake_process_with_keypair)
        assert keypair.cert is not None
        assert "BEGIN CERTIFICATE" in keypair.cert

    def test_key_property_returns_pem(self, fake_process_with_keypair):
        """key property should return the PEM string."""
        keypair = Saml2Keypair(fake_process_with_keypair)
        assert keypair.key is not None
        assert "PRIVATE KEY" in keypair.key

    def test_get_cert_b64_strips_headers(self, fake_process_with_keypair):
        """get_cert_b64() should strip PEM headers and newlines."""
        keypair = Saml2Keypair(fake_process_with_keypair)
        cert_b64 = keypair.get_cert_b64()
        assert cert_b64 is not None
        assert "BEGIN CERTIFICATE" not in cert_b64
        assert "END CERTIFICATE" not in cert_b64
        assert "\n" not in cert_b64

    def test_get_cert_b64_none_when_not_configured(self, fake_process_no_keypair):
        """get_cert_b64() should return None when not configured."""
        keypair = Saml2Keypair(fake_process_no_keypair)
        assert keypair.get_cert_b64() is None

    def test_invalid_pem_treated_as_not_configured(self, fake_process_invalid_pem):
        """Invalid PEM content should be treated as not configured."""
        keypair = Saml2Keypair(fake_process_invalid_pem)
        cert, key = keypair.load_keypair()
        assert cert is None
        assert key is None
        assert keypair.is_configured() is False

    def test_keypair_cached_after_first_load(self, fake_process_with_keypair):
        """Subsequent calls should return cached values without re-reading files."""
        keypair = Saml2Keypair(fake_process_with_keypair)
        cert1, key1 = keypair.load_keypair()
        # Delete files — second call should still return cached values
        os.unlink(fake_process_with_keypair.SOGO_SAML2_SP_CERT_FILE)
        os.unlink(fake_process_with_keypair.SOGO_SAML2_SP_KEY_FILE)
        cert2, key2 = keypair.load_keypair()
        assert cert1 == cert2
        assert key1 == key2
