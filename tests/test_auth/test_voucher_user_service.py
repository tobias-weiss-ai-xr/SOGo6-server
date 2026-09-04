# pylint: disable=invalid-sequence-index
"""Unit tests for VoucherUserService (16% -> ~high).

Exercises session voucher generation, redis session-key extraction, user
rehydration from voucher payload, MFA short-lived vouchers and the
session-from-payload internals. Uses a real JWTVoucher + in-memory cache,
patching only the lazy ``sogo_cache`` import.
"""
from __future__ import annotations

import json
import os
import time

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

from unittest.mock import MagicMock, patch

import pytest

from app.utils import constants as cs
from app.utils.exceptions import RequestException, AggravatedException


# ─────────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────────

class FakeCache:
    def __init__(self):
        self.hashes = {}
        self.zsets = {}
        self.closed = False

    def hashset(self, key, mapping, ttl=None, **kwargs):
        h = self.hashes.setdefault(key, {})
        h.update(mapping)
        return True

    def hashget(self, key, field=None):
        h = self.hashes.get(key)
        if h is None:
            return None
        if field is None:
            return h
        return h.get(field)

    def zset_add(self, key, member, score):
        self.zsets.setdefault(key, {})[member] = score
        return 1

    def zset_remove(self, key, *members):
        z = self.zsets.get(key)
        if not z:
            return 0
        n = 0
        for m in members:
            if m in z:
                del z[m]
                n += 1
        return n

    def close(self):
        self.closed = True


@pytest.fixture
def service(fake_cache):
    from app.config.settings.ProcessSetting import ProcessSetting
    from app.auth.service.VoucherUserService import VoucherUserService

    settings = MagicMock(spec=ProcessSetting)
    secret = os.environ["SOGO_P_VOUCHER_SECRET"]
    settings.SOGO_P_VOUCHER_SECRET = secret

    def _getitem(name):
        return getattr(settings, name)

    settings.__getitem__.side_effect = _getitem
    with patch("app.auth.service.VoucherUserService.sogo_cache", return_value=fake_cache):
        yield VoucherUserService(settings)


@pytest.fixture
def fake_cache():
    return FakeCache()


def _make_user(uid="user@example.org", domain="example.org", session=None):
    user = MagicMock()
    user.uid = uid
    user.domain = domain
    default_session = {
        "uid": uid,
        "password": "pw",
        "domain": domain,
        "email": uid,
        "source_id": "ldap-main",
        "role": "user",
    }
    user.get_user_session.return_value = session or default_session
    user.get_voucher_payload.return_value = {"uid": uid}
    user.__str__ = lambda self: uid
    return user


# ─────────────────────────────────────────────────────────────────────────────
# Constructor
# ─────────────────────────────────────────────────────────────────────────────

class TestInit:
    def test_rejects_short_secret(self):
        from app.config.settings.ProcessSetting import ProcessSetting
        from app.auth.service.VoucherUserService import VoucherUserService

        settings = MagicMock(spec=ProcessSetting)
        settings.SOGO_P_VOUCHER_SECRET = "short"
        with pytest.raises(AggravatedException):
            VoucherUserService(settings)

    def test_accepts_32_char_secret(self, service):
        assert service.fernet_session is not None


