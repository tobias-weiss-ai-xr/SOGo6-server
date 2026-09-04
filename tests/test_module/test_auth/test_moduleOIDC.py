"""Unit tests for ModuleOIDC (OpenID Connect client module).

Tests the OIDC relying-party module covering:
- Discovery (well-known configuration + JWKS)
- Authorization URL generation (PKCE + nonce + state)
- PKCE state persistence (Redis)
- Token exchange
- ID token validation (JWT)
- User info retrieval
- Email extraction with fallbacks
- End-session URL building
"""
from unittest.mock import MagicMock, patch

import pytest

from app.module.auth.ModuleOIDC import ModuleOIDC
from app.utils.exceptions import RequestException


@pytest.fixture
def oidc():
    return ModuleOIDC(
        issuer="https://idp.example.org",
        client_id="client1",
        client_secret="secret1",
        scope="openid profile email",
        email_claim="email",
    )


class TestInit:
    def test_defaults(self):
        oidc = ModuleOIDC()
        assert oidc._issuer == ""
        assert oidc._scope == "openid profile email"
        assert oidc._email_claim == "email"
        assert oidc._allow_redirect_uris == frozenset()

    def test_allow_redirect_uris_as_frozenset(self):
        oidc = ModuleOIDC(allow_redirect_uris=["https://app.example.org/cb"])
        assert oidc._allow_redirect_uris == frozenset(["https://app.example.org/cb"])


class TestDiscover:
    def test_missing_issuer_raises(self, oidc):
        oidc._issuer = ""
        with pytest.raises(RequestException):
            oidc.discover()



