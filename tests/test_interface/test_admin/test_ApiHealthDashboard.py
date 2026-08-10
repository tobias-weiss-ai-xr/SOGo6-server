"""Tests for System Health Dashboard (#33)."""
import pytest
from unittest.mock import patch, MagicMock


class TestHealthDashboard:
    def test_dashboard_returns_services(self):
        from app.api.v1.admin.ApiHealthDashboard import ApiHealthDashboard
        # Verify the view exists and has correct method
        view = ApiHealthDashboard()
        assert hasattr(view, 'get')
    
    def test_health_check_service_names(self):
        from app.api.v1.admin.ApiHealthDashboard import _check_service
        result = _check_service("TestService", lambda: "ok")
        assert result["name"] == "TestService"
        assert result["status"] == "ok"
        assert "latency_ms" in result

    def test_health_check_service_failure(self):
        from app.api.v1.admin.ApiHealthDashboard import _check_service
        def failing():
            raise ConnectionError("DB down")
        result = _check_service("FailingService", failing)
        assert result["status"] == "error"
        assert "DB down" in result.get("detail", "")

    def test_health_check_latency_measured(self):
        import time
        from app.api.v1.admin.ApiHealthDashboard import _check_service
        result = _check_service("SlowService", lambda: time.sleep(0.01) or "ok")
        assert result["latency_ms"] > 5
        assert result["status"] == "ok"