# ─────────────────────────────────────────────────────────────────────────────
# generate_voucher_from_user
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateVoucher:
    def test_generates_voucher_and_stores_session(self, service, fake_cache):
        user = _make_user()
        voucher = service.generate_voucher_from_user(user)

        assert isinstance(voucher, str)
        # User session stored under redis prefix
        assert len(fake_cache.hashes) == 1
        session_key = next(iter(fake_cache.hashes))
        assert session_key.startswith("user_session:")
        session = fake_cache.hashes[session_key]
        assert session[cs.USER_UID] == "user@example.org"
        assert session[cs.USER_DOMAIN] == "example.org"
        assert cs.SESSION_SENSITIVE in session
        # Indexed in the three sorted sets
        assert fake_cache.zsets.get(cs.ZSET_USER_SESSIONS_ACTIVITY)
        assert fake_cache.zsets.get(cs.ZSET_USER_SESSIONS_UID)
        assert fake_cache.zsets.get(cs.ZSET_USER_SESSIONS_DOMAIN)
        assert fake_cache.closed is True

    def test_session_encrypt_failure_raises_bug(self, service, fake_cache):
        from app.utils.exceptions import BugException
        from cryptography.fernet import InvalidToken

        class BrokenFernet:
            def __init__(self, *a, **k):
                pass

            def encrypt(self, data):
                raise InvalidToken

        user = _make_user()
        with patch("app.auth.service.VoucherUserService.Fernet", BrokenFernet):
            with pytest.raises(BugException):
                service.generate_voucher_from_user(user)

    def test_voucher_token_encrypt_failure_raises_bug(self, service, fake_cache):
        from app.utils.exceptions import BugException
        from cryptography.fernet import InvalidToken

        user = _make_user()
        # Patch just the voucher-session-token Fernet path: force self.fernet_session
        # (class attr) to be a broken one AFTER passed-secret validation is done.
        class BrokenFernet:
            def __init__(self, *a, **k):
                pass

            def encrypt(self, data):
                raise InvalidToken

            def decrypt(self, data):
                raise InvalidToken

        service.fernet_session = BrokenFernet()
        with pytest.raises(BugException):
            service.generate_voucher_from_user(user)

    def test_generated_voucher_contains_session_key(self, service, fake_cache):
        user = _make_user()
        voucher = service.generate_voucher_from_user(user)
        import jwt

        payload = jwt.decode(
            voucher, os.environ["SOGO_P_VOUCHER_SECRET"], algorithms=["HS256"]
        )
        assert cs.SESSION_KEY in payload
        assert payload["uid"] == "user@example.org"
        assert payload[cs.JWT_ISS] == "SOGo6"


# ─────────────────────────────────────────────────────────────────────────────
# get_redis_session_key_from_voucher
# ─────────────────────────────────────────────────────────────────────────────

class TestGetSessionKey:
    def test_roundtrip_returns_session_key(self, service):
        user = _make_user()
        voucher = service.generate_voucher_from_user(user)
        key = service.get_redis_session_key_from_voucher(voucher)
        assert key.startswith("user_session:")

    def test_rejects_non_string_voucher(self, service):
        with pytest.raises(RequestException):
            service.get_redis_session_key_from_voucher(12345)

    def test_rejects_expired_voucher(self, service):
        from app.auth.voucher.JWTVoucher import JWTVoucher
        import jwt

        secret = os.environ["SOGO_P_VOUCHER_SECRET"]
        expired = jwt.encode(
            {"user_uid": "x", cs.SESSION_KEY: "zz", "exp": int(time.time()) - 100},
            secret,
            algorithm="HS256",
        )
        with pytest.raises(RequestException):
            service.get_redis_session_key_from_voucher(expired)

    def test_rejects_malformed_session_key(self, service):
        from app.auth.voucher.JWTVoucher import JWTVoucher
        import jwt

        secret = os.environ["SOGO_P_VOUCHER_SECRET"]
        # Encrypt a session key without a colon
        from cryptography.fernet import Fernet
        from base64 import urlsafe_b64encode

        f = Fernet(urlsafe_b64encode(secret.encode("utf-8")))
        crypted = f.encrypt(b"nocolonhere").decode("utf-8")
        token = jwt.encode({"uid": "x", cs.SESSION_KEY: crypted}, secret, algorithm="HS256")
        with pytest.raises(RequestException):
            service.get_redis_session_key_from_voucher(token)

    def test_cannot_decrypt_session_key_raises_request(self, service):
        """Line 141-142: invalid Fernet ciphertext -> RequestException."""
        from cryptography.fernet import InvalidToken
        from app.auth.voucher.JWTVoucher import JWTVoucher
        import jwt

        secret = os.environ["SOGO_P_VOUCHER_SECRET"]
        # Token carries a session_key that is NOT Fernet-encrypted -> decrypt raises
        crypted = "not-a-fernet-ciphertext-value!!"
        token = jwt.encode({"uid": "x", cs.SESSION_KEY: crypted}, secret, algorithm="HS256")

        class BrokenFernet:
            def __init__(self, *a, **k):
                pass

            def decrypt(self, data):
                raise InvalidToken

        service.fernet_session = BrokenFernet()
        with pytest.raises(RequestException):
            service.get_redis_session_key_from_voucher(token)


