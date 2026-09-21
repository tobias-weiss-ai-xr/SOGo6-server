"""
S/MIME trust bundle verification tests.

Tests that SOGO_SMIME_TRUST_BUNDLE enables CA trust verification for
signer certificates in S/MIME signatures.
"""

import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from cryptography import x509
from cryptography.x509 import (
    BasicConstraints,
    CertificateBuilder,
    Name,
    NameAttribute,
    NameOID,
    random_serial_number,
)

from app.service.smime.SMimeCrypto import (
    build_signed_message,
    canonical_bytes,
    verify_signed_message,
)


def make_cert(cn: str, email: str, days: int = 30, issuer_cert=None, issuer_key=None, is_ca: bool = False):
    """Create an X.509 certificate, optionally signed by an issuer."""
    key = generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    subject = Name([NameAttribute(NameOID.COMMON_NAME, cn)])
    
    builder = (
        CertificateBuilder()
        .subject_name(subject)
        .public_key(key.public_key())
        .serial_number(random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(
            x509.SubjectAlternativeName([x509.RFC822Name(email)]),
            critical=False,
        )
    )
    
    if issuer_cert and issuer_key:
        # Signed by CA
        builder = builder.issuer_name(issuer_cert.subject)
    else:
        # Self-signed
        builder = builder.issuer_name(subject)
    
    # Add CA basic constraint for CA certificates
    if is_ca:
        builder = builder.add_extension(
            BasicConstraints(ca=True, path_length=None), critical=True
        )
    
    cert = builder.sign(issuer_key if issuer_key else key, hashes.SHA256())
    return cert, key


def build_sample_message() -> "Message":
    from email.message import EmailMessage
    from email.utils import make_msgid

    msg = EmailMessage()
    msg["From"] = f"Sender <sender@{'example.org'}>"
    msg["To"] = "recipient@example.org"
    msg["Subject"] = "S/MIME trust test"
    msg["Message-ID"] = make_msgid(domain="example.org")
    msg["Date"] = "Tue, 01 Jan 2026 12:00:00 +0000"
    msg.set_content("Hello, trust test.")
    return msg


class TestTrustBundle:
    """Tests for SOGO_SMIME_TRUST_BUNDLE trust verification."""

    def test_trusted_none_when_env_unset(self, monkeypatch):
        """When SOGO_SMIME_TRUST_BUNDLE is not set, trusted field is None."""
        monkeypatch.delenv("SOGO_SMIME_TRUST_BUNDLE", raising=False)
        
        cert, key = make_cert("SelfSigned", "self@example.org")
        msg = build_sample_message()
        signed = build_signed_message(msg, cert, key)
        result = verify_signed_message(signed)
        
        assert result is not None
        assert result["valid"] is True
        # trusted should be None when env is unset
        assert result.get("trusted") is None

    def test_trusted_false_for_self_signed_not_in_bundle(self, monkeypatch):
        """Self-signed cert not in bundle yields trusted=False."""
        # Create a self-signed cert
        cert, key = make_cert("SelfSigned", "self@example.org")
        msg = build_sample_message()
        signed = build_signed_message(msg, cert, key)
        
        # Create a trust bundle with a different CA
        ca_cert, ca_key = make_cert("TrustCA", "ca@trust.org", is_ca=True)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as f:
            f.write(ca_cert.public_bytes(serialization.Encoding.PEM).decode())
            bundle_path = f.name
        
        try:
            monkeypatch.setenv("SOGO_SMIME_TRUST_BUNDLE", bundle_path)
            result = verify_signed_message(signed)
            
            assert result is not None
            assert result["valid"] is True
            # Self-signed cert not in bundle should yield trusted=False
            assert result.get("trusted") is False
        finally:
            os.unlink(bundle_path)

    def test_trusted_true_when_cert_chains_to_bundle(self, monkeypatch):
        """Cert that chains to the bundle yields trusted=True."""
        # Create a CA
        ca_cert, ca_key = make_cert("TrustCA", "ca@trust.org", is_ca=True)
        
        # Create a cert signed by the CA
        user_cert, user_key = make_cert("User", "user@example.org", 
                                       issuer_cert=ca_cert, issuer_key=ca_key)
        
        msg = build_sample_message()
        signed = build_signed_message(msg, user_cert, user_key)
        
        # Create trust bundle with CA cert
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as f:
            f.write(ca_cert.public_bytes(serialization.Encoding.PEM).decode())
            bundle_path = f.name
        
        try:
            monkeypatch.setenv("SOGO_SMIME_TRUST_BUNDLE", bundle_path)
            result = verify_signed_message(signed)
            
            assert result is not None
            assert result["valid"] is True
            # Cert chains to bundle, so trusted should be True
            assert result.get("trusted") is True
        finally:
            os.unlink(bundle_path)

    def test_trusted_false_when_bundle_empty(self, monkeypatch):
        """When bundle is empty file, cert cannot chain, trusted=False."""
        cert, key = make_cert("SelfSigned", "self@example.org")
        msg = build_sample_message()
        signed = build_signed_message(msg, cert, key)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as f:
            f.write("")  # Empty bundle
            bundle_path = f.name
        
        try:
            monkeypatch.setenv("SOGO_SMIME_TRUST_BUNDLE", bundle_path)
            result = verify_signed_message(signed)
            
            assert result is not None
            assert result["valid"] is True
            assert result.get("trusted") is False
        finally:
            os.unlink(bundle_path)

    def test_trusted_false_when_signature_invalid(self, monkeypatch):
        """When signature is invalid, trusted=False regardless of bundle."""
        # Create signed message
        cert, key = make_cert("Signer", "signer@example.org")
        msg = build_sample_message()
        signed = build_signed_message(msg, cert, key)
        
        # Tamper with content to make signature invalid
        # Get the raw message and modify it
        raw = signed.as_bytes()
        tampered = raw.replace(b"Hello, trust test.", b"Hello, TAMPERED!")
        
        from email import message_from_bytes
        from email.policy import SMTP
        tampered_msg = message_from_bytes(tampered, policy=SMTP)
        
        # Create a CA and bundle
        ca_cert, ca_key = make_cert("TrustCA", "ca@trust.org", is_ca=True)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as f:
            f.write(ca_cert.public_bytes(serialization.Encoding.PEM).decode())
            bundle_path = f.name
        
        try:
            monkeypatch.setenv("SOGO_SMIME_TRUST_BUNDLE", bundle_path)
            result = verify_signed_message(tampered_msg)
            
            assert result is not None
            assert result["valid"] is False
            # Invalid signature means trusted=False even with bundle
            assert result.get("trusted") is False
        finally:
            os.unlink(bundle_path)
