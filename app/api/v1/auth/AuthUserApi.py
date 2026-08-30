from __future__ import annotations
from typing import TYPE_CHECKING

import os

from flask import g, request, Response
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.interface.auth.InterfaceAuthUser import InterfaceAuthUser
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils import errors as err
from app.utils.logger.logger import logger_api

from .schema import authUser as sch

if TYPE_CHECKING:
    from app.config.settings.ProcessSetting import ProcessSetting


blp = Blueprint("Auth", __name__, url_prefix="/auth")


@blp.before_request
def init_admin_config() -> None:
    """
    Init the interface and others if needed 
    """
    logger_api.debug("Calling before_request for ApiAdminConfig")
    process: ProcessSetting = g.process_settings
    system_settings: dict = g.system_settings
    default_domain: dict = g.default_domain_settings
    interface_api = InterfaceAuthUser(process, system_settings, default_domain)
    g.inter = interface_api


@blp.route("/mode")
class ApiAuthUserMode(MethodView):
    """
    Action

    Return the authneticaiton mode for this user
    """
    @blp.arguments(sch.AuthUserGetMechSchema, location='query', as_kwargs=True, error_status_code=400)
    @blp.response(200)
    def get(self, username:str, redirect:str) -> ResponseReturnValue:
        """
        Action, return the url location of the login system for this username.
        redirect is only useful for SSO that needs callback.
        """
        interface_api: InterfaceAuthUser = g.inter
        return interface_api.get_login_mech(username, redirect)


@blp.route("/login")
class ApiAuthUserLogin(MethodView):
    """
    Action, plain login for user
    """

    @blp.arguments(sch.AuthUserBasicPostSchema, example=sch.AuthUserBasicPostSchema.example(), error_status_code=400)
    @blp.response(200)
    def post(self, new_data:dict) -> ResponseReturnValue:
        """
        Action, Authenticate the user for plain mode
        """
        # Per-IP rate limiting (defaults: 20 requests / 60 s per IP).
        # Configurable via env — e.g. a CI test-runner or a NAT-ed office
        # legitimately exceeds 20 logins/min from a single source IP.
        from app.service import sogo_cache
        from app.utils.api.login_rate_limiter import LoginRateLimiter

        client_ip = request.remote_addr or "unknown"
        limiter = LoginRateLimiter(sogo_cache())
        ip_max = int(os.environ.get("SOGO_P_LOGIN_IP_MAX", "20"))
        ip_window = int(os.environ.get("SOGO_P_LOGIN_IP_WINDOW", "60"))
        if limiter.is_ip_rate_limited(client_ip, max_attempts=ip_max, window_seconds=ip_window):
            logger_api.warning("Rate-limited login from IP=%s (%d/%ds)", client_ip, ip_max, ip_window)
            return create_api_base_response(None, err.ERROR_LOGIN_FAILED)

        interface_api : InterfaceAuthUser = g.inter
        return interface_api.plain_login(new_data)


