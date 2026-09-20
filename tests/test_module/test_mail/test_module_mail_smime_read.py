"""Read-side S/MIME tests: decrypt enveloped mail + verify signed mail via
ModuleMail._parse_mail, and the LDAP directory-lookup hook."""

from email import message_from_bytes
from email.policy import SMTP

from app.service.smime.SMimeCrypto import (
    build_encrypted_message,
    build_signed_message,
    canonical_bytes,
)
from app.service.smime.SMimeKeyManager import SMimeKeyManager
from tests.test_service.test_smime.test_smime_crypto import (
    DictCache,
    build_sample_message,
    make_cert,
)


class FakeKeyManager(SMimeKeyManager):
    """SMimeKeyManager over a dict cache (no Redis)."""

    def __init__(self, cache=None):
        super().__init__(cache=cache or DictCache())


def _mail_dict(msg):
    return {"uid": "42", "mail": msg, "flags": {"seen": False, "all": []}, "size": 100}


def _make_module(monkeypatch, key_manager=None):
    from unittest.mock import MagicMock

    from app.module.mail.ModuleMail import ModuleMail

    mock_user = MagicMock()
    mock_user.uid = "test_user_123"
    mock_user.login_mail_server = "user@example.com"
    mock_user.profile.preferences.get.return_value = {}
    module = ModuleMail(user=mock_user, mail_settings=MagicMock())
    if key_manager is not None:
        monkeypatch.setattr(
            "app.module.mail.ModuleMail.SMimeKeyManager", lambda: key_manager
        )
    return module


def test_parse_signed_mail_verifies_signature(monkeypatch):
    cert, key = make_cert("Alice Sender", "alice@example.org")
    inner = build_sample_message()
    signed = build_signed_message(inner, cert, key)
    # build_signed_message returns a Message built for sending; re-parse the
    # bytes like the IMAP fetch path would.
    stored = message_from_bytes(signed.as_bytes(policy=SMTP))
    module = _make_module(monkeypatch)

    parsed = module._parse_mail(_mail_dict(stored))

    assert parsed["is_signed"] is True
    assert parsed["signature_valid"] is True
    assert parsed["certificates"] and parsed["certificates"][0]["subject_cn"] == "Alice Sender"
    assert parsed["contents"], "signed content must still be parsed"


def test_parse_tampered_signed_mail_reports_invalid(monkeypatch):
    cert, key = make_cert("Alice Sender", "alice@example.org")
    inner = build_sample_message()
    inner.replace_header("Subject", "Original subject")
    signed = build_signed_message(inner, cert, key)
    raw = signed.as_bytes(policy=SMTP)
    # Tamper with the signed content after signing.
    raw = raw.replace(b"Subject: Original subject", b"Subject: Evil subject")
    stored = message_from_bytes(raw)
    module = _make_module(monkeypatch)

    parsed = module._parse_mail(_mail_dict(stored))

    assert parsed["is_signed"] is True
    assert parsed["signature_valid"] is False


def test_parse_encrypted_mail_decrypts_with_user_key(monkeypatch):
    cert, key = make_cert("Bob Recipient", "bob@example.org")
    inner = build_sample_message()
    envelope = build_encrypted_message(inner, [cert])
    stored = message_from_bytes(envelope.as_bytes(policy=SMTP))

    mgr = FakeKeyManager()
    mgr.store("test_user_123", cert, key)
    module = _make_module(monkeypatch, key_manager=mgr)

    parsed = module._parse_mail(_mail_dict(stored))

    assert parsed["is_encrypted"] is True
    assert any("Sample" in (c.get("content") or "") or c.get("content") for c in parsed["contents"]), (
        "decrypted inner content must be visible"
    )


def test_parse_encrypted_mail_without_key_stays_opaque(monkeypatch):
    cert, _key = make_cert("Bob Recipient", "bob@example.org")
    inner = build_sample_message()
    envelope = build_encrypted_message(inner, [cert])
    stored = message_from_bytes(envelope.as_bytes(policy=SMTP))

    module = _make_module(monkeypatch, key_manager=FakeKeyManager())

    parsed = module._parse_mail(_mail_dict(stored))

    assert parsed["is_encrypted"] is True
    assert parsed["contents"] == []


def test_directory_lookup_caches_cert_into_store():
    cert, _key = make_cert("Carol Directory", "carol@example.org")
    from cryptography.hazmat.primitives.serialization import Encoding

    der = cert.public_bytes(Encoding.DER)

    mgr = FakeKeyManager()
    calls = []

    def lookup(addr):
        calls.append(addr)
        return der

    resolved = mgr.get_public_cert_for_recipient("carol@example.org", directory_lookup=lookup)
    assert resolved is not None
    assert calls == ["carol@example.org"]
    # Second resolution hits the index — lookup not called again.
    again = mgr.get_public_cert_for_recipient("carol@example.org", directory_lookup=lookup)
    assert again is not None
    assert calls == ["carol@example.org"]


def test_directory_lookup_failure_returns_none():
    mgr = FakeKeyManager()

    def broken(_addr):
        raise RuntimeError("ldap down")

    assert mgr.get_public_cert_for_recipient("x@example.org", directory_lookup=broken) is None
