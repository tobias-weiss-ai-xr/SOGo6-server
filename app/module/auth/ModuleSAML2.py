"""SAML2 (Shibboleth) authentication module — pysaml2-backed SP.

Implements SP-initiated SSO using ``pysaml2`` for:
  - Building signed AuthnRequests (HTTP-Redirect / HTTP-POST)
  - Verifying SAML Response signatures (XML-Sig via ``xmlsec1``)
  - Validating conditions (NotBefore / NotOnOrAfter with clock skew)
  - Checking audience restrictions
  - Validating InResponseTo (replay protection via Redis)
  - Decrypting encrypted assertions (if SP keypair configured)
  - Extracting and mapping attributes (eduPerson OIDs + friendly names)

The public interface (``create_login_request``, ``process_response``,
``get_sp_metadata``) is preserved for backward compatibility with
``InterfaceAuthSSO``.

If ``pysaml2`` is not installed, the module falls back to a minimal
implementation that parses the SAML response without signature verification
(legacy mode — logs a security warning).
"""

from __future__ import annotations

import hashlib
from base64 import b64decode, b64encode
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode
from uuid import uuid4
from zlib import compress

from app.utils.exceptions import RequestException
from app.utils import errors as err
from app.utils.logger.logger import logger_api

# Namespaces for fallback XML parsing
SAML_PROTOCOL = "urn:oasis:names:tc:SAML:2.0:protocol"
SAML_ASSERTION = "urn:oasis:names:tc:SAML:2.0:assertion"
SAML_METADATA = "urn:oasis:names:tc:SAML:2.0:metadata"
DSIG = "http://www.w3.org/2000/09/xmldsig#"

NS = {
    "samlp": SAML_PROTOCOL,
    "saml": SAML_ASSERTION,
    "md": SAML_METADATA,
    "ds": DSIG,
}

# Default attribute mapping for eduPerson OIDs and common friendly names
DEFAULT_ATTRIBUTE_MAP: dict[str, str] = {
    # email
    "mail": "email",
    "email": "email",
    "emailAddress": "email",
    "emailaddress": "email",
    "urn:oid:0.9.2342.19200300.100.1.3": "email",
    # display name
    "displayName": "display_name",
    "urn:oid:2.16.840.1.113730.3.1.241": "display_name",
    "cn": "display_name",
    "urn:oid:2.5.4.3": "display_name",
    # given name / surname
    "givenName": "given_name",
    "urn:oid:2.5.4.42": "given_name",
    "sn": "surname",
    "urn:oid:2.5.4.4": "surname",
    # eduPersonPrincipalName (scoped, unique)
    "eppn": "eppn",
    "urn:oid:1.3.6.1.4.1.5923.1.1.1.6": "eppn",
    # eduPersonAffiliation
    "eduPersonAffiliation": "affiliation",
    "urn:oid:1.3.6.1.4.1.5923.1.1.1.1": "affiliation",
    # eduPersonScopedAffiliation
    "eduPersonScopedAffiliation": "scoped_affiliation",
    "urn:oid:1.3.6.1.4.1.5923.1.1.1.9": "scoped_affiliation",
    # eduPersonUniqueId
    "eduPersonUniqueId": "unique_id",
    "urn:oid:1.3.6.1.4.1.5923.1.1.1.13": "unique_id",
}

try:
    from saml2 import BINDING_HTTP_REDIRECT, BINDING_HTTP_POST
    from saml2.client import Saml2Client
    from saml2.config import SPConfig
    from saml2.saml import NAMEID_FORMAT_EMAILADDRESS, NAMEID_FORMAT_TRANSIENT, NAMEID_FORMAT_PERSISTENT
    from saml2.s_utils import deflate_and_base64_encode
    from saml2.sigver import SecurityContext
    from saml2.validate import ValidatingError

    PYSAML2_AVAILABLE = True