@blp.route("/callback/<string:domain>")
class ApiAuthUserCallback(MethodView):
    """
    Action, is the callback for SSO (OIDC / SAML2).
    """

    # Accept both GET (OIDC redirect) and POST (SAML HTTP-POST)
    accepted_content_types: set[str] = {"application/json",
                                        "application/x-www-form-urlencoded",
                                        "text/plain",
                                        "application/xml",
                                        "text/xml"}

    @blp.response(200)
    def get(self, domain: str) -> ResponseReturnValue:
        """
        Handle the OIDC authorization code callback (GET redirect).
        Query params:
          - code: the authorization code (OIDC)
          - state: CSRF token (OIDC)
          - SAMLResponse: base64-encoded SAML response (SAML HTTP-Redirect)
          - RelayState: opaque state (SAML)
        """
        from app.config.settings.DomainSettings import AuthSettingsObj
        from app.config.settings.ProcessSetting import process_config
        from app.interface.auth.InterfaceAuthSSO import InterfaceAuthSSO
        from app.config.init_config import init_get_system_and_default_domain_settings

        # Get the domain auth settings
        system_settings, default_domain_settings = init_get_system_and_default_domain_settings()
        default_auth = AuthSettingsObj(default_domain_settings.get("AUTH_SETTINGS", {}))

        # If domain is not empty, try to load per-domain settings
        domain_auth = default_auth
        if domain:
            try:
                from app.config.db import tables as tbl
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
                result = list(db.select_from_table(
                    tbl.TABLE_DOMAIN.name,
                    (tbl.COL_DOMAIN_SETTINGS.name,),
                    condition=condition,
                ))
                if result:
                    domain_settings = result[0][0]
                    domain_auth = AuthSettingsObj(domain_settings.get("AUTH_SETTINGS", {}))
            except Exception as exc:  # pylint: disable=broad-except
                from app.utils.logger.logger import logger_api
                logger_api.warning("Could not load domain settings for %s: %s", domain, exc)

        # Build query params dict
        params: dict[str, str] = dict(request.args)

        sso = InterfaceAuthSSO(process_config)
        body, status = sso.handle_callback(domain, domain_auth, params)

        # If the callback produced a JWT token, redirect the user to the
        # frontend with the token as a hash fragment (best practice).
        if isinstance(body, dict) and body.get("data", {}).get("jwt_token"):
            token = body["data"]["jwt_token"]
            frontend_url = process_config.SOGO_P_PUBLIC_BASE_URL or "http://localhost:3000"
            redirect_url = f"{frontend_url.rstrip('/')}/auth/callback#token={token}"
            from flask import redirect as flask_redirect
            return flask_redirect(redirect_url)

        # Otherwise return the API response directly
        from app.utils.api.ApiBaseResponse import create_api_base_response
        return create_api_base_response(body.get("data", body), error_code=body.get("error_code", ""))

    @blp.response(200)
    def post(self, domain: str) -> ResponseReturnValue:
        """
        Handle the SAML2 HTTP-POST callback.
        """
        # SAML POST can be form-encoded or raw XML
        params: dict[str, str] = {}
        if request.form:
            params = dict(request.form)
        elif request.data:
            data_str = request.get_data(as_text=True)
            if data_str.startswith("<"):
                params = {"SAMLResponse": data_str}
            else:
                # Assume URL-encoded
                from urllib.parse import parse_qs
                qs = parse_qs(data_str)
                for key, values in qs.items():
                    params[key] = values[0] if values else ""

        from app.config.settings.DomainSettings import AuthSettingsObj
        from app.config.settings.ProcessSetting import process_config
        from app.interface.auth.InterfaceAuthSSO import InterfaceAuthSSO
        from app.config.init_config import init_get_system_and_default_domain_settings

        system_settings, default_domain_settings = init_get_system_and_default_domain_settings()
        default_auth = AuthSettingsObj(default_domain_settings.get("AUTH_SETTINGS", {}))

        domain_auth = default_auth
        if domain:
            try:
                from app.config.db import tables as tbl
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
                result = list(db.select_from_table(
                    tbl.TABLE_DOMAIN.name,
                    (tbl.COL_DOMAIN_SETTINGS.name,),
                    condition=condition,
                ))
                if result:
                    domain_settings = result[0][0]
                    domain_auth = AuthSettingsObj(domain_settings.get("AUTH_SETTINGS", {}))
            except Exception as exc:  # pylint: disable=broad-except
                from app.utils.logger.logger import logger_api
                logger_api.warning("Could not load domain settings for %s: %s", domain, exc)

        sso = InterfaceAuthSSO(process_config)
        body, status = sso.handle_callback(domain, domain_auth, params)

        from flask import make_response
        from flask import redirect as flask_redirect

        if isinstance(body, dict):
            data = body.get("data")
            if isinstance(data, dict) and data.get("jwt_token"):
                token = data["jwt_token"]
                frontend_url = process_config.SOGO_P_PUBLIC_BASE_URL or "http://localhost:3000"
                redirect_url = f"{frontend_url.rstrip('/')}/auth/callback#token={token}"
                return flask_redirect(redirect_url)

            from app.utils.api.ApiBaseResponse import create_api_base_response
            return create_api_base_response(body.get("data", body), error_code=body.get("error_code", ""))

        # ``body`` may be a plain string (e.g. an SSO error message / redirect
        # payload). Do not attempt dict access on it.
        return make_response(
            {"error": body if body is not None else "callback failed"},
            status if isinstance(status, int) else 400,
        )


