"""
S/MIME (RFC 5751 / CMS) signing and encryption for outgoing mail.

Design decisions (deliberately small and correct):

* **Signing** produces the standard ``multipart/signed`` + detached
  ``application/pkcs7-signature`` layout (RFC 5751 §3.2). The first part
  carries the exact canonical CRLF bytes that were signed — the body text is
  assembled byte-for-byte so the signature validates against the received part
  without re-serialization drift.

* **Encryption** produces the modern single-part
  ``application/pkcs7-mime; smime-type=enveloped-data`` layout (RFC 5751 §3.4 /
  RFC 8551), the form Thunderbird/Outlook emit and accept. ``cryptography``
  only implements PKCS7 *signing*, so enveloped-data is done with the OpenSSL 3
  CLI shipped in the image (``openssl smime -encrypt|-decrypt -outform DER``).
  Test verification uses the same CLI (``-verify -content`` + ``-decrypt``),
  proving OpenSSL interop.

* Keys/certificates are user-owned X.509 (see ``SMimeKeyManager``). Signing
  needs only the sender's own pair. Encryption needs one public cert per
  recipient (served by the SMIME public-cert endpoint). No external CA needed
  — self-signed certs verify with a trust warning, like SOGo5 S/MIME.

The module is pure apart from the OpenSSL subprocess, so unit tests run
without Redis or a database.
"""

from __future__ import annotations

import base64
import subprocess
import uuid
from email import message_from_bytes
from email.message import Message
from email.policy import SMTP
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509 import Certificate

DEFAULT_DIGEST = hashes.SHA256
MICALG = "sha-256"  # matches DEFAULT_DIGEST

# Outer headers copied verbatim from the inner message (order preserved).
COPIED_HEADERS = (
    "From",
    "To",
    "Cc",
    "Bcc",
    "Reply-To",
    "Subject",
    "Message-ID",
    "Date",
    "X-Priority",
    "In-Reply-To",
    "References",
)


class SMimeError(Exception):
    """Raised for any S/MIME operation failure."""


def canonical_bytes(message: Message) -> bytes:
    """Serialize a MIME message in canonical CRLF form (RFC 5751 §3.1).

    ``policy.SMTP`` emits CRLF line endings and no trailing whitespace, which
    is the canonical form required before signing an S/MIME entity.
    """
    return message.as_bytes(policy=SMTP)


def build_detached_pkcs7(
    content: bytes,
    cert: Certificate,
    private_key: RSAPrivateKey,
    digest_algorithm: type[hashes.HashAlgorithm] = DEFAULT_DIGEST,
) -> bytes:
    """Build a detached CMS/PKCS7 signature (DER) over *content*."""
    return (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(content)
        .add_signer(cert, private_key, digest_algorithm())
        .sign(
            serialization.Encoding.DER,
            [pkcs7.PKCS7Options.Binary, pkcs7.PKCS7Options.DetachedSignature],
        )
    )


def _assemble_multipart_signed(
    inner: bytes, sig_der: bytes, boundary: str
) -> bytes:
    """Byte-exact assembly of ``multipart/signed`` (RFC 5751 §3.2).

    Built as raw bytes so the signed part 1 is transmitted verbatim. The
    signature is detached base64 DER in an ``application/pkcs7-signature``
    part, exactly like Thunderbird/Outlook.
    """
    sig_b64 = base64.b64encode(sig_der).decode("ascii")
    lines = [
        f"Content-Type: multipart/signed; "
        f'protocol="application/pkcs7-signature"; micalg="{MICALG}"; '
        f'boundary="{boundary}"',
        "",
    ]
    # Ensure canonical CRLF everywhere.
    head = ("\r\n".join(lines) + "\r\n").encode("ascii")
    body = (
        f"--{boundary}\r\n".encode("ascii")
        + inner
        + b"\r\n"
        + f"--{boundary}\r\n".encode("ascii")
        + (
            'Content-Type: application/pkcs7-signature; name="smime.p7s"; '
            'smime-type=signed-data\r\n'
            "Content-Transfer-Encoding: base64\r\n"
            'Content-Disposition: attachment; filename="smime.p7s"\r\n'
            "\r\n"
            + sig_b64
            + "\r\n"
            + f"--{boundary}--\r\n"
        ).encode("ascii")
    )
    return head + body


