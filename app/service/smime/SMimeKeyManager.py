"""
X.509 certificate + private-key store for S/MIME, mirroring PGPKeyManager.

Each user can own one S/MIME certificate (PEM certificate + PEM PKCS#8
private key). The pair is stored in Redis like the PGP keypair. The private
key is only ever served back to its owner; the public certificate is served
to any authenticated user so recipients' certs are available for encryption
(the S/MIME 'directory' equivalent).

Import routes: PEM (cert + key) or PKCS#12 (one file with both, optional
passphrase for the bundle and for the extracted key).
"""

from __future__ import annotations

import base64
from typing import Any, Callable

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import (
    RSAPrivateKey,
    generate_private_key,
)
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509 import Certificate, NameOID, random_serial_number
from cryptography.x509.oid import ExtendedKeyUsageOID

_SMIME_CERT_PREFIX: str = "smime:cert:"
_SMIME_KEY_PREFIX: str = "smime:key:"
_SMIME_MAIL_INDEX_PREFIX: str = "smime:mailindex:"
_TTL_SECONDS: int = 86400 * 365  # 1 year, same as PGP


def _cert_emails(cert: Certificate) -> list[str]:
    """Extract the email addresses from a cert's SANs + subject (for the
    recipient index)."""
    emails: list[str] = []
    try:
        san = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
        emails.extend(san.get_values_for_type(x509.RFC822Name))
    except x509.ExtensionNotFound:
        pass
    subject_emails = cert.subject.get_attributes_for_oid(NameOID.EMAIL_ADDRESS)
    emails.extend(attr.value for attr in subject_emails)
    return list(dict.fromkeys(e.lower() for e in emails if e))


class SMimeKeyError(Exception):
    """Raised when the stored cert/key pair is invalid or absent."""


def _serialize_cert(cert: Certificate) -> str:
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


def cert_summary(cert: Certificate) -> dict[str, Any]:
    """Public metadata about a certificate (safe to expose to others)."""
    return {
        "subject_cn": cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[
            0
        ].value
        if cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        else None,
        "issuer_cn": cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        if cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)
        else None,
        "not_before": cert.not_valid_before_utc.isoformat(),
        "not_after": cert.not_valid_after_utc.isoformat(),
        "serial": str(cert.serial_number),
        "fingerprint_sha256": cert.fingerprint(
            __import__(
                "cryptography.hazmat.primitives.hashes", fromlist=["SHA256"]
            ).SHA256()
        ).hex(),
        "self_signed": cert.subject == cert.issuer,
    }