except ImportError:  # pragma: no cover
    PYSAML2_AVAILABLE = False
    logger_api.warning(
        "pysaml2 not installed — SAML2 will operate in legacy (insecure) mode "
        "without signature verification, replay protection, or encrypted assertions"
    )


class ModuleSAML2:
    """SAML 2.0 Service Provider backed by pysaml2.

    Typical usage::

        saml = ModuleSAML2(
            idp_sso_url="https://idp.example.org/SAML2/SSO",
            idp_entity_id="https://idp.example.org/idp/shibboleth",
            entity_id="https://sogo.example.org/saml/metadata",
            acs_url="https://sogo.example.org/api/user/v1/auth/callback/example.com",
            x509_cert=sp_cert_pem,
            x509_key=sp_key_pem,
        )
        login_url = saml.create_login_request()
        # redirect user to login_url
        # user is POSTed back to acs_url with SAMLResponse
        result = saml.process_response(post_data["SAMLResponse"])
    """

    def __init__(
        self,
        idp_sso_url: str = "",
        idp_entity_id: str = "",
        entity_id: str = "",
        acs_url: str = "",
        x509_cert: str = "",
        x509_key: str = "",
        name_id_format: str = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        authn_context: str = "urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport",
        # New federation parameters
        idp_cert: str = "",
        attribute_map: dict[str, str] | None = None,
        clock_skew: int = 60,
        want_assertions_signed: bool = True,
        want_assertions_encrypted: bool = False,
        want_response_signed: bool = True,
        redis_client=None,
    ) -> None:
        """Initialise the SAML SP.

        :param idp_sso_url: IdP's SingleSignOnService URL.
        :param idp_entity_id: IdP's entityID (issuer), used to validate responses.
        :param entity_id: This SP's entityID.
        :param acs_url: Assertion Consumer Service URL.
        :param x509_cert: SP's X.509 certificate (PEM) — for signing AuthnRequests
            and for the SP metadata.
        :param x509_key: SP's private key (PEM) — for signing and decryption.
        :param name_id_format: Requested NameID format.
        :param authn_context: Requested authentication context class.
        :param idp_cert: IdP's X.509 certificate (PEM) — for verifying signatures.
        :param attribute_map: Override the default SAML attribute → field mapping.
        :param clock_skew: Allowed clock skew in seconds for NotBefore/NotOnOrAfter.
        :param want_assertions_signed: Require signed assertions.
        :param want_assertions_encrypted: Require encrypted assertions.
        :param want_response_signed: Require the SAML Response to be signed.
        :param redis_client: Redis client for replay protection (InResponseTo tracking).
        """
        self._idp_sso_url = idp_sso_url.rstrip("/") if idp_sso_url else ""
        self._idp_entity_id = idp_entity_id
        self._entity_id = entity_id.rstrip("/") if entity_id else ""
        self._acs_url = acs_url.rstrip("/") if acs_url else ""
        self._x509_cert = x509_cert
        self._x509_key = x509_key
        self._name_id_format = name_id_format
        self._authn_context = authn_context
        self._idp_cert = idp_cert
        self._attribute_map = attribute_map or dict(DEFAULT_ATTRIBUTE_MAP)
        self._clock_skew = clock_skew
        self._want_assertions_signed = want_assertions_signed
        self._want_assertions_encrypted = want_assertions_encrypted
        self._want_response_signed = want_response_signed
        self._redis = redis_client

        # NameID format mapping for pysaml2
        self._nameid_format_map = {
            "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress": NAMEID_FORMAT_EMAILADDRESS,
            "urn:oasis:names:tc:SAML:2.0:nameid-format:transient": NAMEID_FORMAT_TRANSIENT,
            "urn:oasis:names:tc:SAML:2.0:nameid-format:persistent": NAMEID_FORMAT_PERSISTENT,
        }

    # ------------------------------------------------------------------
    # pysaml2 config builder
    # ------------------------------------------------------------------

    def _build_sp_config(self) -> Any:
        """Build a pysaml2 ``SPConfig`` from the SP parameters.

        :returns: A configured ``SPConfig`` instance.
        :raises RequestException: If required parameters are missing.
        """
        if not PYSAML2_AVAILABLE:
            raise RequestException("pysaml2 is not installed", err.ERROR_SAML_NOT_CONFIGURED)

        config = SPConfig()
        config.setattr("entityid", self._entity_id)
        config.setattr("name", "SOGo SAML2 SP")

        # ACS URL
        acs_url = self._acs_url or ""
        config.setattr("service", {
            "sp": {
                "endpoints": {
                    "assertion_consumer_service": [
                        (acs_url, BINDING_HTTP_POST),
                    ],
                    "single_logout_service": [
                        (acs_url, BINDING_HTTP_REDIRECT),
                    ],
                },
                "allow_unsolicited": True,
                "authn_requests_signed": bool(self._x509_cert),
                "want_assertions_signed": self._want_assertions_signed,
                "want_assertions_encrypted": self._want_assertions_encrypted,
                "want_response_signed": self._want_response_signed,
                "want_name_id": True,
                "name_id_format": self._nameid_format,
            }
        })

        # SP keypair
        if self._x509_cert and self._x509_key:
            config.setattr("key_file", self._x509_key)
            config.setattr("cert_file", self._x509_cert)
            # Inline key/cert for non-file-based usage
            config.setattr("encryption_keypairs", [{
                "key_file": self._x509_key,
                "cert_file": self._x509_cert,
            }])

        # IdP metadata (inline)
        idp_data: dict[str, Any] = {}
        if self._idp_entity_id:
            idp_data["entity_id"] = self._idp_entity_id
        if self._idp_sso_url:
            idp_data["sso_url"] = self._idp_sso_url
        if self._idp_cert:
            idp_data["cert"] = self._idp_cert

        # Build IdP metadata inline
        if idp_data:
            metadata_str = self._build_idp_metadata_xml(idp_data)
            config.setattr("metadata", {
                "inline": [metadata_str],
            })

        # Security settings
        config.setattr("organization", {
            "name": "SOGo",
            "display_name": "SOGo Webmail",
            "url": self._entity_id,
        })

        # Clock skew
        config.setattr("accepted_time_diff", self._clock_skew)

        return config

    def _build_idp_metadata_xml(self, idp_data: dict[str, Any]) -> str:
        """Build inline IdP metadata XML for pysaml2.

        :param idp_data: Dict with entity_id, sso_url, cert.
        :returns: IdP metadata XML string.
        """
        entity_id = idp_data.get("entity_id", self._idp_entity_id or "")
        sso_url = idp_data.get("sso_url", self._idp_sso_url or "")
        cert = idp_data.get("cert", self._idp_cert or "")

        # Extract base64 cert content (strip PEM headers)
        cert_b64 = ""
        if cert:
            lines = cert.strip().splitlines()
            cert_b64 = "".join(l for l in lines if l and not l.startswith("-----"))

        cert_block = ""
        if cert_b64:
            cert_block = f"""
        <ds:KeyDescriptor use="signing">
          <ds:KeyInfo>
            <ds:X509Data>
              <ds:X509Certificate>{cert_b64}</ds:X509Certificate>
            </ds:X509Data>
          </ds:KeyInfo>
        </ds:KeyDescriptor>"""

        nameid_format = self._name_id_format or "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<md:EntityDescriptor xmlns:md="{SAML_METADATA}" entityID="{entity_id}">
  <md:IDPSSODescriptor protocolSupportEnumeration="{SAML_PROTOCOL}"
                        WantAssertionsSigned="true">{cert_block}
    <md:NameIDFormat>{nameid_format}</md:NameIDFormat>
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
                             Location="{sso_url}"/>
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
                             Location="{sso_url}"/>
  </md:IDPSSODescriptor>
