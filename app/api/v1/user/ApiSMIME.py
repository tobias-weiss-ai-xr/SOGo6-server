"""S/MIME Certificate API — manage the user's X.509 S/MIME pair.

Endpoints:
* ``GET  /smime/certificate``        — status of the caller's own cert
* ``POST /smime/certificate``        — import a PEM (cert+key) or PKCS#12 pair
* ``POST /smime/certificate/generate`` — generate a self-signed S/MIME cert
* ``DELETE /smime/certificate``      — remove the caller's pair
* ``GET  /smime/certificate/<address>`` — public cert metadata for a recipient
  (used by the encryption directory)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from cryptography.hazmat.primitives import serialization as _ser

from app.service.smime.SMimeKeyManager import (
    SMimeKeyError,
    SMimeKeyManager,
    cert_summary,
    fetch_ldap_user_certificate,
)
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User

blp = Blueprint("SMIME Certificates", __name__, url_prefix="/smime")


class SMimeImportSchema(Schema):
    cert_pem = fields.String(required=False, metadata={"description": "PEM certificate (mutually exclusive with bundle)"})
    key_pem = fields.String(required=False, metadata={"description": "PEM PKCS#8 private key (with cert_pem)"})
    bundle = fields.String(required=False, metadata={"description": "Base64 PKCS#12 bundle (mutually exclusive with PEM fields)"})
    bundle_password = fields.String(required=False, load_default="", metadata={"description": "Password of the PKCS#12 bundle"})
    key_password = fields.String(required=False, load_default="", metadata={"description": "Optional separate password for the private key"})
    common_name = fields.String(required=False, load_default="", metadata={"description": "CN for self-signed generation"})
    days = fields.Integer(required=False, load_default=365, metadata={"description": "Validity of a self-signed cert in days"})


@blp.route("/certificate")
class ApiSMimeCertificate(MethodView):
    """Own S/MIME certificate management."""

    @blp.response(200)
    def get(self) -> ResponseReturnValue:
        """Return the caller's S/MIME cert status (or null when absent)."""
        user: User = g.user
        manager = SMimeKeyManager()
        return create_api_base_response({"certificate": manager.summary(user.uid)})

    @blp.arguments(SMimeImportSchema)
    @blp.response(200)
    def post(self, data: dict) -> ResponseReturnValue:
        """Import a PEM or PKCS#12 S/MIME pair."""
        user: User = g.user
        manager = SMimeKeyManager()
        try:
            if data.get("bundle"):
                import base64

                try:
                    p12 = base64.b64decode(data["bundle"])
                except Exception as exc:
                    raise RequestException(
                        "Invalid base64 in PKCS#12 bundle",
                        error=err.ERROR_SMIME_INVALID_BUNDLE,
                    ) from exc
                cert, key = SMimeKeyManager.parse_pkcs12(
                    p12, data.get("bundle_password") or None, data.get("key_password") or None
                )
            else:
                if not data.get("cert_pem") or not data.get("key_pem"):
                    raise RequestException(
                        "Provide either cert_pem+key_pem or a PKCS#12 bundle",
                        error=err.ERROR_SMIME_INVALID_BUNDLE,
                    )
                cert, key = SMimeKeyManager.parse_pem(data["cert_pem"], data["key_pem"])
                # ensure the pair matches (public key of cert == public key of key)
                cert_pub = cert.public_key().public_bytes(
                    _ser.Encoding.DER, _ser.PublicFormat.SubjectPublicKeyInfo
                )
                key_pub = key.public_key().public_bytes(
                    _ser.Encoding.DER, _ser.PublicFormat.SubjectPublicKeyInfo
                )
                if cert_pub != key_pub:
                    raise RequestException(
                        "Certificate and private key do not match",
                        error=err.ERROR_SMIME_KEY_MISMATCH,
                    )
            manager.store(user.uid, cert, key)
        except SMimeKeyError as exc:
            raise RequestException(str(exc), error=err.ERROR_SMIME_INVALID_PARSE) from exc
        logger_api.info("User %s imported an S/MIME certificate", user.uid)
        return create_api_base_response({"certificate": cert_summary(cert)})

    @blp.response(200)
    def delete(self) -> ResponseReturnValue:
        """Remove the caller's S/MIME pair."""
        user: User = g.user
        SMimeKeyManager().delete(user.uid)
        return create_api_base_response({"status": "deleted"})


@blp.route("/certificate/generate")
class ApiSMimeGenerate(MethodView):
    """Generate a self-signed S/MIME certificate (no CA required)."""

    @blp.arguments(SMimeImportSchema)
    @blp.response(200)
    def post(self, data: dict) -> ResponseReturnValue:
        user: User = g.user
        manager = SMimeKeyManager()
        cn = data.get("common_name") or user.cn or user.uid
        cert, _ = manager.generate_self_signed(
            user.uid, cn, user.mail or None, days=data.get("days") or 365
        )
        logger_api.info("User %s generated an S/MIME self-signed cert", user.uid)
        return create_api_base_response({"certificate": cert_summary(cert)})


@blp.route("/certificate/<string:address>")
class ApiSMimeRecipient(MethodView):
    """Public S/MIME cert lookup for a recipient (encryption directory)."""

    @blp.response(200)
    def get(self, address: str) -> ResponseReturnValue:
        user: User = g.user
        manager = SMimeKeyManager()
        cert = manager.get_public_cert_for_recipient(
            address, directory_lookup=fetch_ldap_user_certificate
        )
        return create_api_base_response(
            {"certificate": cert_summary(cert) if cert else None}
        )