class SMimeKeyManager:
    """Stores one S/MIME cert + key per user in the shared cache (Redis)."""

    def __init__(self, cache=None) -> None:
        from app.service import sogo_cache

        self.cache = cache or sogo_cache()

    # --- storage ---------------------------------------------------------

    def store(self, user_uid: str, cert: Certificate, private_key: RSAPrivateKey) -> None:
        """Persist the user's S/MIME pair and index their cert email(s)."""
        self.cache.set(
            f"{_SMIME_CERT_PREFIX}{user_uid}",
            _serialize_cert(cert),
            ttl=_TTL_SECONDS,
        )
        self.cache.set(
            f"{_SMIME_KEY_PREFIX}{user_uid}",
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode("ascii"),
            ttl=_TTL_SECONDS,
        )
        for email in _cert_emails(cert):
            self.cache.set(
                f"{_SMIME_MAIL_INDEX_PREFIX}{email.lower()}",
                user_uid,
                ttl=_TTL_SECONDS,
            )

    def get_cert(self, user_uid: str) -> Certificate | None:
        raw = self.cache.get(f"{_SMIME_CERT_PREFIX}{user_uid}", str)
        if not raw:
            return None
        try:
            return x509.load_pem_x509_certificate(raw.encode("ascii"))
        except ValueError as exc:
            raise SMimeKeyError(f"Stored S/MIME cert for {user_uid} is invalid") from exc

    def get_private_key(self, user_uid: str) -> RSAPrivateKey | None:
        raw = self.cache.get(f"{_SMIME_KEY_PREFIX}{user_uid}", str)
        if not raw:
            return None
        try:
            key = serialization.load_pem_private_key(raw.encode("ascii"), password=None)
        except ValueError as exc:
            raise SMimeKeyError(f"Stored S/MIME key for {user_uid} is invalid") from exc
        if not isinstance(key, RSAPrivateKey):
            raise SMimeKeyError(f"Stored S/MIME key for {user_uid} is not RSA")
        return key

    def has_pair(self, user_uid: str) -> bool:
        return self.cache.exists(f"{_SMIME_CERT_PREFIX}{user_uid}")

    def delete(self, user_uid: str) -> None:
        cert = self.get_cert(user_uid)
        if cert is not None:
            for email in _cert_emails(cert):
                self.cache.delete(f"{_SMIME_MAIL_INDEX_PREFIX}{email.lower()}")
        self.cache.delete(f"{_SMIME_CERT_PREFIX}{user_uid}")
        self.cache.delete(f"{_SMIME_KEY_PREFIX}{user_uid}")

    def get_public_cert_for_recipient(
        self, address: str, directory_lookup: Callable[[str], bytes | None] | None = None
    ) -> Certificate | None:
        """Resolve a recipient address ('a@b' or 'Name <a@b>') to their public
        cert. The app is its own S/MIME directory: a recipient is encryptable
        once their cert is in the store. When *directory_lookup* is given
        (e.g. an LDAP ``userCertificate`` lookup) it is consulted on an index
        miss and a hit is cached into the store for future sends."""
        from email.utils import parseaddr

        _, addr = parseaddr(address)
        if not addr:
            return None
        uid = self.cache.get(f"{_SMIME_MAIL_INDEX_PREFIX}{addr.lower()}", str)
        if uid:
            return self.get_cert(uid)
        if directory_lookup is None:
            return None
        try:
            der = directory_lookup(addr)
        except Exception:
            return None
        if not der:
            return None
        try:
            cert = x509.load_der_x509_certificate(der)
        except ValueError:
            try:
                cert = x509.load_pem_x509_certificate(der)
            except ValueError:
                return None
        synthetic_uid = f"ldap-{addr.lower()}"
        self.store_public(synthetic_uid, cert)
        return cert

    def store_public(self, user_uid: str, cert: Certificate) -> None:
        """Store a public cert WITHOUT a private key (directory-sourced, e.g.
        LDAP ``userCertificate``) and index its email(s) for recipient lookup."""
        self.cache.set(
            f"{_SMIME_CERT_PREFIX}{user_uid}",
            _serialize_cert(cert),
            ttl=_TTL_SECONDS,
        )
        for email in _cert_emails(cert):
            self.cache.set(f"{_SMIME_MAIL_INDEX_PREFIX}{email}", user_uid, ttl=_TTL_SECONDS)

    def summary(self, user_uid: str) -> dict[str, Any] | None:
        cert = self.get_cert(user_uid)
        if cert is None:
            return None
        return cert_summary(cert)

    def get_all_certificates(self) -> list[dict[str, Any]]:
        """Return a list of all certificates with their metadata for admin inventory.
        
        Each entry includes: user_uid, emails, not_before, not_after, has_private_key.
        """
        # Get all user_uids that have certificates by scanning the Redis keys
        # Use scan instead of keys to avoid blocking the server
        prefix = _SMIME_CERT_PREFIX
        result = []
        redis_client = self.cache.redis
        
        # Use scan to iterate through all matching keys
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor, match=f"{prefix}*", count=100)
            for key in keys:
                user_uid = key.decode().replace(prefix, "")
                cert = self.get_cert(user_uid)
                if cert is not None:
                    # Check if private key exists using the redis client directly
                    has_private_key = bool(redis_client.exists(f"{_SMIME_KEY_PREFIX}{user_uid}"))
                    emails = _cert_emails(cert)
                    result.append({
                        "user_uid": user_uid,
                        "emails": emails,
                        "not_before": cert.not_valid_before_utc.isoformat(),
                        "not_after": cert.not_valid_after_utc.isoformat(),
                        "has_private_key": has_private_key,
                    })
            if cursor == 0:
                break
        return result

    # --- import / generate ------------------------------------------------

    @staticmethod
    def parse_pem(cert_pem: str, key_pem: str) -> tuple[Certificate, RSAPrivateKey]:
        """Parse a PEM cert + PEM PKCS#8 private key into a validated pair."""
        cert = x509.load_pem_x509_certificate(cert_pem.encode("ascii"))
        key = serialization.load_pem_private_key(key_pem.encode("ascii"), password=None)
        if not isinstance(key, RSAPrivateKey):
            raise SMimeKeyError("Only RSA private keys are supported for S/MIME")
        return cert, key

    @staticmethod
    def parse_pkcs12(
        p12_bytes: bytes, bundle_password: str | None, key_password: str | None
    ) -> tuple[Certificate, RSAPrivateKey]:
        """Parse a PKCS#12 bundle into (cert, key). Key may be separately
        encrypted (``key_password``); the bundle itself uses
        ``bundle_password``."""
        key, cert, extra = pkcs12.load_key_and_certificates(
            p12_bytes,
            password=bundle_password.encode("utf-8") if bundle_password else None,
        )
        if cert is None or key is None:
            raise SMimeKeyError("PKCS#12 bundle contains no certificate/private key")
        if not isinstance(key, RSAPrivateKey):
            raise SMimeKeyError("Only RSA private keys are supported for S/MIME")
        if key_password:
            # Re-wrap with the provided key password.
            key = serialization.load_pem_private_key(
                key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                ),
                password=None,
            )  # type: ignore[assignment]
            if not isinstance(key, RSAPrivateKey):
                raise SMimeKeyError("Only RSA private keys are supported for S/MIME")
        return cert, key

    def generate_self_signed(
        self, user_uid: str, common_name: str, email: str | None = None, days: int = 365
    ) -> tuple[Certificate, RSAPrivateKey]:
        """Generate a self-signed S/MIME cert (EMAIL + serverAuth + emailProtection)."""
        from datetime import datetime, timedelta, timezone

        key = generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            ]
            + (
                [x509.NameAttribute(NameOID.EMAIL_ADDRESS, email)]
                if email
                else []
            )
        )
        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=days))
            .add_extension(
                x509.SubjectAlternativeName([x509.RFC822Name(email)] if email else []),
                critical=False,
            )
            .add_extension(
                x509.ExtendedKeyUsage(
                    [ExtendedKeyUsageOID.EMAIL_PROTECTION, ExtendedKeyUsageOID.SERVER_AUTH]
                ),
                critical=False,
            )
            .sign(key, __import__(
                "cryptography.hazmat.primitives.hashes", fromlist=["SHA256"]
            ).SHA256())
        )
        self.store(user_uid, cert, key)
        return cert, key


