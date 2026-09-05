# pylint: disable=invalid-sequence-index
"""Coverage tests for admin-calendar + SSO interfaces (sogo-cov-53).

Targets (combined gate target >= 90%):

* ``app.interface.admin.InterfaceApiAdminCalendar`` -- ``clean()`` maintenance
  operation: missing target, by user_uid, by calendar_key and the
  ``RequestException`` branch.
* ``app.interface.auth.InterfaceAuthSSO`` -- SSO callback dispatch (OIDC /
  SAML2 / CAS / unknown), the full OIDC and SAML2 callback flows including
  missing-attribute and error branches, the OIDC/SAML builders (simple mode,
  federation metadata, provider DB overrides, Redis availability), the
  redirect-uri builder, the SSO user auth/onboarding path and the per-domain
  user-source loader.

Everything is mocked / in-memory: no network, no real redis / db / ldap.
"""
from __future__ import annotations

import os

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

# ---------------------------------------------------------------------------
# ``authlib`` is imported by ``app.module.auth.ModuleOIDC`` at module import
# time but is NOT a declared dependency in pyproject.toml (it is installed
# manually in the runtime image).  Stub it out when it is missing so the
# interface module can still be imported in bare test environments.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - depends on environment
    import authlib  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on environment
    import sys
    import types

    def _stub_authlib() -> None:  # pragma: no cover
        pkg = types.ModuleType("authlib")
        sys.modules["authlib"] = pkg
        for sub in ("integrations", "jose", "oauth2"):
            mod = types.ModuleType(f"authlib.{sub}")
            setattr(pkg, sub, mod)
            sys.modules[f"authlib.{sub}"] = mod
        requests_client = types.ModuleType("authlib.integrations.requests_client")
        requests_client.OAuth2Session = type("OAuth2Session", (), {})
        sys.modules["authlib.integrations.requests_client"] = requests_client
        pkg.integrations.requests_client = requests_client
        sys.modules["authlib.jose"].JsonWebKey = type("JsonWebKey", (), {})
        sys.modules["authlib.jose"].JsonWebToken = type("JsonWebToken", (), {})
        rfc = types.ModuleType("authlib.oauth2.rfc6749")
        rfc.OAuth2Token = type("OAuth2Token", (), {})
        sys.modules["authlib.oauth2.rfc6749"] = rfc
        pkg.oauth2.rfc6749 = rfc

    _stub_authlib()

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.interface.admin.InterfaceApiAdminCalendar import InterfaceApiAdminCalendar
from app.interface.auth.InterfaceAuthSSO import InterfaceAuthSSO
from app.utils import errors as err
from app.utils.exceptions import RequestException


# ===========================================================================
# Shared fakes / builders
# ===========================================================================

class FakeCache:
    """In-memory cache with the minimal Redis client surface used by SSO."""

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


def _process(**overrides):
    base = {
        "SOGO_P_PUBLIC_BASE_URL": "https://mail.example.org",
        "SOGO_SAML2_CLOCK_SKEW": 0,
        "SOGO_P_VOUCHER_SECRET": "0123456789abcdef0123456789abcdef",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def iface():
    return InterfaceAuthSSO(_process())


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


# ===========================================================================
# InterfaceApiAdminCalendar
# ===========================================================================

class TestAdminCalendarClean:
    @staticmethod
    def _make():
        process = MagicMock()
        with patch("app.interface.admin.InterfaceApiAdminCalendar.ModuleCalendar") as mc:
            iface = InterfaceApiAdminCalendar(process)
        return iface, mc

    def test_missing_target_returns_error(self):
        iface, _ = self._make()
        body, status = iface.clean()
        assert status == err.ERROR_CALENDAR_MAINTENANCE_REQUIRE_TARGET.h
        assert body["error_code"] == err.ERROR_CALENDAR_MAINTENANCE_REQUIRE_TARGET.c

    def test_clean_by_user_uid(self):
        iface, mc = self._make()
        mc.return_value.clean.return_value = 5
        body, status = iface.clean(user_uid="u1")
        assert status == 200
        assert body["data"]["purged_rows"] == 5
        assert body["error_code"] == err.ERROR_NO_ERROR.c
        mc.return_value.clean.assert_called_once_with(user_uid="u1", calendar_key=None)

    def test_clean_by_calendar_key(self):
        iface, mc = self._make()
        mc.return_value.clean.return_value = 0
        body, status = iface.clean(calendar_key="ck")
        assert status == 200
        assert body["data"]["purged_rows"] == 0
        mc.return_value.clean.assert_called_once_with(user_uid=None, calendar_key="ck")

    def test_clean_module_request_exception(self):
        iface, mc = self._make()
        mc.return_value.clean.side_effect = RequestException(
            "boom", err.ERROR_CALENDAR_MAINTENANCE_REQUIRE_TARGET
        )
        body, status = iface.clean(user_uid="u")
        assert status == err.ERROR_CALENDAR_MAINTENANCE_REQUIRE_TARGET.h
        assert body["error_code"] == err.ERROR_CALENDAR_MAINTENANCE_REQUIRE_TARGET.c

    def test_init_constructs_calendar_module(self):
        process = MagicMock()
        with patch("app.interface.admin.InterfaceApiAdminCalendar.ModuleCalendar") as mc:
            InterfaceApiAdminCalendar(process)
        mc.assert_called_once_with(process_settings=process)


# ===========================================================================
# InterfaceAuthSSO - handle_callback dispatch
# ===========================================================================

class TestHandleCallback:
    def test_dispatches_oidc(self, iface):
        da = _domain_auth("openid")
        with patch.object(iface, "_handle_oidc_callback", return_value=("body", 200)) as m:
            result = iface.handle_callback("example.org", da, {"code": "abc"})
        m.assert_called_once_with("example.org", da, {"code": "abc"})
        assert result == ("body", 200)

    def test_dispatches_saml(self, iface):
        da = _domain_auth("saml2")
        with patch.object(iface, "_handle_saml_callback", return_value=("body", 200)) as m:
            result = iface.handle_callback("example.org", da, {"SAMLResponse": "x"})
        m.assert_called_once_with("example.org", da, {"SAMLResponse": "x"})
        assert result == ("body", 200)

    def test_cas_not_implemented(self, iface):
        da = _domain_auth("cas")
        body, status = iface.handle_callback("example.org", da, {})
        assert status == err.ERROR_UNKOWN.h
        assert body["error_code"] == err.ERROR_UNKOWN.c
        assert "not implemented" in body["data"]

    def test_unsupported_auth_type(self, iface):
        da = _domain_auth("ldap")
        body, status = iface.handle_callback("example.org", da, {})
        assert status == err.ERROR_UNKOWN.h
        assert body["error_code"] == err.ERROR_UNKOWN.c
        assert "not supported" in body["data"]


# ===========================================================================
# InterfaceAuthSSO - OIDC callback
# ===========================================================================

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
            "id_token": "itok",
            "access_token": "at",
            "refresh_token": "rt",
            "expires_in": 1200,
            "scope": "openid",
        }
        oidc.validate_id_token.return_value = {"sub": "sub1", "email": "u@example.org"}
        oidc.get_user_info.return_value = {"email": "u@example.org"}
        oidc.get_email.return_value = "u@example.org"
        oidc.get_subject.return_value = "sub1"
        cache = FakeCache()

        with patch.object(iface, "_build_oidc", return_value=oidc), patch(
            "app.service.sogo_cache", return_value=cache
        ), patch.object(
            iface, "_authenticate_sso_user", return_value={"jwt_token": "tok"}
        ) as auth_m, patch.object(
            iface, "_build_redirect_uri", return_value="https://mail.example.org/api/user/v1/auth/callback/example.org"
        ):
            body, status = iface._handle_oidc_callback(
                "example.org", da, {"code": "c", "state": "s"}
            )

        assert status == 200
        assert body["data"]["jwt_token"] == "tok"
        assert body["data"]["oidc_sub"] == "sub1"
        auth_m.assert_called_once_with("example.org", "u@example.org", "oidc")
        stored = cache.store.get("user_oidc_session:u@example.org")
        assert stored["access_token"] == "at"
        assert stored["refresh_token"] == "rt"
        assert stored["expires_in"] == 1200
        assert stored["scope"] == "openid"
        assert cache.closed is True

    def test_no_id_token_in_response(self, iface):
        da = _domain_auth("openid")
        oidc = MagicMock()
        oidc.fetch_token.return_value = {"access_token": "at"}
        with patch.object(iface, "_build_oidc", return_value=oidc):
            body, status = iface._handle_oidc_callback("example.org", da, {"code": "c"})
        assert status == err.ERROR_OIDC_TOKEN_EXCHANGE_FAILED.h
        assert body["error_code"] == err.ERROR_OIDC_TOKEN_EXCHANGE_FAILED.c

    def test_missing_email(self, iface):
        da = _domain_auth("openid")
        oidc = MagicMock()
        oidc.fetch_token.return_value = {"id_token": "it"}
        oidc.validate_id_token.return_value = {"sub": "s"}
        oidc.get_email.return_value = None
        with patch.object(iface, "_build_oidc", return_value=oidc):
            body, status = iface._handle_oidc_callback("example.org", da, {"code": "c"})
        assert status == err.ERROR_OIDC_USERINFO_FAILED.h
        assert body["error_code"] == err.ERROR_OIDC_USERINFO_FAILED.c

    def test_cache_failure_does_not_break_auth(self, iface):
        da = _domain_auth("openid")
        oidc = MagicMock()
        oidc.fetch_token.return_value = {"id_token": "it"}
        oidc.validate_id_token.return_value = {"sub": "s"}
        oidc.get_user_info.return_value = {}
        oidc.get_email.return_value = "u@example.org"
        oidc.get_subject.return_value = "s"

        def _boom(*args, **kwargs):
            raise RuntimeError("redis down")

        with patch.object(iface, "_build_oidc", return_value=oidc), patch(
            "app.service.sogo_cache", side_effect=_boom
        ), patch.object(
            iface, "_authenticate_sso_user", return_value={"jwt_token": "t"}
        ):
            body, status = iface._handle_oidc_callback("example.org", da, {"code": "c"})

        assert status == 200
        assert body["data"]["jwt_token"] == "t"

    def test_generic_exception_maps_to_token_exchange_error(self, iface):
        da = _domain_auth("openid")
        oidc = MagicMock()
        oidc.fetch_token.return_value = {"id_token": "it"}
        oidc.validate_id_token.side_effect = RuntimeError("bad jwt")
        with patch.object(iface, "_build_oidc", return_value=oidc):
            body, status = iface._handle_oidc_callback("example.org", da, {"code": "c"})
        assert status == err.ERROR_OIDC_TOKEN_EXCHANGE_FAILED.h

    def test_request_exception_is_propagated(self, iface):
        da = _domain_auth("openid")
        oidc = MagicMock()

        def _raise(*args, **kwargs):
            raise RequestException("boom", err.ERROR_OIDC_NOT_CONFIGURED)

        oidc.discover.side_effect = _raise
        with patch.object(iface, "_build_oidc", return_value=oidc), pytest.raises(
            RequestException
        ) as excinfo:
            iface._handle_oidc_callback("example.org", da, {"code": "c"})
        assert excinfo.value.error.c == err.ERROR_OIDC_NOT_CONFIGURED.c