@blp.route("/saml2/metadata")
class ApiAuthSaml2Metadata(MethodView):
    """Serve the SP's SAML2 metadata XML."""

    @blp.response(200)
    def get(self) -> ResponseReturnValue:
        """Return SP metadata XML for IdP administrator import."""
        from app.config.settings.DomainSettings import AuthSettingsObj
        from app.config.settings.ProcessSetting import process_config
        from app.interface.auth.InterfaceAuthSSO import InterfaceAuthSSO
        from app.config.init_config import init_get_system_and_default_domain_settings

        system_settings, default_domain_settings = init_get_system_and_default_domain_settings()
        default_auth = AuthSettingsObj(default_domain_settings.get("AUTH_SETTINGS", {}))

        sso = InterfaceAuthSSO(process_config)
        try:
            saml = sso._build_saml(default_auth, "")
            metadata_xml = saml.get_sp_metadata()
            return Response(metadata_xml, mimetype="application/xml")
        except Exception as exc:  # pylint: disable=broad-except
            logger_api.error("SAML2 metadata request failed: %s", exc)
            return create_api_base_response(str(exc), err.ERROR_SAML_NOT_CONFIGURED)


@blp.route("/saml2/metadata/<string:domain>")
class ApiAuthSaml2MetadataDomain(MethodView):
    """Serve the SP's SAML2 metadata XML for a specific domain."""

    @blp.response(200)
    def get(self, domain: str) -> ResponseReturnValue:
        """Return SP metadata XML for the given domain."""
        from app.config.settings.DomainSettings import AuthSettingsObj
        from app.config.settings.ProcessSetting import process_config
        from app.interface.auth.InterfaceAuthSSO import InterfaceAuthSSO
        from app.config.init_config import init_get_system_and_default_domain_settings
        from app.config.db import tables as tbl
        from app.manager.db.ClientSQL import ClientSQL
        from app.utils.db.Condition import EqualCondition
        from app.utils.module.importManager import import_and_instantiate_manager

        system_settings, default_domain_settings = init_get_system_and_default_domain_settings()
        default_auth = AuthSettingsObj(default_domain_settings.get("AUTH_SETTINGS", {}))
        domain_auth = default_auth

        if domain:
            try:
                db_type = f"Client{process_config.SOGO_P_DB_TYPE}"
                db: ClientSQL = import_and_instantiate_manager(
                    module_path="app.manager.db",
                    module_and_class_name=db_type,
                    module_args=process_config.get_db_settings(),
                )
                db.connect()
                condition = EqualCondition(tbl.COL_DOMAIN_NAME.name, domain)
                result = list(db.select_from_table(
                    tbl.TABLE_DOMAIN.name,
                    (tbl.COL_DOMAIN_SETTINGS.name,),
                    condition=condition,
                ))
                if result:
                    domain_settings = result[0][0]
                    domain_auth = AuthSettingsObj(domain_settings.get("AUTH_SETTINGS", {}))
            except Exception as exc:  # pylint: disable=broad-except
                logger_api.warning("Could not load domain settings for %s: %s", domain, exc)

        sso = InterfaceAuthSSO(process_config)
        try:
            saml = sso._build_saml(domain_auth, domain)
            metadata_xml = saml.get_sp_metadata()
            return Response(metadata_xml, mimetype="application/xml")
        except Exception as exc:  # pylint: disable=broad-except
            logger_api.error("SAML2 metadata request failed for domain %s: %s", domain, exc)
            return create_api_base_response(str(exc), err.ERROR_SAML_NOT_CONFIGURED)


