"""Matrix Chat — real Ed25519 federation signing (replaces HMAC fake).

These tests assert:
- The server generates and persists an Ed25519 key pair on POST /config.
- /serverkey returns the public key in Matrix Server-Server v2 format.
- Outbound messages are signed with Ed25519 signatures (64 bytes → 86 base64
  chars), NOT the former HMAC-SHA256 hex digest.
- Legacy hex seeds (migration path) still work.
"""
from __future__ import annotations

import json
import secrets

import pytest

from app import create_app
from app.utils import constants as cs
from app.service import sogo_cache

ADMIN = "/api/admin/v1/matrix"


@pytest.fixture()
def admin_client(monkeypatch):
    from app.auth.Admin import Admin

    app = create_app(cs.SOGO_NOT_INIT)
    app.config["TESTING"] = True
    monkeypatch.setattr("app.VoucherAdminService.__init__", lambda self, ps: None)
    monkeypatch.setattr(
        "app.VoucherAdminService.generate_admin_from_voucher",
        staticmethod(lambda token: Admin("smoke-admin")),
    )
    return app.test_client()


@pytest.fixture(autouse=True)
def _isolate():
    cache = sogo_cache()
    cache.delete(
        "mx_room:config", "mx_room:index",
        "mx_link:index", "mx_msg:index",
        "mx_key:https://matrix.org",
    )


# ------------------------------------------------------------------------
# Config & key management
# ------------------------------------------------------------------------
def _default_config_payload():
    return {
        "homeserver": "https://matrix.org",
        "enabled": True,
        "bridge_enabled": False,
        "widget_url": "/matrix/widget",
    }


def test_post_config_generates_and_stores_ed25519_key(admin_client):
    payload = _default_config_payload()
    resp = admin_client.post(
        f"{ADMIN}/config",
        json=payload,
        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["signing_key_preview"]
    assert "..." in data["signing_key_preview"]
    assert len(data["signing_key_preview"]) <= 12


def test_get_serverkey_returns_ed25519_public_key(admin_client):
    # First configure
    admin_client.post(f"{ADMIN}/config", json=_default_config_payload(),
                      headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"})

    resp = admin_client.get(f"{ADMIN}/serverkey", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["server_name"] == "https://matrix.org"
    assert "verify_keys" in data
    verify_keys = data["verify_keys"]
    assert len(verify_keys) == 1
    key_id, key_info = next(iter(verify_keys.items()))
    assert key_id.startswith("ed25519:")
    # Ed25519 public key is 32 bytes → base64 is 44 chars
    assert len(key_info["key"]) == 44


def test_serverkey_fails_without_config(admin_client):
    resp = admin_client.get(f"{ADMIN}/serverkey", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 400
    body = resp.get_json()
    if isinstance(body, list):
        body = body[0]
    # The envelope wraps our response in body['data']
    assert body["data"]["success"] is False
    assert "E000004" in body["data"]["error_code"]


# ------------------------------------------------------------------------
# Real Ed25519 signing on messages (not HMAC)
# ------------------------------------------------------------------------
def test_send_message_signed_with_ed25519_not_hmac(admin_client):
    # Configure with key
    admin_client.post(f"{ADMIN}/config", json=_default_config_payload(),
                      headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"})

    room_id = "!test:local"
    resp = admin_client.post(
        f"{ADMIN}/rooms/{room_id}/send",
        json={"sender": "alice", "content": "Hello world"},
        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    event = resp.get_json()["data"]
    assert "signatures" in event
    sigs = event["signatures"]
    # Server name key
    assert "https://matrix.org" in sigs
    server_sigs = sigs["https://matrix.org"]
    key_id, sig_b64 = next(iter(server_sigs.items()))
    # Ed25519 signature is 64 bytes → base64 length 88 (with padding)
    assert len(sig_b64) == 88
    # Must NOT be a 64-char hex string (old HMAC length)
    try:
        int(sig_b64, 16)
        assert False, "Signature must NOT be hex (old HMAC)"
    except ValueError:
        pass  # expected – base64 not hex


def test_send_message_no_signature_without_key(admin_client):
    # POST config without signing_key AND without default generation
    # Work around: first store a raw config with no keys
    cache = sogo_cache()
    cache.set("mx_room:config", json.dumps({"homeserver": "https://nowhere.net", "enabled": True}), 3600)
    # clear any auto-generated keys
    cache.delete("mx_key:https://nowhere.net")

    resp = admin_client.post(
        f"{ADMIN}/rooms/!nowhere/send",
        json={"sender": "alice", "content": "Hello"},
        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    event = resp.get_json()["data"]
    assert "signatures" not in event


# ------------------------------------------------------------------------
# Ed25519 unit tests on the signer
# We import the module *directly* to avoid loading app/__init__.py which
# requires SOGO_* environment variables at import time.
# ------------------------------------------------------------------------
@pytest.fixture(scope="session")
def matrix_signing_module():
    import sys
    from importlib.util import module_from_spec, spec_from_file_location

    path = "app/service/matrix/MatrixSigning.py"
    spec = spec_from_file_location("MatrixSigning", path)
    mod = module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules["MatrixSigning"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_ed25519_sign_verify_roundtrip(matrix_signing_module):
    MatrixSigningKey = matrix_signing_module.MatrixSigningKey
    key = MatrixSigningKey()
    event = {"room_id": "!foo", "type": "m.test", "content": {}}
    sig_b64 = key.sign_pdu(event)
    assert len(sig_b64) == 88  # 64 bytes → base64 with padding = 88
    assert key.verify_pdu(event, sig_b64) is True


def test_ed25519_fails_tampered_event(matrix_signing_module):
    MatrixSigningKey = matrix_signing_module.MatrixSigningKey
    key = MatrixSigningKey()
    event = {"room_id": "!foo", "type": "m.test", "content": {}}
    sig_b64 = key.sign_pdu(event)
    event["content"]["extra"] = 1
    assert key.verify_pdu(event, sig_b64) is False


def test_ed25519_fails_wrong_key(matrix_signing_module):
    MatrixSigningKey = matrix_signing_module.MatrixSigningKey
    key1 = MatrixSigningKey()
    key2 = MatrixSigningKey()
    event = {"room_id": "!foo"}
    sig = key1.sign_pdu(event)
    assert key2.verify_pdu(event, sig) is False


def test_seed_determinism(matrix_signing_module):
    MatrixSigningKey = matrix_signing_module.MatrixSigningKey
    seed = "a" * 43  # 43 urlsafe base64 chars encodes 32 bytes
    k1 = MatrixSigningKey(seed)
    k2 = MatrixSigningKey(seed)
    assert k1.private_seed_b64 == k2.private_seed_b64
    assert k1.public_key_b64 == k2.public_key_b64


def test_hex_seed_migration(matrix_signing_module):
    MatrixSigningKey = matrix_signing_module.MatrixSigningKey
    hex_seed = secrets.token_hex(32)
    key = MatrixSigningKey(hex_seed)
    assert key.private_seed_b64
    assert len(key.public_key_b64) == 44
