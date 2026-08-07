"""Tests for the honest eIDAS signature implementation.

Verifies that the module really signs with RSA and rejects tampered
documents, garbage signatures and unregistered certificates.
"""
from __future__ import annotations

import sys
from unittest import mock

import pytest

sys.path.insert(0, ".")

from app.api.v1.admin import ApiEidasSignatures as eidas


@pytest.fixture()
def signature_set():
    """Sign a known document and return (doc_hash, signature, cert_hash)."""
    key = eidas._get_signing_key()
    doc_hash = eidas._compute_document_hash("Hello eIDAS world")
    signature = eidas._sign_document(doc_hash, key)
    cert_hash = eidas._register_self_issued_cert(key)
    return doc_hash, signature, cert_hash


class TestSignVerify:
    def test_round_trip_valid(self, signature_set):
        doc_hash, signature, cert_hash = signature_set
        result = eidas._verify_signature(signature, doc_hash, cert_hash)
        assert result["valid"] is True

    def test_tampered_document_rejected(self, signature_set):
        """Changing the document must invalidate the signature."""
        _, signature, cert_hash = signature_set
        tampered_hash = eidas._compute_document_hash("Hello eIDAS world!")
        result = eidas._verify_signature(signature, tampered_hash, cert_hash)
        assert result["valid"] is False
        assert "verif" in result["reason"].lower() or "invalid" in result["reason"].lower()

    def test_garbage_signature_rejected(self, signature_set):
        doc_hash, _, cert_hash = signature_set
        result = eidas._verify_signature("a" * 64, doc_hash, cert_hash)
        assert result["valid"] is False

    def test_unknown_certificate_rejected(self, signature_set):
        doc_hash, signature, _ = signature_set
        result = eidas._verify_signature(signature, doc_hash, "de" * 32)
        assert result["valid"] is False

    def test_old_hole_closed_random_cert_hash_invalid(self):
        """A random 64-char hash used to be accepted as a valid certificate."""
        assert eidas._validate_cert_chain("f" * 64)["valid"] is False

    def test_empty_inputs(self):
        assert eidas._verify_signature("", "x" * 64, "")["valid"] is False
        assert eidas._verify_signature("sig" * 16, "", "")["valid"] is False


class TestDocumentHash:
    def test_sha256(self):
        assert eidas._compute_document_hash("a") == "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb"

    def test_unknown_algorithm_falls_back_to_sha256(self):
        assert eidas._compute_document_hash("a", "SHA-999") == "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb"