"""Tests for the RFC 9116 security.txt endpoint (CRA Art. 14(2))."""

import pytest


def test_security_txt_well_known(client):
    """GET /.well-known/security.txt returns the disclosure policy."""
    resp = client.get("/api/.well-known/security.txt")
    assert resp.status_code == 200
    assert resp.mimetype == "text/plain"
    body = resp.get_data(as_text=True)
    assert "Contact:" in body
    assert "Policy:" in body
    assert "CRA" in body or "coordinated" in body.lower()


def test_security_txt_short_path(client):
    """GET /security.txt also works (RFC 9116 recommends both)."""
    resp = client.get("/api/security.txt")
    assert resp.status_code == 200
    assert "Contact:" in resp.get_data(as_text=True)


def test_security_txt_no_cache(client):
    """Policy should not be cached."""
    resp = client.get("/api/.well-known/security.txt")
    assert resp.headers.get("Cache-Control") == "no-store"
