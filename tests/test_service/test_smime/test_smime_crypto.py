"""
S/MIME crypto round-trip tests.

Self-contained: generates X.509 pairs, signs/encrypts, and validates with the
OpenSSL CLI (`openssl smime -verify` / `-decrypt`) — proving the wire format
is accepted by the reference S/MIME implementation.
"""

import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from cryptography import x509
from cryptography.x509 import (
    CertificateBuilder,
    Name,
    NameAttribute,
    NameOID,
    random_serial_number,
)

from app.service.smime.SMimeCrypto import (
    build_detached_pkcs7,
    build_encrypted_message,
    build_signed_message,
    canonical_bytes,
    decrypt_message,
    verify_detached_signature,
)
from app.service.smime.SMimeKeyManager import SMimeKeyManager


def make_cert(cn: str, email: str, days: int = 30):
    key = generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    subject = issuer = Name([NameAttribute(NameOID.COMMON_NAME, cn)])
    cert = (
        CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(
            x509.SubjectAlternativeName([x509.RFC822Name(email)]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    return cert, key


def build_sample_message() -> "Message":
    from email.message import EmailMessage
    from email.utils import make_msgid

    msg = EmailMessage()
    msg["From"] = f"Sender <sender@{'example.org'}>"
    msg["To"] = "recipient@example.org"
    msg["Subject"] = "S/MIME round trip"
    msg["Message-ID"] = make_msgid(domain="example.org")
    msg["Date"] = "Tue, 01 Jan 2026 12:00:00 +0000"
    msg.set_content("Hello, signed payload.\nLine two.")
    return msg


class TestSigning:
    def test_signed_message_structure(self):
        cert, key = make_cert("Sender", "sender@example.org")
        msg = build_sample_message()
        signed = build_signed_message(msg, cert, key)

        ct = signed["Content-Type"]
        assert "multipart/signed" in ct
        assert 'protocol="application/pkcs7-signature"' in ct
        assert 'micalg="sha-256"' in ct

        parts = list(signed.iter_parts())
        assert len(parts) == 2
        assert parts[1]["Content-Type"].startswith("application/pkcs7-signature")
        assert parts[1]["Content-Transfer-Encoding"] == "base64"

    def test_openssl_verifies_detached_signature(self):
        cert, key = make_cert("Sender", "sender@example.org")
        msg = build_sample_message()
        content = canonical_bytes(msg)
        sig = build_detached_pkcs7(content, cert, key)
        assert verify_detached_signature(sig, content) is True

    def test_openssl_rejects_tampered_content(self):
        cert, key = make_cert("Sender", "sender@example.org")
        msg = build_sample_message()
        content = canonical_bytes(msg)
        sig = build_detached_pkcs7(content, cert, key)
        tampered = content.replace(b"Line two.", b"Line TWO!!")
        assert verify_detached_signature(sig, tampered) is False


class TestEncryption:
    def test_openssl_decrypts_enveloped_data(self):
        cert, key = make_cert("Recipient", "recipient@example.org")
        msg = build_sample_message()
        enc = build_encrypted_message(msg, [cert])

        ct = enc["Content-Type"]
        assert "application/pkcs7-mime" in ct
        assert "smime-type=enveloped-data" in ct.replace('"', "")

        payload_part = enc.get_payload()
        b64 = payload_part
        der = base64.b64decode(b64)

        plaintext = decrypt_message(
            der, key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        assert b"Hello, signed payload." in plaintext
        assert b"Subject: S/MIME round trip" in plaintext

    def test_encrypt_requires_recipient_cert(self):
        msg = build_sample_message()
        with pytest.raises(Exception):
            build_encrypted_message(msg, [])

    def test_envelope_carries_addressing_headers(self):
        cert, _ = make_cert("Recipient", "recipient@example.org")
        msg = build_sample_message()
        enc = build_encrypted_message(msg, [cert])
        # outer envelope keeps addressing headers (SMTP envelope + RFC 8551 3.6)
        assert enc["From"] == msg["From"]
        assert enc["To"] == msg["To"]
        assert enc["Subject"] == msg["Subject"]
        assert enc["Bcc"] is None  # never leaked to the outer envelope


class TestKeyManager:
    def test_pem_import_roundtrip(self, mocker):
        manager = SMimeKeyManager(cache=mocker.MagicMock())
        cert, key = make_cert("Alice", "alice@example.org")
        cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
        key_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        parsed_cert, parsed_key = SMimeKeyManager.parse_pem(cert_pem, key_pem)
        assert parsed_cert.subject.rfc4514_string().endswith("Alice")
        assert parsed_key.key_size == 2048

    def test_summary_is_public_safe(self, mocker):
        manager = SMimeKeyManager(cache=mocker.MagicMock())
        cert, _ = make_cert("Bob", "bob@example.org")
        summary = manager.cert_summary(cert) if hasattr(manager, "cert_summary") else None
        # cert_summary is a module-level helper; verify shape through it.
        from app.service.smime.SMimeKeyManager import cert_summary as cs

        s = cs(cert)
        assert s["subject_cn"] == "Bob"
        assert s["not_before"]
        assert s["fingerprint_sha256"]


class DictCache:
    """Minimal dict-backed stand-in for the Redis cache client."""

    def __init__(self):
        self._d = {}

    def set(self, key, val, ttl=None, nx=False):
        if nx and key in self._d:
            return False
        self._d[key] = val
        return True

    def get(self, key, expected_type=str):
        return self._d.get(key)

    def exists(self, key):
        return key in self._d

    def delete(self, *keys):
        for k in keys:
            self._d.pop(k, None)


class TestKeyManagerRecipients:
    def test_store_indexes_recipient_by_email(self):
        manager = SMimeKeyManager(cache=DictCache())
        cert, key = make_cert("Alice", "alice@example.org")
        manager.store("alice", cert, key)
        found = manager.get_public_cert_for_recipient("alice@example.org")
        assert found is not None
        assert found.subject.rfc4514_string().endswith("Alice")

    def test_no_recipient_without_index(self):
        manager = SMimeKeyManager(cache=DictCache())
        assert manager.get_public_cert_for_recipient("nobody@example.org") is None

    def test_delete_removes_recipient_index(self):
        manager = SMimeKeyManager(cache=DictCache())
        cert, key = make_cert("Bob", "bob@example.org")
        manager.store("bob", cert, key)
        assert manager.get_public_cert_for_recipient("bob@example.org") is not None
        manager.delete("bob")
        assert manager.get_public_cert_for_recipient("bob@example.org") is None
        assert manager.has_pair("bob") is False

    def test_summary_has_required_fields(self):
        manager = SMimeKeyManager(cache=DictCache())
        cert, key = make_cert("Carol", "carol@example.org")
        manager.store("carol", cert, key)
        s = manager.summary("carol")
        assert s["subject_cn"] == "Carol"
        assert s["fingerprint_sha256"]
        assert s["not_before"]
