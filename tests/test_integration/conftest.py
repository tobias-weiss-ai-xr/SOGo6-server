"""Integration test fixtures with real auth."""
import pytest
from app import create_app
from app.utils import constants as cs
from app.auth.voucher.JWTVoucher import JWTVoucher
from app.config.init_config import process_config


@pytest.fixture
def app():
    """Create a Flask app for testing."""
    application = create_app(cs.SOGO_OK)
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def admin_token():
    """Generate a valid admin JWT for testing."""
    secret = process_config.SOGO_P_VOUCHER_SECRET
    voucher = JWTVoucher(secret)
    payload = {
        "uid": "admin",
    }
    return voucher.create_voucher(payload, 3600)


@pytest.fixture
def auth_headers(admin_token):
    """Authorization headers for admin API calls."""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def user_token():
    """Generate a valid user JWT for testing."""
    secret = process_config.SOGO_P_VOUCHER_SECRET
    voucher = JWTVoucher(secret)
    payload = {
        "uid": "maxmustermann@example.org",
    }
    return voucher.create_voucher(payload, 3600)


@pytest.fixture
def user_auth_headers(user_token):
    """Authorization headers for user API calls."""
    return {"Authorization": f"Bearer {user_token}"}
