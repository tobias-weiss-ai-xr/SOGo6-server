"""HTTP integration tests for all admin API endpoints."""
import json
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