class TestDiscover:
    @patch("requests.get")
    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()

        assert oidc._jwks == [{"kid": "key1"}]
        assert mock_get.call_count == 2
        assert "idp.example.org/.well-known/openid-configuration" in mock_get.call_args_list[0][0][0]

    @patch("requests.get")
    def test_no_jwks_uri_skips_jwks_fetch(self, mock_get, oidc):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_get.return_value = mock_resp

        oidc.discover()

        assert oidc._jwks == []
        assert mock_get.call_count == 1

    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()

        assert oidc._jwks == [{"kid": "key1"}]
        assert mock_get.call_count == 2
        assert "idp.example.org/.well-known/openid-configuration" in mock_get.call_args_list[0][0][0]
    @patch("requests.get")
    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()

        assert oidc._jwks == [{"kid": "key1"}]
        assert mock_get.call_count == 2
        assert "idp.example.org/.well-known/openid-configuration" in mock_get.call_args_list[0][0][0]
    @patch("requests.get")
    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()

        assert oidc._jwks == [{"kid": "key1"}]
        assert mock_get.call_count == 2
        assert "idp.example.org/.well-known/openid-configuration" in mock_get.call_args_list[0][0][0]
    @patch("requests.get")
    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()

        assert oidc._jwks == [{"kid": "key1"}]
        assert mock_get.call_count == 2
        assert "idp.example.org/.well-known/openid-configuration" in mock_get.call_args_list[0][0][0]
    @patch("requests.get")
    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()

        assert oidc._jwks == [{"kid": "key1"}]
        assert mock_get.call_count == 2
        assert "idp.example.org/.well-known/openid-configuration" in mock_get.call_args_list[0][0][0]
    @patch("requests.get")
    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()

        assert oidc._jwks == [{"kid": "key1"}]
        assert mock_get.call_count == 2
        assert "idp.example.org/.well-known/openid-configuration" in mock_get.call_args_list[0][0][0]
    @patch("requests.get")
    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()

        assert oidc._jwks == [{"kid": "key1"}]
        assert mock_get.call_count == 2
        assert "idp.example.org/.well-known/openid-configuration" in mock_get.call_args_list[0][0][0]
    @patch("requests.get")
    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()

        assert oidc._jwks == [{"kid": "key1"}]
        assert mock_get.call_count == 2
        assert "idp.example.org/.well-known/openid-configuration" in mock_get.call_args_list[0][0][0]
    @patch("requests.get")
    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()

        assert oidc._jwks == [{"kid": "key1"}]
        assert mock_get.call_count == 2
        assert "idp.example.org/.well-known/openid-configuration" in mock_get.call_args_list[0][0][0]
    @patch("requests.get")
    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()

        assert oidc._jwks == [{"kid": "key1"}]
        assert mock_get.call_count == 2
        assert "idp.example.org/.well-known/openid-configuration" in mock_get.call_args_list[0][0][0]
    @patch("requests.get")
    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()

        assert oidc._jwks == [{"kid": "key1"}]
        assert mock_get.call_count == 2
        assert "idp.example.org/.well-known/openid-configuration" in mock_get.call_args_list[0][0][0]
    @patch("requests.get")
    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()

        assert oidc._jwks == [{"kid": "key1"}]
        assert mock_get.call_count == 2
        assert "idp.example.org/.well-known/openid-configuration" in mock_get.call_args_list[0][0][0]
    @patch("requests.get")
    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()

        assert oidc._jwks == [{"kid": "key1"}]
        assert mock_get.call_count == 2
        assert "idp.example.org/.well-known/openid-configuration" in mock_get.call_args_list[0][0][0]
    @patch("requests.get")
    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()

        assert oidc._jwks == [{"kid": "key1"}]
        assert mock_get.call_count == 2
        assert "idp.example.org/.well-known/openid-configuration" in mock_get.call_args_list[0][0][0]
    @patch("requests.get")
    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()

        assert oidc._jwks == [{"kid": "key1"}]
        assert mock_get.call_count == 2
        assert "idp.example.org/.well-known/openid-configuration" in mock_get.call_args_list[0][0][0]
    @patch("requests.get")
    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()

        assert oidc._jwks == [{"kid": "key1"}]
        assert mock_get.call_count == 2
        assert "idp.example.org/.well-known/openid-configuration" in mock_get.call_args_list[0][0][0]
    @patch("requests.get")
    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()

        assert oidc._jwks == [{"kid": "key1"}]
        assert mock_get.call_count == 2
        assert "idp.example.org/.well-known/openid-configuration" in mock_get.call_args_list[0][0][0]
    @patch("requests.get")
    def test_fetches_metadata_and_jwks(self, mock_get, oidc):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {
            "jwks_uri": "https://idp.example.org/jwks",
            "authorization_endpoint": "https://idp.example.org/authorize",
        }
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"keys": [{"kid": "key1"}]}
        mock_get.side_effect = [mock_resp1, mock_resp2]

        oidc.discover()
    def test_returns_value(self, oidc):
        oidc._metadata = {"authorization_endpoint": "https://idp.example.org/authorize"}
        assert oidc._get_metadata("authorization_endpoint") == "https://idp.example.org/authorize"

    def test_returns_default_when_missing(self, oidc):
        oidc._metadata = {}
        assert oidc._get_metadata("missing", "fallback") == "fallback"


class TestCreateAuthorizationUrl:
    def test_builds_url_with_params(self, oidc):
        oidc._metadata = {"authorization_endpoint": "https://idp.example.org/authorize"}
        with patch.object(oidc, "_persist_pkce_state") as mock_persist:
            url = oidc.create_authorization_url("https://app.example.org/cb", state="st")

            assert url.startswith("https://idp.example.org/authorize?")
            assert "response_type=code" in url
            assert "client_id=client1" in url
            assert "redirect_uri=" in url
            assert "scope=" in url
            assert "state=" in url
            assert "code_challenge=" in url
            assert "code_challenge_method=S256" in url
            assert "nonce=" in url
            mock_persist.assert_called_once()

    def test_generates_nonce(self, oidc):
        oidc._metadata = {"authorization_endpoint": "https://idp.example.org/authorize"}
        with patch.object(oidc, "_persist_pkce_state"):
            oidc.create_authorization_url("https://app.example.org/cb")
        assert oidc._expected_nonce is not None
        assert oidc._code_verifier is not None

    def test_fallback_endpoint_from_issuer(self, oidc):
        oidc._metadata = {}
        with patch.object(oidc, "_persist_pkce_state"):
            url = oidc.create_authorization_url("https://app.example.org/cb")
        assert url.startswith("https://idp.example.org/authorize?")
        assert "code_verifier" not in url  # verifier is never sent, only challenge


class TestPkceStatePersistence:
    def test_persist_state_stores_in_redis(self, oidc):
        oidc._code_verifier = "verifier123"
        oidc._expected_nonce = "nonce123"
        mock_cache = MagicMock()
        with patch("app.service.sogo_cache", return_value=mock_cache):
            oidc._persist_pkce_state("state123")

            key = mock_cache.set.call_args[0][0]
            assert key == "oidc:state:state123"
            stored = mock_cache.set.call_args[0][1]
            assert stored["code_verifier"] == "verifier123"
            assert stored["nonce"] == "nonce123"

    def test_persist_state_swallows_errors(self, oidc):
        with patch("app.service.sogo_cache", side_effect=RuntimeError("no redis")):
            oidc._persist_pkce_state("state123")  # must not raise

    def test_load_state_restores_verifier(self, oidc):
        mock_cache = MagicMock()
        mock_cache.get.return_value = {"code_verifier": "cv1", "nonce": "nn1"}
        with patch("app.service.sogo_cache", return_value=mock_cache):
            oidc._load_pkce_state("state123")
        assert oidc._code_verifier == "cv1"
        assert oidc._expected_nonce == "nn1"

    def test_load_state_missing_sets_verifier_none(self, oidc):
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        with patch("app.service.sogo_cache", return_value=mock_cache):
            oidc._load_pkce_state("state123")
        assert oidc._code_verifier is None

    def test_delete_state(self, oidc):
        mock_cache = MagicMock()
        with patch("app.service.sogo_cache", return_value=mock_cache):
            oidc._delete_pkce_state("state123")
        mock_cache.delete.assert_called_once_with("oidc:state:state123")


class TestFetchToken:
    def test_missing_code_verifier_raises(self, oidc):
        oidc._code_verifier = None
        with pytest.raises(RequestException) as exc_info:
            oidc.fetch_token("code123", "https://app.example.org/cb")
        assert "no code verifier" in str(exc_info.value).lower()

    @patch("app.module.auth.ModuleOIDC.OAuth2Session")
    def test_exchanges_token(self, mock_session_cls, oidc):
        oidc._metadata = {"token_endpoint": "https://idp.example.org/token"}
        oidc._code_verifier = "cv1"
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.fetch_token.return_value = {
            "access_token": "at1",
            "id_token": "id1",
        }

        result = oidc.fetch_token("code123", "https://app.example.org/cb")

        assert result["access_token"] == "at1"
        assert result["id_token"] == "id1"
        mock_session.fetch_token.assert_called_once()
        kwargs = mock_session.fetch_token.call_args[1]
        assert kwargs["code"] == "code123"
        assert kwargs["code_verifier"] == "cv1"

    @patch("app.module.auth.ModuleOIDC.OAuth2Session")
    def test_exchange_clears_code_verifier(self, mock_session_cls, oidc):
        oidc._metadata = {"token_endpoint": "https://idp.example.org/token"}
        oidc._code_verifier = "cv1"
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        oidc.fetch_token("code123", "https://app.example.org/cb")

        assert oidc._code_verifier is None


