"""
Utility module for AES-256 encryption/decryption of sensitive data
"""
import os
import base64
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from app.utils.errors import ERROR_INVALID_ENCRYPTED_DATA
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger

SOGO_AES_ENC_KEY = os.environ.get('SOGO_AES_ENC_KEY', None)

def get_encryption_key() -> bytes:
    """
    Get the AES encryption key from environment or generate a default one
    
    :return: 32 bytes key for AES-256
    :rtype: bytes
    """
    if SOGO_AES_ENC_KEY:
        try:
            return base64.b64decode(SOGO_AES_ENC_KEY)
        except Exception:
            # If it's a raw string, convert it
            return SOGO_AES_ENC_KEY.encode('utf-8').ljust(32)[:32]
    else:
        raise ValueError("Encryption key not set in environment variable 'SOGO_AES_ENC_KEY'")


def encrypt_password(password: str) -> str:
    """
    Encrypt a password using AES-256-CBC
    
    :param password: Plain text password
    :type password: str
    :return: Base64 encoded encrypted password with IV prepended
    :rtype: str
    """
    if not password:
        return ""

    # Generate a random 16-byte IV
    iv = os.urandom(16)

    # Get encryption key
    key = get_encryption_key()

    # Create cipher
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()

    # PKCS7 padding to align with AES block size (128 bits = 16 bytes)
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(password.encode('utf-8')) + padder.finalize()

    # Encrypt
    encrypted = encryptor.update(padded_data) + encryptor.finalize()

    # Return IV + encrypted data in base64
    return base64.b64encode(iv + encrypted).decode('utf-8')


def decrypt_password(encrypted_password: str, account_id: str | None = None) -> str:
    """
    Decrypt a password using AES-256-CBC

    :param encrypted_password: Base64 encoded encrypted password with IV prepended
    :type encrypted_password: str
    :param account_id: Optional identifier of the account being decrypted, used for logging
    :type account_id: str | None
    :return: Plain text password
    :rtype: str
    """
    if not encrypted_password:
        return ""

    try:
        encrypted_data = base64.b64decode(encrypted_password, validate=True)
    except Exception:
        # Don't log sensitive information - use generic error
        logger.error("Failed to base64 decode encrypted password")
        raise RequestException(error=ERROR_INVALID_ENCRYPTED_DATA)

    try:
        # Extract IV (first 16 bytes)
        iv = encrypted_data[:16]
        encrypted = encrypted_data[16:]

        # Get encryption key
        key = get_encryption_key()

        # Create cipher
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()

        # Decrypt
        decrypted_padded = decryptor.update(encrypted) + decryptor.finalize()

        # Remove padding
        unpadder = padding.PKCS7(128).unpadder()
        decrypted = unpadder.update(decrypted_padded) + unpadder.finalize()

        return decrypted.decode('utf-8')
    except Exception:
        # In case of decryption error, use generic message to avoid leaking info
        raise ValueError("Failed to decrypt password")


def _derive_key(salt: bytes, info: bytes) -> bytes:
    """Derive a 32-byte AES key from the master key via HKDF-SHA256.

    Used to scope keys per context (e.g. per recipient for at-rest PHI).

    :param salt: HKDF salt (e.g. recipient identifier)
    :type salt: bytes
    :param info: HKDF context label
    :type info: bytes
    :return: 32-byte derived key
    :rtype: bytes
    """
    master = get_encryption_key()
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=info,
    ).derive(master)


def encrypt_gcm(plaintext: str, context: str = "default") -> str:
    """Encrypt data with authenticated AES-256-GCM.

    Key is derived from ``SOGO_AES_ENC_KEY`` via HKDF scoped by *context*
    (e.g. recipient email), so data for different contexts uses different keys.

    Output format (base64): ``version(1) || nonce(12) || tag(16) || ciphertext``

    :param plaintext: UTF-8 text to encrypt
    :type plaintext: str
    :param context: HKDF context (recipient / data owner)
    :type context: str
    :return: Base64-encoded authenticated ciphertext
    :rtype: str
    :raises ValueError: If the master encryption key is not configured
    """
    if not plaintext:
        return ""
    key = _derive_key(context.encode("utf-8"), b"sogo-at-rest-gcm-v1")
    nonce = os.urandom(12)
    encryptor = Cipher(
        algorithms.AES(key), modes.GCM(nonce), backend=default_backend()
    ).encryptor()
    ciphertext = encryptor.update(plaintext.encode("utf-8")) + encryptor.finalize()
    return base64.b64encode(b"\x01" + nonce + encryptor.tag + ciphertext).decode("utf-8")


def decrypt_gcm(encrypted: str, context: str = "default") -> str:
    """Decrypt and verify data produced by :func:`encrypt_gcm`.

    :param encrypted: Base64 payload produced by :func:`encrypt_gcm`
    :type encrypted: str
    :param context: HKDF context used during encryption
    :type context: str
    :return: Original plaintext
    :rtype: str
    :raises ValueError: On corrupted data, wrong key, or unsupported version
    """
    if not encrypted:
        return ""
    try:
        raw = base64.b64decode(encrypted, validate=True)
    except Exception as exc:
        raise ValueError("Invalid base64 payload") from exc
    if len(raw) < 1 + 12 + 16:
        raise ValueError("Payload too short")
    version, nonce, tag, ciphertext = raw[0], raw[1:13], raw[13:29], raw[29:]
    if version != 0x01:
        raise ValueError(f"Unsupported encryption version 0x{version:02x}")
    key = _derive_key(context.encode("utf-8"), b"sogo-at-rest-gcm-v1")
    try:
        decryptor = Cipher(
            algorithms.AES(key), modes.GCM(nonce, tag), backend=default_backend()
        ).decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    except Exception as exc:
        # GCM raises InvalidTag on wrong key or tampered data
        raise ValueError("Decryption failed or data corrupted") from exc
    return plaintext.decode("utf-8")
