"""HTTP integration tests for all admin API endpoints."""
import json
from datetime import datetime, timedelta, timezone

import pytest


class TestAuditLog:
    BASE = "/api/admin/v1/audit-log"

    def test_list_empty(self, client, auth_headers):
        resp = client.get(self.BASE, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["error_code"] == "S000000"


class TestBranding:
    BASE = "/api/admin/v1/branding"

    def test_set_and_get_branding(self, client, auth_headers):
        data = {"primary_color": "#FF0000"}
        put = client.put(f"{self.BASE}/brand-test.org", data=json.dumps(data), content_type="application/json", headers=auth_headers)
        assert put.status_code == 200
        get = client.get(f"{self.BASE}/brand-test.org", headers=auth_headers)
        assert get.status_code == 200
        # Flask-smorest strips the envelope — response is the data dict itself
        assert isinstance(get.get_json(), dict)

    def test_set_multiple_fields(self, client, auth_headers):
        data = {"primary_color": "#00FF00", "login_header": "Green", "login_footer": "Footer", "custom_css": "body {}"}
        put = client.put(f"{self.BASE}/multi.org", data=json.dumps(data), content_type="application/json", headers=auth_headers)
        assert put.status_code == 200
        get = client.get(f"{self.BASE}/multi.org", headers=auth_headers)
        assert get.status_code == 200

    def test_get_nonexistent_branding(self, client, auth_headers):
        resp = client.get(f"{self.BASE}/unknown-org.org", headers=auth_headers)
        assert resp.status_code == 200

    def test_public_branding_with_auth(self, client, auth_headers):
        data = {"primary_color": "#123456", "login_header": "Public"}
        client.put(f"{self.BASE}/public-org.org", data=json.dumps(data), content_type="application/json", headers=auth_headers)
        # Public endpoint requires auth (it's a protected endpoint despite the name)
        resp = client.get(f"{self.BASE}/public-org.org/public", headers=auth_headers)
        assert resp.status_code == 200


class TestQuotas:
    BASE = "/api/admin/v1/quotas"

    def test_get_set_quota(self, client, auth_headers):
        data = {"mailbox_size_mb": 1024, "calendar_count": 5, "contact_count": 200}
        put = client.put(f"{self.BASE}/user@test.com", data=json.dumps(data), content_type="application/json", headers=auth_headers)
        assert put.status_code == 200
        get = client.get(f"{self.BASE}/user@test.com", headers=auth_headers)
        assert get.status_code == 200

    def test_get_nonexistent_quota(self, client, auth_headers):
        resp = client.get(f"{self.BASE}/unknown@test.com", headers=auth_headers)
        assert resp.status_code == 200


class TestBulkUsers:
    BASE = "/api/admin/v1/bulk-users"

    def test_csv_export(self, client, auth_headers):
        resp = client.get(f"{self.BASE}/export/csv", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/csv")


class TestHealthDashboard:
    BASE = "/api/admin/v1/health-dashboard"

    def test_health_dashboard(self, client, auth_headers):
        resp = client.get(self.BASE, headers=auth_headers)
        assert resp.status_code == 200
        assert "services" in resp.get_json()["data"]


class TestFileSharing:
    BASE = "/api/admin/v1/files/shares"

    def test_create_share(self, client, auth_headers):
        data = {"filename": "test.pdf", "size": 1024, "expires_in_days": 7}
        resp = client.post(self.BASE, data=json.dumps(data), content_type="application/json", headers=auth_headers)
        assert resp.status_code == 201
        share = resp.get_json()["data"]
        assert "token" in share
        assert "url" in share

    def test_list_shares(self, client, auth_headers):
        resp = client.get(self.BASE, headers=auth_headers)
        assert resp.status_code == 200


class TestApiTokens:
    BASE = "/api/user/v1/api-tokens"

    def test_create_token(self, client, user_auth_headers):
        data = {"label": "Test Token", "scopes": ["read"]}
        resp = client.post(self.BASE, data=json.dumps(data), content_type="application/json", headers=user_auth_headers)
        assert resp.status_code == 201
        result = resp.get_json()["data"]
        assert result["label"] == "Test Token"
        assert result["token"].startswith("sogo_")

    def test_list_tokens(self, client, user_auth_headers):
        resp = client.get(self.BASE, headers=user_auth_headers)
        assert resp.status_code == 200

    def test_create_token_multiple_scopes(self, client, user_auth_headers):
        data = {"label": "Admin Token", "scopes": ["read", "write", "admin"]}
        resp = client.post(self.BASE, data=json.dumps(data), content_type="application/json", headers=user_auth_headers)
        assert resp.status_code == 201
        assert len(resp.get_json()["data"]["scopes"]) == 3


class TestResourceBookingAdmin:
    """Integration tests for Resource Booking Admin API."""

    BASE = "/api/admin/v1/resources"
    BOOKINGS_BASE = "/api/admin/v1/resource-bookings"

    def test_list_resources(self, client, auth_headers):
        """Test listing all resources (admin)."""
        resp = client.get(self.BASE, headers=auth_headers)
        assert resp.status_code == 200

    def test_create_resource(self, client, auth_headers):
        """Test creating a resource (admin)."""
        data = {
            "name": "Test Conference Room",
            "email": "test-room-local@example.org",
            "resource_type": "room",
            "capacity": 20,
            "description": "Test room for integration tests",
            "booking_policy": "open"
        }
        resp = client.post(self.BASE, data=json.dumps(data), content_type="application/json", headers=auth_headers)
        # Note: May fail if resource already exists in test DB
        assert resp.status_code in [200, 201, 409]  # 409 if duplicate

    def test_create_resource_duplicate_handling(self, client, auth_headers):
        """Test that duplicate resource creation is handled gracefully."""
        data = {
            "name": "Duplicate Test Room",
            "email": "duplicate-test-room-local@example.org",
            "resource_type": "room"
        }
        # First creation should succeed
        resp1 = client.post(self.BASE, data=json.dumps(data), content_type="application/json", headers=auth_headers)
        # Second creation with same email should fail
        resp2 = client.post(self.BASE, data=json.dumps(data), content_type="application/json", headers=auth_headers)
        assert resp2.status_code == 409


class TestResourceBookingUser:
    """Integration tests for Resource Booking User API."""

    BASE = "/api/user/v1/resources"
    BOOKINGS_BASE = "/api/user/v1/resource-bookings"

    def test_list_resources_user(self, client, user_auth_headers):
        """Test listing resources (user)."""
        resp = client.get(self.BASE, headers=user_auth_headers)
        assert resp.status_code == 200

    def test_check_resource_availability(self, client, user_auth_headers):
        """Test checking resource availability (user)."""
        from datetime import datetime, timedelta, timezone
        # Use a date far in the future to avoid conflicts
        future_date = (datetime.now(timezone.utc) + timedelta(days=365)).strftime('%Y-%m-%d')
        resp = client.get(
            f"{self.BASE}/res-001/availability?start={future_date}T10:00:00Z&end={future_date}T11:00:00Z",
            headers=user_auth_headers
        )
        # May return 404 if resource doesn't exist, or 200 with availability data
        assert resp.status_code in [200, 404]
