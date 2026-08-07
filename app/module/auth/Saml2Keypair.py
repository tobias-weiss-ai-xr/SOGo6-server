"""SAML2 SP keypair management.

Loads the SP's X.509 certificate and private key from configurable file paths.
The keypair is used for:
  1. Signing AuthnRequests
  2. Decrypting encrypted assertions
  3. Including the certificate in SP metadata

If the files do not exist, the module operates in unsigned mode and logs a warning.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.config.settings.ProcessSetting import ProcessSetting


class Saml2Keypair:
    """Manage the SP X.509 certificate and private key."""

    def __init__(self, process: ProcessSetting) -> None:
        self._cert_file = process.SOGO_SAML2_SP_CERT_FILE
        self._key_file = process.SOGO_SAML2_SP_KEY_FILE
        self._cert: str | None = None
        self._key: str | None = None
        self._loaded = False

    def load_keypair(self) -> tuple[str | None, str | None]:
        """Load the SP certificate and private key from disk.

        :returns: ``(cert_pem, key_pem)`` — either may be ``None`` if the file
            does not exist or is empty.
        """
        if self._loaded:
            return self._cert, self._key

        cert_pem: str | None = None
        key_pem: str | None = None

        # Load certificate
        if self._cert_file and os.path.isfile(self._cert_file):
            try:
                with open(self._cert_file, "r", encoding="utf-8") as f:
                    cert_pem = f.read().strip()
                if cert_pem and "BEGIN CERTIFICATE" not in cert_pem:
                    logger_api.warning("SAML2 SP cert file %s does not contain a PEM certificate", self._cert_file)
                    cert_pem = None
            except OSError as exc:
                logger_api.warning("SAML2 SP cert file %s could not be read: %s", self._cert_file, exc)
        else:
            logger_api.debug("SAML2 SP cert file not found: %s", self._cert_file)

        # Load private key
        if self._key_file and os.path.isfile(self._key_file):
            try:
                with open(self._key_file, "r", encoding="utf-8") as f:
                    key_pem = f.read().strip()
                if key_pem and "PRIVATE KEY" not in key_pem:
                    logger_api.warning("SAML2 SP key file %s does not contain a PEM private key", self._key_file)
                    key_pem = None
            except OSError as exc:
                logger_api.warning("SAML2 SP key file %s could not be read: %s", self._key_file, exc)
        else:
            logger_api.debug("SAML2 SP key file not found: %s", self._key_file)

        self._cert = cert_pem
        self._key = key_pem
        self._loaded = True

        if not self.is_configured():
            logger_api.warning(
                "SAML2 SP keypair not configured — AuthnRequests will not be signed, "
                "encrypted assertions not supported. Generate with: "
                "openssl req -x509 -newkey rsa:2048 -keyout sp-key.pem -out sp-cert.pem "
                "-days 3650 -nodes -subj \"/CN=sogo-sp\""
            )

        return self._cert, self._key

    def is_configured(self) -> bool:
        """Return True if both cert and key are available."""
        if not self._loaded:
            self.load_keypair()
        return self._cert is not None and self._key is not None

    @property
    def cert(self) -> str | None:
        """Return the SP certificate PEM, or None."""
        if not self._loaded:
            self.load_keypair()
        return self._cert

    @property
    def key(self) -> str | None:
        """Return the SP private key PEM, or None."""
        if not self._loaded:
            self.load_keypair()
        return self._key

    def get_cert_b64(self) -> str | None:
        """Return the SP certificate as base64 (no headers/newlines), or None.

        Used for embedding in SAML metadata ``<ds:X509Certificate>`` elements.
        """
        cert = self.cert
        if not cert:
            return None
        # Strip PEM headers and newlines
        lines = cert.splitlines()
        b64_lines = [line for line in lines if line and not line.startswith("-----")]
        return "".join(b64_lines)
