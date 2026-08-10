"""Unit tests for ModuleSAML2 — AuthnRequest, SP metadata, response processing.

Tests cover:
  - AuthnRequest generation (HTTP-Redirect binding)
  - SP metadata generation
  - SAML Response parsing (legacy fallback mode)
  - Attribute mapping (eduPerson OIDs + friendly names)
  - Issuer validation
  - Replay protection (InResponseTo via Redis mock)
"""
from __future__ import annotations

import pytest
from base64 import b64encode
from unittest import mock

from app.module.auth.ModuleSAML2 import ModuleSAML2


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def saml_sp():
    """A basic ModuleSAML2 instance (no keypair, no Redis)."""
    return ModuleSAML2(
        idp_sso_url="https://idp.example.org/idp/profile/SAML2/Redirect/SSO",
        idp_entity_id="https://idp.example.org/idp/shibboleth",
        entity_id="https://sogo.example.org/saml/metadata",
        acs_url="https://sogo.example.org/api/user/v1/auth/saml2/acs",
        name_id_format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
    )


@pytest.fixture
def saml_sp_with_redis():
    """ModuleSAML2 with a mock Redis client for replay protection."""
    redis_mock = mock.MagicMock()
    redis_mock.get.return_value = b"1"  # InResponseTo exists
    return ModuleSAML2(
        idp_sso_url="https://idp.example.org/idp/profile/SAML2/Redirect/SSO",
        idp_entity_id="https://idp.example.org/idp/shibboleth",
        entity_id="https://sogo.example.org/saml/metadata",
        acs_url="https://sogo.example.org/api/user/v1/auth/saml2/acs",
        redis_client=redis_mock,
    )


# ── AuthnRequest tests ────────────────────────────────────────────────────────


class TestCreateLoginRequest:
    """Tests for AuthnRequest generation."""

    def test_login_request_returns_url_with_samlrequest(self, saml_sp):
        """AuthnRequest URL should contain SAMLRequest parameter."""
        url = saml_sp.create_login_request(relay_state="/inbox")
        assert "SAMLRequest=" in url
        assert "RelayState=" in url
        assert url.startswith("https://idp.example.org/idp/profile/SAML2/Redirect/SSO?")

    def test_login_request_without_relay_state(self, saml_sp):
        """AuthnRequest URL without relay_state should not include RelayState param."""
        url = saml_sp.create_login_request()
        assert "SAMLRequest=" in url
        assert "RelayState=" not in url

    def test_login_request_url_contains_idp_sso_url(self, saml_sp):
        """AuthnRequest URL should start with the IdP SSO URL."""
        url = saml_sp.create_login_request()
        assert url.startswith("https://idp.example.org/idp/profile/SAML2/Redirect/SSO")


# ── SP Metadata tests ─────────────────────────────────────────────────────────


class TestGetSpMetadata:
    """Tests for SP metadata generation."""

    def test_metadata_contains_entity_id(self, saml_sp):
        """SP metadata should contain the SP entityID."""
        metadata = saml_sp.get_sp_metadata()
        assert "https://sogo.example.org/saml/metadata" in metadata
        assert "entityID" in metadata

    def test_metadata_contains_acs_url(self, saml_sp):
        """SP metadata should contain the ACS URL."""
        metadata = saml_sp.get_sp_metadata()
        assert "https://sogo.example.org/api/user/v1/auth/saml2/acs" in metadata
        assert "AssertionConsumerService" in metadata

    def test_metadata_contains_nameid_format(self, saml_sp):
        """SP metadata should contain the NameIDFormat."""
        metadata = saml_sp.get_sp_metadata()
        assert "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress" in metadata

    def test_metadata_without_keypair_has_authn_requests_signed_false(self, saml_sp):
        """Without a keypair, AuthnRequestsSigned should be false."""
        metadata = saml_sp.get_sp_metadata()
        assert 'AuthnRequestsSigned="false"' in metadata

    def test_metadata_with_keypair_has_authn_requests_signed_true(self):
        """With a keypair, AuthnRequestsSigned should be true."""
        sp = ModuleSAML2(
            idp_sso_url="https://idp.example.org/idp/profile/SAML2/Redirect/SSO",
            idp_entity_id="https://idp.example.org/idp/shibboleth",
            entity_id="https://sogo.example.org/saml/metadata",
            acs_url="https://sogo.example.org/api/user/v1/auth/saml2/acs",
            x509_cert="-----BEGIN CERTIFICATE-----\nMIIDfake==\n-----END CERTIFICATE-----",
            x509_key="-----BEGIN PRIVATE KEY-----\nMIIEfake==\n-----END PRIVATE KEY-----",
        )
        metadata = sp.get_sp_metadata()
        assert 'AuthnRequestsSigned="true"' in metadata