class TestValidateIdToken:
    def test_no_jwks_raises(self, oidc):
        oidc._jwks = []
        with pytest.raises(RequestException):
            oidc.validate_id_token("jwt")

    @patch("app.module.auth.ModuleOIDC.JsonWebToken")
    def test_validates_and_checks_claims(self, mock_jwt_cls, oidc):
        oidc._jwks = [{"kid": "key1"}]
        oidc._expected_nonce = "expected_nonce"
        mock_jwt = MagicMock()
        mock_claims = MagicMock()
        mock_claims.get.return_value = "expected_nonce"
        mock_jwt.decode.return_value = mock_claims
        mock_jwt_cls.return_value = mock_jwt

        result = oidc.validate_id_token("jwt")

        mock_jwt.decode.assert_called_once()
        kwargs = mock_jwt.decode.call_args[1]
        assert kwargs["claims_options"]["iss"]["value"] == "https://idp.example.org"
        assert kwargs["claims_options"]["aud"]["value"] == "client1"
        mock_claims.validate.assert_called_once()

    @patch("app.module.auth.ModuleOIDC.JsonWebToken")
    def test_nonce_mismatch_raises(self, mock_jwt_cls, oidc):
        oidc._jwks = [{"kid": "key1"}]
        oidc._expected_nonce = "expected"
        mock_jwt = MagicMock()
        mock_claims = MagicMock()
        mock_claims.get.return_value = "wrong_nonce"
        mock_jwt.decode.return_value = mock_claims
        mock_jwt_cls.return_value = mock_jwt

        with pytest.raises(RequestException) as exc_info:
            oidc.validate_id_token("jwt")
        assert "nonce" in str(exc_info.value).lower()


class TestGetUserInfo:
    def test_no_endpoint_raises(self, oidc):
        oidc._metadata = {}
        with pytest.raises(RequestException):
            oidc.get_user_info()

    def test_no_session_raises(self, oidc):
        oidc._metadata = {"userinfo_endpoint": "https://idp.example.org/userinfo"}
        oidc._session = None
        with pytest.raises(RequestException):
            oidc.get_user_info()

    def test_fetches_userinfo(self, oidc):
        oidc._metadata = {"userinfo_endpoint": "https://idp.example.org/userinfo"}
        oidc._session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"email": "user@example.org"}
        oidc._session.get.return_value = mock_resp

        result = oidc.get_user_info()

        assert result == {"email": "user@example.org"}
        oidc._session.get.assert_called_once_with("https://idp.example.org/userinfo")


class TestGetEmail:
    def test_email_from_userinfo(self, oidc):
        email = oidc.get_email({"email": "a@example.org"}, {"email": "b@example.org"})
        assert email == "a@example.org"

    def test_email_from_id_token(self, oidc):
        email = oidc.get_email({}, {"email": "b@example.org"})
        assert email == "b@example.org"

    def test_fallback_constructed_email(self, oidc):
        email = oidc.get_email({}, {"sub": "user123"})
        assert email == "user123@idp.example.org"

    def test_email_claim_custom(self, oidc):
        oidc._email_claim = "mail"
        email = oidc.get_email({"mail": "c@example.org"}, {})
        assert email == "c@example.org"


class TestGetSubject:
    def test_returns_sub(self, oidc):
        assert oidc.get_subject({"sub": "subject1"}) == "subject1"

    def test_missing_sub_returns_empty(self, oidc):
        assert oidc.get_subject({}) == ""


class TestGetEndSessionUrl:
    def test_returns_empty_when_no_endpoint(self, oidc):
        oidc._metadata = {}
        assert oidc.get_end_session_url("hint") == ""

    def test_builds_logout_url(self, oidc):
        oidc._metadata = {"end_session_endpoint": "https://idp.example.org/logout"}
        url = oidc.get_end_session_url("hint123", "https://app.example.org/bye")
        assert url.startswith("https://idp.example.org/logout?")
        assert "id_token_hint=hint123" in url
        assert "post_logout_redirect_uri=" in url

    def test_logout_without_redirect(self, oidc):
        oidc._metadata = {"end_session_endpoint": "https://idp.example.org/logout"}
        url = oidc.get_end_session_url("hint123")
        assert "post_logout_redirect_uri" not in url
