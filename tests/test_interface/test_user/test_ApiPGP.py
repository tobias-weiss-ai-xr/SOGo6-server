"""Functional tests for ApiPGP — key generate/get/delete + encrypt/decrypt,
with PGPKeyManager mocked.
"""
from types import SimpleNamespace
from unittest import mock

import pytest
from flask import Flask, g

from app.api.v1.user.ApiPGP import blp
from app.utils import errors as err

MOD = "app.api.v1.user.ApiPGP"

USER = SimpleNamespace(uid="user-1")

ARMORED_KEY = (
    "-----BEGIN PGP PUBLIC KEY BLOCK-----\n"
    "YWJjZA==\n"
    "-----END PGP PUBLIC KEY BLOCK-----\n"
)


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.before_request
    def _set_user():
        g.user = USER

    app.register_blueprint(blp)

    with mock.patch(f"{MOD}.PGPKeyManager") as mgr_cls:
        mgr = mgr_cls.return_value
        yield app.test_client(), mgr


class TestGenerate:
    def test_generate_ok(self, client):
        c, mgr = client
        mgr.has_keypair.return_value = False
        mgr.generate_keypair.return_value = {"fingerprint": "A" * 40, "public_key": ARMORED_KEY}
        resp = c.post("/pgp/key/generate", json={"passphrase": "secret"})
        assert resp.status_code == 201
        assert resp.json["data"]["fingerprint"] == "A" * 40
        mgr.generate_keypair.assert_called_once_with("user-1", passphrase="secret")

    def test_generate_default_passphrase(self, client):
        c, mgr = client
        mgr.has_keypair.return_value = False
        mgr.generate_keypair.return_value = {"fingerprint": "B" * 40}
        resp = c.post("/pgp/key/generate", json={})
        assert resp.status_code == 201
        mgr.generate_keypair.assert_called_once_with("user-1", passphrase="")

    def test_generate_already_exists(self, client):
        c, mgr = client
        mgr.has_keypair.return_value = True
        resp = c.post("/pgp/key/generate", json={})
        assert resp.status_code == err.ERROR_PGP_KEY_ALREADY_EXISTS.h
        assert resp.json["error_code"] == err.ERROR_PGP_KEY_ALREADY_EXISTS.c
        mgr.generate_keypair.assert_not_called()


class TestGetKey:
    def test_get_key_ok(self, client):
        c, mgr = client
        mgr.get_public_key.return_value = ARMORED_KEY
        resp = c.get("/pgp/key")
        assert resp.status_code == 200
        data = resp.json["data"]
        assert data["public_key"] == ARMORED_KEY
        # fingerprint derived from the armored key (sha256 hex, 40 chars upper)
        assert len(data["fingerprint"]) == 40

    def test_get_key_not_found(self, client):
        c, mgr = client
        mgr.get_public_key.return_value = None
        resp = c.get("/pgp/key")
        assert resp.status_code == err.ERROR_PGP_KEY_NOT_FOUND.h
        assert resp.json["error_code"] == err.ERROR_PGP_KEY_NOT_FOUND.c

    def test_get_key_unarmorable(self, client):
        c, mgr = client
        mgr.get_public_key.return_value = "no armor here"
        resp = c.get("/pgp/key")
        assert resp.status_code == 200
        assert resp.json["data"]["fingerprint"] == ""


class TestDeleteKey:
    def test_delete_ok(self, client):
        c, mgr = client
        resp = c.delete("/pgp/key")
        assert resp.status_code == 200
        assert resp.json["data"] == {"status": "deleted"}
        mgr.delete_keypair.assert_called_once_with("user-1")


class TestEncrypt:
    def test_encrypt_ok(self, client):
        c, mgr = client
        mgr.get_public_key.return_value = ARMORED_KEY
        mgr.encrypt_message.return_value = "-----BEGIN PGP MESSAGE-----"
        resp = c.post("/pgp/encrypt", json={"message": "hello", "recipient": "b@x.org"})
        assert resp.status_code == 200
        assert resp.json["data"]["encrypted"] == "-----BEGIN PGP MESSAGE-----"
        mgr.encrypt_message.assert_called_once_with("hello", ARMORED_KEY)

    def test_encrypt_recipient_no_key(self, client):
        c, mgr = client
        mgr.get_public_key.return_value = None
        resp = c.post("/pgp/encrypt", json={"message": "hello", "recipient": "nobody@x.org"})
        assert resp.status_code == err.ERROR_PGP_RECIPIENT_KEY_NOT_FOUND.h
        assert resp.json["error_code"] == err.ERROR_PGP_RECIPIENT_KEY_NOT_FOUND.c

    def test_encrypt_failure(self, client):
        c, mgr = client
        mgr.get_public_key.return_value = ARMORED_KEY
        mgr.encrypt_message.side_effect = ValueError("boom")
        resp = c.post("/pgp/encrypt", json={"message": "hello", "recipient": "b@x.org"})
        assert resp.status_code == err.ERROR_PGP_ENCRYPT_FAILED.h
        assert resp.json["error_code"] == err.ERROR_PGP_ENCRYPT_FAILED.c

    def test_encrypt_validation(self, client):
        c, _ = client
        resp = c.post("/pgp/encrypt", json={})
        assert resp.status_code == 422


class TestDecrypt:
    def test_decrypt_ok(self, client):
        c, mgr = client
        mgr.get_private_key.return_value = ARMORED_KEY
        mgr.decrypt_message.return_value = "top secret"
        resp = c.post("/pgp/decrypt", json={"armored_message": "MSG"})
        assert resp.status_code == 200
        assert resp.json["data"]["plaintext"] == "top secret"
        mgr.decrypt_message.assert_called_once_with("MSG", ARMORED_KEY)

    def test_decrypt_no_key(self, client):
        c, mgr = client
        mgr.get_private_key.return_value = None
        resp = c.post("/pgp/decrypt", json={"armored_message": "MSG"})
        assert resp.status_code == err.ERROR_PGP_KEY_NOT_FOUND.h
        assert resp.json["error_code"] == err.ERROR_PGP_KEY_NOT_FOUND.c

    def test_decrypt_failure(self, client):
        c, mgr = client
        mgr.get_private_key.return_value = ARMORED_KEY
        mgr.decrypt_message.side_effect = ValueError("bad")
        resp = c.post("/pgp/decrypt", json={"armored_message": "MSG"})
        assert resp.status_code == err.ERROR_PGP_DECRYPT_FAILED.h
        assert resp.json["error_code"] == err.ERROR_PGP_DECRYPT_FAILED.c