@blp.route("/saml2/start")
class ApiAuthSaml2Start(MethodView):
    """Initiate SP-initiated SAML2 SSO."""

    @blp.response(200)
    def get(self) -> ResponseReturnValue:
        """Generate a SAML AuthnRequest and return the redirect URL.

        Query params:
          - domain: the domain (for per-domain IdP config)
          - provider: SAML2 provider ID (for multi-IdP / federation)
          - relay_state: opaque value preserved across the SSO flow
        """
        from app.config.settings.DomainSettings import AuthSettingsObj
        from app.config.settings.ProcessSetting import process_config
        from app.interface.auth.InterfaceAuthSSO import InterfaceAuthSSO
        from app.config.init_config import init_get_system_and_default_domain_settings
        from app.config.db import tables as tbl
        from app.manager.db.ClientSQL import ClientSQL
        from app.utils.db.Condition import EqualCondition
        from app.utils.module.importManager import import_and_instantiate_manager

        domain = request.args.get("domain", "")
        relay_state = request.args.get("relay_state", "")

        system_settings, default_domain_settings = init_get_system_and_default_domain_settings()
        default_auth = AuthSettingsObj(default_domain_settings.get("AUTH_SETTINGS", {}))
        domain_auth = default_auth

        if domain:
            try:
                db_type = f"Client{process_config.SOGO_P_DB_TYPE}"
                db: ClientSQL = import_and_instantiate_manager(
                    module_path="app.manager.db",
                    module_and_class_name=db_type,
                    module_args=process_config.get_db_settings(),
                )
                db.connect()
                condition = EqualCondition(tbl.COL_DOMAIN_NAME.name, domain)
                result = list(db.select_from_table(
                    tbl.TABLE_DOMAIN.name,
                    (tbl.COL_DOMAIN_SETTINGS.name,),
                    condition=condition,
                ))
                if result:
                    domain_settings = result[0][0]
                    domain_auth = AuthSettingsObj(domain_settings.get("AUTH_SETTINGS", {}))
            except Exception as exc:  # pylint: disable=broad-except
                logger_api.warning("Could not load domain settings for %s: %s", domain, exc)

        sso = InterfaceAuthSSO(process_config)
        try:
            saml = sso._build_saml(domain_auth, domain)
            redirect_url = saml.create_login_request(relay_state=relay_state)
            from flask import redirect as flask_redirect
            return flask_redirect(redirect_url)
        except Exception as exc:  # pylint: disable=broad-except
            logger_api.error("SAML2 start failed: %s", exc)
            return create_api_base_response(str(exc), err.ERROR_SAML_NOT_CONFIGURED)


@blp.route("/saml2/acs")
class ApiAuthSaml2Acs(MethodView):
    """SAML2 Assertion Consumer Service endpoint."""

    accepted_content_types: set[str] = {"application/x-www-form-urlencoded", "text/plain", "application/xml", "text/xml"}

    @blp.response(200)
    def post(self) -> ResponseReturnValue:
        """Process the SAML Response POSTed by the IdP.

        Accepts form-encoded ``SAMLResponse`` and optional ``RelayState``.
        The domain is extracted from the SP entity ID or RelayState.
        """
        from app.config.settings.DomainSettings import AuthSettingsObj
        from app.config.settings.ProcessSetting import process_config
        from app.interface.auth.InterfaceAuthSSO import InterfaceAuthSSO
        from app.config.init_config import init_get_system_and_default_domain_settings
        from app.config.db import tables as tbl
        from app.manager.db.ClientSQL import ClientSQL
        from app.utils.db.Condition import EqualCondition
        from app.utils.module.importManager import import_and_instantiate_manager

        params: dict[str, str] = {}
        if request.form:
            params = dict(request.form)
        elif request.data:
            data_str = request.get_data(as_text=True)
            if data_str.startswith("<"):
                params = {"SAMLResponse": data_str}
            else:
                from urllib.parse import parse_qs
                qs = parse_qs(data_str)
                for key, values in qs.items():
                    params[key] = values[0] if values else ""

        # Determine domain from RelayState or query param
        domain = request.args.get("domain", "") or params.get("RelayState", "")

        system_settings, default_domain_settings = init_get_system_and_default_domain_settings()
        default_auth = AuthSettingsObj(default_domain_settings.get("AUTH_SETTINGS", {}))
        domain_auth = default_auth

        if domain:
            try:
                db_type = f"Client{process_config.SOGO_P_DB_TYPE}"
                db: ClientSQL = import_and_instantiate_manager(
                    module_path="app.manager.db",
                    module_and_class_name=db_type,
                    module_args=process_config.get_db_settings(),
                )
                db.connect()
                condition = EqualCondition(tbl.COL_DOMAIN_NAME.name, domain)
                result = list(db.select_from_table(
                    tbl.TABLE_DOMAIN.name,
                    (tbl.COL_DOMAIN_SETTINGS.name,),
                    condition=condition,
                ))
                if result:
                    domain_settings = result[0][0]
                    domain_auth = AuthSettingsObj(domain_settings.get("AUTH_SETTINGS", {}))
            except Exception as exc:  # pylint: disable=broad-except
                logger_api.warning("Could not load domain settings for %s: %s", domain, exc)

        sso = InterfaceAuthSSO(process_config)
        body, status = sso.handle_callback(domain, domain_auth, params)

        if isinstance(body, dict) and body.get("data", {}).get("jwt_token"):
            token = body["data"]["jwt_token"]
            frontend_url = process_config.SOGO_P_PUBLIC_BASE_URL or "http://localhost:3000"
            redirect_url = f"{frontend_url.rstrip('/')}/auth/callback#token={token}"
            from flask import redirect as flask_redirect
            return flask_redirect(redirect_url)

        return create_api_base_response(body.get("data", body), error_code=body.get("error_code", ""))