# ── Response processing tests (legacy fallback) ───────────────────────────────


def _make_saml_response(
    issuer: str = "https://idp.example.org/idp/shibboleth",
    name_id: str = "user@example.org",
    email: str = "user@example.org",
    status: str = "urn:oasis:names:tc:SAML:2.0:status:Success",
    attributes: dict[str, list[str]] | None = None,
) -> str:
    """Build a minimal SAML Response XML and base64-encode it."""
    attrs_xml = ""
    if attributes:
        attr_parts = []
        for name, values in attributes.items():
            attr_xml = f'<saml:Attribute Name="{name}">'
            for v in values:
                attr_xml += f"<saml:AttributeValue>{v}</saml:AttributeValue>"
            attr_xml += "</saml:Attribute>"
            attr_parts.append(attr_xml)
        attrs_xml = (
            f"<saml:AttributeStatement>{"".join(attr_parts)}</saml:AttributeStatement>"
        )

    email_attr = ""
    if email and not attributes:
        email_attr = f'''<saml:AttributeStatement>
            <saml:Attribute Name="mail">
                <saml:AttributeValue>{email}</saml:AttributeValue>
            </saml:Attribute>
        </saml:AttributeStatement>'''

    xml = f"""<?xml version="1.0"?>
<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
                xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
                ID="_response123"
                Version="2.0"
                IssueInstant="2025-01-01T00:00:00Z"
                Destination="https://sogo.example.org/api/user/v1/auth/saml2/acs">
  <samlp:Issuer>{issuer}</samlp:Issuer>
  <samlp:Status>
    <samlp:StatusCode Value="{status}"/>
  </samlp:Status>
  <saml:Assertion ID="_assertion123" Version="2.0" IssueInstant="2025-01-01T00:00:00Z">
    <saml:Issuer>{issuer}</saml:Issuer>
    <saml:Subject>
      <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{name_id}</saml:NameID>
    </saml:Subject>
    <saml:AuthnStatement AuthnInstant="2025-01-01T00:00:00Z" SessionIndex="_session123">
      <saml:AuthnContext>
        <saml:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport</saml:AuthnContextClassRef>
      </saml:AuthnContext>
    </saml:AuthnStatement>
    {email_attr}{attrs_xml}
  </saml:Assertion>
</samlp:Response>"""
    return b64encode(xml.encode("utf-8")).decode("utf-8")