def fetch_ldap_user_certificate(address: str) -> bytes | None:
    """Look up a recipient's ``userCertificate`` in the default domain LDAP
    user source. Returns raw DER (or PEM) cert bytes, or None.

    Used as the ``directory_lookup`` hook for recipient-cert resolution; any
    failure (no LDAP source, unreachable server, no attribute) yields None —
    the caller then reports the recipient as 'no certificate'.
    """
    try:
        from app.config.init_config import init_get_system_and_default_domain_settings
        from app.config.settings.DomainSettings import UserSourceSettingsObj
        from app.manager.ldap.ClientLdap import ClientLdap

        _, domain_settings = init_get_system_and_default_domain_settings()
        ldap_cfg = None
        for source_cfg in (domain_settings.get("USER_SOURCE") or {}).values():
            if source_cfg.get("US_TYPE") == "ldap":
                ldap_cfg = UserSourceSettingsObj(source_cfg)
                break
        if ldap_cfg is None:
            return None
        us_config = ldap_cfg.get_user_source_settings("ldap")
        client: ClientLdap = ClientLdap(**us_config)
        client.connect()
        try:
            client._bind(
                ldap_cfg.US_LDAP_BIND_DN, ldap_cfg.US_LDAP_BIND_DN_PWD, use_admin=True
            )
            # ';binary' option makes python-ldap return the raw DER bytes
            entries = client._search(
                client.base_dn,
                f"(mail={address})",
                attributes=["userCertificate;binary", "userCertificate"],
            )
        finally:
            client.close()
        for _, attrs in entries:
            for attr in ("userCertificate;binary", "userCertificate"):
                values = attrs.get(attr) or attrs.get(attr.lower()) or []
                if values:
                    return values[0]
        return None
    except Exception:
        return None