# ===========================================================================
# InterfaceAuthSSO - SAML2 callback
# ===========================================================================

class TestSamlCallback:
    def test_missing_response(self, iface):
        da = _domain_auth("saml2")
        body, status = iface._handle_saml_callback("example.org", da, {})
        assert status == err.ERROR_SAML_RESPONSE_INVALID.h
        assert body["error_code"] == err.ERROR_SAML_RESPONSE_INVALID.c

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
            body, status = iface._handle_saml_callback(
                "example.org", da, {"SAMLResponse": "b64"}
            )

        assert status == 200
        assert body["data"]["jwt_token"] == "tok"
        assert body["data"]["saml_name_id"] == "nameid"
        assert body["data"]["saml_attributes"] == {"mail": ["u@example.org"]}
        assert body["data"]["saml_display_name"] == "User U"
        assert body["data"]["saml_eppn"] == "u@example.org"
        assert body["data"]["saml_issuer"] == "https://idp.example.org"
        auth_m.assert_called_once_with(
            "example.org", "u@example.org", "saml2",
            display_name="User U", eppn="u@example.org",
        )

    def test_email_fallback_to_eppn(self, iface):
        da = _domain_auth("saml2")
        saml = MagicMock()
        saml.process_response.return_value = {"eppn": "u@example.org"}
        with patch.object(iface, "_build_saml", return_value=saml), patch.object(
            iface, "_authenticate_sso_user", return_value={"jwt_token": "t"}
        ) as auth_m:
            body, status = iface._handle_saml_callback(
                "example.org", da, {"SAMLResponse": "b64"}
            )
        assert status == 200
        auth_m.assert_called_once_with(
            "example.org", "u@example.org", "saml2",
            display_name="", eppn="u@example.org",
        )

    def test_email_fallback_to_name_id(self, iface):
        da = _domain_auth("saml2")
        saml = MagicMock()
        saml.process_response.return_value = {"name_id": "uid@example.org"}
        with patch.object(iface, "_build_saml", return_value=saml), patch.object(
            iface, "_authenticate_sso_user", return_value={"jwt_token": "t"}
        ) as auth_m:
            body, status = iface._handle_saml_callback(
                "example.org", da, {"SAMLResponse": "b64"}
            )
        assert status == 200
        auth_m.assert_called_once_with(
            "example.org", "uid@example.org", "saml2",
            display_name="", eppn="",
        )

    def test_no_email_identity(self, iface):
        da = _domain_auth("saml2")
        saml = MagicMock()
        saml.process_response.return_value = {}
        with patch.object(iface, "_build_saml", return_value=saml):
            body, status = iface._handle_saml_callback(
                "example.org", da, {"SAMLResponse": "b64"}
            )
        assert status == err.ERROR_SAML_RESPONSE_INVALID.h
        assert body["error_code"] == err.ERROR_SAML_RESPONSE_INVALID.c

    def test_generic_exception(self, iface):
        da = _domain_auth("saml2")
        saml = MagicMock()
        saml.process_response.side_effect = RuntimeError("bad xml")
        with patch.object(iface, "_build_saml", return_value=saml):
            body, status = iface._handle_saml_callback(
                "example.org", da, {"SAMLResponse": "b64"}
            )
        assert status == err.ERROR_SAML_RESPONSE_INVALID.h

    def test_request_exception_is_propagated(self, iface):
        da = _domain_auth("saml2")
        saml = MagicMock()

        def _raise(*args, **kwargs):
            raise RequestException("boom", err.ERROR_SAML_RESPONSE_INVALID)

        saml.process_response.side_effect = _raise
        with patch.object(iface, "_build_saml", return_value=saml), pytest.raises(
            RequestException
        ) as excinfo:
            iface._handle_saml_callback("example.org", da, {"SAMLResponse": "b64"})
        assert excinfo.value.error.c == err.ERROR_SAML_RESPONSE_INVALID.c