@blp.route("/saml2/discovery")
class ApiAuthSaml2Discovery(MethodView):
    """SAML2 discovery service (WAYF - Where Are You From)."""

    @blp.response(200)
    def get(self) -> ResponseReturnValue:
        """Return a list of available IdPs for user selection.

        If ``SOGO_D_SAML2_DISCOVERY_SERVICE_URL`` is set, redirect to the
        external WAYF.  Otherwise, return a JSON list of IdPs from the
        federation metadata or provider DB.
        """
        from app.config.settings.DomainSettings import AuthSettingsObj
        from app.config.settings.ProcessSetting import process_config
        from app.module.auth.Saml2Metadata import Saml2Metadata
        from app.module.auth.ModuleSaml2Provider import ModuleSaml2Provider
        from app.config.init_config import init_get_system_and_default_domain_settings

        system_settings, default_domain_settings = init_get_system_and_default_domain_settings()
        default_auth = AuthSettingsObj(default_domain_settings.get("AUTH_SETTINGS", {}))

        # If external WAYF is configured, redirect to it
        if default_auth.SOGO_D_SAML2_DISCOVERY_SERVICE_URL:
            from flask import redirect as flask_redirect
            return flask_redirect(default_auth.SOGO_D_SAML2_DISCOVERY_SERVICE_URL)

        # Build IdP list from federation metadata and/or provider DB
        idps: list[dict] = []

        # 1. Fetch from federation metadata if configured
        if default_auth.SOGO_D_SAML2_FEDERATION_METADATA_URL:
            try:
                metadata = Saml2Metadata(process_config)
                federation_idps = metadata.get_federation_idps(default_auth.SOGO_D_SAML2_FEDERATION_METADATA_URL)
                for idp in federation_idps:
                    idps.append({
                        "entity_id": idp.get("entity_id", ""),
                        "name": idp.get("name", idp.get("entity_id", "")),
                        "sso_url": idp.get("sso_url", ""),
                        "logo_url": idp.get("logo_url", ""),
                    })
            except Exception as exc:  # pylint: disable=broad-except
                logger_api.warning("SAML2 discovery: failed to fetch federation metadata: %s", exc)

        # 2. Add providers from DB
        try:
            provider_module = ModuleSaml2Provider(process_config)
            providers = provider_module.list_providers(active_only=True)
            for p in providers:
                if not any(i["entity_id"] == p.get("entity_id", "") for i in idps):
                    idps.append({
                        "entity_id": p.get("entity_id", ""),
                        "name": p.get("name", p.get("entity_id", "")),
                        "sso_url": p.get("sso_url", ""),
                        "logo_url": "",
                    })
        except Exception as exc:  # pylint: disable=broad-except
            logger_api.warning("SAML2 discovery: failed to load providers from DB: %s", exc)

        return create_api_base_response({"idps": idps, "total": len(idps)})

    @blp.response(200)
    def post(self) -> ResponseReturnValue:
        """Accept the selected IdP entity ID and return the AuthnRequest URL."""
        from app.config.settings.DomainSettings import AuthSettingsObj
        from app.config.settings.ProcessSetting import process_config
        from app.config.init_config import init_get_system_and_default_domain_settings

        data = request.get_json(silent=True) or {}
        entity_id = data.get("entity_id", "")
        relay_state = data.get("relay_state", "")
        domain = data.get("domain", "")

        if not entity_id:
            return create_api_base_response("entity_id is required", err.ERROR_SAML_NOT_CONFIGURED)

        system_settings, default_domain_settings = init_get_system_and_default_domain_settings()
        default_auth = AuthSettingsObj(default_domain_settings.get("AUTH_SETTINGS", {}))
        domain_auth = default_auth

        # Load domain settings if domain is specified
        if domain:
            try:
                from app.config.db import tables as tbl
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
                result = list(db.select_from_table(
                    tbl.TABLE_DOMAIN.name,
                    (tbl.COL_DOMAIN_SETTINGS.name,),
                    condition=condition,
                ))
                if result:
                    domain_settings = result[0][0]
                    domain_auth = AuthSettingsObj(domain_settings.get("AUTH_SETTINGS", {}))
            except Exception as exc:  # pylint: disable=broad-except
                logger_api.warning("Could not load domain settings for %s: %s", domain, exc)

        # Find the provider by entity_id and build the SAML module
        try:
            from app.module.auth.ModuleSaml2Provider import ModuleSaml2Provider
            provider_module = ModuleSaml2Provider(process_config)
            provider = provider_module.get_provider_by_entity_id(entity_id)
            if not provider:
                return create_api_base_response(
                    f"SAML2 provider not found for entity_id '{entity_id}'",
                    err.ERROR_SAML_PROVIDER_NOT_FOUND,
                )

            # Build SAML module using the provider config
            from app.module.auth.ModuleSAML2 import ModuleSAML2
            from app.module.auth.Saml2Keypair import Saml2Keypair

            acs_url = f"{(process_config.SOGO_P_PUBLIC_BASE_URL or 'http://localhost:5001').rstrip('/')}/api/user/v1/auth/saml2/acs"
            sp_entity_id = domain_auth.SOGO_D_SAML2_SP_ENTITY_ID or acs_url.replace("/acs", "/metadata")

            keypair = Saml2Keypair(process_config)
            sp_cert, sp_key = keypair.load_keypair()

            saml = ModuleSAML2(
                idp_sso_url=provider.get("sso_url", ""),
                idp_entity_id=provider.get("entity_id", ""),
                entity_id=sp_entity_id,
                acs_url=acs_url,
                x509_cert=sp_cert or "",
                x509_key=sp_key or "",
                idp_cert=provider.get("certificate", ""),
                attribute_map=domain_auth.SOGO_D_SAML2_ATTRIBUTE_MAP or None,
                clock_skew=process_config.SOGO_SAML2_CLOCK_SKEW,
                redis_client=None,  # Will be set by _build_saml in callback
            )

            redirect_url = saml.create_login_request(relay_state=relay_state or domain)
            return create_api_base_response({"redirect_url": redirect_url, "entity_id": entity_id})
        except Exception as exc:  # pylint: disable=broad-except
            logger_api.error("SAML2 discovery POST failed: %s", exc)
            return create_api_base_response(str(exc), err.ERROR_SAML_RESPONSE_INVALID)


@blp.route("/logout")
class ApiAuthUserLogout(MethodView):
    """
    Action, revoke the current user session
    """

    @blp.response(200)
    def post(self) -> ResponseReturnValue:
        """
        Action, logout the authenticated user by revoking the session associated
        with the JWT token present in the Authorization header.
        """
        auth_header = request.authorization
        voucher_data: str = ""
        if auth_header and auth_header.token:
            voucher_data = auth_header.token
        interface_api: InterfaceAuthUser = g.inter
        return interface_api.logout(voucher_data)
