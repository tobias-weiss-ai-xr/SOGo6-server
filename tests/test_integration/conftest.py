"""Integration test fixtures — real bootstrap + real admin JWT via login API.

Module-level init_sogo() replicates app/run.py startup: creates all tables
on an empty DB, seeds system/domain settings from SOGO_INIT_*_PATH JSONs.
Requires live MariaDB + Redis (CI provides service containers).
"""
import json
import os
import pytest
from app import create_app
from app.config.init_config import init_sogo
from app.service import set_cache, set_agent

sogo_state, _cache, _agent = init_sogo()
set_cache(_cache)
set_agent(_agent)


@pytest.fixture(scope="session")
def _app():
    """Create a Flask app for testing (session-scoped)."""
    application = create_app(sogo_state)
    application.config["TESTING"] = True
    # mirrors app/run.py: UI sends trailing-slash URLs that strict matching 308s
    application.url_map.strict_slashes = False
    return application


@pytest.fixture
def app(_app):
    return _app


@pytest.fixture
def client(app):
    return app.test_client()


def _login(client, endpoint, username, password):
    """Helper to obtain a JWT token."""
    resp = client.post(
        endpoint,
        data=json.dumps({"username": username, "password": password}),
        content_type="application/json",
    )
    data = resp.get_json()
    if data and data.get("data") and data["data"].get("jwt_token"):
        return data["data"]["jwt_token"]
    raise RuntimeError(f"Could not obtain token: {data}")


@pytest.fixture(scope="session")
def _admin_token(_app):
    """Obtain a real admin JWT."""
    with _app.test_client() as c:
        return _login(c, "/api/admin/v1/auth/login", "admin", os.environ.get("SOGO_P_ADMIN_PWD", "admin"))


@pytest.fixture
def admin_token(_admin_token):
    return _admin_token


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def _user_token(_app):
    """Obtain a real user JWT. The seeded user source is LDAP — skip
    gracefully where no LDAP with the test user exists (CI service set is
    mariadb+redis only; the superproject test-stack boots LDAP with the
    seed defaults below). Live stacks override SOGO_TEST_USER/
    SOGO_TEST_PASSWORD (e.g. prod DN on 42.20)."""
    username = os.environ.get("SOGO_TEST_USER", "maxmustermann@example.org")
    password = os.environ.get("SOGO_TEST_PASSWORD", "UniMarburg2026!")
    with _app.test_client() as c:
        resp = c.post(
            "/api/user/v1/auth/login",
            data=json.dumps({"username": username, "password": password}),
            content_type="application/json",
        )
        data = resp.get_json()
        if not (data and data.get("data") and data["data"].get("jwt_token")):
            pytest.skip("user login unavailable (no LDAP user source in this environment)")
        return data["data"]["jwt_token"]


@pytest.fixture
def user_token(_user_token):
    return _user_token


@pytest.fixture
def user_auth_headers(user_token):
    return {"Authorization": f"Bearer {user_token}"}