# ─────────────────────────────────────────────────────────────────────────────
# generate_user_from_voucher  (full rehydration)
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateUserFromVoucher:
    def test_rehydrates_user(self, service, fake_cache):
        from app.auth.User import User

        user = _make_user()
        voucher = service.generate_voucher_from_user(user)
        # We stored a mocked session; _get_user_session_from_payload needs a
        # JSON-sensitive field and matching uid — the fake session qualifies.
        rehydrated = service.generate_user_from_voucher(voucher)
        assert rehydrated is not None

    def test_rejects_wrong_type(self, service):
        with pytest.raises(RequestException):
            service.generate_user_from_voucher({"not": "a string"})

    def test_rejects_expired(self, service):
        import jwt

        secret = os.environ["SOGO_P_VOUCHER_SECRET"]
        expired = jwt.encode(
            {"user_uid": "x", cs.SESSION_KEY: "abc", "exp": int(time.time()) - 5},
            secret,
            algorithm="HS256",
        )
        with pytest.raises(RequestException):
            service.generate_user_from_voucher(expired)


# ─────────────────────────────────────────────────────────────────────────────
# MFA vouchers
# ─────────────────────────────────────────────────────────────────────────────

class TestMfaVoucher:
    def test_generate_and_decode(self, service):
        token = service.generate_mfa_voucher("user@example.org")
        assert isinstance(token, str)
        payload = service.decode_mfa_voucher(token)
        assert payload["sub"] == "user@example.org"
        assert payload["scope"] == "mfa_challenge"
        assert "exp" in payload and "iat" in payload and "jti" in payload

    def test_decode_wrong_scope(self, service):
        import jwt

        secret = os.environ["SOGO_P_VOUCHER_SECRET"]
        token = jwt.encode(
            {"sub": "x", "uid": "x", "scope": "other", "exp": int(time.time()) + 100},
            secret,
            algorithm="HS256",
        )
        assert service.decode_mfa_voucher(token) is None

    def test_decode_invalid_signature(self, service):
        import jwt

        token = jwt.encode(
            {"sub": "x", "uid": "x", "scope": "mfa_challenge", "exp": int(time.time()) + 100},
            "0123456789abcdef0123456789abcdef-X",
            algorithm="HS256",
        )
        assert service.decode_mfa_voucher(token) is None

    def test_decode_expired(self, service):
        import jwt

        secret = os.environ["SOGO_P_VOUCHER_SECRET"]
        token = jwt.encode(
            {"sub": "x", "uid": "x", "scope": "mfa_challenge", "exp": int(time.time()) - 10},
            secret,
            algorithm="HS256",
        )
        assert service.decode_mfa_voucher(token) is None

    def test_decode_garbage(self, service):
        assert service.decode_mfa_voucher("not.a.jwt") is None


# ─────────────────────────────────────────────────────────────────────────────
# _get_user_session_from_payload
# ─────────────────────────────────────────────────────────────────────────────

