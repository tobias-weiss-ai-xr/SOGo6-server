"""OpenID Connect authentication module.

Implements the Authorization Code flow with PKCE / state verification.
Handles discovery, authorization URL generation, token exchange, and
user-info retrieval for federated SSO via any standard OIDC provider.
"""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlencode

from authlib.integrations.requests_client import OAuth2Session
from authlib.jose import JsonWebKey, JsonWebToken
from authlib.oauth2.rfc6749 import OAuth2Token

from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api


class ModuleOIDC:
    """OIDC Relying Party (client) that wraps authlib's OAuth2Session.

    Typical usage (called from the authentication interface layer)::

        oidc = ModuleOIDC(domain_settings.SOGO_D_* fields)
        auth_url = oidc.create_authorization_url(redirect_uri, state)
        token = oidc.fetch_token(code, redirect_uri)
        userinfo = oidc.get_user_info()
    """

    def __init__(
        self,
        issuer: str = "",
        client_id: str = "",
        client_secret: str = "",
        scope: str = "openid profile email",
        email_claim: str = "email",
        allow_redirect_uris: list[str] | None = None,
    ) -> None:
        """Initialise the OIDC client from per-domain settings.

        :param issuer: OIDC provider's issuer URL (used for discovery).
        :param client_id: Client identifier assigned by the provider.
        :param client_secret: Client secret assigned by the provider.
        :param scope: Space-separated scope string.
        :param email_claim: Claim that carries the user's email address in
            the userinfo response (default ``email`` — standard OIDC).
        :param allow_redirect_uris: Allowed redirect URIs for CSRF validation.
        """
        self._issuer = issuer
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope
        self._email_claim = email_claim
        self._allow_redirect_uris = frozenset(allow_redirect_uris or [])

        # Filled by discover()
        self._metadata: dict[str, Any] = {}
        self._jwks: list[dict[str, Any]] = []

        # Filled after token exchange
        self._session: OAuth2Session | None = None
        self._token: OAuth2Token | None = None

        # PKCE code verifier (generated per authorization request)
        self._code_verifier: str | None = None
        # Nonce for ID token replay protection
        self._expected_nonce: str | None = None

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> None:
        """Fetch the OIDC discovery document and JWKS.

        Must be called before :meth:`create_authorization_url` or
        :meth:`fetch_token`.
        """
        if not self._issuer:
            raise RequestException("OIDC issuer URL is not configured")

        # Strip trailing slash for well-known URL construction
        issuer = self._issuer.rstrip("/")
        well_known = f"{issuer}/.well-known/openid-configuration"

        import requests

        logger_api.debug("OIDC discovery: fetching %s", well_known)
        resp = requests.get(well_known, timeout=10)
        resp.raise_for_status()
        self._metadata = resp.json()

        # Fetch JWKS
        jwks_uri = self._metadata.get("jwks_uri", "")
        if jwks_uri:
            jwks_resp = requests.get(jwks_uri, timeout=10)
            jwks_resp.raise_for_status()
            jwks_body: dict = jwks_resp.json()
            self._jwks = jwks_body.get("keys", [])
            logger_api.debug("OIDC discovery: loaded %d JWK keys", len(self._jwks))

    def _get_metadata(self, key: str, default: str = "") -> str:
        """Safe accessor for discovery metadata."""
        val = self._metadata.get(key)
        return str(val) if val else default

    # ------------------------------------------------------------------
    # Authorization URL
    # ------------------------------------------------------------------

    def create_authorization_url(
        self,
        redirect_uri: str,
        state: str = "",
    ) -> str:
        """Build the authorisation URL to redirect the user's browser to.

        Uses PKCE (Proof Key for Code Exchange) to protect against
        authorization code interception attacks. The code verifier is
        stored on the instance and must match the one used in
        :meth:`fetch_token`.

        :param redirect_uri: Callback URL that the provider will redirect
            back to after authentication.
        :param state: Opaque value for CSRF protection (bound to the user's
            session cookie by the caller).
        :returns: Absolute URL pointing to the provider's authorisation
            endpoint with all required query parameters.
        """
        import hashlib
        import base64

        # Generate PKCE code verifier and challenge (S256)
        self._code_verifier = secrets.token_urlsafe(64)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(self._code_verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")

        # Generate nonce for ID token replay protection
        self._expected_nonce = secrets.token_urlsafe(32)

        auth_endpoint = self._get_metadata("authorization_endpoint", "")
        if not auth_endpoint:
            # Fallback: construct from issuer
            auth_endpoint = f"{self._issuer.rstrip('/')}/authorize"

        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "scope": self._scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "nonce": self._expected_nonce,
        }

        authorization_url = f"{auth_endpoint}?{urlencode(params)}"
        logger_api.debug("OIDC authorization URL built (PKCE+S256+nonce)")
        return authorization_url

    # ------------------------------------------------------------------
    # Token exchange
    # ------------------------------------------------------------------

    def fetch_token(
        self,
        code: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        """Exchange the authorisation ``code`` for an access / ID token.

        Uses PKCE code verifier generated during :meth:`create_authorization_url`
        to prove possession of the original authorization request.

        :param code: The authorisation code returned by the provider.
        :param redirect_uri: Must match the redirect URI used in the
            authorisation request.
        :returns: Decoded token response (access_token, id_token, …).
        :raises RequestException: If no PKCE code verifier was generated
            (i.e., create_authorization_url was not called first).
        """
        if not self._code_verifier:
            raise RequestException(
                "OIDC PKCE: no code verifier available. "
                "create_authorization_url() must be called before fetch_token()."
            )

        token_endpoint = self._get_metadata("token_endpoint", "")
        if not token_endpoint:
            token_endpoint = f"{self._issuer.rstrip('/')}/token"

        session = OAuth2Session(
            client_id=self._client_id,
            client_secret=self._client_secret,
            scope=self._scope,
        )

        logger_api.debug("OIDC token exchange: POST %s (PKCE enabled)", token_endpoint)
        token: OAuth2Token = session.fetch_token(
            token_endpoint,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=self._code_verifier,
        )
        self._session = session
        self._token = token

        # Clear PKCE verifier after use (one-time use)
        self._code_verifier = None

        return dict(token)

    # ------------------------------------------------------------------
    # Validate ID token (JWT)
    # ------------------------------------------------------------------

    def validate_id_token(self, id_token: str) -> dict[str, Any]:
        """Validate and decode the ID token JWT.

        Checks:
        - Signature against the provider's JWKS
        - ``iss`` matches the expected issuer
        - ``aud`` contains our client_id
        - Token is not expired (``exp``)
        - ``nonce`` matches the expected nonce (replay protection)

        :param id_token: The raw JWT string (from the token response).
        :returns: Decoded claims if valid.
        :raises RequestException: If validation fails.
        """
        if not self._jwks:
            raise RequestException("OIDC: no JWKS loaded, call discover() first")

        jwt = JsonWebToken(["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"])

        # Load public keys
        public_keys = [JsonWebKey.import_key(k) for k in self._jwks]

        # Validate
        claims = jwt.decode(
            id_token,
            public_keys,
            claims_options={
                "iss": {"value": self._issuer.rstrip("/")},
                "aud": {"value": self._client_id},
            },
        )
        claims.validate()  # raises on expiry / invalid claims

        # Validate nonce (replay attack protection)
        if self._expected_nonce is not None:
            actual_nonce = claims.get("nonce")
            if actual_nonce is None or not secrets.compare_digest(str(actual_nonce), self._expected_nonce):
                raise RequestException("OIDC ID token nonce mismatch (possible replay attack)")
            # Clear nonce after validation (one-time use)
            self._expected_nonce = None

        logger_api.debug(
            "OIDC ID token validated for subject: %s (nonce OK)",
            claims.get("sub"),
        )
        return dict(claims)

    # ------------------------------------------------------------------
    # User info
    # ------------------------------------------------------------------

    def get_user_info(self) -> dict[str, Any]:
        """Fetch the userinfo endpoint using the access token.

        :returns: JSON body of the userinfo response.
        """
        userinfo_endpoint = self._get_metadata("userinfo_endpoint", "")
        if not userinfo_endpoint:
            raise RequestException("OIDC: no userinfo_endpoint in provider metadata")

        if not self._session:
            raise RequestException("OIDC: no active session, call fetch_token() first")

        resp = self._session.get(userinfo_endpoint)
        resp.raise_for_status()
        return resp.json()

    def get_email(self, userinfo: dict[str, Any], id_token_claims: dict[str, Any]) -> str:
        """Extract the user's email address from the available sources.

        Precedence:
        1. Userinfo endpoint response (``email_claim`` field)
        2. ID token claims (``email_claim`` field)
        3. ID token ``sub`` claim (opaque, used as fallback)

        :param userinfo: Parsed userinfo endpoint response.
        :param id_token_claims: Decoded ID token claims.
        :returns: Email address string.
        """
        email = userinfo.get(self._email_claim, "") or id_token_claims.get(self._email_claim, "")
        if not email:
            email = f"{id_token_claims.get('sub', 'unknown')}@{self._issuer.replace('https://', '').replace('http://', '').split('/')[0]}"
            logger_api.warning(
                "OIDC: %s claim not found in userinfo or id_token, "
                "falling back to constructed email: %s",
                self._email_claim,
                email,
            )
        return email

    def get_subject(self, id_token_claims: dict[str, Any]) -> str:
        """Return the ``sub`` claim from the validated ID token."""
        return str(id_token_claims.get("sub", ""))

    # ------------------------------------------------------------------
    # End-session (RP-initiated logout)
    # ------------------------------------------------------------------

    def get_end_session_url(
        self,
        id_token_hint: str,
        post_logout_redirect_uri: str = "",
    ) -> str:
        """Build the RP-initiated logout URL for the OIDC provider.

        :param id_token_hint: The ID token (JWT) to pass as a hint.
        :param post_logout_redirect_uri: Where to redirect after logout.
        :returns: Absolute logout URL (may be empty if not supported).
        """
        end_session = self._metadata.get("end_session_endpoint", "")
        if not end_session:
            return ""

        params: dict[str, str] = {"id_token_hint": id_token_hint}
        if post_logout_redirect_uri:
            params["post_logout_redirect_uri"] = post_logout_redirect_uri

        return f"{end_session}?{urlencode(params)}"
