"""Live-stack integration tests for the Agent Action Layer.

Runs against the full stack (MariaDB + Redis + optional LDAP) following the
existing integration fixtures; skips gracefully where the stack is absent.
"""
import json
import time


import pytest



@pytest.fixture
def mint_token(app):
    """Mint a real API token directly into the live Redis (no UI/login needed).

    Mirrors POST /api/user/v1/api-tokens: metadata + hash index + user index,
    with the encrypted user_session blob so requests rebuild a full User.
    """
    from app.api.v1.user import ApiApiTokens as m
    from app.auth.User import User
    from app.service import sogo_cache
    from json import dumps as js_dumps

    from app.module.user.ModuleUserProfile import ModuleUserProfile
    from app.config.init_config import init_get_system_and_default_domain_settings
    from app.config.settings.ProcessSetting import process_config

    _system, default_domain_settings = init_get_system_and_default_domain_settings()

    def _mint(uid: str = "agent-it", domain: str = "example.org", scopes: list | None = None):
        user = User(uid, "integration-test-password", domain=domain)
        # Mirror login onboarding: a token user needs a profile row, exactly
        # like a real first login would have created.
        profile_module = ModuleUserProfile(process_config, default_domain_settings)
        if not profile_module.is_user_profile_present(user.uid):
            profile_module.create_user_profile(user)
        token = m._generate_token()
        token_hash = m._hash_token(token)
        token_id = token_hash[:16]
        cache = sogo_cache()
        data = {
            "label": "agent-it",
            "scopes": scopes or ["read"],
            "created_at": int(time.time()),
            "expires_at": None,
            "last_used_at": None,
            "user_session": m._session_cipher(process_config)
            .encrypt(js_dumps(user.get_user_session()).encode("utf-8"))
            .decode("utf-8"),
        }
        cache.set(f"{m._API_TOKEN_PREFIX}{uid}:{token_id}", js_dumps(data), ttl=3600)
        cache.set(f"{m._API_TOKEN_HASH_PREFIX}{token_hash}", f"{uid}:{token_id}", ttl=3600)
        return token, token_id

    return _mint


class TestAgentHappyPaths:
    """3.1 — token → facade action → revoke → 401 (token store is the real Redis)."""

    def test_manifest_token_lifecycle(self, client, mint_token):
        token, token_id = mint_token()
        headers = {"Authorization": f"Bearer {token}"}

        manifest = client.get("/api/user/v1/agent/manifest", headers=headers)
        assert manifest.status_code == 200
        actions = manifest.get_json()["data"]["actions"]
        assert any(a["id"] == "mail.messages.list" for a in actions)

        # revoke (delete from token store = what DELETE /api-tokens/{id} does)
        from app.api.v1.user import ApiApiTokens as m
        from app.auth.User import User
        from app.service import sogo_cache
        sogo_cache().delete(f"{m._API_TOKEN_PREFIX}agent-it:{token_id}")

        again = client.get("/api/user/v1/agent/manifest", headers=headers)
        assert again.status_code == 401

    def test_manifest_with_voucher_session(self, client, user_auth_headers):
        """UI AI panel path: session voucher has no token_scopes → allowed."""
        manifest = client.get("/api/user/v1/agent/manifest", headers=user_auth_headers)
        assert manifest.status_code == 200

    def test_anonymous_rejected(self, client):
        manifest = client.get("/api/user/v1/agent/manifest")
        assert manifest.status_code == 401


class TestScopeEnforcement:
    """3.2 — mail:read token calling send → 403 S000513."""

    def test_read_token_cannot_send(self, client, mint_token):
        token, _ = mint_token(scopes=["mail:read"])

        resp = client.post(
            "/api/user/v1/agent/mail/send",
            data=json.dumps({"from": "agent@example.org", "to": ["to@example.org"],
                             "subject": "x", "body": "x"}),
            content_type="application/json",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        assert resp.get_json().get("error_code") == "S000513"

    def test_calendar_read_token_cannot_write(self, client, mint_token):
        token, _ = mint_token(scopes=["calendar:read"])

        resp = client.post(
            "/api/user/v1/agent/calendar/events",
            data=json.dumps({"title": "nope"}),
            content_type="application/json",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        assert resp.get_json().get("error_code") == "S000513"

    def test_read_class_grants_module_reads(self, client, mint_token):
        """`read` grants mail:read + calendar:read + contacts:read."""
        token, _ = mint_token(scopes=["read"])

        headers = {"Authorization": f"Bearer {token}"}
        # No backend contact: scope check must PASS (403 forbidden only on
        # missing scope) — interface errors surface as other codes.
        events = client.get(
            "/api/user/v1/agent/calendar/events?from=2026-01-01T00:00:00Z&to=2026-01-31T00:00:00Z",
            headers=headers,
        )
        assert events.status_code != 403


class TestImpersonation:
    """3.3 — admin issues token → acts as target → revoke → 401."""

    TARGET = "maxmustermann@example.org"

    def _issue(self, client, auth_headers, scopes=("calendar:read",)):
        resp = client.post(
            "/api/admin/v1/impersonation-tokens",
            data=json.dumps({"target_uid": self.TARGET, "scopes": list(scopes), "label": "agent-it"}),
            content_type="application/json",
            headers=auth_headers,
        )
        data = resp.get_json()
        payload = data.get("data") if isinstance(data, dict) else None
        token = payload.get("token") if isinstance(payload, dict) else None
        if resp.status_code != 200 or not token:
            pytest.skip(f"impersonation issue unavailable: {resp.status_code} {data}")
        return token, payload

    def test_issue_act_revoke(self, client, auth_headers):
        import os
        if os.environ.get("SOGO_TEST_USER"):
            self.TARGET = os.environ["SOGO_TEST_USER"]

        token, meta = self._issue(client, auth_headers)
        assert token.startswith("sogoimp_")
        assert meta["target_uid"] == self.TARGET

        headers = {"Authorization": f"Bearer {token}"}
        manifest = client.get("/api/user/v1/agent/manifest", headers=headers)
        assert manifest.status_code == 200, "impersonated token must act as target (basic tier)"

        events = client.get("/api/user/v1/agent/calendar/events", headers=headers)
        assert events.status_code != 403, "calendar:read scope must be granted"

        revoke = client.delete(f"/api/admin/v1/impersonation-tokens/{meta['id']}", headers=auth_headers)
        assert revoke.status_code in (200, 204)
        assert client.get("/api/user/v1/agent/manifest", headers=headers).status_code == 401

    def test_impersonation_requires_admin(self, client, user_auth_headers):
        resp = client.post(
            "/api/admin/v1/impersonation-tokens",
            data=json.dumps({"target_uid": self.TARGET, "scopes": ["read"]}),
            content_type="application/json",
            headers=user_auth_headers,
        )
        assert resp.status_code in (401, 403)