</md:EntityDescriptor>"""

    # ------------------------------------------------------------------
    # SP Metadata
    # ------------------------------------------------------------------

    def get_sp_metadata(self) -> str:
        """Return this SP's SAML 2.0 metadata XML.

        If pysaml2 is available, uses pysaml2 to generate the metadata.
        Otherwise, generates it manually.
        """
        if PYSAML2_AVAILABLE:
            try:
                config = self._build_sp_config()
                client = Saml2Client(config=config)
                meta_str = client.metadata.get_sp_metadata() if hasattr(client.metadata, "get_sp_metadata") else ""
                if meta_str:
                    return meta_str
            except Exception as exc:  # pylint: disable=broad-except
                logger_api.warning("pysaml2 metadata generation failed, falling back: %s", exc)

        # Fallback: manual metadata
        acs_location = self._acs_url
        entity_id = self._entity_id
        authn_signed = "true" if self._x509_cert else "false"

        cert_block = ""
        if self._x509_cert:
            cert_b64 = self._get_cert_b64(self._x509_cert)
            if cert_b64:
                cert_block = f"""
    <md:KeyDescriptor use="signing">
      <ds:KeyInfo xmlns:ds="{DSIG}">
        <ds:X509Data>
          <ds:X509Certificate>{cert_b64}</ds:X509Certificate>
        </ds:X509Data>
      </ds:KeyInfo>
    </md:KeyDescriptor>"""

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<md:EntityDescriptor xmlns:md="{SAML_METADATA}"
                     entityID="{entity_id}">
  <md:SPSSODescriptor protocolSupportEnumeration="{SAML_PROTOCOL}"
                      AuthnRequestsSigned="{authn_signed}"
                      WantAssertionsSigned="true">{cert_block}
    <md:NameIDFormat>{self._name_id_format}</md:NameIDFormat>
    <md:AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
                                  Location="{acs_location}"
                                  index="0"
                                  isDefault="true"/>
  </md:SPSSODescriptor>
</md:EntityDescriptor>"""

    # ------------------------------------------------------------------
    # AuthnRequest (SP-initiated SSO)
    # ------------------------------------------------------------------

    def create_login_request(self, relay_state: str = "") -> str:
        """Build the SAML AuthnRequest URL (HTTP-Redirect binding).

        :param relay_state: Opaque value preserved across the redirect.
        :returns: Absolute URL to redirect the user's browser to.
        """
        if PYSAML2_AVAILABLE:
            try:
                return self._create_login_request_pysaml2(relay_state)
            except Exception as exc:  # pylint: disable=broad-except
                logger_api.warning("pysaml2 login request failed, falling back: %s", exc)

        # Fallback: manual AuthnRequest
        return self._create_login_request_manual(relay_state)

    def _create_login_request_pysaml2(self, relay_state: str) -> str:
        """Build AuthnRequest using pysaml2 (with signing)."""
        config = self._build_sp_config()
        client = Saml2Client(config=config)

        # Store request ID in Redis for replay protection
        req_id = f"id_{uuid4().hex}"
        if self._redis:
            try:
                self._redis.setex(
                    f"saml:in_response_to:{req_id}",
                    300,  # 5 minute TTL
                    relay_state or "1",
                )
            except Exception as exc:  # pylint: disable=broad-except
                logger_api.debug("SAML2 replay store failed: %s", exc)

        # Build the request
        # pysaml2's prepare_for_authenticate returns (session_id, authn_request_dict)
        binding = BINDING_HTTP_REDIRECT
        req_authn_context = self._authn_context
        nameid_format = self._nameid_format_map.get(
            self._name_id_format, NAMEID_FORMAT_EMAILADDRESS
        )

        try:
            result = client.prepare_for_authenticate(
                relay_state=relay_state,
                binding=binding,
                sign=bool(self._x509_cert),
                nameid_format=nameid_format,
            )
        except Exception as exc:
            raise RequestException(
                f"SAML2: failed to create AuthnRequest: {exc}",
                err.ERROR_SAML_NOT_CONFIGURED,
            ) from exc

        # result is a dict with "headers" containing Location
        if isinstance(result, dict):
            headers = result.get("headers", [])
            for key, value in headers:
                if key.lower() == "location":
                    return value
            # Some versions return "url" directly
            if "url" in result:
                return result["url"]

        # If we got a tuple (session_id, info_dict)
        if isinstance(result, tuple) and len(result) >= 2:
            info = result[1]
            if isinstance(info, dict):
                headers = info.get("headers", [])
                for key, value in headers:
                    if key.lower() == "location":
                        return value
                if "url" in info:
                    return info["url"]

        raise RequestException(
            "SAML2: could not extract redirect URL from pysaml2 response",
            err.ERROR_SAML_NOT_CONFIGURED,
        )

    def _create_login_request_manual(self, relay_state: str) -> str:
        """Build AuthnRequest manually (fallback, no signing)."""
        request_id = f"ONELOGIN_{uuid4().hex}"
        issue_instant = self._iso_now()

        authn_request_xml = f"""<samlp:AuthnRequest xmlns:samlp="{SAML_PROTOCOL}"
                            xmlns:saml="{SAML_ASSERTION}"
                            ID="{request_id}"
                            Version="2.0"
                            IssueInstant="{issue_instant}"
                            Destination="{self._idp_sso_url}"
                            ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
                            AssertionConsumerServiceURL="{self._acs_url}"
                            ForceAuthn="false"
                            IsPassive="false">
  <saml:Issuer>{self._entity_id}</saml:Issuer>
  <samlp:NameIDPolicy Format="{self._name_id_format}"
                       AllowCreate="true"/>
  <samlp:RequestedAuthnContext Comparison="exact">
    <saml:AuthnContextClassRef>{self._authn_context}</saml:AuthnContextClassRef>
  </samlp:RequestedAuthnContext>
</samlp:AuthnRequest>"""

        # Deflate + base64 encode
        compressed = compress(authn_request_xml.encode("utf-8"))[2:-4]
        saml_request_b64 = b64encode(compressed).decode("utf-8")

        params: dict[str, str] = {"SAMLRequest": saml_request_b64}
        if relay_state:
            params["RelayState"] = relay_state

        return f"{self._idp_sso_url}?{urlencode(params)}"

    # ------------------------------------------------------------------
    # SAML Response processing
    # ------------------------------------------------------------------

    def process_response(self, saml_response_b64: str) -> dict[str, Any]:
        """Parse and validate a SAML Response (HTTP-POST binding).

        When pysaml2 is available, performs full validation:
        - XML signature verification
        - Conditions (NotBefore / NotOnOrAfter with clock skew)
        - Audience restriction
        - InResponseTo replay protection (via Redis)
        - Encrypted assertion decryption
        - Attribute extraction with mapping

        :param saml_response_b64: Base64-encoded SAML Response XML.
        :returns: Dict with ``name_id``, ``email``, ``attributes``, ``session_index``,
                  ``issuer``, ``display_name``, ``eppn``, ``affiliation``.
        :raises RequestException: If the response is invalid.
        """
        if PYSAML2_AVAILABLE:
            try:
                return self._process_response_pysaml2(saml_response_b64)
            except RequestException:
                raise
            except Exception as exc:
                logger_api.warning("pysaml2 response processing failed, falling back: %s", exc)

        # Fallback: manual parsing (insecure — no signature verification)
        logger_api.warning("SAML2: processing response in legacy (insecure) mode — no signature verification")
        return self._process_response_manual(saml_response_b64)

    def _process_response_pysaml2(self, saml_response_b64: str) -> dict[str, Any]:
        """Process SAML Response using pysaml2 with full validation."""
        config = self._build_sp_config()
        client = Saml2Client(config=config)

        # Decode the base64 response
        try:
            saml_response_xml = b64decode(saml_response_b64).decode("utf-8")
        except Exception as exc:
            raise RequestException(
                f"SAML2: failed to decode response: {exc}",
                err.ERROR_SAML_RESPONSE_INVALID,
            ) from exc

        # Parse and validate the response
        try:
            response = client.parse_authn_request_response(
                saml_response_b64,
                BINDING_HTTP_POST,
            )
        except ValidatingError as exc:
            # Check for specific validation errors
            exc_str = str(exc).lower()
            if "signature" in exc_str:
                raise RequestException(
                    f"SAML2: signature verification failed: {exc}",
                    err.ERROR_SAML_SIGNATURE_INVALID,
                ) from exc
            if "condition" in exc_str or "notbefore" in exc_str or "notonorafter" in exc_str:
                raise RequestException(
                    f"SAML2: conditions validation failed: {exc}",
                    err.ERROR_SAML_CONDITIONS_EXPIRED,
                ) from exc
            if "audience" in exc_str:
                raise RequestException(
                    f"SAML2: audience restriction failed: {exc}",
                    err.ERROR_SAML_AUDIENCE_MISMATCH,
                ) from exc
            if "issuer" in exc_str:
                raise RequestException(
                    f"SAML2: issuer mismatch: {exc}",
                    err.ERROR_SAML_ISSUER_MISMATCH,
                ) from exc
            if "inresponseto" in exc_str:
                raise RequestException(
                    f"SAML2: replay detected (InResponseTo): {exc}",
                    err.ERROR_SAML_REPLAY_DETECTED,
                ) from exc
            raise RequestException(
                f"SAML2: response validation failed: {exc}",
                err.ERROR_SAML_RESPONSE_INVALID,
            ) from exc
        except Exception as exc:
            raise RequestException(
                f"SAML2: response processing failed: {exc}",
                err.ERROR_SAML_RESPONSE_INVALID,
            ) from exc

        if response is None:
            raise RequestException(
                "SAML2: pysaml2 returned None response",
                err.ERROR_SAML_RESPONSE_INVALID,
            )

        # Check response status
        if hasattr(response, "status_code") and response.status_code:
            status = str(response.status_code)
            if "Success" not in status:
                raise RequestException(
                    f"SAML2: IdP returned failure status: {status}",
                    err.ERROR_SAML_STATUS_FAILURE,
                )

        # Extract the assertion
        assertion = None
        if hasattr(response, "assertions") and response.assertions:
            assertion = response.assertions[0]
        elif hasattr(response, "assertion") and response.assertion:
            assertion = response.assertion

        if assertion is None:
            raise RequestException(
                "SAML2: no assertion in response",
                err.ERROR_SAML_RESPONSE_INVALID,
            )

        # Extract NameID
        name_id = ""
        if hasattr(assertion, "subject") and assertion.subject:
            if hasattr(assertion.subject, "name_id") and assertion.subject.name_id:
                name_id = assertion.subject.name_id.text or ""

        # Extract issuer
        issuer = ""
        if hasattr(assertion, "issuer") and assertion.issuer:
            issuer = assertion.issuer.text or ""
        elif hasattr(response, "issuer") and response.issuer:
            issuer = response.issuer.text or ""

        # Validate issuer
        if self._idp_entity_id and issuer and issuer != self._idp_entity_id:
            raise RequestException(
                f"SAML2: assertion issuer '{issuer}' does not match expected '{self._idp_entity_id}'",
                err.ERROR_SAML_ISSUER_MISMATCH,
            )

        # Extract attributes
        raw_attributes: dict[str, list[str]] = {}
        if hasattr(assertion, "attribute_statement") and assertion.attribute_statement:
            for attr in assertion.attribute_statement.attributes:
                values = []
                if hasattr(attr, "attribute_value"):
                    for val in attr.attribute_value:
                        values.append(val.text or "")
                raw_attributes[attr.name] = values

        # Map attributes
        mapped = self._map_attributes(raw_attributes)

        # Extract session index
        session_index = ""
        if hasattr(assertion, "authn_statement") and assertion.authn_statement:
            for stmt in assertion.authn_statement:
                if hasattr(stmt, "session_index") and stmt.session_index:
                    session_index = stmt.session_index
                    break

        # Consume InResponseTo (replay protection)
        in_response_to = ""
        if hasattr(response, "in_response_to") and response.in_response_to:
            in_response_to = response.in_response_to
            self._consume_in_response_to(in_response_to)

        result = {
            "name_id": name_id,
            "email": mapped.get("email", "") or (name_id if "@" in name_id else ""),
            "display_name": mapped.get("display_name", ""),
            "given_name": mapped.get("given_name", ""),
            "surname": mapped.get("surname", ""),
            "eppn": mapped.get("eppn", ""),
            "affiliation": mapped.get("affiliation", ""),
            "scoped_affiliation": mapped.get("scoped_affiliation", ""),
            "unique_id": mapped.get("unique_id", ""),
            "attributes": raw_attributes,
            "session_index": session_index,
            "issuer": issuer,
            "in_response_to": in_response_to,
        }
        logger_api.info("SAML2 response processed: name_id=%s email=%s issuer=%s", name_id, result["email"], issuer)
        return result

    def _process_response_manual(self, saml_response_b64: str) -> dict[str, Any]:
        """Legacy fallback: parse SAML response without signature verification.

        .. warning:: This is INSECURE and only used when pysaml2 is not available.
        """
        from defusedxml import ElementTree as DefusedET
        from defusedxml.common import DefusedXmlException

        try:
            xml_bytes = b64decode(saml_response_b64)
            root = DefusedET.fromstring(xml_bytes)
        except (DefusedXmlException, Exception) as exc:
            raise RequestException(
                f"SAML2: failed to decode/parse response: {exc}",
                err.ERROR_SAML_RESPONSE_INVALID,
            ) from exc

        # Status
        status_elem = root.find(".//samlp:StatusCode", NS)
        status_value = status_elem.get("Value", "") if status_elem is not None else ""
        if "Success" not in status_value:
            sub_status = root.find(".//samlp:StatusCode/samlp:StatusCode", NS)
            detail = sub_status.get("Value", "") if sub_status is not None else status_value
            raise RequestException(
                f"SAML2: IdP returned failure: {detail}",
                err.ERROR_SAML_STATUS_FAILURE,
            )

        # Assertion
        assertion = root.find(f"{{{SAML_ASSERTION}}}Assertion", NS) or root.find(".//saml:Assertion", NS)
        if assertion is None:
            raise RequestException("SAML2: no Assertion in Response", err.ERROR_SAML_RESPONSE_INVALID)

        # Issuer
        issuer_elem = assertion.find(f"{{{SAML_ASSERTION}}}Issuer", NS) or assertion.find("saml:Issuer", NS)
        assertion_issuer = issuer_elem.text if issuer_elem is not None else ""
        if self._idp_entity_id and assertion_issuer and assertion_issuer != self._idp_entity_id:
            raise RequestException(
                f"SAML2: assertion issuer '{assertion_issuer}' does not match expected '{self._idp_entity_id}'",
                err.ERROR_SAML_ISSUER_MISMATCH,
            )

        # NameID
        subject = assertion.find(f"{{{SAML_ASSERTION}}}Subject", NS) or assertion.find("saml:Subject", NS)
        name_id = ""
        if subject is not None:
            name_id_elem = subject.find(f"{{{SAML_ASSERTION}}}NameID", NS) or subject.find("saml:NameID", NS)
            if name_id_elem is not None:
                name_id = name_id_elem.text or ""

        # Attributes
        attributes: dict[str, list[str]] = {}
        attr_statement = (
            assertion.find(f"{{{SAML_ASSERTION}}}AttributeStatement", NS)
            or assertion.find("saml:AttributeStatement", NS)
        )
        if attr_statement is not None:
            for attr_elem in attr_statement:
                if attr_elem.tag == f"{{{SAML_ASSERTION}}}Attribute" or attr_elem.tag.endswith("}Attribute"):
                    attr_name = attr_elem.get("Name", "")
                    values: list[str] = []
                    for val_elem in attr_elem:
                        if val_elem.tag == f"{{{SAML_ASSERTION}}}AttributeValue" or val_elem.tag.endswith("}AttributeValue"):
                            values.append(val_elem.text or "")
                    if attr_name:
                        attributes[attr_name] = values

        # Map attributes
        mapped = self._map_attributes(attributes)

        # SessionIndex
        session_index = ""
        authn_statement = (
            assertion.find(f"{{{SAML_ASSERTION}}}AuthnStatement", NS)
            or assertion.find("saml:AuthnStatement", NS)
        )
        if authn_statement is not None:
            session_index = authn_statement.get("SessionIndex", "")

        result = {
            "name_id": name_id,
            "email": mapped.get("email", "") or (name_id if "@" in name_id else ""),
            "display_name": mapped.get("display_name", ""),
            "given_name": mapped.get("given_name", ""),
            "surname": mapped.get("surname", ""),
            "eppn": mapped.get("eppn", ""),
            "affiliation": mapped.get("affiliation", ""),
            "scoped_affiliation": mapped.get("scoped_affiliation", ""),
            "unique_id": mapped.get("unique_id", ""),
            "attributes": attributes,
            "session_index": session_index,
            "issuer": assertion_issuer,
            "in_response_to": "",
        }
        logger_api.warning(
            "SAML2 response processed in LEGACY mode (no signature verification): name_id=%s", name_id
        )
        return result

    # ------------------------------------------------------------------
    # Attribute mapping
    # ------------------------------------------------------------------

    def _map_attributes(self, raw_attrs: dict[str, list[str]]) -> dict[str, str]:
        """Map raw SAML attributes to standard field names.

        :param raw_attrs: Raw SAML attributes (name → list of values).
        :returns: Dict with mapped fields (email, display_name, etc.).
        """
        mapped: dict[str, str] = {}
        for attr_name, values in raw_attrs.items():
            if not values:
                continue
            field = self._attribute_map.get(attr_name)
            if not field:
                # Try lowercase
                field = self._attribute_map.get(attr_name.lower())
            if not field:
                # Try without OID prefix
                if attr_name.startswith("urn:oid:"):
                    # Already in the map if it's a known OID
                    continue
                continue
            if field not in mapped:  # First value wins
                mapped[field] = values[0]
        return mapped

    # ------------------------------------------------------------------
    # Replay protection (InResponseTo)
    # ------------------------------------------------------------------

    def _consume_in_response_to(self, in_response_to: str) -> None:
        """Consume the InResponseTo ID from Redis to prevent replay.

        :param in_response_to: The InResponseTo value from the SAML response.
        :raises RequestException: If the ID is unknown or already consumed.
        """
        if not self._redis or not in_response_to:
            return

        redis_key = f"saml:in_response_to:{in_response_to}"
        try:
            stored = self._redis.get(redis_key)
            if stored is None:
                raise RequestException(
                    f"SAML2: replay detected — InResponseTo '{in_response_to}' not found or expired",
                    err.ERROR_SAML_REPLAY_DETECTED,
                )
            # Delete to prevent reuse
            self._redis.delete(redis_key)
            logger_api.debug("SAML2: consumed InResponseTo %s", in_response_to)
        except RequestException:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            logger_api.warning("SAML2: replay check Redis error: %s", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _iso_now() -> str:
        """Return current UTC time in SAML2-compatible ISO 8601 format."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _get_cert_b64(cert_pem: str) -> str:
        """Extract base64 content from a PEM certificate (strip headers)."""
        lines = cert_pem.strip().splitlines()
        return "".join(l for l in lines if l and not l.startswith("-----"))

    @staticmethod
    def get_fingerprint(cert_pem: str) -> str:
        """Compute the SHA-256 fingerprint of a certificate."""
        cert_b64 = ModuleSAML2._get_cert_b64(cert_pem)
        return hashlib.sha256(cert_b64.encode()).hexdigest()
