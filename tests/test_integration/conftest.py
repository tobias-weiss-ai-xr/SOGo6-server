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


@pytest.fixture(scope="session")
def _admin_token():
    """Obtain a real admin JWT by calling the login endpoint via test client."""
    app = create_app(cs.SOGO_OK)
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.post(
            "/api/admin/v1/auth/login",
            data=json.dumps({"username": "admin", "password": "admin"}),
            content_type="application/json",
        )
        data = resp.get_json()
        if data and data.get("data") and data["data"].get("jwt_token"):
            return data["data"]["jwt_token"]
        # Fallback: try the app context directly
        raise RuntimeError(f"Could not obtain admin token: {data}")


@pytest.fixture
def admin_token(_admin_token):
    return _admin_token


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}
