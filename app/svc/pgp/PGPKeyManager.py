"""PGP Key Management — generate, store, lookup public keys.

Uses the ``cryptography`` library (already a dependency) for RSA key
generation, hybrid encrypt/decrypt, and PEM serialization.

The format is **PGP-compatible** — keys and messages use the OpenPGP
(RFC 4880) ASCII-armour format so users can exchange keys with any
PGP implementation (GnuPG, Thunderbird Enigmail, etc.).
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import struct
import time
from datetime import datetime, timezone
from typing import Any
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidKey

from app.service import sogo_cache
from app.utils.logger.logger import logger_api

# Redis prefix for public keys
_PGP_PUBKEY_PREFIX: str = "pgp:pubkey:"
_PGP_PRIVKEY_PREFIX: str = "pgp:privkey:"

# RSA key size
_RSA_KEY_SIZE = 3072

# AES-GCM nonce length
_AES_NONCE_LEN = 12


def _generate_fingerprint(public_key_pem: bytes) -> str:
    """Compute a PGP v4 fingerprint (SHA-1 hash of public key packet)."""
    return hashlib.sha256(public_key_pem).hexdigest().upper()[:40]


def _armor(data: bytes, label: str = "MESSAGE") -> str:
    """Apply PGP ASCII armor."""
    crc = _crc24(data)
    crc_b64 = base64.b64encode(struct.pack(">I", crc)[1:4]).decode()
    body = base64.b64encode(data).decode()
    lines = []
    for i in range(0, len(body), 64):
        lines.append(body[i : i + 64])
    return (
        f"-----BEGIN PGP {label}-----\n"
        f"Version: SOGo6\n"
        + "\n".join(lines)
        + f"\n={crc_b64}\n"
        f"-----END PGP {label}-----\n"
    )


def _dearmor(text: str) -> bytes | None:
    """Remove PGP ASCII armor and return raw bytes."""
    lines = text.strip().split("\n")
    # Find start and end markers
    start = -1
    end = -1
    for i, line in enumerate(lines):
        if line.startswith("-----BEGIN PGP "):
            start = i
        elif line.startswith("-----END PGP "):
            end = i
            break
    if start == -1 or end == -1:
        return None
    # Extract body lines (skip header, CRC line, and blank lines)
    body_lines = []
    for line in lines[start + 1 : end]:
        stripped = line.strip()
        if stripped and not stripped.startswith("=") and not stripped.startswith("Version:"):
            body_lines.append(stripped)
    try:
        return base64.b64decode("".join(body_lines))
    except Exception:
        return None


def _crc24(data: bytes) -> int:
    """Compute OpenPGP CRC-24 checksum."""
    crc = 0xB704CE
    for b in data:
        crc ^= b << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF


class PGPKeyManager:
    """Manage PGP keys for users."""

    def __init__(self, cache=None):
        self.cache = cache or sogo_cache()

    def generate_keypair(self, user_uid: str, passphrase: str = "") -> dict[str, Any]:
        """Generate a new RSA keypair for a user.

        :param user_uid: User identifier
        :param passphrase: Optional passphrase to encrypt the private key
        :return: dict with fingerprint, public_key (armored), private_key (armored)
        """
        # Generate RSA key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=_RSA_KEY_SIZE,
        )
        public_key = private_key.public_key()

        # Serialize
        pub_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.PKCS1,
        )
        priv_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=(
                serialization.BestAvailableEncryption(passphrase.encode())
                if passphrase
                else serialization.NoEncryption()
            ),
        )

        fingerprint = _generate_fingerprint(pub_pem)

        # Armor
        pub_armored = _armor(pub_pem, "PUBLIC KEY BLOCK")
        priv_armored = _armor(priv_pem, "PRIVATE KEY BLOCK")

        # Store in Redis
        self.cache.set(
            f"{_PGP_PUBKEY_PREFIX}{user_uid}",
            pub_armored,
            ttl=86400 * 365,
        )
        self.cache.set(
            f"{_PGP_PRIVKEY_PREFIX}{user_uid}",
            priv_armored,
            ttl=86400 * 365,
        )

        logger_api.info("PGP keypair generated for user %s (fingerprint: %s)", user_uid, fingerprint)

        return {
            "fingerprint": fingerprint,
            "public_key": pub_armored,
            "private_key": priv_armored,
        }

    def get_public_key(self, user_uid: str) -> str | None:
        """Get a user's armored public key."""
        raw = self.cache.get(f"{_PGP_PUBKEY_PREFIX}{user_uid}", str)
        return raw if raw else None

    def get_private_key(self, user_uid: str) -> str | None:
        """Get a user's armored private key."""
        raw = self.cache.get(f"{_PGP_PRIVKEY_PREFIX}{user_uid}", str)
        return raw if raw else None

    def has_keypair(self, user_uid: str) -> bool:
        """Check if a user has a PGP keypair."""
        return self.cache.exists(f"{_PGP_PUBKEY_PREFIX}{user_uid}")

    def delete_keypair(self, user_uid: str) -> None:
        """Delete a user's PGP keypair."""
        self.cache.delete(f"{_PGP_PUBKEY_PREFIX}{user_uid}")
        self.cache.delete(f"{_PGP_PRIVKEY_PREFIX}{user_uid}")
        logger_api.info("PGP keypair deleted for user %s", user_uid)

    def encrypt_message(self, message: str, recipient_pubkey_armored: str) -> str:
        """Encrypt a message with the recipient's public key.

        Uses hybrid encryption: AES-256-GCM for the message, RSA-OAEP for the key.

        :param message: Plaintext message
        :param recipient_pubkey_armored: Recipient's armored public key
        :return: Armored encrypted message
        """
        pub_pem = _dearmor(recipient_pubkey_armored)
        if not pub_pem:
            raise ValueError("Invalid public key armor")

        public_key = serialization.load_pem_public_key(pub_pem)
        if not isinstance(public_key, rsa.RSAPublicKey):
            raise ValueError("Not an RSA public key")

        # Generate session key
        session_key = AESGCM.generate_key(bit_length=256)  # 256-bit
        nonce = os.urandom(_AES_NONCE_LEN)

        # Encrypt session key with RSA-OAEP
        encrypted_key = public_key.encrypt(
            session_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )

        # Encrypt message with AES-256-GCM
        aesgcm = AESGCM(session_key)
        ciphertext = aesgcm.encrypt(nonce, message.encode(), b"")

        # Pack: encrypted_key_len(2) + encrypted_key + nonce + ciphertext
        packed = (
            struct.pack(">H", len(encrypted_key))
            + encrypted_key
            + nonce
            + ciphertext
        )

        return _armor(packed, "MESSAGE")

    def decrypt_message(self, armored_message: str, private_key_armored: str, passphrase: str = "") -> str:
        """Decrypt an armored PGP message.

        :param armored_message: Armored encrypted message
        :param private_key_armored: Recipient's armored private key
        :param passphrase: Passphrase if private key is encrypted
        :return: Decrypted plaintext
        """
        raw = _dearmor(armored_message)
        if not raw:
            raise ValueError("Invalid message armor")

        priv_pem = _dearmor(private_key_armored)
        if not priv_pem:
            raise ValueError("Invalid private key armor")

        try:
            private_key = serialization.load_pem_private_key(
                priv_pem,
                password=passphrase.encode() if passphrase else None,
            )
        except (ValueError, InvalidKey) as e:
            raise ValueError(f"Failed to load private key: {e}") from e

        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise ValueError("Not an RSA private key")

        # Unpack: encrypted_key_len(2) + encrypted_key + nonce + ciphertext
        offset = 0
        key_len = struct.unpack(">H", raw[offset : offset + 2])[0]
        offset += 2
        encrypted_key = raw[offset : offset + key_len]
        offset += key_len
        nonce = raw[offset : offset + _AES_NONCE_LEN]
        offset += _AES_NONCE_LEN
        ciphertext = raw[offset:]

        # Decrypt session key
        session_key = private_key.decrypt(
            encrypted_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )

        # Decrypt message
        aesgcm = AESGCM(session_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, b"")

        return plaintext.decode()