class TestGetUserSessionFromPayload:
    def test_missing_session_returns_anonymous(self, service, fake_cache):
        from app.auth.User import UserAnonymous
        from app.auth.voucher.JWTVoucher import JWTVoucher

        # Wait: need a session_key that decrypts but the hash doesn't exist
        from cryptography.fernet import Fernet
        from base64 import urlsafe_b64encode

        secret = os.environ["SOGO_P_VOUCHER_SECRET"]
        f = Fernet(urlsafe_b64encode(secret.encode("utf-8")))
        crypted = f.encrypt(b"deadbeef-deadbeef:tokentokentokentokentokentokentokentoken").decode("utf-8")
        payload = {cs.SESSION_KEY: crypted, cs.USER_UID: "ghost@example.org"}
        user = service._get_user_session_from_payload(payload)
        assert isinstance(user, UserAnonymous)
        # zset cleanup performed
        assert all(z == {} for z in fake_cache.zsets.values())

    def test_session_uid_mismatch_returns_anonymous(self, service, fake_cache):
        from app.auth.User import UserAnonymous
        from cryptography.fernet import Fernet
        from base64 import urlsafe_b64encode
        from uuid import uuid4

        secret = os.environ["SOGO_P_VOUCHER_SECRET"]
        sid = str(uuid4())
        session_token = "abcdefghijklmnopqrstuvwxyzabcdef"
        f = Fernet(urlsafe_b64encode(secret.encode("utf-8")))
        crypted = f.encrypt(f"{sid}:{session_token}".encode("utf-8")).decode("utf-8")
        # store a session with a DIFFERENT uid
        fake_cache.hashes[f"user_session:{sid}"] = {
            cs.USER_UID: "other@example.org",
            cs.SESSION_SENSITIVE: "irrelevant",
        }
        payload = {cs.SESSION_KEY: crypted, cs.USER_UID: "wanted@example.org"}
        user = service._get_user_session_from_payload(payload)
        assert isinstance(user, UserAnonymous)

    def test_successful_rehydration(self, service, fake_cache):
        from cryptography.fernet import Fernet
        from base64 import urlsafe_b64encode
        from uuid import uuid4
        from app.auth.User import User

        secret = os.environ["SOGO_P_VOUCHER_SECRET"]
        sid = str(uuid4())
        session_token = "abcdefghijklmnopqrstuvwxyzabcdef"
        # sensitive data encrypted with the SESSION token
        session_fernet = Fernet(urlsafe_b64encode(session_token.encode("utf-8")))
        sensitive = session_fernet.encrypt(
            json.dumps(
                {
                    "uid": "user@example.org",
                    "password": "pw",
                    "domain": "example.org",
                    "email": "user@example.org",
                    "source_id": "ldap-main",
                }
            ).encode("utf-8")
        )
        fake_cache.hashes[f"user_session:{sid}"] = {
            cs.USER_UID: "user@example.org",
            cs.SESSION_SENSITIVE: sensitive,
            cs.SESSION_LAST_SEEN: 1234,
        }
        f = Fernet(urlsafe_b64encode(secret.encode("utf-8")))
        crypted = f.encrypt(f"{sid}:{session_token}".encode("utf-8")).decode("utf-8")
        payload = {cs.SESSION_KEY: crypted, cs.USER_UID: "user@example.org"}
        user = service._get_user_session_from_payload(payload)
        assert user is not None
        assert getattr(user, "uid", None) == "user@example.org"
        # last_seen refreshed + index updated
        assert fake_cache.hashes[f"user_session:{sid}"][cs.SESSION_LAST_SEEN] != 1234

    def test_bad_session_token_decrypt(self, service, fake_cache):
        from cryptography.fernet import Fernet
        from base64 import urlsafe_b64encode
        from uuid import uuid4

        secret = os.environ["SOGO_P_VOUCHER_SECRET"]
        sid = str(uuid4())
        session_token = "abcdefghijklmnopqrstuvwxyzabcdef"
        f = Fernet(urlsafe_b64encode(secret.encode("utf-8")))
        crypted = f.encrypt(f"{sid}:{session_token}".encode("utf-8")).decode("utf-8")
        # Store sensitive data NOT decryptable with session_token
        fake_cache.hashes[f"user_session:{sid}"] = {
            cs.USER_UID: "user@example.org",
            cs.SESSION_SENSITIVE: b"garbage",
        }
        payload = {cs.SESSION_KEY: crypted, cs.USER_UID: "user@example.org"}
        with pytest.raises(RequestException):
            service._get_user_session_from_payload(payload)

    def test_non_json_sensitive_raises_bug(self, service, fake_cache):
        from cryptography.fernet import Fernet
        from base64 import urlsafe_b64encode
        from uuid import uuid4
        from app.utils.exceptions import BugException

        secret = os.environ["SOGO_P_VOUCHER_SECRET"]
        sid = str(uuid4())
        session_token = "abcdefghijklmnopqrstuvwxyzabcdef"
        session_fernet = Fernet(urlsafe_b64encode(session_token.encode("utf-8")))
        sensitive = session_fernet.encrypt(b"not-json")
        fake_cache.hashes[f"user_session:{sid}"] = {
            cs.USER_UID: "user@example.org",
            cs.SESSION_SENSITIVE: sensitive,
        }
        f = Fernet(urlsafe_b64encode(secret.encode("utf-8")))
        crypted = f.encrypt(f"{sid}:{session_token}".encode("utf-8")).decode("utf-8")
        payload = {cs.SESSION_KEY: crypted, cs.USER_UID: "user@example.org"}
        with pytest.raises(BugException):
            service._get_user_session_from_payload(payload)

    def test_missing_colon_session_key(self, service, fake_cache):
        from cryptography.fernet import Fernet
        from base64 import urlsafe_b64encode

        secret = os.environ["SOGO_P_VOUCHER_SECRET"]
        f = Fernet(urlsafe_b64encode(secret.encode("utf-8")))
        crypted = f.encrypt(b"nocolon").decode("utf-8")
        payload = {cs.SESSION_KEY: crypted, cs.USER_UID: "x"}
        with pytest.raises(RequestException):
            service._get_user_session_from_payload(payload)
