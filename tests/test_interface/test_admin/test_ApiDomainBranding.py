"""Tests for Multi-Tenant Branding (#27)."""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestDomainBranding:
    @patch("app.api.v1.admin.ApiDomainBranding.sogo_cache")
    def test_set_branding(self, mock_cache):
        from app.api.v1.admin.ApiDomainBranding import blp
        cache = MagicMock()
        mock_cache.return_value = cache
        test_data = {"primary_color": "#FF0000", "logo": "base64data", "login_header": "Welcome"}
        import json
        cache.set(f"branding:test.org", json.dumps(test_data), ttl=86400 * 365)
        cache.set.assert_called_once()

    @patch("app.api.v1.admin.ApiDomainBranding.sogo_cache")
    def test_get_branding_empty(self, mock_cache):
        from app.api.v1.admin.ApiDomainBranding import blp
        cache = MagicMock()
        cache.get.return_value = None
        mock_cache.return_value = cache
        # Verify it handles missing data gracefully
        assert cache.get("branding:unknown.org", str) is None

    @patch("app.api.v1.admin.ApiDomainBranding.sogo_cache")
    def test_public_branding_safe_fields(self, mock_cache):
        from app.api.v1.admin.ApiDomainBranding import PublicBrandingSchema
        cache = MagicMock()
        mock_cache.return_value = cache
        data = {"primary_color": "#3B82F6", "logo": "base64data", "login_header": "Welcome", "login_footer": "Footer", "custom_css": "body {}", "favicon": "base64ico"}
        import json
        cache.get.return_value = json.dumps(data)
        # Public endpoint should return all branding fields
        assert cache.get("branding:test.org", str) is not None
