# pylint: disable=invalid-sequence-index
"""Unit tests for InterfaceAuthSSO (11% -> high).

Covers OIDC/SAML2 dispatch, callback flows (success and failure branches),
voucher generation, redirect-URI building and the SSO user onboarding path.
"""
from __future__ import annotations

import os

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.interface.auth.InterfaceAuthSSO import InterfaceAuthSSO
from app.utils import errors as err
from app.utils.exceptions import RequestException


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / builders
# ─────────────────────────────────────────────────────────────────────────────

class FakeCache:
    def __init__(self):
        self.store = {}
        self.closed = False

    def set(self, key, val, ttl=None, nx=False):
        self.store[key] = val
        return True

    def get(self, key, expected_type=str):
        return self.store.get(key)

    def close(self):
        self.closed = True


@pytest.fixture
def iface():
    process = SimpleNamespace(
        SOGO_P_PUBLIC_BASE_URL="https://mail.example.org",
        SOGO_SAML2_CLOCK_SKEW=0,
        SOGO_P_VOUCHER_SECRET="0123456789abcdef0123456789abcdef",
    )
    return InterfaceAuthSSO(process)


def _domain_auth(auth_type="openid", **overrides):
    base = {
        "SOGO_D_AUTH_TYPE": auth_type,
        "SOGO_D_OPENID_CONFIG_URL": "https://idp.example.org/.well-known/openid-configuration",
        "SOGO_D_OPENID_CLIENT_NAME": "sogo",
        "SOGO_D_OPENID_CLIENT_SECRET": "secret",
        "SOGO_D_OPENID_SCOPE": "openid email profile",
        "SOGO_D_OPENID_EMAIL": "email",
        "SOGO_D_OPENID_ALLOW_REDIRECT": ["https://mail.example.org/*"],
        "SOGO_D_SAML2_URL": "https://idp.example.org/sso",
        "SOGO_D_SAML2_IDP_METADATA_URL": "",
        "SOGO_D_SAML2_IDP_ENTITY_ID": "https://idp.example.org",
        "SOGO_D_SAML2_SP_ENTITY_ID": "",
        "SOGO_D_SAML2_PROVIDER_ID": "",
        "SOGO_D_SAML2_ATTRIBUTE_MAP": None,
        "SOGO_D_SAML2_WANT_ENCRYPTED_ASSERTIONS": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ─────────────────────────────────────────────────────────────────────────────
# handle_callback dispatch
# ─────────────────────────────────────────────────────────────────────────────

class TestHandleCallback:
    def test_dispatches_oidc(self, iface):
        da = _domain_auth("openid")
        with patch.object(iface, "_handle_oidc_callback", return_value=("body", 200)) as m:
            res = iface.handle_callback("example.org", da, {"code": "abc"})
        m.assert_called_once()
        assert res == ("body", 200)

    def test_dispatches_saml(self, iface):
        da = _domain_auth("saml2")
        with patch.object(iface, "_handle_saml_callback", return_value=("body", 200)) as m:
            res = iface.handle_callback("example.org", da, {"SAMLResponse": "x"})
        m.assert_called_once()
        assert res == ("body", 200)

    def test_cas_not_implemented(self, iface):
        da = _domain_auth("cas")
        body, status = iface.handle_callback("example.org", da, {})
        assert status >= 400

    def test_unsupported_auth_type(self, iface):
        da = _domain_auth("ldap")
        body, status = iface.handle_callback("example.org", da, {})
        assert status >= 400


# ─────────────────────────────────────────────────────────────────────────────
# OIDC callback
# ─────────────────────────────────────────────────────────────────────────────

class TestOidcCallback:
    def test_missing_code(self, iface):
        da = _domain_auth("openid")
        body, status = iface._handle_oidc_callback("example.org", da, {})
        assert status == err.ERROR_OIDC_TOKEN_EXCHANGE_FAILED.h
        assert body["error_code"] == err.ERROR_OIDC_TOKEN_EXCHANGE_FAILED.c

    def test_full_success_flow(self, iface):
        da = _domain_auth("openid")
        oidc = MagicMock()
        oidc.discover.return_value = None
        oidc.fetch_token.return_value = {
            "id_token": "idtok",
            "access_token": "at",
            "refresh_token": "rt",
            "expires_in": 3600,
            "scope": "openid",
        }
        oidc.validate_id_token.return_value = {"sub": "sub123", "email": "u@example.org"}
        oidc.get_user_info.return_value = {"email": "u@example.org"}
        oidc.get_email.return_value = "u@example.org"
        oidc.get_subject.return_value = "sub123"

        cache = FakeCache()

        with patch.object(iface, "_build_oidc", return_value=oidc), patch(
            "app.service.sogo_cache", return_value=cache
        ), patch.object(
            iface, "_authenticate_sso_user", return_value={"jwt_token": "tok"}
        ) as auth_m, patch.object(iface, "_build_redirect_uri", return_value="https://mail.example.org/api/user/v1/auth/callback/example.org"):
            body, status = iface._handle_oidc_callback("example.org", da, {"code": "c", "state": "s"})

        assert status == 200
        assert body["data"]["jwt_token"] == "tok"
        assert body["data"]["oidc_sub"] == "sub123"
        auth_m.assert_called_once_with("example.org", "u@example.org", "oidc")
        # OIDC tokens stored in redis
        assert "user_oidc_session:u@example.org" in cache.store
        assert cache.closed is True

    def test_no_id_token(self, iface):
        da = _domain_auth("openid")
        oidc = MagicMock()
        oidc.fetch_token.return_value = {"access_token": "at"}
        with patch.object(iface, "_build_oidc", return_value=oidc):
            body, status = iface._handle_oidc_callback("example.org", da, {"code": "c"})
        assert status == err.ERROR_OIDC_TOKEN_EXCHANGE_FAILED.h

    def test_no_email(self, iface):
        da = _domain_auth("openid")
        oidc = MagicMock()
        oidc.fetch_token.return_value = {"id_token": "it"}
        oidc.validate_id_token.return_value = {}
        oidc.get_email.return_value = None
        with patch.object(iface, "_build_oidc", return_value=oidc):
            body, status = iface._handle_oidc_callback("example.org", da, {"code": "c"})
        assert status == err.ERROR_OIDC_USERINFO_FAILED.h
        assert body["error_code"] == err.ERROR_OIDC_USERINFO_FAILED.c

    def test_cache_failure_continues_auth(self, iface):
        da = _domain_auth("openid")
        oidc = MagicMock()
        oidc.fetch_token.return_value = {"id_token": "it"}
        oidc.validate_id_token.return_value = {"sub": "s"}
        oidc.get_user_info.return_value = {}
        oidc.get_email.return_value = "u@example.org"
        oidc.get_subject.return_value = "s"

        def _boom(*a, **k):
            raise RuntimeError("redis down")

        with patch.object(iface, "_build_oidc", return_value=oidc), patch(
            "app.service.sogo_cache", side_effect=_boom
        ), patch.object(iface, "_authenticate_sso_user", return_value={"jwt_token": "t"}):
            body, status = iface._handle_oidc_callback("example.org", da, {"code": "c"})

        assert status == 200
        assert body["data"]["jwt_token"] == "t"

    def test_generic_exception_maps_to_token_exchange_failed(self, iface):
        da = _domain_auth("openid")
        oidc = MagicMock()
        oidc.discover.side_effect = RuntimeError("network")
        with patch.object(iface, "_build_oidc", return_value=oidc):
            body, status = iface._handle_oidc_callback("example.org", da, {"code": "c"})
        assert status == err.ERROR_OIDC_TOKEN_EXCHANGE_FAILED.h

    def test_request_exception_propagates(self, iface):
        da = _domain_auth("openid")
        oidc = MagicMock()

        def _raise(*a, **k):
            raise RequestException("boom", err.ERROR_OIDC_NOT_CONFIGURED)

        oidc.discover.side_effect = _raise
        with patch.object(iface, "_build_oidc", return_value=oidc), pytest.raises(RequestException):
            iface._handle_oidc_callback("example.org", da, {"code": "c"})


# ─────────────────────────────────────────────────────────────────────────────
# SAML2 callback
# ─────────────────────────────────────────────────────────────────────────────

class TestSamlCallback:
    def test_missing_response(self, iface):
        da = _domain_auth("saml2")
        body, status = iface._handle_saml_callback("example.org", da, {})
        assert status == err.ERROR_SAML_RESPONSE_INVALID.h

    def test_full_success_flow(self, iface):
        da = _domain_auth("saml2")
        saml = MagicMock()
        saml.process_response.return_value = {
            "email": "u@example.org",
            "display_name": "User U",
            "eppn": "u@example.org",
            "name_id": "nameid",
            "attributes": {"mail": ["u@example.org"]},
            "issuer": "https://idp.example.org",
        }
        with patch.object(iface, "_build_saml", return_value=saml), patch.object(
            iface, "_authenticate_sso_user", return_value={"jwt_token": "tok"}
        ) as auth_m:
            body, status = iface._handle_saml_callback("example.org", da, {"SAMLResponse": "b64"})

        assert status == 200
        assert body["data"]["jwt_token"] == "tok"
        assert body["data"]["saml_name_id"] == "nameid"
        assert body["data"]["saml_issuer"] == "https://idp.example.org"
        assert body["data"]["saml_eppn"] == "u@example.org"
        auth_m.assert_called_once_with("example.org", "u@example.org", "saml2",
                                       display_name="User U", eppn="u@example.org")

    def test_email_fallback_eppn(self, iface):
        da = _domain_auth("saml2")
        saml = MagicMock()
        saml.process_response.return_value = {"eppn": "u@example.org"}
        with patch.object(iface, "_build_saml", return_value=saml), patch.object(
            iface, "_authenticate_sso_user", return_value={"jwt_token": "t"}
        ) as auth_m:
            body, status = iface._handle_saml_callback("example.org", da, {"SAMLResponse": "b64"})
        auth_m.assert_called_once_with("example.org", "u@example.org", "saml2",
                                       display_name="", eppn="u@example.org")
        assert status == 200

    def test_no_email_identity(self, iface):
        da = _domain_auth("saml2")
        saml = MagicMock()
        saml.process_response.return_value = {}
        with patch.object(iface, "_build_saml", return_value=saml):
            body, status = iface._handle_saml_callback("example.org", da, {"SAMLResponse": "b64"})
        assert status == err.ERROR_SAML_RESPONSE_INVALID.h

    def test_generic_exception(self, iface):
        da = _domain_auth("saml2")
        saml = MagicMock()
        saml.process_response.side_effect = RuntimeError("bad saml")
        with patch.object(iface, "_build_saml", return_value=saml):
            body, status = iface._handle_saml_callback("example.org", da, {"SAMLResponse": "b64"})
        assert status == err.ERROR_SAML_RESPONSE_INVALID.h


# ─────────────────────────────────────────────────────────────────────────────
# _build_oidc / _build_saml / redirect uri
# ─────────────────────────────────────────────────────────────────────────────

class TestBuilders:
    def test_build_oidc_requires_config_url(self, iface):
        da = _domain_auth("openid", SOGO_D_OPENID_CONFIG_URL="")
        with pytest.raises(RequestException):
            iface._build_oidc(da)

    def test_build_oidc_ok(self, iface):
        da = _domain_auth("openid")
        with patch("app.interface.auth.InterfaceAuthSSO.ModuleOIDC") as m:
            iface._build_oidc(da)
        m.assert_called_once()
        _, kwargs = m.call_args
        assert kwargs["issuer"] == da.SOGO_D_OPENID_CONFIG_URL
        assert kwargs["client_id"] == "sogo"
        assert kwargs["client_secret"] == "secret"
        assert kwargs["scope"] == "openid email profile"
        assert kwargs["email_claim"] == "email"
        assert kwargs["allow_redirect_uris"] == ["https://mail.example.org/*"]

    def test_build_saml_requires_url(self, iface):
        da = _domain_auth("saml2", SOGO_D_SAML2_URL="", SOGO_D_SAML2_IDP_METADATA_URL="")
        with pytest.raises(RequestException):
            iface._build_saml(da, "example.org")

    def test_build_saml_simple_mode(self, iface):
        da = _domain_auth("saml2")
        with patch("app.interface.auth.InterfaceAuthSSO.ModuleSAML2") as m, patch(
            "app.interface.auth.InterfaceAuthSSO.Saml2Keypair"
        ) as kp:
            kp.return_value.load_keypair.return_value = ("cert", "key")
            iface._build_saml(da, "example.org")
        m.assert_called_once()
        args, kwargs = m.call_args
        assert kwargs["idp_sso_url"] == "https://idp.example.org/sso"
        assert kwargs["idp_entity_id"] == "https://idp.example.org"
        assert kwargs["want_assertions_encrypted"] is False

    def test_build_saml_derives_sp_entity_id(self, iface):
        da = _domain_auth("saml2", SOGO_D_SAML2_SP_ENTITY_ID="")
        with patch("app.interface.auth.InterfaceAuthSSO.ModuleSAML2") as m, patch(
            "app.interface.auth.InterfaceAuthSSO.Saml2Keypair"
        ) as kp:
            kp.return_value.load_keypair.return_value = ("cert", "key")
            iface._build_saml(da, "example.org")
        _, kwargs = m.call_args
        assert "mail.example.org/api/user/v1/auth/metadata" in kwargs["entity_id"]

    def test_build_saml_metadata_url(self, iface):
        da = _domain_auth(
            "saml2",
            SOGO_D_SAML2_URL="",
            SOGO_D_SAML2_IDP_METADATA_URL="https://idp.example.org/metadata",
            SOGO_D_SAML2_IDP_ENTITY_ID="",
        )
        mf = MagicMock()
        mf.get_idp_config.return_value = {
            "sso_url": "https://idp.example.org/new-sso",
            "certificate": "idpcert",
            "entity_id": "https://idp.example.org/real",
        }
        with patch("app.interface.auth.InterfaceAuthSSO.ModuleSAML2") as m, patch(
            "app.interface.auth.InterfaceAuthSSO.Saml2Keypair"
        ) as kp, patch(
            "app.module.auth.Saml2Metadata.Saml2Metadata", return_value=mf
        ) as mcls:
            kp.return_value.load_keypair.return_value = ("cert", "key")
            iface._build_saml(da, "example.org")
        mcls.assert_called_once()
        _, kwargs = m.call_args
        assert kwargs["idp_sso_url"] == "https://idp.example.org/new-sso"
        assert kwargs["idp_cert"] == "idpcert"
        assert kwargs["idp_entity_id"] == "https://idp.example.org/real"

    def test_build_saml_metadata_failure_no_sso_raises(self, iface):
        da = _domain_auth(
            "saml2",
            SOGO_D_SAML2_URL="",
            SOGO_D_SAML2_IDP_METADATA_URL="https://idp.example.org/metadata",
        )
        mf = MagicMock()
        mf.get_idp_config.side_effect = RuntimeError("http fail")
        with patch("app.interface.auth.InterfaceAuthSSO.Saml2Keypair") as kp, patch(
            "app.module.auth.Saml2Metadata.Saml2Metadata", return_value=mf
        ), pytest.raises(RequestException) as exc:
            kp.return_value.load_keypair.return_value = ("cert", "key")
            iface._build_saml(da, "example.org")
        assert exc.value.error.c == err.ERROR_SAML_METADATA_FETCH_FAILED.c

    def test_build_saml_metadata_failure_with_sso_continues(self, iface):
        da = _domain_auth(
            "saml2",
            SOGO_D_SAML2_IDP_METADATA_URL="https://idp.example.org/metadata",
        )
        mf = MagicMock()
        mf.get_idp_config.side_effect = RuntimeError("http fail")
        with patch("app.interface.auth.InterfaceAuthSSO.ModuleSAML2") as m, patch(
            "app.interface.auth.InterfaceAuthSSO.Saml2Keypair"
        ) as kp, patch(
            "app.module.auth.Saml2Metadata.Saml2Metadata", return_value=mf
        ):
            kp.return_value.load_keypair.return_value = ("cert", "key")
            iface._build_saml(da, "example.org")
        _, kwargs = m.call_args
        assert kwargs["idp_sso_url"] == "https://idp.example.org/sso"

    def test_build_saml_provider_from_db(self, iface):
        da = _domain_auth("saml2", SOGO_D_SAML2_PROVIDER_ID="prov-1")
        prov = MagicMock()
        prov.get_provider.return_value = {
            "sso_url": "https://prov.example.org/sso",
            "entity_id": "https://prov.example.org",
            "certificate": "provcert",
        }
        with patch("app.interface.auth.InterfaceAuthSSO.ModuleSAML2") as m, patch(
            "app.interface.auth.InterfaceAuthSSO.Saml2Keypair"
        ) as kp, patch(
            "app.module.auth.ModuleSaml2Provider.ModuleSaml2Provider", return_value=prov
        ):
            kp.return_value.load_keypair.return_value = ("cert", "key")
            iface._build_saml(da, "example.org")
        _, kwargs = m.call_args
        assert kwargs["idp_sso_url"] == "https://prov.example.org/sso"
        assert kwargs["idp_cert"] == "provcert"

    def test_build_saml_provider_missing_warns(self, iface):
        da = _domain_auth("saml2", SOGO_D_SAML2_PROVIDER_ID="prov-1")
        prov = MagicMock()
        prov.get_provider.return_value = None
        with patch("app.interface.auth.InterfaceAuthSSO.ModuleSAML2") as m, patch(
            "app.interface.auth.InterfaceAuthSSO.Saml2Keypair"
        ) as kp, patch(
            "app.module.auth.ModuleSaml2Provider.ModuleSaml2Provider", return_value=prov
        ):
            kp.return_value.load_keypair.return_value = ("cert", "key")
            iface._build_saml(da, "example.org")
        _, kwargs = m.call_args
        assert kwargs["idp_sso_url"] == "https://idp.example.org/sso"

    def test_build_saml_provider_db_error_ignored(self, iface):
        da = _domain_auth("saml2", SOGO_D_SAML2_PROVIDER_ID="prov-1")
        prov = MagicMock()
        prov.get_provider.side_effect = RuntimeError("db down")
        with patch("app.interface.auth.InterfaceAuthSSO.ModuleSAML2") as m, patch(
            "app.interface.auth.InterfaceAuthSSO.Saml2Keypair"
        ) as kp, patch(
            "app.module.auth.ModuleSaml2Provider.ModuleSaml2Provider", return_value=prov
        ):
            kp.return_value.load_keypair.return_value = ("cert", "key")
            iface._build_saml(da, "example.org")
        _, kwargs = m.call_args
        assert kwargs["idp_sso_url"] == "https://idp.example.org/sso"

    def test_build_saml_redis_unavailable_ok(self, iface):
        da = _domain_auth("saml2")

        def _boom(*a, **k):
            raise RuntimeError("redis down")

        with patch("app.interface.auth.InterfaceAuthSSO.ModuleSAML2") as m, patch(
            "app.interface.auth.InterfaceAuthSSO.Saml2Keypair"
        ) as kp, patch("app.service.sogo_cache", side_effect=_boom):
            kp.return_value.load_keypair.return_value = ("cert", "key")
            iface._build_saml(da, "example.org")
        _, kwargs = m.call_args
        assert kwargs["redis_client"] is None

    def test_build_saml_redis_client_passed(self, iface):
        da = _domain_auth("saml2")
        cache = FakeCache()
        with patch("app.interface.auth.InterfaceAuthSSO.ModuleSAML2") as m, patch(
            "app.interface.auth.InterfaceAuthSSO.Saml2Keypair"
        ) as kp, patch("app.service.sogo_cache", return_value=cache):
            kp.return_value.load_keypair.return_value = ("cert", "key")
            iface._build_saml(da, "example.org")
        _, kwargs = m.call_args
        assert kwargs["redis_client"] is cache

    def test_build_redirect_uri(self, iface):
        assert iface._build_redirect_uri("example.org") == (
            "https://mail.example.org/api/user/v1/auth/callback/example.org"
        )

    def test_build_redirect_uri_default(self):
        p = SimpleNamespace(SOGO_P_PUBLIC_BASE_URL="", SOGO_SAML2_CLOCK_SKEW=0)
        i = InterfaceAuthSSO(p)
        assert i._build_redirect_uri("d.org") == "http://localhost:5001/api/user/v1/auth/callback/d.org"


# ─────────────────────────────────────────────────────────────────────────────
# _authenticate_sso_user
# ─────────────────────────────────────────────────────────────────────────────

class TestAuthenticateSsoUser:
    def test_success_returns_jwt(self, iface):
        voucher = MagicMock()
        voucher.generate_voucher_from_user.return_value = "jwt-token"
        user_module_us = MagicMock()
        user_module_us.check_login.return_value = True

        with patch(
            "app.config.init_config.init_get_system_and_default_domain_settings",
            return_value=(
                {},
                {
                    "USER_SOURCE": {"us1": {"display_name": "Ldap"}},
                    "AUTH_SETTINGS": {},
                },
            ),
        ), patch(
            "app.module.auth.ModuleAuth.ModuleAuth"
        ), patch.object(
            iface, "_load_domain_user_sources", return_value={}
        ), patch(
            "app.module.auth.ModuleUserSource.ModuleUserSource", return_value=user_module_us
        ), patch(
            "app.auth.service.VoucherUserService.VoucherUserService", return_value=voucher
        ):
            result = iface._authenticate_sso_user("example.org", "u@example.org", "oidc")

        assert result == {"jwt_token": "jwt-token"}
        user_module_us.check_login.assert_called_once()

    def test_onboarding_path(self, iface):
        """User not in source -> profile + calendar + addressbook created."""
        voucher = MagicMock()
        voucher.generate_voucher_from_user.return_value = "jwt-2"
        user_module_us = MagicMock()
        user_module_us.check_login.return_value = False

        profile = MagicMock()
        profile.is_user_profile_present.return_value = False
        profile.get_partial_user_preferences.return_value = {
            "USER_GENERAL": {"SOGO_U_TIMEZONE": "Europe/Berlin"}
        }

        with patch(
            "app.config.init_config.init_get_system_and_default_domain_settings",
            return_value=({}, {"USER_SOURCE": {}, "AUTH_SETTINGS": {}}),
        ), patch("app.module.auth.ModuleAuth.ModuleAuth"), patch.object(
            iface, "_load_domain_user_sources", return_value={}
        ), patch(
            "app.module.auth.ModuleUserSource.ModuleUserSource", return_value=user_module_us
        ), patch(
            "app.module.user.ModuleUserProfile.ModuleUserProfile", return_value=profile
        ) as mp, patch(
            "app.module.calendar.ModuleCalendar.ModuleCalendar"
        ) as mc, patch(
            "app.module.contact.ModuleContact.ModuleContact"
        ) as mct, patch(
            "app.auth.service.VoucherUserService.VoucherUserService", return_value=voucher
        ):
            result = iface._authenticate_sso_user("example.org", "new@example.org", "saml2")

        assert result == {"jwt_token": "jwt-2"}
        profile.create_user_profile.assert_called_once()
        mc.return_value.create_personal_calendar.assert_called_once()
        mct.return_value.create_personal_addressbook.assert_called_once()

    def test_existing_profile_skips_onboarding(self, iface):
        voucher = MagicMock()
        voucher.generate_voucher_from_user.return_value = "jwt-3"
        user_module_us = MagicMock()
        user_module_us.check_login.return_value = False
        profile = MagicMock()
        profile.is_user_profile_present.return_value = True

        with patch(
            "app.config.init_config.init_get_system_and_default_domain_settings",
            return_value=({}, {"USER_SOURCE": {}, "AUTH_SETTINGS": {}}),
        ), patch("app.module.auth.ModuleAuth.ModuleAuth"), patch.object(
            iface, "_load_domain_user_sources", return_value={}
        ), patch(
            "app.module.auth.ModuleUserSource.ModuleUserSource", return_value=user_module_us
        ), patch(
            "app.module.user.ModuleUserProfile.ModuleUserProfile", return_value=profile
        ), patch(
            "app.auth.service.VoucherUserService.VoucherUserService", return_value=voucher
        ):
            result = iface._authenticate_sso_user("example.org", "new@example.org", "saml2")

        assert result == {"jwt_token": "jwt-3"}
        profile.create_user_profile.assert_not_called()

    def test_user_source_error_continues_to_voucher(self, iface):
        voucher = MagicMock()
        voucher.generate_voucher_from_user.return_value = "jwt-4"

        with patch(
            "app.config.init_config.init_get_system_and_default_domain_settings",
            return_value=({}, {"USER_SOURCE": {}, "AUTH_SETTINGS": {}}),
        ), patch(
            "app.module.auth.ModuleAuth.ModuleAuth"
        ), patch.object(
            iface, "_load_domain_user_sources", side_effect=RuntimeError("db down")
        ), patch(
            "app.auth.service.VoucherUserService.VoucherUserService", return_value=voucher
        ):
            result = iface._authenticate_sso_user("example.org", "u@example.org", "oidc")

        assert result == {"jwt_token": "jwt-4"}

    def test_sso_user_sets_auth_method_on_session(self, iface):
        """SSO sessions must be marked so per-request source checks are skipped."""
        voucher = MagicMock()
        user_module_us = MagicMock()
        user_module_us.check_login.return_value = False
        profile = MagicMock()
        profile.is_user_profile_present.return_value = True

        with patch(
            "app.config.init_config.init_get_system_and_default_domain_settings",
            return_value=({}, {"USER_SOURCE": {}, "AUTH_SETTINGS": {}}),
        ), patch("app.module.auth.ModuleAuth.ModuleAuth"), patch.object(
            iface, "_load_domain_user_sources", return_value={}
        ), patch(
            "app.module.auth.ModuleUserSource.ModuleUserSource", return_value=user_module_us
        ), patch(
            "app.module.user.ModuleUserProfile.ModuleUserProfile", return_value=profile
        ), patch(
            "app.auth.service.VoucherUserService.VoucherUserService", return_value=voucher
        ):
            iface._authenticate_sso_user("example.org", "oidc@example.org", "oidc")

        user_passed = voucher.generate_voucher_from_user.call_args.args[0]
        assert user_passed.auth_method == "oidc"
        assert user_passed.password == ""

    def test_saml_user_sets_auth_method_on_session(self, iface):
        voucher = MagicMock()
        user_module_us = MagicMock()
        user_module_us.check_login.return_value = False
        profile = MagicMock()
        profile.is_user_profile_present.return_value = True

        with patch(
            "app.config.init_config.init_get_system_and_default_domain_settings",
            return_value=({}, {"USER_SOURCE": {}, "AUTH_SETTINGS": {}}),
        ), patch("app.module.auth.ModuleAuth.ModuleAuth"), patch.object(
            iface, "_load_domain_user_sources", return_value={}
        ), patch(
            "app.module.auth.ModuleUserSource.ModuleUserSource", return_value=user_module_us
        ), patch(
            "app.module.user.ModuleUserProfile.ModuleUserProfile", return_value=profile
        ), patch(
            "app.auth.service.VoucherUserService.VoucherUserService", return_value=voucher
        ):
            iface._authenticate_sso_user("example.org", "saml@example.org", "saml2")

        user_passed = voucher.generate_voucher_from_user.call_args.args[0]
        assert user_passed.auth_method == "saml2"


# ─────────────────────────────────────────────────────────────────────────────
# _load_domain_user_sources
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadDomainUserSources:
    def test_empty_domain_returns_default(self, iface):
        default_us = {"us1": "settings"}
        assert iface._load_domain_user_sources("", None, None, default_us) == default_us

    def test_no_db_result_returns_default(self, iface):
        default_us = {"us1": "settings"}
        db = MagicMock()
        db.select_from_table.return_value = []

        with patch("app.config.settings.ProcessSetting.process_config") as pc, patch(
            "app.utils.module.importManager.import_and_instantiate_manager",
            return_value=db,
        ):
            pc.SOGO_P_DB_TYPE = "SQLite"
            result = iface._load_domain_user_sources("example.org", None, None, default_us)
        assert result == default_us

    def test_db_result_overrides_default(self, iface):
        default_us = {"us1": "default"}
        db = MagicMock()
        db.select_from_table.return_value = [
            ({"USER_SOURCE": {"us2": {"display_name": "Custom"}}},)
        ]

        class _US:
            def __init__(self, d):
                self.d = d

        with patch("app.config.settings.DomainSettings.UserSourceSettingsObj", _US), patch(
            "app.config.settings.ProcessSetting.process_config"
        ) as pc, patch(
            "app.utils.module.importManager.import_and_instantiate_manager",
            return_value=db,
        ):
            pc.SOGO_P_DB_TYPE = "SQLite"
            result = iface._load_domain_user_sources("example.org", None, None, default_us)
        assert "us2" in result
        assert "us1" not in result