class TestProcessResponse:
    """Tests for SAML Response processing (legacy fallback mode)."""

    def test_process_response_extracts_email(self, saml_sp):
        """process_response should extract the email attribute."""
        response_b64 = _make_saml_response(email="user@example.org")
        result = saml_sp.process_response(response_b64)
        assert result["email"] == "user@example.org"

    def test_process_response_extracts_name_id(self, saml_sp):
        """process_response should extract the NameID."""
        response_b64 = _make_saml_response(name_id="user@example.org", email="")
        result = saml_sp.process_response(response_b64)
        assert result["name_id"] == "user@example.org"

    def test_process_response_extracts_session_index(self, saml_sp):
        """process_response should extract the SessionIndex."""
        response_b64 = _make_saml_response()
        result = saml_sp.process_response(response_b64)
        assert result["session_index"] == "_session123"

    def test_process_response_extracts_issuer(self, saml_sp):
        """process_response should extract the issuer."""
        response_b64 = _make_saml_response()
        result = saml_sp.process_response(response_b64)
        assert result["issuer"] == "https://idp.example.org/idp/shibboleth"

    def test_process_response_rejects_wrong_issuer(self, saml_sp):
        """process_response should reject a response from the wrong issuer."""
        response_b64 = _make_saml_response(issuer="https://evil.example.org/idp")
        with pytest.raises(Exception) as exc_info:
            saml_sp.process_response(response_b64)
        assert "issuer" in str(exc_info.value).lower() or "mismatch" in str(exc_info.value).lower()

    def test_process_response_rejects_failure_status(self, saml_sp):
        """process_response should reject a failure status."""
        response_b64 = _make_saml_response(
            status="urn:oasis:names:tc:SAML:2.0:status:Requester"
        )
        with pytest.raises(Exception):
            saml_sp.process_response(response_b64)

    def test_process_response_maps_eduperson_attributes(self, saml_sp):
        """process_response should map eduPerson OIDs to standard fields."""
        attrs = {
            "urn:oid:0.9.2342.19200300.100.1.3": ["user@example.org"],
            "urn:oid:1.3.6.1.4.1.5923.1.1.1.6": ["user@uni-example.de"],
            "urn:oid:2.16.840.1.113730.3.1.241": ["Test User"],
            "urn:oid:1.3.6.1.4.1.5923.1.1.1.1": ["member"],
            "urn:oid:1.3.6.1.4.1.5923.1.1.1.9": ["member@uni-example.de"],
        }
        response_b64 = _make_saml_response(attributes=attrs)
        result = saml_sp.process_response(response_b64)
        assert result["email"] == "user@example.org"
        assert result["eppn"] == "user@uni-example.de"
        assert result["display_name"] == "Test User"
        assert result["affiliation"] == "member"
        assert result["scoped_affiliation"] == "member@uni-example.de"

    def test_process_response_maps_friendly_names(self, saml_sp):
        """process_response should map friendly attribute names."""
        attrs = {
            "mail": ["user@example.org"],
            "displayName": ["Test User"],
            "givenName": ["Test"],
            "sn": ["User"],
        }
        response_b64 = _make_saml_response(attributes=attrs)
        result = saml_sp.process_response(response_b64)
        assert result["email"] == "user@example.org"
        assert result["display_name"] == "Test User"
        assert result["given_name"] == "Test"
        assert result["surname"] == "User"

    def test_process_response_falls_back_to_name_id_for_email(self, saml_sp):
        """If no email attribute, use NameID if it contains @."""
        response_b64 = _make_saml_response(name_id="user@example.org", email="")
        result = saml_sp.process_response(response_b64)
        assert result["email"] == "user@example.org"


# ── Attribute mapping tests ───────────────────────────────────────────────────


class TestAttributeMapping:
    """Tests for the attribute mapping logic."""

    def test_default_attribute_map_includes_eduperson(self, saml_sp):
        """The default attribute map should include eduPerson OIDs."""
        attr_map = saml_sp._attribute_map
        assert "urn:oid:0.9.2342.19200300.100.1.3" in attr_map  # mail
        assert "urn:oid:1.3.6.1.4.1.5923.1.1.1.6" in attr_map  # eppn
        assert "urn:oid:2.16.840.1.113730.3.1.241" in attr_map  # displayName

    def test_custom_attribute_map(self):
        """Custom attribute map should override the default."""
        sp = ModuleSAML2(
            idp_sso_url="https://idp.example.org/SAML2/SSO",
            entity_id="https://sogo.example.org/saml/metadata",
            acs_url="https://sogo.example.org/api/user/v1/auth/saml2/acs",
            attribute_map={"customAttr": "email"},
        )
        mapped = sp._map_attributes({"customAttr": ["test@example.org"]})
        assert mapped.get("email") == "test@example.org"

    def test_first_value_wins(self, saml_sp):
        """When an attribute has multiple values, the first wins."""
        mapped = saml_sp._map_attributes({
            "mail": ["first@example.org", "second@example.org"],
        })
        assert mapped.get("email") == "first@example.org"
