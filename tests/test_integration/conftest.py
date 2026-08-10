"""Integration test fixtures — obtain real admin JWT via login API."""
import json
import pytest
from app import create_app
from app.utils import constants as cs
from app.config.init_config import process_config, init_infra


@pytest.fixture(scope="session")
def _app():
    """Create a Flask app for testing (session-scoped)."""
    application = create_app(cs.SOGO_OK)
    application.config["TESTING"] = True
    return application


@pytest.fixture
def app(_app):
    return _app


@pytest.fixture
def client(app):
    return app.test_client()


def _login( client, endpoint, username, password):
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
def _admin_token():
    """Obtain a real admin JWT."""
    app = create_app(cs.SOGO_OK)
    app.config["TESTING"] = True
    with app.test_client() as c:
        return _login(c, "/api/admin/v1/auth/login", "admin", "admin")


@pytest.fixture
def admin_token(_admin_token):
    return _admin_token


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def _user_token():
    """Obtain a real user JWT."""
    app = create_app(cs.SOGO_OK)
    app.config["TESTING"] = True
    with app.test_client() as c:
        return _login(c, "/api/user/v1/auth/login", "maxmustermann@example.org", "UniMarburg2026!")


@pytest.fixture
def user_token(_user_token):
    return _user_token


@pytest.fixture
def user_auth_headers(user_token):
    return {"Authorization": f"Bearer {user_token}"}
