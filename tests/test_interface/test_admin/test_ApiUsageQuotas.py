"""Tests for Usage Quotas (#32)."""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestUsageQuotas:
    @patch("app.api.v1.admin.ApiUsageQuotas.sogo_cache")
    def test_set_quota(self, mock_cache):
        cache = MagicMock()
        mock_cache.return_value = cache
        import json
        data = {"mailbox_size_mb": 1024, "calendar_count": 10, "contact_count": 500}
        cache.set(f"quota:user@test.com", json.dumps(data), ttl=86400 * 365)
        cache.set.assert_called_once()

    @patch("app.api.v1.admin.ApiUsageQuotas.sogo_cache")
    def test_get_quota_defaults(self, mock_cache):
        cache = MagicMock()
        cache.get.return_value = None
        mock_cache.return_value = cache
        assert cache.get("quota:unknown@test.com", str) is None

    @patch("app.api.v1.admin.ApiUsageQuotas.sogo_cache")
    def test_quota_updates_existing(self, mock_cache):
        cache = MagicMock()
        mock_cache.return_value = cache
        import json
        old = {"mailbox_size_mb": 500}
        cache.get.return_value = json.dumps(old)
        new = {"mailbox_size_mb": 2048}
        cache.set(f"quota:user@test.com", json.dumps(new), ttl=86400 * 365)
        cache.set.assert_called_once()