def build_signed_message(
    message: Message,
    cert: Certificate,
    private_key: RSAPrivateKey,
    *,
    boundary: str | None = None,
) -> Message:
    """Wrap *message* into ``multipart/signed`` with a detached PKCS7 signature.

    The signed part carries the exact canonical bytes of *message*. Returns a
    parsed ``EmailMessage`` ready for delivery.
    """
    inner = canonical_bytes(message)
    sig_der = build_detached_pkcs7(inner, cert, private_key)
    boundary = boundary or f"=sogo-smime-{uuid.uuid4().hex}=="
    raw = _assemble_multipart_signed(inner, sig_der, boundary)

    # Move the outer headers that apply to the whole (signed) entity onto the
    # multipart root; headers of *content* (part 1) stay in the signed bytes.
    outer = message_from_bytes(raw, policy=SMTP)
    for header in COPIED_HEADERS:
        if message[header] and not outer[header]:
            outer[header] = message[header]
    return outer


def _run_openssl(*args: str) -> bytes:
    """Run the OpenSSL CLI, returning stdout or raising :class:`SMimeError`."""
    proc = subprocess.run(
        ["openssl", *args],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SMimeError(
            "openssl %s failed: %s"
            % (" ".join(args[:2]), proc.stderr.decode("utf-8", "replace").strip())
        )
    return proc.stdout


def build_encrypted_message(
    message: Message,
    recipient_certs: list[Certificate],
) -> Message:
    """Encrypt *message* to *recipient_certs* (single-part enveloped-data).

    Uses ``openssl smime -encrypt`` (AES-256-CBC) and wraps the DER enveloped
    data in a base64 ``application/pkcs7-mime; smime-type=enveloped-data``
    part, the RFC 5751/8551 form.
    """
    inner = canonical_bytes(message)
    if not recipient_certs:
        raise SMimeError("S/MIME encryption needs at least one recipient certificate")
    cert_pems = [
        cert.public_bytes(serialization.Encoding.PEM) for cert in recipient_certs
    ]
    der = _openssl_encrypt(inner, cert_pems)

    b64 = base64.b64encode(der).decode("ascii")
    raw = (
        'Content-Type: application/pkcs7-mime; smime-type=enveloped-data; '
        'name="smime.p7m"\r\n'
        "Content-Transfer-Encoding: base64\r\n"
        'Content-Disposition: attachment; filename="smime.p7m"\r\n'
        "\r\n"
        + b64
        + "\r\n"
    )
    return message_from_bytes(raw.encode("ascii"), policy=SMTP)


def _openssl_encrypt(inner: bytes, cert_pems: list[bytes]) -> bytes:
    """Run ``openssl smime -encrypt -outform DER`` with per-recipient certs.

    Certificates are passed via a single temp dir; ``-certfile`` is not used so
    the recipient set is exactly ``-encrypt``'s cert list.
    """
    import tempfile
    import os

    cert_paths: list[str] = []
    tmpdir = tempfile.mkdtemp(prefix="sogo6-smime-")
    try:
        for i, pem in enumerate(cert_pems):
            p = os.path.join(tmpdir, f"cert-{i}.pem")
            with open(p, "wb") as fh:
                fh.write(pem)
            cert_paths.append(p)
        proc = subprocess.run(
            [
                "openssl", "smime", "-encrypt", "-aes-256-cbc",
                "-inform", "SMIME", "-outform", "DER", *cert_paths,
            ],
            input=inner,
            capture_output=True,
            check=False,
        )
    finally:
        for p in cert_paths:
            try:
                os.unlink(p)
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass
    if proc.returncode != 0:
        raise SMimeError(
            "openssl smime -encrypt failed: %s"
            % proc.stderr.decode("utf-8", "replace").strip()
        )
    return proc.stdout


def decrypt_message(payload: bytes, private_key_pem: bytes) -> bytes:
    """Decrypt a DER enveloped-data blob with a PEM private key (openssl CLI)."""
    import tempfile
    import os

    fd, key_path = tempfile.mkstemp(prefix="sogo6-smime-key-", suffix=".pem")
    with os.fdopen(fd, "wb") as fh:
        fh.write(private_key_pem)
    try:
        proc = subprocess.run(
            ["openssl", "smime", "-decrypt", "-inform", "DER", "-inkey", key_path],
            input=payload,
            capture_output=True,
            check=False,
        )
    finally:
        try:
            os.unlink(key_path)
        except OSError:
            pass
    if proc.returncode != 0:
        raise SMimeError(
            "openssl smime -decrypt failed: %s"
            % proc.stderr.decode("utf-8", "replace").strip()
        )
    return proc.stdout


def decrypt_enveloped_message(
    message: Message, private_key_pem: bytes
) -> Message | None:
    """Decrypt a single-part ``application/pkcs7-mime`` enveloped-data message.

    Returns the decrypted inner :class:`~email.message.Message`, or None when
    the message isn't enveloped-data or decryption fails.
    """
    if message.get_content_type() not in (
        "application/pkcs7-mime",
        "application/x-pkcs7-mime",
    ):
        return None
    # 'enveloped-data' may appear quoted after a parse round-trip
    # (smime-type="enveloped-data"), so match the value only.
    if "enveloped-data" not in str(message.get("Content-Type", "")):
        return None
    payload = message.get_payload(decode=True)
    if not payload:
        return None
    try:
        inner = decrypt_message(payload, private_key_pem)
    except SMimeError:
        return None
    try:
        return message_from_bytes(inner, policy=SMTP)
    except Exception:
        return None


def verify_detached_signature(sig_der: bytes, content: bytes) -> bool:
    """Verify a detached PKCS7 signature over *content* using the OpenSSL CLI.

    Returns True when the signature is cryptographically valid (the signer's
    *certificate identity* is NOT checked here — trust anchoring is a separate
    concern, like every S/MIME client that shows "certificate not trusted").
    """
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".der", delete=False) as sig_fh:
        sig_fh.write(sig_der)
        sig_path = sig_fh.name
    with tempfile.NamedTemporaryFile(delete=False) as content_fh:
        content_fh.write(content)
        content_path = content_fh.name
    try:
        proc = subprocess.run(
            [
                "openssl",
                "smime",
                "-verify",
                "-inform",
                "DER",
                "-in",
                sig_path,
                "-content",
                content_path,
                "-noverify",
            ],
            capture_output=True,
            check=False,
        )
        return proc.returncode == 0
    finally:
        import os

        os.unlink(sig_path)
        os.unlink(content_path)