# ===========================================================================
# InterfaceAuthSSO - builders / redirect uri
# ===========================================================================

class TestBuildOidc:
    def test_missing_discovery_url_raises(self, iface):
        da = _domain_auth("openid", SOGO_D_OPENID_CONFIG_URL="")
        with pytest.raises(RequestException) as excinfo:
            iface._build_oidc(da)
        assert excinfo.value.error.c == err.ERROR_OIDC_NOT_CONFIGURED.c

    def test_constructs_module(self, iface):
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


class TestBuildSaml:
    def test_requires_configuration(self, iface):
        da = _domain_auth("saml2", SOGO_D_SAML2_URL="", SOGO_D_SAML2_IDP_METADATA_URL="")
        with pytest.raises(RequestException) as excinfo:
            iface._build_saml(da, "example.org")
        assert excinfo.value.error.c == err.ERROR_SAML_NOT_CONFIGURED.c

    def test_simple_mode(self, iface):
        da = _domain_auth("saml2")
        with patch("app.interface.auth.InterfaceAuthSSO.ModuleSAML2") as m, patch(
            "app.interface.auth.InterfaceAuthSSO.Saml2Keypair"
        ) as kp:
            kp.return_value.load_keypair.return_value = ("cert", "key")
            iface._build_saml(da, "example.org")
        m.assert_called_once()
        _, kwargs = m.call_args
        assert kwargs["idp_sso_url"] == "https://idp.example.org/sso"
        assert kwargs["idp_entity_id"] == "https://idp.example.org"
        assert kwargs["x509_cert"] == "cert"
        assert kwargs["x509_key"] == "key"
        assert kwargs["want_assertions_signed"] is True
        assert kwargs["want_assertions_encrypted"] is False
        assert kwargs["name_id_format"] == "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"

    def test_derived_sp_entity_id_when_unset(self, iface):
        da = _domain_auth("saml2", SOGO_D_SAML2_SP_ENTITY_ID="")
        with patch("app.interface.auth.InterfaceAuthSSO.ModuleSAML2") as m, patch(
            "app.interface.auth.InterfaceAuthSSO.Saml2Keypair"
        ) as kp:
            kp.return_value.load_keypair.return_value = ("cert", "key")
            iface._build_saml(da, "example.org")
        _, kwargs = m.call_args
        assert kwargs["entity_id"] == (
            "https://mail.example.org/api/user/v1/auth/metadata/example.org"
        )

    def test_configured_sp_entity_id_kept(self, iface):
        da = _domain_auth("saml2", SOGO_D_SAML2_SP_ENTITY_ID="sp-entity")
        with patch("app.interface.auth.InterfaceAuthSSO.ModuleSAML2") as m, patch(
            "app.interface.auth.InterfaceAuthSSO.Saml2Keypair"
        ) as kp:
            kp.return_value.load_keypair.return_value = ("cert", "key")
            iface._build_saml(da, "example.org")
        _, kwargs = m.call_args
        assert kwargs["entity_id"] == "sp-entity"

    def test_metadata_url_flow(self, iface):
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

    def test_metadata_failure_without_sso_raises(self, iface):
        da = _domain_auth(
            "saml2",
            SOGO_D_SAML2_URL="",
            SOGO_D_SAML2_IDP_METADATA_URL="https://idp.example.org/metadata",
        )
        mf = MagicMock()
        mf.get_idp_config.side_effect = RuntimeError("http fail")
        with patch("app.interface.auth.InterfaceAuthSSO.Saml2Keypair") as kp, patch(
            "app.module.auth.Saml2Metadata.Saml2Metadata", return_value=mf
        ), pytest.raises(RequestException) as excinfo:
            kp.return_value.load_keypair.return_value = ("cert", "key")
            iface._build_saml(da, "example.org")
        assert excinfo.value.error.c == err.ERROR_SAML_METADATA_FETCH_FAILED.c

    def test_metadata_failure_with_sso_continues(self, iface):
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

    def test_provider_from_db_overrides(self, iface):
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
        assert kwargs["idp_entity_id"] == "https://prov.example.org"

    def test_provider_missing_keeps_defaults(self, iface):
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

    def test_provider_db_error_ignored(self, iface):
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

    def test_redis_unavailable(self, iface):
        da = _domain_auth("saml2")

        def _boom(*args, **kwargs):
            raise RuntimeError("redis down")

        with patch("app.interface.auth.InterfaceAuthSSO.ModuleSAML2") as m, patch(
            "app.interface.auth.InterfaceAuthSSO.Saml2Keypair"
        ) as kp, patch("app.service.sogo_cache", side_effect=_boom):
            kp.return_value.load_keypair.return_value = ("cert", "key")
            iface._build_saml(da, "example.org")
        _, kwargs = m.call_args
        assert kwargs["redis_client"] is None

    def test_redis_client_passed(self, iface):
        da = _domain_auth("saml2")
        cache = FakeCache()
        with patch("app.interface.auth.InterfaceAuthSSO.ModuleSAML2") as m, patch(
            "app.interface.auth.InterfaceAuthSSO.Saml2Keypair"
        ) as kp, patch("app.service.sogo_cache", return_value=cache):
            kp.return_value.load_keypair.return_value = ("cert", "key")
            iface._build_saml(da, "example.org")
        _, kwargs = m.call_args
        assert kwargs["redis_client"] is cache


