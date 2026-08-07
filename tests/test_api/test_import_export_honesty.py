"""Honest-behavior tests for the PST/M365 import/export endpoints.

The discovery/analyze endpoints previously returned fabricated mailbox
inventories (hash-derived folder counts, "analysis": "simulated").  These
tests pin the honest behavior: M365 discovery calls the REAL Graph API with
the caller's token and surfaces failures, and PST analysis never prints
invented counts (engine gate via readpst presence).
"""
from __future__ import annotations

import json
import pathlib

import pytest

from app import create_app
from app.utils import constants as cs


@pytest.fixture()
def client():
    app = create_app(cs.SOGO_NOT_INIT)
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def authed_client(client, monkeypatch):
    """Same client, but the admin-authentic flows through a fake voucher
    session: generate_admin_from_voucher returns a human for any token, so the
    tested handlers actually run (that is the point of the smoke)."""
    from app.auth.Admin import Admin

    # The smorest admin blueprint instantiates VoucherAdminService before
    # calling generate_admin_from_voucher; skip the real ctor (it enforces a
    # 32-char secret that the test env does not provide) and fake the token
    # exchange.
    monkeypatch.setattr(
        "app.VoucherAdminService.__init__",
        lambda self, process_settings: None,
    )
    monkeypatch.setattr(
        "app.VoucherAdminService.generate_admin_from_voucher",
        staticmethod(lambda token: Admin("smoke-admin")),
    )
    client.environ_base["HTTP_AUTHORIZATION"] = "Bearer test-token"
    return client


class FakeResp:
    """requests.Response stand-in so tests never touch the network."""

    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


FAKE_FOLDER = {
    "id": "F1",
    "displayName": "Inbox",
    "totalItemCount": 120,
    "unreadItemCount": 3,
}


def test_m365_discover_graph_failure_is_honest(authed_client, monkeypatch):
    """A Graph 401 must yield a real error, not fabricated data."""
    def broken_get(url, headers, timeout):
        assert url.startswith("https://graph.microsoft.com/v1.0/users/")
        assert headers.get("Authorization") == "Bearer tok"
        return FakeResp(401, {"error": {"message": "Invalid scope"}})

    monkeypatch.setattr("requests.get", broken_get)
    resp = authed_client.post(
        "/api/admin/v1/admin/import/m365/discover",
        json={"email": "u@example.com", "access_token": "tok"},
    )
    assert resp.status_code == 501  # S0003B5
    body = resp.get_json()
    assert "simulated" not in json.dumps(body)
    assert body["error_code"] == "S0003B5"


def test_graph_discover_success_uses_real_payload(authed_client, monkeypatch):
    calls = {}

    def fake_get(url, **kwargs):
        calls["url"] = url
        calls["auth"] = kwargs["headers"]["Authorization"]
        calls["timeout"] = kwargs["timeout"]
        return FakeResp(200, {"value": [FAKE_FOLDER]})

    monkeypatch.setattr("requests.get", fake_get)
    resp = authed_client.post(
        "/api/admin/v1/admin/import/m365/discover",
        json={"email": "u@example.com", "access_token": "tok"},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert "simulated" not in json.dumps(data)
    assert data["total_messages"] == 120  # real sum from Graph
    assert data["folders"][0]["displayName"] == "Inbox"
    assert "AQMk" not in json.dumps(data)  # no hash-invented ids
    assert calls["auth"] == "Bearer tok"
    assert calls["timeout"] == (3.05, 30)
    assert "u%40example.com" in calls["url"] or "u@example.com" in calls["url"]


def test_pst_analyze_never_invents_counts(authed_client, monkeypatch):
    import app.api.v1.admin.ApiImportExport as mod

    monkeypatch.setattr(mod.shutil, "which", lambda name: None)  # no readpst
    # Path with no traversal/absolute prefix: passes the handler's security
    # gate so the engine gate itself is what we exercise.
    pst = pathlib.Path("pst_smoke_sample.pst")
    pst.write_bytes(b"!BDN" + b"\x00" * 60)
    try:
        resp = authed_client.post(
            "/api/admin/v1/admin/import/pst/analyze",
            json={"pst_path": "pst_smoke_sample.pst"},
        )
    finally:
        pst.unlink(missing_ok=True)
    assert resp.status_code == 501  # S0003B3 engine unavailable
    body = resp.get_json()
    assert "estimated_messages" not in json.dumps(body)
    assert "simulated" not in json.dumps(body)
    assert body["data"]["pst"]["valid"] is True
    assert body["data"]["pst"]["format"] == "ansi"


def test_pst_analyze_missing_file(authed_client):
    resp = authed_client.post(
        "/api/admin/v1/admin/import/pst/analyze",
        json={"pst_path": "no_such_file_here.pst"},
    )
    assert resp.status_code == 400  # success=False -> 400
    body = resp.get_json()
    if isinstance(body, list):  # smorest error envelope
        body = body[0]
    # the handler's honest code sits either top-level or inside data
    inner = body.get("data") if isinstance(body.get("data"), dict) else {}
    code = inner.get("error_code") or body.get("error_code")
    assert code == "E000008"


def test_m365_import_graph_failure_does_not_create_job(authed_client, monkeypatch):
    monkeypatch.setattr(
        "requests.get",
        lambda url, **kwargs: FakeResp(403, {"error": {"message": "forbidden"}}),
    )
    resp = authed_client.post(
        "/api/admin/v1/admin/import/m365/import",
        json={"email": "u@example.com", "access_token": "tok", "target_user": "t"},
    )
    assert resp.status_code == 501  # S0003B5
    assert "job_id" not in resp.get_json()["data"]