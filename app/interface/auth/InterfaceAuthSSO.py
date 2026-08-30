"""Interface for SSO (OIDC / SAML2) authentication.

This layer sits between the API callbacks and the specific protocol modules.
It determines whether the domain is configured for OIDC or SAML2 and
delegates to the correct implementation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.config.settings.SystemSettings import SystemSettingsObj
from app.config.settings.DomainSettings import UserSourceSettingsObj
from app.module.auth.ModuleOIDC import ModuleOIDC
from app.module.auth.ModuleSAML2 import ModuleSAML2
from app.module.auth.Saml2Keypair import Saml2Keypair
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.config.settings.DomainSettings import AuthSettingsObj
    from app.config.settings.ProcessSetting import ProcessSetting


class InterfaceAuthSSO:
    """Handles the SSO callback and user creation for OIDC and SAML2."""

    def __init__(
        self,
        process: ProcessSetting,
    ) -> None:
        self._process = process

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def handle_callback(
        self,
        domain: str,
        domain_auth: AuthSettingsObj,
        query_params: dict[str, str],
    ) -> tuple[dict, int]:
        """Process an SSO callback for the given domain.

        Dispatches to either OIDC or SAML2 based on the domain's auth type.

        :param domain: The domain (used in the URL and for user-source lookups).
        :param domain_auth: The domain's :class:`AuthSettingsObj`.
        :param query_params: Raw query parameters from the callback request.
        :returns: API response tuple ``(body, status_code)``.
        """
        auth_type = domain_auth.SOGO_D_AUTH_TYPE

        if auth_type == "openid":
            return self._handle_oidc_callback(domain, domain_auth, query_params)
        if auth_type == "saml2":
            return self._handle_saml_callback(domain, domain_auth, query_params)
        if auth_type in ("cas",):
            message = f"SSO callback not implemented for auth type '{auth_type}'"
            logger_api.warning(message)
            return create_api_base_response(message, err.ERROR_UNKOWN)
        message = f"SSO callback not supported for auth type '{auth_type}'"
        return create_api_base_response(message, err.ERROR_UNKOWN)

    # ------------------------------------------------------------------
    # OIDC callback
    # ------------------------------------------------------------------

    def _handle_oidc_callback(
        self,
        domain: str,
        domain_auth: AuthSettingsObj,
        params: dict[str, str],
    ) -> tuple[dict, int]:
        """Handle the OIDC authorization code callback.

        Flow:
        1. Validate state (CSRF)
        2. Exchange auth code for tokens
        3. Validate ID token
        4. Fetch userinfo
        5. Extract email
        6. Look up / authenticate user
        7. Generate JWT voucher
        8. Redirect to frontend with token
        """
        code = params.get("code", "")
        _ = params.get("state", "")
        # For now, the state is passed via the redirect URL — in production,
        # validate against the session cookie value.

        if not code:
            return create_api_base_response("Missing authorization code", err.ERROR_OIDC_TOKEN_EXCHANGE_FAILED)

        redirect_uri = self._build_redirect_uri(domain)

        try:
            oidc = self._build_oidc(domain_auth)
            oidc.discover()

            # Exchange code for token
            token_data = oidc.fetch_token(code, redirect_uri)
            id_token_jwt = token_data.get("id_token", "")

            if not id_token_jwt:
                return create_api_base_response("No id_token in OIDC response", err.ERROR_OIDC_TOKEN_EXCHANGE_FAILED)

            # Validate ID token
            id_claims = oidc.validate_id_token(id_token_jwt)

            # Fetch userinfo
            userinfo = oidc.get_user_info()

            # Extract email
            email = oidc.get_email(userinfo, id_claims)

            if not email:
                return create_api_base_response(
                    "Could not determine user email from OIDC response",
                    err.ERROR_OIDC_USERINFO_FAILED,
                )

            # Store OIDC tokens in Redis for later token exchange (OpenCloud file picker)
            # Keyed by user email (uid) with 24h TTL to match session lifetime
            try:
                from app.service import sogo_cache
                cache = sogo_cache()
                oidc_tokens = {
                    "access_token": token_data.get("access_token", ""),
                    "refresh_token": token_data.get("refresh_token", ""),
                    "expires_in": token_data.get("expires_in", 3600),
                    "scope": token_data.get("scope", ""),
                }
                cache.set(f"user_oidc_session:{email}", oidc_tokens, ttl=86400)
                cache.close()
                logger_api.info("Stored OIDC tokens for user %s (TTL=24h)", email)
            except Exception as exc:  # pylint: disable=broad-except
                logger_api.warning("Failed to store OIDC tokens for %s: %s", email, exc)
                # Continue anyway — file picker will fail but auth succeeds

            # Authenticate the user in the local user source
            result = self._authenticate_sso_user(domain, email, "oidc")

            # Add the OIDC subject for reference
            result["oidc_sub"] = oidc.get_subject(id_claims)
            return create_api_base_response(result)

        except RequestException:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            logger_api.error("OIDC callback failed: %s", str(exc))
            return create_api_base_response(str(exc), err.ERROR_OIDC_TOKEN_EXCHANGE_FAILED)

    # ------------------------------------------------------------------
    # SAML2 callback
    # ------------------------------------------------------------------

    def _handle_saml_callback(
        self,
        domain: str,
        domain_auth: AuthSettingsObj,
        params: dict[str, str],
    ) -> tuple[dict, int]:
        """Handle the SAML2 HTTP-POST callback.

        Flow:
        1. Decode SAMLResponse
        2. Parse assertion, validate issuer
        3. Extract email / NameID
        4. Look up / authenticate user
        5. Generate JWT voucher
        6. Return token for frontend redirect
        """
        saml_response_b64 = params.get("SAMLResponse", "")

        if not saml_response_b64:
            return create_api_base_response("Missing SAMLResponse", err.ERROR_SAML_RESPONSE_INVALID)

        try:
            saml = self._build_saml(domain_auth, domain)
            result = saml.process_response(saml_response_b64)

            # Use mapped attributes: prefer email, fall back to eppn, then name_id
            email = result.get("email", "") or result.get("eppn", "") or result.get("name_id", "")

            if not email:
                return create_api_base_response(
                    "Could not determine user identity from SAML assertion",
                    err.ERROR_SAML_RESPONSE_INVALID,
                )

            # Authenticate the user in the local user source
            auth_result = self._authenticate_sso_user(
                domain, email, "saml2",
                display_name=result.get("display_name", ""),
                eppn=result.get("eppn", ""),
            )
            auth_result["saml_name_id"] = result.get("name_id", "")
            auth_result["saml_attributes"] = result.get("attributes", {})
            auth_result["saml_display_name"] = result.get("display_name", "")
            auth_result["saml_eppn"] = result.get("eppn", "")
            auth_result["saml_issuer"] = result.get("issuer", "")
            return create_api_base_response(auth_result)

        except RequestException:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            logger_api.error("SAML callback failed: %s", str(exc))
            return create_api_base_response(str(exc), err.ERROR_SAML_RESPONSE_INVALID)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _build_oidc(self, domain_auth: AuthSettingsObj) -> ModuleOIDC:
        """Construct an OIDC module from domain settings."""
        if not domain_auth.SOGO_D_OPENID_CONFIG_URL:
            raise RequestException("OIDC not configured", err.ERROR_OIDC_NOT_CONFIGURED)

        return ModuleOIDC(
            issuer=domain_auth.SOGO_D_OPENID_CONFIG_URL,
            client_id=domain_auth.SOGO_D_OPENID_CLIENT_NAME,
            client_secret=domain_auth.SOGO_D_OPENID_CLIENT_SECRET,
            scope=domain_auth.SOGO_D_OPENID_SCOPE,
            email_claim=domain_auth.SOGO_D_OPENID_EMAIL,
            allow_redirect_uris=domain_auth.SOGO_D_OPENID_ALLOW_REDIRECT,
        )

    def _build_saml(self, domain_auth: AuthSettingsObj, domain: str) -> ModuleSAML2:
        """Construct a SAML2 module from domain settings.

        Supports two modes:
        1. Simple mode: only ``SOGO_D_SAML2_URL`` is set (backward compatible).
        2. Federation mode: ``SOGO_D_SAML2_IDP_METADATA_URL`` or
           ``SOGO_D_SAML2_FEDERATION_METADATA_URL`` is set, enabling metadata
           fetching, signature verification, and replay protection.
        """
        if not domain_auth.SOGO_D_SAML2_URL and not domain_auth.SOGO_D_SAML2_IDP_METADATA_URL:
            raise RequestException("SAML2 not configured", err.ERROR_SAML_NOT_CONFIGURED)

        # Build the ACS URL (our callback endpoint)
        acs_url = self._build_redirect_uri(domain)

        # SP entity ID — use configured value or derive from ACS URL
        sp_entity_id = domain_auth.SOGO_D_SAML2_SP_ENTITY_ID
        if not sp_entity_id:
            sp_entity_id = acs_url.replace("/callback/", "/metadata/").rstrip("/")

        # Load SP keypair for signing / decryption
        keypair = Saml2Keypair(self._process)
        sp_cert, sp_key = keypair.load_keypair()

        # IdP certificate (for signature verification)
        # In federation mode, this comes from the provider DB / metadata.
        # In simple mode, it may not be available (legacy insecure mode).
        idp_cert = ""
        idp_entity_id = domain_auth.SOGO_D_SAML2_IDP_ENTITY_ID
        idp_sso_url = domain_auth.SOGO_D_SAML2_URL

        # If metadata URL is configured, fetch IdP config from metadata
        if domain_auth.SOGO_D_SAML2_IDP_METADATA_URL:
            try:
                from app.module.auth.Saml2Metadata import Saml2Metadata
                metadata_fetcher = Saml2Metadata(self._process)
                idp_config = metadata_fetcher.get_idp_config(
                    domain_auth.SOGO_D_SAML2_IDP_METADATA_URL,
                    entity_id=idp_entity_id or None,
                )
                idp_sso_url = idp_config.get("sso_url", idp_sso_url)
                idp_cert = idp_config.get("certificate", "")
                if not idp_entity_id:
                    idp_entity_id = idp_config.get("entity_id", "")
                logger_api.info(
                    "SAML2: loaded IdP config from metadata URL (entity_id=%s)",
                    idp_entity_id,
                )
            except Exception as exc:  # pylint: disable=broad-except
                logger_api.warning("SAML2: failed to fetch IdP metadata: %s", exc)
                if not idp_sso_url:
                    raise RequestException(
                        f"SAML2: failed to fetch IdP metadata and no SSO URL configured: {exc}",
                        err.ERROR_SAML_METADATA_FETCH_FAILED,
                    ) from exc

        # Load provider from DB if provider_id is set
        if domain_auth.SOGO_D_SAML2_PROVIDER_ID:
            try:
                from app.module.auth.ModuleSaml2Provider import ModuleSaml2Provider
                provider_module = ModuleSaml2Provider(self._process)
                provider = provider_module.get_provider(domain_auth.SOGO_D_SAML2_PROVIDER_ID)
                if provider:
                    idp_sso_url = provider.get("sso_url", idp_sso_url)
                    idp_entity_id = provider.get("entity_id", idp_entity_id)
                    idp_cert = provider.get("certificate", idp_cert)
                    logger_api.info(
                        "SAML2: loaded provider '%s' from DB (entity_id=%s)",
                        domain_auth.SOGO_D_SAML2_PROVIDER_ID,
                        idp_entity_id,
                    )
                else:
                    logger_api.warning(
                        "SAML2: provider '%s' not found in DB",
                        domain_auth.SOGO_D_SAML2_PROVIDER_ID,
                    )
            except Exception as exc:  # pylint: disable=broad-except
                logger_api.warning("SAML2: failed to load provider from DB: %s", exc)

        # Get Redis client for replay protection
        redis_client = None
        try:
            from app.service import sogo_cache
            redis_client = sogo_cache()
        except Exception as exc:  # pylint: disable=broad-except
            logger_api.debug("SAML2: Redis not available for replay protection: %s", exc)

        # Attribute map from domain settings
        attribute_map = domain_auth.SOGO_D_SAML2_ATTRIBUTE_MAP or None

        return ModuleSAML2(
            idp_sso_url=idp_sso_url,
            idp_entity_id=idp_entity_id,
            entity_id=sp_entity_id,
            acs_url=acs_url,
            x509_cert=sp_cert or "",
            x509_key=sp_key or "",
            name_id_format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
            idp_cert=idp_cert,
            attribute_map=attribute_map,
            clock_skew=self._process.SOGO_SAML2_CLOCK_SKEW,
            want_assertions_signed=True,
            want_assertions_encrypted=domain_auth.SOGO_D_SAML2_WANT_ENCRYPTED_ASSERTIONS,
            want_response_signed=bool(sp_cert),
            redis_client=redis_client,
        )

    def _build_redirect_uri(self, domain: str) -> str:
        """Build the callback URL for this domain.

        Uses the public base URL when configured, otherwise falls back to
        the API's own external URL.
        """
        base = self._process.SOGO_P_PUBLIC_BASE_URL or "http://localhost:5001"
        base = base.rstrip("/")
        return f"{base}/api/user/v1/auth/callback/{domain}"

    def _authenticate_sso_user(
        self,
        domain: str,
        email: str,
        auth_type: str,
        display_name: str = "",
        eppn: str = "",
    ) -> dict[str, Any]:
        """Authenticate / create an SSO user and generate a JWT voucher.

        Steps:
        1. If the user exists in the user source, generate a voucher
        2. If not, create the user profile (onboarding)
        3. Return the JWT token

        :param domain: The domain name.
        :param email: The user's verified email from the IdP.
        :param auth_type: ``"oidc"`` or ``"saml2"`` — used for logging.
        :returns: A dict with ``jwt_token`` key.
        """
        from app.auth.User import User
        from app.auth.service.VoucherUserService import VoucherUserService
        from app.config.settings.DomainSettings import (
            AuthSettingsObj,
            UserSourceSettingsObj,
        )
        from app.config.settings.SystemSettings import SystemSettingsObj
        from app.config.settings.UserSettings import UserGeneralSettings
        from app.module.auth.ModuleAuth import ModuleAuth
        from app.module.auth.ModuleUserSource import ModuleUserSource
        from app.module.calendar.ModuleCalendar import ModuleCalendar
        from app.module.contact.ModuleContact import ModuleContact
        from app.module.user.ModuleUserProfile import ModuleUserProfile
        from app.config.init_config import (
            init_get_system_and_default_domain_settings,
        )

        logger_api.info("SSO auth (%s) for email=%s domain=%s", auth_type, email, domain)

        # Get system & domain settings
        system_settings, default_domain_settings = init_get_system_and_default_domain_settings()
        system_obj = SystemSettingsObj(system_settings)
        default_auth = AuthSettingsObj(default_domain_settings.get("AUTH_SETTINGS", {}))

        default_us_raw = default_domain_settings.get("USER_SOURCE", {})
        default_us: dict[str, UserSourceSettingsObj] = {}
        for src_uid, src_settings in default_us_raw.items():
            default_us[src_uid] = UserSourceSettingsObj(src_settings)

        _ = ModuleAuth(self._process, system_obj, default_auth, default_us)

        # Prepare user
        user = User(email, password="")  # password is empty — we use SSO
        user.domain = domain
        user.mail = email
        # Use SAML display_name if available, otherwise derive from email
        user.cn = display_name or email.split("@")[0]

        # Check if user exists in user source (domain settings)
        try:
            user_sources = self._load_domain_user_sources(domain, system_obj, default_auth, default_us)
            module_us = ModuleUserSource(user_sources)

            # Try to authenticate with an empty password — this just checks existence
            # for user sources that allow anonymous lookups.
            auth_ok = module_us.check_login(user)
            if auth_ok:
                logger_api.info("SSO user %s authenticated in user source", email)
            else:
                # User not found in user source — create user profile directly
                logger_api.info("SSO user %s not found in user source, creating profile", email)
                user_profile_module = ModuleUserProfile(self._process, default_domain_settings)
                if not user_profile_module.is_user_profile_present(email):
                    user_profile_module.create_user_profile(user)
                    # Create personal calendar & addressbook
                    raw_gen = user_profile_module.get_partial_user_preferences(
                        email, UserGeneralSettings.subparent.lower()
                    )
                    user_tz = raw_gen.get(UserGeneralSettings.subparent, {}).get(
                        "SOGO_U_TIMEZONE", "UTC"
                    )
                    ModuleCalendar(self._process).create_personal_calendar(email, tz=user_tz)
                    ModuleContact(self._process).create_personal_addressbook(email)
                    logger_api.info("SSO user %s onboarded (calendar + addressbook)", email)
        except Exception as exc:  # pylint: disable=broad-except
            logger_api.warning("SSO user source check failed for %s: %s", email, exc)

        # Generate voucher
        voucher_service = VoucherUserService(self._process)
        voucher_data = voucher_service.generate_voucher_from_user(user)

        return {"jwt_token": voucher_data}

    @staticmethod
    def _load_domain_user_sources(
        domain: str,
        system_settings: SystemSettingsObj,
        default_auth: AuthSettingsObj,
        default_us: dict[str, UserSourceSettingsObj],
    ) -> dict[str, UserSourceSettingsObj]:
        """Load user source settings for the given domain."""
        if not domain:
            return default_us

        from app.config.db import tables as tbl
        from app.config.settings.ProcessSetting import process_config
        from app.manager.db.ClientSQL import ClientSQL
        from app.utils.db.Condition import EqualCondition
        from app.utils.module.importManager import import_and_instantiate_manager

        db_type = f"Client{process_config.SOGO_P_DB_TYPE}"
        db: ClientSQL = import_and_instantiate_manager(
            module_path="app.manager.db",
            module_and_class_name=db_type,
            module_args=process_config.get_db_settings(),
        )
        db.connect()
        condition = EqualCondition(tbl.COL_DOMAIN_NAME.name, domain)
        result = list(
            db.select_from_table(
                tbl.TABLE_DOMAIN.name,
                (tbl.COL_DOMAIN_SETTINGS.name,),
                condition=condition,
            )
        )
        if result:
            domain_settings = result[0][0]
            domain_us_raw = domain_settings.get("USER_SOURCE", {})
            domain_us: dict[str, UserSourceSettingsObj] = {}
            for src_uid, src_settings in domain_us_raw.items():
                domain_us[src_uid] = UserSourceSettingsObj(src_settings)
            return domain_us
        return default_us