class TestBuildRedirectUri:
    def test_uses_public_base_url(self, iface):
        assert iface._build_redirect_uri("example.org") == (
            "https://mail.example.org/api/user/v1/auth/callback/example.org"
        )

    def test_falls_back_to_localhost(self):
        iface = InterfaceAuthSSO(_process(SOGO_P_PUBLIC_BASE_URL=""))
        assert iface._build_redirect_uri("d.org") == (
            "http://localhost:5001/api/user/v1/auth/callback/d.org"
        )


# ===========================================================================
# InterfaceAuthSSO - _authenticate_sso_user
# ===========================================================================

def _sso_user_authed_settings():
    return (
        {},
        {
            "USER_SOURCE": {"us1": {"display_name": "Ldap"}},
            "AUTH_SETTINGS": {},
        },
    )


class TestAuthenticateSsoUser:
    def test_user_found_in_source_returns_jwt(self, iface):
        voucher = MagicMock()
        voucher.generate_voucher_from_user.return_value = "jwt-1"
        module_us = MagicMock()
        module_us.check_login.return_value = True

        with patch(
            "app.config.init_config.init_get_system_and_default_domain_settings",
            return_value=_sso_user_authed_settings(),
        ), patch("app.module.auth.ModuleAuth.ModuleAuth"), patch.object(
            iface, "_load_domain_user_sources", return_value={}
        ), patch(
            "app.module.auth.ModuleUserSource.ModuleUserSource", return_value=module_us
        ), patch(
            "app.auth.service.VoucherUserService.VoucherUserService", return_value=voucher
        ):
            result = iface._authenticate_sso_user("example.org", "u@example.org", "oidc")

        assert result == {"jwt_token": "jwt-1"}
        module_us.check_login.assert_called_once()

    def test_onboarding_creates_profile_calendar_and_contacts(self, iface):
        voucher = MagicMock()
        voucher.generate_voucher_from_user.return_value = "jwt-2"
        module_us = MagicMock()
        module_us.check_login.return_value = False
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
            "app.module.auth.ModuleUserSource.ModuleUserSource", return_value=module_us
        ), patch(
            "app.module.user.ModuleUserProfile.ModuleUserProfile", return_value=profile
        ), patch(
            "app.module.calendar.ModuleCalendar.ModuleCalendar"
        ) as mc, patch(
            "app.module.contact.ModuleContact.ModuleContact"
        ) as mct, patch(
            "app.auth.service.VoucherUserService.VoucherUserService", return_value=voucher
        ):
            result = iface._authenticate_sso_user(
                "example.org", "new@example.org", "saml2", display_name="New User"
            )

        assert result == {"jwt_token": "jwt-2"}
        profile.create_user_profile.assert_called_once()
        profile.get_partial_user_preferences.assert_called_once_with(
            "new@example.org", "user_general"
        )
        mc.return_value.create_personal_calendar.assert_called_once_with(
            "new@example.org", tz="Europe/Berlin"
        )
        mct.return_value.create_personal_addressbook.assert_called_once_with(
            "new@example.org"
        )

    def test_existing_profile_skips_onboarding(self, iface):
        voucher = MagicMock()
        voucher.generate_voucher_from_user.return_value = "jwt-3"
        module_us = MagicMock()
        module_us.check_login.return_value = False
        profile = MagicMock()
        profile.is_user_profile_present.return_value = True

        with patch(
            "app.config.init_config.init_get_system_and_default_domain_settings",
            return_value=({}, {"USER_SOURCE": {}, "AUTH_SETTINGS": {}}),
        ), patch("app.module.auth.ModuleAuth.ModuleAuth"), patch.object(
            iface, "_load_domain_user_sources", return_value={}
        ), patch(
            "app.module.auth.ModuleUserSource.ModuleUserSource", return_value=module_us
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
        ), patch("app.module.auth.ModuleAuth.ModuleAuth"), patch.object(
            iface, "_load_domain_user_sources", side_effect=RuntimeError("db down")
        ), patch(
            "app.auth.service.VoucherUserService.VoucherUserService", return_value=voucher
        ):
            result = iface._authenticate_sso_user("example.org", "u@example.org", "oidc")

        assert result == {"jwt_token": "jwt-4"}

    def test_oidc_user_session_fields(self, iface):
        voucher = MagicMock()
        module_us = MagicMock()
        module_us.check_login.return_value = False
        profile = MagicMock()
        profile.is_user_profile_present.return_value = True

        with patch(
            "app.config.init_config.init_get_system_and_default_domain_settings",
            return_value=({}, {"USER_SOURCE": {}, "AUTH_SETTINGS": {}}),
        ), patch("app.module.auth.ModuleAuth.ModuleAuth"), patch.object(
            iface, "_load_domain_user_sources", return_value={}
        ), patch(
            "app.module.auth.ModuleUserSource.ModuleUserSource", return_value=module_us
        ), patch(
            "app.module.user.ModuleUserProfile.ModuleUserProfile", return_value=profile
        ), patch(
            "app.auth.service.VoucherUserService.VoucherUserService", return_value=voucher
        ):
            iface._authenticate_sso_user("example.org", "oidc@example.org", "oidc")

        user = voucher.generate_voucher_from_user.call_args.args[0]
        assert user.auth_method == "oidc"
        assert user.password == ""
        assert user.domain == "example.org"
        assert user.mail == "oidc@example.org"
        # cn derived from email local part when no display_name given
        assert user.cn == "oidc"

    def test_saml_user_uses_display_name_for_cn(self, iface):
        voucher = MagicMock()
        module_us = MagicMock()
        module_us.check_login.return_value = True

        with patch(
            "app.config.init_config.init_get_system_and_default_domain_settings",
            return_value=_sso_user_authed_settings(),
        ), patch("app.module.auth.ModuleAuth.ModuleAuth"), patch.object(
            iface, "_load_domain_user_sources", return_value={}
        ), patch(
            "app.module.auth.ModuleUserSource.ModuleUserSource", return_value=module_us
        ), patch(
            "app.auth.service.VoucherUserService.VoucherUserService", return_value=voucher
        ):
            iface._authenticate_sso_user(
                "example.org", "saml@example.org", "saml2", display_name="SAML User"
            )

        user = voucher.generate_voucher_from_user.call_args.args[0]
        assert user.auth_method == "saml2"
        assert user.cn == "SAML User"


# ===========================================================================
# InterfaceAuthSSO - _load_domain_user_sources
# ===========================================================================

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
            result = iface._load_domain_user_sources(
                "example.org", None, None, default_us
            )
        assert result == default_us

    def test_db_result_overrides_default(self, iface):
        default_us = {"us1": "default"}
        db = MagicMock()
        db.select_from_table.return_value = [
            ({"USER_SOURCE": {"us2": {"display_name": "Custom"}}},)
        ]

        with patch("app.config.settings.DomainSettings.UserSourceSettingsObj", SimpleNamespace), patch(
            "app.config.settings.ProcessSetting.process_config"
        ) as pc, patch(
            "app.utils.module.importManager.import_and_instantiate_manager",
            return_value=db,
        ):
            pc.SOGO_P_DB_TYPE = "SQLite"
            result = iface._load_domain_user_sources(
                "example.org", None, None, default_us
            )
        assert "us2" in result
        assert "us1" not in result
        assert result["us2"].display_name == "Custom"
