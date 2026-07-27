"""Tests for Audit Log (#24)."""
import json
import pytest
from unittest.mock import MagicMock, patch
from app.api.v1.admin.ApiAuditLog import audit, _AUDIT_ZSET


class TestAuditLog:
    @patch("app.api.v1.admin.ApiAuditLog.sogo_cache")
    def test_audit_adds_entry(self, mock_cache):
        cache = MagicMock()
        cache.zset_count.return_value = 1
        mock_cache.return_value = cache
        audit("user.login", actor="admin@test.com", target="user", detail="Login from 192.168.1.1", ip="192.168.1.1")
        assert cache.zset_add.called
        args = cache.zset_add.call_args
        assert args[0][0] == _AUDIT_ZSET

    @patch("app.api.v1.admin.ApiAuditLog.sogo_cache")
    def test_audit_trims_old_entries(self, mock_cache):
        cache = MagicMock()
        cache.zset_count.return_value = 10001
        mock_cache.return_value = cache
        audit("test.event", actor="test@test.com")
        assert cache.zset_remove.called

    @patch("app.api.v1.admin.ApiAuditLog.sogo_cache")
    def test_multiple_audit_entries(self, mock_cache):
        cache = MagicMock()
        cache.zset_count.return_value = 1
        mock_cache.return_value = cache
        for i in range(5):
            audit(f"event.{i}", actor=f"user{i}@test.com")
        assert cache.zset_add.call_count == 5
