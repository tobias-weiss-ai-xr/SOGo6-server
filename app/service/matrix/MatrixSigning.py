"""Matrix Server-Server v2 Ed25519 signing (replaces fake HMAC).

Matrix federation uses Ed25519 keys (not HMAC) to sign PDUs (event JSON)
with Ed25519 over canonical JSON (sorted keys, no-whitespace separators).

Reference: https://matrix.org/docs/spec/server_server/v2#authentication

This module provides Ed25519 key pair generation, seed-based determinism,
and signing/verification for outgoing PDUs. The private seed is kept
secret (stored encrypted at rest), the public key is served via
/_matrix/key/v2/server for federation.

Migration: legacy hex seeds (from the old HMAC era) are auto-detected and
converted to raw 32-byte form for Ed25519.
"""
from __future__ import annotations

import base64
import binascii
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization


# Matrix uses SHA-512 for reference hashes; Ed25519 uses SHA-512 under the hood
CANONICAL = {"sort_keys": True, "separators": (",", ":")}


def _decode_seed(seed: str) -> bytes:
    """Decode a seed string to raw bytes.

    Accepts:
    - base64url string (with/without padding)
    - hex string (for migration from the old HMAC token)
    Returns the 32-byte raw seed for Ed25519.
    """
    # Try hex first (migration path)
    try:
        raw = binascii.unhexlify(seed)
        if len(raw) == 32:
            return raw
    except Exception:  # pylint: disable=broad-except
        pass

    # Try base64url / base64
    try:
        # base64url decoding (no padding)
        missing = 4 - len(seed) % 4
        padded = seed + ("=" * missing)
        raw = base64.urlsafe_b64decode(padded)
        if len(raw) == 32:
            return raw
        # Standard base64 if urlsafe fails
        raw = base64.b64decode(padded)
        if len(raw) == 32:
            return raw
    except Exception:  # pylint: disable=broad-except
        pass

    raise ValueError(f"Seed string could not be decoded to a valid 32-byte Ed25519 seed: {seed[:20]}...")


class MatrixSigningKey:
    """Ed25519 key pair for Matrix Server-Server v2 signing.

    Initialise from a 32-byte seed passed as:
      - base64url-encoded string (preferred, stored in Redis)
      - hex string (auto-detected, migration path from old HMAC tokens)
      - None → fresh random key pair generated
    """

    def __init__(self, seed_str: str | None = None) -> None:
        if seed_str:
            seed = _decode_seed(seed_str)
            self._private = Ed25519PrivateKey.from_private_bytes(seed)
        else:
            self._private = Ed25519PrivateKey.generate()

    # ------------------------------------------------------------
    @property
    def private_seed_b64(self) -> str:
        """Base64url-encoded 32-byte seed for persistent storage."""
        raw = self._private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @property
    def public_key_b64(self) -> str:
        """Base64-encoded public key bytes (Ed25519, 32 bytes)."""
        raw = self._private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.b64encode(raw).decode()

    @property
    def key_id(self) -> str:
        """Matrix key identifier: 'ed25519:' + base64 public key."""
        return f"ed25519:{self.public_key_b64}"

    # ------------------------------------------------------------
    def sign_pdu(self, event: dict) -> str:
        """Sign a Matrix PDU (event dict) as Server-Server v2.

        Canonicalises the JSON, then signs with Ed25519. Returns
        the raw Ed25519 signature (64 bytes) as base64 string.
        """
        canonical = json.dumps(event, **CANONICAL).encode()
        signature = self._private.sign(canonical)
        return base64.b64encode(signature).decode()

    def verify_pdu(self, event: dict, signature_b64: str) -> bool:
        """Verify a Server-Server v2 PDU signature against our public key."""
        try:
            canonical = json.dumps(event, **CANONICAL).encode()
            sig = base64.b64decode(signature_b64)
            self._private.public_key().verify(sig, canonical)
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def reference_hash(self, event: dict) -> str:
        """Compute the Matrix reference hash (SHA-512 of canonical JSON) for a PDU."""
        import hashlib as _hl
        canonical = json.dumps(event, **CANONICAL).encode()
        return _hl.sha512(canonical).hexdigest()


# ------------------------------------------------------------
# Convenience functions
# ------------------------------------------------------------
def sign_matrix_event(event: dict, seed_b64: str) -> str:
    """Sign a Matrix PDU using an Ed25519 seed stored as base64/hex string.

    This is the replacement for the former HMAC-SHA256 fake.
    """
    signer = MatrixSigningKey(seed_b64)
    return signer.sign_pdu(event)


def generate_matrix_signing_key() -> MatrixSigningKey:
    """Generate a fresh Ed25519 Matrix signing key pair."""
    return MatrixSigningKey()
