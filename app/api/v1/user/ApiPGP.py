"""PGP End-to-End Encryption API — key generation, management, encrypt/decrypt."""
from __future__ import annotations

from typing import TYPE_CHECKING

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.service.pgp.PGPKeyManager import PGPKeyManager
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User

blp = Blueprint("PGP Encryption", __name__, url_prefix="/pgp")


class PGPKeyResponseSchema(Schema):
    fingerprint = fields.String()
    public_key = fields.String()


class PGPKeyGenerateSchema(Schema):
    passphrase = fields.String(load_default="", metadata={"description": "Optional passphrase for the private key"})


class PGPEncryptSchema(Schema):
    message = fields.String(required=True, metadata={"description": "Plaintext message to encrypt"})
    recipient = fields.String(required=True, metadata={"description": "Recipient email or user UID"})


class PGPDecryptSchema(Schema):
    armored_message = fields.String(required=True, metadata={"description": "Armored encrypted message"})


@blp.route("/key/generate")
class ApiPGPGenerate(MethodView):
    """Generate a new PGP keypair."""

    @blp.arguments(PGPKeyGenerateSchema)
    def post(self, data: dict) -> ResponseReturnValue:
        """Generate a new PGP keypair for the current user."""
        user: User = g.user
        manager = PGPKeyManager()

        if manager.has_keypair(user.uid):
            return create_api_base_response(None, err.ERROR_PGP_KEY_ALREADY_EXISTS)

        result = manager.generate_keypair(user.uid, passphrase=data.get("passphrase", ""))
        logger_api.info("PGP key generated for user %s", user.uid)
        return create_api_base_response(result, code=201)


@blp.route("/key")
class ApiPGPGetKey(MethodView):
    """Get the current user's PGP public key."""

    def get(self) -> ResponseReturnValue:
        """Return the user's PGP public key info."""
        user: User = g.user
        manager = PGPKeyManager()

        pubkey = manager.get_public_key(user.uid)
        if not pubkey:
            return create_api_base_response(None, err.ERROR_PGP_KEY_NOT_FOUND)

        # Determine fingerprint from stored key
        try:
            from app.service.pgp.PGPKeyManager import _generate_fingerprint
            from app.service.pgp.PGPKeyManager import _dearmor
            pem = _dearmor(pubkey)
            fingerprint = _generate_fingerprint(pem) if pem else ""
        except Exception:
            fingerprint = ""

        return create_api_base_response({
            "fingerprint": fingerprint,
            "public_key": pubkey,
        })


@blp.route("/key")
class ApiPGPDeleteKey(MethodView):
    """Delete the current user's PGP keypair."""

    def delete(self) -> ResponseReturnValue:
        """Delete the user's PGP keypair."""
        user: User = g.user
        manager = PGPKeyManager()
        manager.delete_keypair(user.uid)
        logger_api.info("PGP key deleted for user %s", user.uid)
        return create_api_base_response({"status": "deleted"})


@blp.route("/encrypt")
class ApiPGPEncrypt(MethodView):
    """Encrypt a message with a recipient's public key."""

    @blp.arguments(PGPEncryptSchema)
    def post(self, data: dict) -> ResponseReturnValue:
        """Encrypt a message for a recipient."""
        manager = PGPKeyManager()

        # Look up recipient's public key
        recipient_uid = data["recipient"]
        pubkey = manager.get_public_key(recipient_uid)
        if not pubkey:
            return create_api_base_response(None, err.ERROR_PGP_RECIPIENT_KEY_NOT_FOUND)

        try:
            encrypted = manager.encrypt_message(data["message"], pubkey)
            return create_api_base_response({"encrypted": encrypted})
        except (ValueError, Exception) as e:
            logger_api.error("PGP encrypt failed: %s", e)
            return create_api_base_response(None, err.ERROR_PGP_ENCRYPT_FAILED)


@blp.route("/decrypt")
class ApiPGPDecrypt(MethodView):
    """Decrypt a message with the user's private key."""

    @blp.arguments(PGPDecryptSchema)
    def post(self, data: dict) -> ResponseReturnValue:
        """Decrypt an armored message."""
        user: User = g.user
        manager = PGPKeyManager()

        privkey = manager.get_private_key(user.uid)
        if not privkey:
            return create_api_base_response(None, err.ERROR_PGP_KEY_NOT_FOUND)

        try:
            decrypted = manager.decrypt_message(data["armored_message"], privkey)
            return create_api_base_response({"plaintext": decrypted})
        except ValueError as e:
            return create_api_base_response(None, err.ERROR_PGP_DECRYPT_FAILED)
