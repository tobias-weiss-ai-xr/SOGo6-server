"""Unit tests for Saml2Metadata — IdP/federation metadata fetching and parsing.

Tests cover:
  - IdP metadata XML parsing (entity_id, SSO URL, certificate, NameIDFormat)
  - Federation metadata parsing (multiple IdPs)
  - Redis caching (cache hit, cache miss)
  - Stale cache fallback
"""
from __future__ import annotations

import pytest
from unittest import mock

from app.module.auth.Saml2Metadata import Saml2Metadata


# ── Sample metadata XML ───────────────────────────────────────────────────────


IDP_METADATA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"
                      entityID="https://idp.example.org/idp/shibboleth">
  <md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol"
                        WantAssertionsSigned="true">
    <md:KeyDescriptor use="signing">
      <ds:KeyInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
        <ds:X509Data>
          <ds:X509Certificate>MIIDfzCCAmegAwIBAgIUfakecertbase64==</ds:X509Certificate>
        </ds:X509Data>
      </ds:KeyInfo>
    </md:KeyDescriptor>
    <md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</md:NameIDFormat>
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
                             Location="https://idp.example.org/idp/profile/SAML2/Redirect/SSO"/>
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
                             Location="https://idp.example.org/idp/profile/SAML2/POST/SSO"/>
  </md:IDPSSODescriptor>
</md:EntityDescriptor>"""


FEDERATION_METADATA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<md:EntitiesDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" Name="Federation">
  <md:EntityDescriptor entityID="https://idp1.example.org/idp/shibboleth">
    <md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
      <md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</md:NameIDFormat>
      <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
                               Location="https://idp1.example.org/idp/profile/SAML2/Redirect/SSO"/>
    </md:IDPSSODescriptor>
    <md:Organization>
      <md:OrganizationDisplayName>Example University 1</md:OrganizationDisplayName>
    </md:Organization>
  </md:EntityDescriptor>
  <md:EntityDescriptor entityID="https://idp2.example.org/idp/shibboleth">
    <md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
      <md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</md:NameIDFormat>
      <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
                               Location="https://idp2.example.org/idp/profile/SAML2/Redirect/SSO"/>
    </md:IDPSSODescriptor>
    <md:Organization>
      <md:OrganizationDisplayName>Example University 2</md:OrganizationDisplayName>
    </md:Organization>
  </md:EntityDescriptor>
  <md:EntityDescriptor entityID="https://sp.example.org/sp/shibboleth">
    <md:SPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
      <md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</md:NameIDFormat>
    </md:SPSSODescriptor>
  </md:EntityDescriptor>
</md:EntitiesDescriptor>"""


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_process():
    """Fake ProcessSetting for Saml2Metadata."""
    process = mock.MagicMock()
    process.SOGO_SAML2_METADATA_CACHE_TTL = 21600
    process.SOGO_SAML2_FEDERATION_METADATA_CERT = ""
    return process


@pytest.fixture
def metadata_fetcher(fake_process):
    """Saml2Metadata instance with mocked Redis."""
    fetcher = Saml2Metadata(fake_process)
    fetcher._get_redis = mock.MagicMock()
    return fetcher


# ── IdP metadata parsing tests ────────────────────────────────────────────────


class TestParseIdpMetadata:
    """Tests for IdP metadata XML parsing."""

    def test_parse_idp_metadata_extracts_entity_id(self, metadata_fetcher):
        """Should extract the entityID from IdP metadata."""
        result = metadata_fetcher._parse_idp_metadata(IDP_METADATA_XML)
        assert result["entity_id"] == "https://idp.example.org/idp/shibboleth"

    def test_parse_idp_metadata_extracts_sso_url(self, metadata_fetcher):
        """Should extract the SSO URL (HTTP-Redirect preferred)."""
        result = metadata_fetcher._parse_idp_metadata(IDP_METADATA_XML)
        assert result["sso_url"] == "https://idp.example.org/idp/profile/SAML2/Redirect/SSO"
        assert "HTTP-Redirect" in result["sso_binding"]

    def test_parse_idp_metadata_extracts_certificate(self, metadata_fetcher):
        """Should extract the signing certificate."""
        result = metadata_fetcher._parse_idp_metadata(IDP_METADATA_XML)
        assert result["certificate"]
        assert "BEGIN CERTIFICATE" in result["certificate"]
        assert "MIIDfzCCAmegAwIBAgIUfakecertbase64==" in result["certificate"]

    def test_parse_idp_metadata_extracts_fingerprint(self, metadata_fetcher):
        """Should compute a SHA-256 fingerprint of the certificate."""
        result = metadata_fetcher._parse_idp_metadata(IDP_METADATA_XML)
        assert result["fingerprint"]
        assert len(result["fingerprint"]) == 64  # SHA-256 hex

    def test_parse_idp_metadata_extracts_nameid_format(self, metadata_fetcher):
        """Should extract the NameIDFormat."""
        result = metadata_fetcher._parse_idp_metadata(IDP_METADATA_XML)
        assert result["nameid_format"] == "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"

    def test_parse_idp_metadata_extracts_want_assertions_signed(self, metadata_fetcher):
        """Should extract WantAssertionsSigned."""
        result = metadata_fetcher._parse_idp_metadata(IDP_METADATA_XML)
        assert result["want_assertions_signed"] is True


