"""eIDAS / Qualified Electronic Signatures (#69) — EU compliance market.

Sign documents with qualified electronic signatures per EU Regulation 910/2014.
Timestamp Authority (TSA) integration, certificate chain validation,
document hash verification.

**Honesty contract**: this backend signs and verifies with real asymmetric
cryptography (RSA-2048 / SHA-256). It does *not* however talk to a real EU
Trusted Service Provider (QSCD/TSA), so responses carry ``mode: "simulated-tsp"``
until a TSP integration is configured (see ``SOGO_EIDAS_SIGN_KEY``). Nothing
in this module pretends a hash-chain is a signature.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from flask import request
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.service import sogo_cache
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

blp = Blueprint("eIDAS Signatures", __name__, url_prefix="/admin/eidas")

_SIG_PFX = "eidas_sig:"
_CERT_PFX = "eidas_cert:"
_SIGN_KEY_PFX = "eidas_signing_key:"

# Demo trust roots (kept for listing & POC only — NOT a real EU TSL).
_TSA_ROOT_HASH = hashlib.sha256("eidas-tsa-root-2024".encode()).hexdigest()
_QES_ROOT_HASH = hashlib.sha256("eidas-qes-root-2024".encode()).hexdigest()


def _compute_document_hash(content: str, algorithm: str = "SHA-256") -> str:
    """Hash document content for signing."""
    if algorithm == "SHA-256":
        return hashlib.sha256(content.encode()).hexdigest()
    elif algorithm == "SHA-384":
        return hashlib.sha384(content.encode()).hexdigest()
    elif algorithm == "SHA-512":
        return hashlib.sha512(content.encode()).hexdigest()
    return hashlib.sha256(content.encode()).hexdigest()


def _get_signing_key() -> rsa.RSAPrivateKey:
    """Load the RSA signing key from ``SOGO_EIDAS_SIGN_KEY`` (base64 PKCS#8).

    When unset, an ephemeral key is generated for this process and persisted
    in the app cache so the public key stays discoverable for verification
    while the backend runs. Persist ``SOGO_EIDAS_SIGN_KEY`` for stable
    signatures across restarts.
    """
    env_key = os.environ.get("SOGO_EIDAS_SIGN_KEY", "")
    if env_key:
        try:
            return serialization.load_pem_private_key(
                base64.b64decode(env_key), password=None
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger_api.error("Invalid SOGO_EIDAS_SIGN_KEY, ignoring: %s", exc)

    cache = sogo_cache()
    raw = cache.get(f"{_SIGN_KEY_PFX}default", str)
    if raw:
        try:
            return serialization.load_pem_private_key(raw.encode(), password=None)
        except Exception as exc:  # pylint: disable=broad-except
            logger_api.warning("Cached eIDAS key unusable, generating new: %s", exc)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cache.set(f"{_SIGN_KEY_PFX}default", pem.decode("utf-8"), ttl=86400 * 365)
    return key


def _public_fingerprint(key: rsa.RSAPrivateKey) -> str:
    """SHA-256 fingerprint of the DER public key (used as certificate hash)."""
    der = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()


def _register_self_issued_cert(key: rsa.RSAPrivateKey) -> str:
    """Register the backend's own signing key as a (demo) trust certificate.

    This makes sign→verify round-trips work out of the box while keeping the
    trust list explicit: anything else must be registered via ``/certificates``.

    :return: The certificate hash (fingerprint) just registered.
    :rtype: str
    """
    fp = _public_fingerprint(key)
    cache = sogo_cache()
    if cache.get(f"{_CERT_PFX}{fp}", str):
        return fp
    cert = {
        "hash": fp,
        "type": "QES",
        "name": "SOGo eIDAS signing key (self-issued demo)",
        "country": "demo",
        "valid": True,
        "expires": time.time() + 86400 * 365,
        "registered_at": time.time(),
        "on_eu_tsl": False,
    }
    cache.set(f"{_CERT_PFX}{fp}", json.dumps(cert), ttl=86400 * 365 * 7)
    return fp


def _sign_document(document_hash: str, key: rsa.RSAPrivateKey) -> str:
    """Return a base64 RSA-2048 PKCS#1 v1.5 signature over the digest bytes."""
    signature = key.sign(
        bytes.fromhex(document_hash),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def _create_timestamp_token(document_hash: str, key: rsa.RSAPrivateKey) -> dict:
    """Create an RFC 3161-style timestamp token signed by the TSA key.

    The token is a real cryptographic signature over ``document_hash``,
    timestamp and nonce, so it cannot be forged without the key.
    """
    ts = time.time()
    nonce = secrets.token_hex(8)
    payload = f"tsa:{document_hash}:{ts}:{nonce}".encode("utf-8")
    token = base64.b64encode(key.sign(payload, padding.PKCS1v15(), hashes.SHA256())).decode("utf-8")
    return {
        "token": token,
        "timestamp": ts,
        "tsa_policy": "1.3.6.1.4.1.311.21.4",
        "tsa_name": "SOGo Timestamp Authority (simulated TSP)",
        "serial_number": secrets.token_hex(16),
    }


def _verify_signature(signature: str, document_hash: str, cert_hash: str = "") -> dict:
    """Verify an eIDAS signature against the document hash using the
    configured signing key. No heuristic accepts garbage.

    :return: ``{"valid": bool, "reason": str, "timestamp": float}``
    :rtype: dict
    """
    try:
        if not signature or len(signature) < 32:
            return {"valid": False, "reason": "Invalid signature format", "timestamp": time.time()}
        if not document_hash or len(document_hash) != 64:
            return {"valid": False, "reason": "Invalid document hash", "timestamp": time.time()}
        try:
            sig_bytes = base64.b64decode(signature, validate=True)
        except Exception as exc:
            return {"valid": False, "reason": f"Malformed signature: {exc}", "timestamp": time.time()}

        key = _get_signing_key()
        try:
            key.public_key().verify(
                sig_bytes,
                bytes.fromhex(document_hash),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except InvalidSignature:
            return {"valid": False, "reason": "Signature does not verify against document", "timestamp": time.time()}
        except Exception as exc:  # pylint: disable=broad-except
            logger_api.warning("eIDAS verification error: %s", exc)
            return {"valid": False, "reason": "Verification could not be performed", "timestamp": time.time()}

        chain = _validate_cert_chain(cert_hash)
        if not chain["valid"]:
            return {"valid": False, "reason": "Certificate not on the trust list", "timestamp": time.time()}

        return {"valid": True, "reason": "Signature verified (RSA-2048/SHA-256)", "timestamp": time.time()}
    except Exception as exc:  # pylint: disable=broad-except
        logger_api.error("Unexpected verification failure: %s", exc)
        return {"valid": False, "reason": "Internal verification error", "timestamp": time.time()}


def _validate_cert_chain(cert_hash: str) -> dict:
    """Validate a certificate hash against the registered trust list.

    Only certificates explicitly registered via ``/certificates`` (or the two
    built-in demo roots) are accepted. A random 64-char string is **not** valid.
    """
    if not cert_hash:
        return {"valid": False, "certificate_type": "unknown", "country": "", "provider": "", "expires": 0}

    cache = sogo_cache()
    raw = cache.get(f"{_CERT_PFX}{cert_hash}", str)
    if raw:
        try:
            return json.loads(raw)
        except Exception as exc:  # pylint: disable=broad-except
            logger_api.warning("Corrupt certificate record %s: %s", cert_hash, exc)

    if cert_hash in (_TSA_ROOT_HASH, _QES_ROOT_HASH):
        return {
            "valid": True,
            "on_eu_tsl": False,  # demo roots are NOT on the real EU TSL
            "certificate_type": "QES" if cert_hash == _QES_ROOT_HASH else "TSA",
            "country": "demo",
            "provider": "SOGo-eIDAS",
            "expires": time.time() + 86400 * 365,
        }
    return {"valid": False, "certificate_type": "unknown", "country": "", "provider": "unknown", "expires": 0}


@blp.route("/sign")
class EidasSign(MethodView):
    def post(self) -> ResponseReturnValue:
        body = request.get_json(force=True)
        content = body.get("content", "")
        signer_email = body.get("signer_email", "")
        cert_hash = body.get("certificate_hash", "")
        algorithm = body.get("algorithm", "SHA-256")
        if not content or not signer_email:
            return create_api_base_response(error_code="E000003", error_msg="content and signer_email required", success=False)

        key = _get_signing_key()
        doc_hash = _compute_document_hash(content, algorithm)
        timestamp = _create_timestamp_token(doc_hash, key)
        sig = _sign_document(doc_hash, key)

        cache = sogo_cache()
        sig_id = secrets.token_hex(12)
        record = {
            "id": sig_id,
            "document_hash": doc_hash,
            "signature": sig,
            "signer": signer_email,
            "certificate_hash": cert_hash or _register_self_issued_cert(key),
            "algorithm": algorithm,
            "signature_algorithm": "RSA-2048 PKCS#1 v1.5 / SHA-256",
            "timestamp": timestamp,
            "created_at": time.time(),
            "mode": "eid-tsp-simulated",
        }
        cache.set(f"{_SIG_PFX}{sig_id}", json.dumps(record), ttl=86400 * 365 * 7)

        logger_api.info("eIDAS signature created: %s by %s", sig_id, signer_email)
        return create_api_base_response(data=record)


@blp.route("/verify")
class EidasVerify(MethodView):
    def post(self) -> ResponseReturnValue:
        body = request.get_json(force=True)
        signature = body.get("signature", "")
        document_hash = body.get("document_hash", "")
        cert_hash = body.get("certificate_hash", "")
        if not signature:
            return create_api_base_response(error_code="E000003", error_msg="signature required", success=False)
        result = _verify_signature(signature, document_hash, cert_hash)
        return create_api_base_response(data=result)


@blp.route("/certificates")
class EidasCertificates(MethodView):
    def get(self) -> ResponseReturnValue:
        certs = [
            {"hash": _TSA_ROOT_HASH, "type": "TSA", "name": "SOGo TSA Root 2024 (demo)", "country": "demo", "valid": True, "on_eu_tsl": False},
            {"hash": _QES_ROOT_HASH, "type": "QES", "name": "SOGo QES Root 2024 (demo)", "country": "demo", "valid": True, "on_eu_tsl": False},
        ]
        return create_api_base_response(data=certs)

    def post(self) -> ResponseReturnValue:
        """Register a new trust service certificate."""
        body = request.get_json(force=True)
        cert_hash = body.get("hash", "")
        cert_type = body.get("type", "QES")
        name = body.get("name", "")
        if not cert_hash or not name:
            return create_api_base_response(error_code="E000003", error_msg="hash and name required", success=False)
        cert = {
            "hash": cert_hash,
            "type": cert_type,
            "name": name,
            "country": body.get("country", "EU"),
            "valid": True,
            "expires": time.time() + 86400 * 365,
            "registered_at": time.time(),
        }
        cache = sogo_cache()
        cache.set(f"{_CERT_PFX}{cert_hash}", json.dumps(cert), ttl=86400 * 365 * 7)
        return create_api_base_response(data=cert)


@blp.route("/signatures")
class EidasSignatureList(MethodView):
    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        idx = list(cache.get(f"{_SIG_PFX}index", list) or [])
        records = []
        for sid in idx:
            raw = cache.get(f"{_SIG_PFX}{sid}", str)
            if raw:
                records.append(json.loads(raw))
        return create_api_base_response(data=records)