def verify_signed_message(message: Message) -> dict[str, Any] | None:
    """Verify a ``multipart/signed`` message's detached PKCS7 signature.

    Returns ``None`` when *message* is not a ``multipart/signed``; otherwise a
    dict with ``valid`` (signature cryptographically verifies), and when the
    signature embeds the signer certificate, ``signer_cn`` / ``signer_email``
    / ``certificate`` (a :class:`Certificate`). Trust anchoring is NOT checked
    (like every S/MIME client that reports a signature as "ok but untrusted").
    """
    if message.get_content_type() != "multipart/signed":
        return None
    try:
        parts = message.get_payload()
    except (AttributeError, TypeError):
        return None
    if not isinstance(parts, list) or len(parts) < 2:
        return None
    content_part, sig_part = parts[0], parts[1]
    if sig_part.get_content_type() not in (
        "application/pkcs7-signature",
        "application/x-pkcs7-signature",
        "application/pgp-signature",
    ):
        return None
    if "pkcs7" not in sig_part.get_content_type():
        return None

    # The signature covers the canonical (CRLF, no trailing whitespace) form
    # of the content entity — exactly the bytes ``policy.SMTP`` emits.
    content = canonical_bytes(content_part)
    sig_der = sig_part.get_payload(decode=True)
    if not sig_der:
        return None

    valid = verify_detached_signature(sig_der, content)
    result: dict[str, Any] = {"valid": valid}
    try:
        from cryptography.hazmat.primitives.serialization import pkcs7 as _pkcs7

        signer_certs = _pkcs7.load_der_pkcs7_certificates(sig_der)
        if signer_certs:
            cert = signer_certs[0]
            from cryptography.x509 import NameOID

            cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
            result["signer_cn"] = cn[0].value if cn else None
            eml = cert.subject.get_attributes_for_oid(NameOID.EMAIL_ADDRESS)
            result["signer_email"] = eml[0].value if eml else None
            result["certificate"] = cert
    except Exception:
        pass  # signer-cert metadata is best-effort; validity already computed
    return result