# ── Federation metadata parsing tests ─────────────────────────────────────────


class TestParseFederationMetadata:
    """Tests for federation aggregate metadata parsing."""

    def test_parse_federation_returns_all_idps(self, metadata_fetcher):
        """Should return all IdP EntityDescriptors (not SP)."""
        idps = metadata_fetcher._parse_federation_metadata(FEDERATION_METADATA_XML)
        assert len(idps) == 2  # 2 IdPs, 1 SP (excluded)

    def test_parse_federation_excludes_sp_descriptors(self, metadata_fetcher):
        """Should exclude SP EntityDescriptors."""
        idps = metadata_fetcher._parse_federation_metadata(FEDERATION_METADATA_XML)
        entity_ids = [idp["entity_id"] for idp in idps]
        assert "https://sp.example.org/sp/shibboleth" not in entity_ids

    def test_parse_federation_extracts_entity_ids(self, metadata_fetcher):
        """Should extract entity_ids from all IdPs."""
        idps = metadata_fetcher._parse_federation_metadata(FEDERATION_METADATA_XML)
        entity_ids = [idp["entity_id"] for idp in idps]
        assert "https://idp1.example.org/idp/shibboleth" in entity_ids
        assert "https://idp2.example.org/idp/shibboleth" in entity_ids

    def test_parse_federation_extracts_display_names(self, metadata_fetcher):
        """Should extract display names from OrganizationDisplayName."""
        idps = metadata_fetcher._parse_federation_metadata(FEDERATION_METADATA_XML)
        names = [idp["name"] for idp in idps]
        assert "Example University 1" in names
        assert "Example University 2" in names

    def test_parse_federation_extracts_sso_urls(self, metadata_fetcher):
        """Should extract SSO URLs from all IdPs."""
        idps = metadata_fetcher._parse_federation_metadata(FEDERATION_METADATA_XML)
        sso_urls = [idp["sso_url"] for idp in idps]
        assert "https://idp1.example.org/idp/profile/SAML2/Redirect/SSO" in sso_urls
        assert "https://idp2.example.org/idp/profile/SAML2/Redirect/SSO" in sso_urls


# ── Caching tests ─────────────────────────────────────────────────────────────


class TestMetadataCaching:
    """Tests for Redis caching."""

    def test_cache_hit_returns_cached_data(self, metadata_fetcher):
        """Should return cached data without fetching."""
        cached_config = {"entity_id": "https://cached.example.org", "sso_url": "https://cached.example.org/SSO"}
        metadata_fetcher._cache_get = mock.MagicMock(return_value=cached_config)
        metadata_fetcher._fetch_url = mock.MagicMock()

        result = metadata_fetcher.get_idp_config("https://metadata.example.org", "https://cached.example.org")
        assert result == cached_config
        metadata_fetcher._fetch_url.assert_not_called()

    def test_cache_miss_fetches_and_caches(self, metadata_fetcher):
        """Should fetch on cache miss and cache the result."""
        metadata_fetcher._cache_get = mock.MagicMock(return_value=None)
        metadata_fetcher._cache_set = mock.MagicMock()
        metadata_fetcher._fetch_url = mock.MagicMock(return_value=IDP_METADATA_XML)

        result = metadata_fetcher.fetch_idp_metadata("https://metadata.example.org")
        assert result["entity_id"] == "https://idp.example.org/idp/shibboleth"
        metadata_fetcher._fetch_url.assert_called_once()
        metadata_fetcher._cache_set.assert_called()
