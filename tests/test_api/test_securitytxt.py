"""Tests for the RFC 9116 security.txt endpoint (CRA Art. 14(2))."""

import pytest

from app import create_app
from app.utils import constants as cs

# The blueprint is registered in the basic API group, which carries the
# /api/user/v1 prefix (same group as /health).
WELL_KNOWN = "/api/user/v1/.well-known/security.txt"
SHORT = "/api/user/v1/security.txt"


@pytest.fixture()
def client():
    app = create_app(cs.SOGO_NOT_INIT)
    app.config["TESTING"] = True
    return app.test_client()


def test_security_txt_well_known(client):
    """GET /.well-known/security.txt returns the disclosure policy."""
    resp = client.get(WELL_KNOWN)
    assert resp.status_code == 200
    assert resp.mimetype == "text/plain"
    body = resp.get_data(as_text=True)
    assert "Contact:" in body
    assert "Policy:" in body
    assert "CRA" in body or "coordinated" in body.lower()


def test_security_txt_short_path(client):
    """GET /security.txt also works (RFC 9116 recommends both)."""
    resp = client.get(SHORT)
    assert resp.status_code == 200
    assert "Contact:" in resp.get_data(as_text=True)


def test_security_txt_no_cache(client):
    """Policy should not be cached."""
    resp = client.get(WELL_KNOWN)
    assert resp.headers.get("Cache-Control") == "no-store"


def test_security_txt_public_without_auth(client):
    """security.txt must be reachable anonymously (CRA Art. 14(2))."""
    resp = client.get(WELL_KNOWN)
    assert resp.status_code == 200
    assert "Anonymous User On Protected Endpoint" not in resp.get_data(as_text=True)
