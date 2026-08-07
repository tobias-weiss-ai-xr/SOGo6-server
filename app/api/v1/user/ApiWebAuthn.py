"""
ApiWebAuthn.py - WebAuthn/Passkeys REST API (User Endpoints)

User-facing API endpoints for WebAuthn passkey management.

Endpoints:
- GET /user/v1/webauthn - Check WebAuthn support and get user's passkeys
- GET /user/v1/webauthn/challenge/register - Get registration challenge
- POST /user/v1/webauthn/register - Register a new passkey
- GET /user/v1/webauthn/challenge/login - Get login challenge
- POST /user/v1/webauthn/login - Authenticate with passkey
- GET /user/v1/webauthn/credentials - List registered passkeys
- POST /user/v1/webauthn/credentials - Add a new passkey
- GET /user/v1/webauthn/credentials/{id} - Get passkey details
- PUT /user/v1/webauthn/credentials/{id} - Update passkey (rename, set default)
- DELETE /user/v1/webauthn/credentials/{id} - Remove passkey

Spec: .openspec/specs/webauthn-passkeys.spec.md
"""

from flask import request, g
from flask.views import MethodView
from flask_smorest import Blueprint

from app.utils import errors

from app.module.auth.ModuleWebAuthn import (
    ModuleWebAuthn,
    RP_ID,
    WebAuthnError,
    WebAuthnChallengeExpiredError,
    WebAuthnChallengeAlreadyUsedError,
    WebAuthnInvalidResponseError,
    WebAuthnCredentialNotFoundError,
    WebAuthnMaxCredentialsError,
)
from app.utils.db.UtlDatabase import UtlDatabase as Db

from marshmallow import Schema, fields, validate


# ---------------------------------------------------------------------------
# Schema Definitions
# ---------------------------------------------------------------------------

class WebAuthnSupportResponseSchema(Schema):
    """Response for WebAuthn support check."""
    supported = fields.Boolean(required=True)
    require_webauthn = fields.Boolean(required=True)
    allow_password_fallback = fields.Boolean(required=True)
    user_has_passkeys = fields.Boolean(required=True)
    passkey_count = fields.Integer(required=True)


class WebAuthnChallengeRequestSchema(Schema):
    """Request schema for getting a challenge."""
    user_verification = fields.String(
        load_default="preferred",
        validate=validate.OneOf(["required", "preferred", "discouraged"])
    )


class WebAuthnRegistrationOptionsSchema(Schema):
    """Response schema for registration options (PublicKeyCredentialCreationOptions)."""
    challenge = fields.String(required=True)
    rp = fields.Dict(required=True)
    user = fields.Dict(required=True)
    pubKeyCredParams = fields.List(fields.Dict(), required=True)
    timeout = fields.Integer(required=True)
    attestation = fields.String(required=True)
    userVerification = fields.String(required=True)
    authenticatorSelection = fields.Dict(required=True)


class WebAuthnAuthenticationOptionsSchema(Schema):
    """Response schema for authentication options (PublicKeyCredentialRequestOptions)."""
    challenge = fields.String(required=True)
    rpId = fields.String(required=True)
    allowCredentials = fields.List(fields.Dict(), required=True)
    timeout = fields.Integer(required=True)
    userVerification = fields.String(required=True)


class WebAuthnRegisterRequestSchema(Schema):
    """Request schema for passkey registration."""
    credential = fields.Dict(required=True)
    name = fields.String(load_default=None)
    is_default = fields.Boolean(load_default=False)
    challenge_id = fields.String(required=True)


class WebAuthnLoginRequestSchema(Schema):
    """Request schema for passkey login."""
    credential = fields.Dict(required=True)
    challenge_id = fields.String(required=True)


class WebAuthnCredentialSchema(Schema):
    """Schema for credential information."""
    id = fields.String(required=True)
    name = fields.String(required=True)
    is_default = fields.Boolean(required=True)
    sign_count = fields.Integer(required=True)
    last_used_at = fields.String(allow_none=True)
    created_at = fields.String(required=True)


class WebAuthnCredentialsResponseSchema(Schema):
    """Response schema for listing credentials."""
    credentials = fields.List(fields.Nested(WebAuthnCredentialSchema), required=True)
    count = fields.Integer(required=True)


class WebAuthnCredentialUpdateSchema(Schema):
    """Schema for updating a credential."""
    name = fields.String()
    is_default = fields.Boolean()


class WebAuthnErrorResponseSchema(Schema):
    """Schema for error responses."""
    error = fields.String(required=True)
    error_code = fields.String(required=True)
    message = fields.String(required=True)


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def login_required(func):
    """Simple auth guard matching the app's global auth model.

    The API-level before_request already rejects anonymous users on protected
    endpoints; this decorator additionally guards the endpoint when invoked
    directly (e.g. in tests) by checking ``g.user.authenticated``.
    """
    import functools
    from flask import abort as flask_abort

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        user = getattr(g, "user", None)
        if user is None or not getattr(user, "authenticated", False):
            flask_abort(401, description="Authentication required")
        return func(*args, **kwargs)

    return wrapper


def admin_required(func):
    """Guard for admin-only endpoints (used by the webauthn admin API)."""
    import functools
    from flask import abort as flask_abort

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        user = getattr(g, "user", None)
        if user is None or not getattr(user, "authenticated", False):
            flask_abort(401, description="Authentication required")
        if not getattr(user, "is_admin", False) and getattr(user, "uid", "") not in getattr(g, "admin_uids", []):
            flask_abort(403, description="Admin privileges required")
        return func(*args, **kwargs)

    return wrapper


def get_current_user():
    """Get the current authenticated user from Flask g."""
    if not hasattr(g, 'user') or not getattr(g.user, 'authenticated', False):
        from flask import abort as flask_abort
        flask_abort(401, description="Authentication required")
    return g.user


def get_client_ip():
    """Get client IP address from request."""
    return request.remote_addr


# ---------------------------------------------------------------------------
# Blueprint Setup
# ---------------------------------------------------------------------------

blp = Blueprint(
    "User WebAuthn",
    __name__,
    url_prefix="/webauthn",
    description="User WebAuthn/Passkeys API v1",
)


# ---------------------------------------------------------------------------
# Endpoint Implementations
# ---------------------------------------------------------------------------

@blp.route("")
class ApiWebAuthnStatus(MethodView):
    """
    GET /user/v1/webauthn
    Check WebAuthn support status for current user.
    """
    
    @blp.response(200, WebAuthnSupportResponseSchema)
    @login_required
    def get(self):
        """Check if WebAuthn is supported and get user status."""
        user = get_current_user()
        user_id = user["uid"]
        
        # Get policy
        policy = ModuleWebAuthn.get_policy()
        
        # Check user's credentials
        passkey_count = ModuleWebAuthn.count_credentials(user_id)
        
        return {
            "supported": True,  # Server supports it
            "require_webauthn": policy.require_webauthn,
            "allow_password_fallback": policy.allow_password_fallback,
            "user_has_passkeys": passkey_count > 0,
            "passkey_count": passkey_count,
        }


@blp.route("/challenge/register")
class ApiWebAuthnRegistrationChallenge(MethodView):
    """
    GET /user/v1/webauthn/challenge/register
    Get a challenge for registering a new passkey.
    """
    
    @blp.arguments(WebAuthnChallengeRequestSchema, location="query")
    @blp.response(200, WebAuthnRegistrationOptionsSchema)
    @login_required
    def get(self, args):
        """Generate and return registration challenge."""
        user = get_current_user()
        user_id = user["uid"]
        user_name = user.get("name", user_id)
        user_display_name = user.get("display_name", user_name)
        
        # Check if user already has too many credentials
        count = ModuleWebAuthn.count_credentials(user_id)
        if count >= ModuleWebAuthn.MAX_CREDENTIALS_PER_USER:
            raise WebAuthnMaxCredentialsError()
        
        # Get policy
        policy = ModuleWebAuthn.get_policy()
        
        # Generate registration options
        options = ModuleWebAuthn.generate_registration_options(
            user_id=user_id,
            user_name=user_name,
            user_display_name=user_display_name,
            attestation=policy.attestation_requirement,
            user_verification=args.get("user_verification", "preferred"),
            timeout=policy.timeout_seconds * 1000,  # Convert to ms
        )
        
        # Create and store challenge
        import base64
        challenge_bytes = base64.urlsafe_b64decode(
            options["challenge"].replace("-", "+").replace("_", "/")
        )
        challenge = ModuleWebAuthn.create_challenge(
            user_id=user_id,
            challenge_type="register",
            challenge_bytes=challenge_bytes,
            rp_id=RP_ID,
        )
        
        # Add challenge_id to response
        options["challenge_id"] = challenge.id
        
        return options


@blp.route("/register")
class ApiWebAuthnRegister(MethodView):
    """
    POST /user/v1/webauthn/register
    Register a new passkey for the current user.
    """
    
    @blp.arguments(WebAuthnRegisterRequestSchema)
    @blp.response(200, WebAuthnCredentialSchema)
    @login_required
    def post(self, args):
        """Register a new passkey."""
        user = get_current_user()
        user_id = user["uid"]
        
        challenge_id = args.get("challenge_id")
        credential_data = args.get("credential", {})
        name = args.get("name")
        is_default = args.get("is_default", False)
        
        # Get the challenge
        challenge = ModuleWebAuthn.get_challenge(challenge_id)
        if not challenge:
            raise WebAuthnChallengeExpiredError()
        
        if challenge.used:
            raise WebAuthnChallengeAlreadyUsedError()
        
        if challenge.is_expired():
            raise WebAuthnChallengeExpiredError()
        
        # Mark challenge as used
        ModuleWebAuthn.mark_challenge_used(challenge_id)
        
        # Convert credential data to the format expected by webauthn
        
        try:
            # Register the credential
            credential = ModuleWebAuthn.register_credential(
                user_id=user_id,
                credential=credential_data,
                name=name,
                is_default=is_default,
            )
            
            # Mark challenge as used (already done above)
            
            return credential.to_dict()
            
        except Exception as e:
            # Log the error
            ModuleWebAuthn._log_action(
                user_id=user_id,
                action="register",
                credential_id=None,
                success=False,
                error_code="WEBAUTHN_REGISTRATION_FAILED",
                metadata={"error": str(e)},
            )
            raise WebAuthnInvalidResponseError(f"Registration failed: {str(e)}")


@blp.route("/challenge/login")
class ApiWebAuthnLoginChallenge(MethodView):
    """
    GET /user/v1/webauthn/challenge/login
    Get a challenge for passkey login.
    """
    
    @blp.arguments(WebAuthnChallengeRequestSchema, location="query")
    @blp.response(200, WebAuthnAuthenticationOptionsSchema)
    def get(self, args):
        """
        Generate and return login challenge.
        
        Note: This endpoint does NOT require authentication since it's
        used as the first step in the login process.
        """
        user_verification = args.get("user_verification", "preferred")
        
        # Get policy
        policy = ModuleWebAuthn.get_policy()
        
        # For login, we don't know the user yet, so we generate a challenge
        # that can be used by any user (we'll verify the user during callback)
        
        # Generate options
        from app.module.auth.ModuleWebAuthn import ModuleWebAuthn as WA
        
        options = WA.generate_authentication_options(
            user_id="",  # Unknown at this point
            user_verification=user_verification,
            timeout=policy.timeout_seconds * 1000,
        )
        
        # Create and store challenge
        import base64
        challenge_bytes = base64.urlsafe_b64decode(
            options["challenge"].replace("-", "+").replace("_", "/")
        )
        challenge = ModuleWebAuthn.create_challenge(
            user_id=None,  # Unknown user
            challenge_type="login",
            challenge_bytes=challenge_bytes,
            rp_id=RP_ID,
        )
        
        # Add challenge_id to response
        options["challenge_id"] = challenge.id
        
        return options


@blp.route("/login")
class ApiWebAuthnLogin(MethodView):
    """
    POST /user/v1/webauthn/login
    Authenticate a user with their passkey.
    """
    
    @blp.arguments(WebAuthnLoginRequestSchema)
    @blp.response(200, WebAuthnCredentialSchema)
    def post(self, args):
        """
        Authenticate with passkey.
        
        This endpoint does not require prior authentication.
        On success, it will create a session and return user info.
        """
        credential_data = args.get("credential", {})
        challenge_id = args.get("challenge_id")
        
        ip_address = get_client_ip()
        
        try:
            # This will authenticate and return the credential + user_id
            credential, user_id = ModuleWebAuthn.authenticate(
                challenge_id=challenge_id,
                credential=credential_data,
                ip_address=ip_address,
            )
            
            # At this point, the user is authenticated
            # In a real implementation, we would create a session
            # For now, we just return the credential info
            
            # Also update the last_used timestamp
            ModuleWebAuthn._update_credential_last_used(credential.id)
            
            return credential.to_dict()
            
        except ModuleWebAuthn.WebAuthnError as e:
            # Log the error
            try:
                # Try to get user_id from challenge if available
                challenge = ModuleWebAuthn.get_challenge(challenge_id)
                user_id_for_log = challenge.user_id if challenge else None
            except:
                user_id_for_log = None
            
            ModuleWebAuthn._log_action(
                user_id=user_id_for_log,
                action="login",
                credential_id=None,
                success=False,
                ip_address=ip_address,
                error_code=e.error_code,
                metadata={"error": str(e)},
            )
            raise
        except Exception as e:
            ModuleWebAuthn._log_action(
                user_id=None,
                action="login",
                credential_id=None,
                success=False,
                ip_address=ip_address,
                error_code="WEBAUTHN_LOGIN_FAILED",
                metadata={"error": str(e)},
            )
            raise WebAuthnInvalidResponseError(f"Login failed: {str(e)}")


@blp.route("/credentials")
class ApiWebAuthnCredentials(MethodView):
    """
    GET /user/v1/webauthn/credentials
    List all passkeys for the current user.
    
    POST /user/v1/webauthn/credentials
    Register a new passkey (alternative endpoint).
    """
    
    @blp.response(200, WebAuthnCredentialsResponseSchema)
    @login_required
    def get(self):
        """List all credentials for the current user."""
        user = get_current_user()
        user_id = user["uid"]
        
        credentials = ModuleWebAuthn.get_credentials_by_user(user_id)
        
        return {
            "credentials": [cred.to_dict() for cred in credentials],
            "count": len(credentials),
        }
    
    @blp.arguments(WebAuthnRegisterRequestSchema)
    @blp.response(200, WebAuthnCredentialSchema)
    @login_required
    def post(self, args):
        """Alternative endpoint to register a new passkey."""
        user = get_current_user()
        user_id = user["uid"]
        
        credential_data = args.get("credential", {})
        name = args.get("name")
        is_default = args.get("is_default", False)
        challenge_id = args.get("challenge_id")
        
        # Get the challenge
        challenge = ModuleWebAuthn.get_challenge(challenge_id)
        if not challenge:
            raise WebAuthnChallengeExpiredError()
        
        try:
            credential = ModuleWebAuthn.register_credential(
                user_id=user_id,
                credential=credential_data,
                name=name,
                is_default=is_default,
            )
            return credential.to_dict()
        except Exception as e:
            raise WebAuthnInvalidResponseError(f"Registration failed: {str(e)}")


@blp.route("/credentials/<string:credential_id>")
class ApiWebAuthnCredentialDetail(MethodView):
    """
    GET /user/v1/webauthn/credentials/{id}
    Get details for a specific passkey.
    
    PUT /user/v1/webauthn/credentials/{id}
    Update a passkey (rename, set as default).
    
    DELETE /user/v1/webauthn/credentials/{id}
    Remove a passkey.
    """
    
    @blp.response(200, WebAuthnCredentialSchema)
    @login_required
    def get(self, credential_id):
        """Get credential details."""
        user = get_current_user()
        user_id = user["uid"]
        
        credential = ModuleWebAuthn.get_credential_by_id(credential_id)
        
        if not credential:
            raise WebAuthnCredentialNotFoundError()
        
        if credential.user_id != user_id:
            from flask import abort as flask_abort; flask_abort(401, description="Authentication required")
        
        return credential.to_dict()
    
    @blp.arguments(WebAuthnCredentialUpdateSchema)
    @blp.response(200, WebAuthnCredentialSchema)
    @login_required
    def put(self, args, credential_id):
        """Update credential properties."""
        user = get_current_user()
        user_id = user["uid"]
        
        credential = ModuleWebAuthn.get_credential_by_id(credential_id)
        
        if not credential:
            raise WebAuthnCredentialNotFoundError()
        
        if credential.user_id != user_id:
            from flask import abort as flask_abort; flask_abort(401, description="Authentication required")
        
        # Update fields
        if "name" in args:
            ModuleWebAuthn.rename_credential(
                credential_id=credential_id,
                user_id=user_id,
                new_name=args["name"],
            )
            credential.name = args["name"]
        
        if "is_default" in args:
            if args["is_default"]:
                ModuleWebAuthn.set_default_credential(user_id, credential_id)
                credential.is_default = True
            else:
                # If unsetting as default, set another as default
                other_creds = ModuleWebAuthn.get_credentials_by_user(user_id)
                if other_creds:
                    ModuleWebAuthn.set_default_credential(
                        user_id, other_creds[0].id
                    )
                credential.is_default = False
        
        # Refresh the credential
        updated_cred = ModuleWebAuthn.get_credential_by_id(credential_id)
        
        return updated_cred.to_dict()
    
    @blp.response(204)
    @login_required
    def delete(self, credential_id):
        """Remove a credential."""
        user = get_current_user()
        user_id = user["uid"]
        
        credential = ModuleWebAuthn.get_credential_by_id(credential_id)
        
        if not credential:
            raise WebAuthnCredentialNotFoundError()
        
        if credential.user_id != user_id:
            from flask import abort as flask_abort; flask_abort(401, description="Authentication required")
        
        # Remove the credential
        success = ModuleWebAuthn.remove_credential(credential_id, user_id)
        
        if not success:
            raise WebAuthnCredentialNotFoundError()
        
        return None


# ---------------------------------------------------------------------------
# Error Handlers
# ---------------------------------------------------------------------------

@blp.errorhandler(WebAuthnError)
def handle_webauthn_error(error):
    """Handle WebAuthn-specific errors."""
    return {
        "error": error.__class__.__name__,
        "error_code": error.error_code,
        "message": error.message,
    }, error.http_status


@blp.errorhandler(errors.SOGo6Error)
def handle_sogo6_error(error):
    """Handle SOGo6 errors."""
    return {
        "error": error.__class__.__name__,
        "error_code": error.error_code,
        "message": error.message,
    }, error.http_status


# ---------------------------------------------------------------------------
# Admin Endpoints
# ---------------------------------------------------------------------------

# These would be in a separate file, but for now we'll add them here
# for completeness

blp_admin = Blueprint(
    "Admin WebAuthn",
    __name__,
    url_prefix="/admin/v1/webauthn",
    description="Admin WebAuthn API v1",
)


@blp_admin.route("/users")
class ApiAdminWebAuthnUsers(MethodView):
    """
    GET /admin/v1/webauthn/users
    List users with passkeys.
    """
    
    @blp.response(200, WebAuthnCredentialsResponseSchema(many=True))
    @login_required
    @admin_required
    def get(self):
        """List all users with their passkeys."""
        # Get all users with credentials
        sql = f"""
        SELECT user_id, COUNT(*) as count 
        FROM {ModuleWebAuthn.TABLE_WEBAUTHN_CREDENTIALS}
        GROUP BY user_id
        ORDER BY count DESC
        """
        rows = Db().execute_read_all(sql)
        
        results = []
        for row in rows:
            user_id = row["user_id"]
            count = row["count"]
            credentials = ModuleWebAuthn.get_credentials_by_user(user_id)
            results.append({
                "user_id": user_id,
                "credentials": [cred.to_dict() for cred in credentials],
                "count": count,
            })
        
        return results


@blp_admin.route("/policies")
class ApiAdminWebAuthnPolicies(MethodView):
    """
    GET /admin/v1/webauthn/policies
    Get current WebAuthn policy.
    
    POST /admin/v1/webauthn/policies
    Update WebAuthn policy.
    """
    
    class PolicySchema(Schema):
        require_webauthn = fields.Boolean()
        allow_password_fallback = fields.Boolean()
        user_verification = fields.String(
            validate=validate.OneOf(["required", "preferred", "discouraged"])
        )
        attestation_requirement = fields.String(
            validate=validate.OneOf(["none", "self", "attested"])
        )
        timeout_seconds = fields.Integer()
    
    @blp.response(200, PolicySchema)
    @login_required
    @admin_required
    def get(self):
        """Get current policy."""
        policy = ModuleWebAuthn.get_policy()
        return {
            "require_webauthn": policy.require_webauthn,
            "allow_password_fallback": policy.allow_password_fallback,
            "user_verification": policy.user_verification,
            "attestation_requirement": policy.attestation_requirement,
            "timeout_seconds": policy.timeout_seconds,
        }
    
    @blp.arguments(PolicySchema)
    @blp.response(200, PolicySchema)
    @login_required
    @admin_required
    def post(self, args):
        """Update policy."""
        policy = ModuleWebAuthn.set_policy(args)
        return {
            "require_webauthn": policy.require_webauthn,
            "allow_password_fallback": policy.allow_password_fallback,
            "user_verification": policy.user_verification,
            "attestation_requirement": policy.attestation_requirement,
            "timeout_seconds": policy.timeout_seconds,
        }


@blp_admin.route("/audit")
class ApiAdminWebAuthnAudit(MethodView):
    """
    GET /admin/v1/webauthn/audit
    Get WebAuthn audit log.
    """
    
    class AuditQuerySchema(Schema):
        user_id = fields.String()
        action = fields.String()
        limit = fields.Integer(load_default=100)
        offset = fields.Integer(load_default=0)
    
    class AuditEntrySchema(Schema):
        id = fields.String()
        user_id = fields.String(allow_none=True)
        action = fields.String()
        credential_id = fields.String(allow_none=True)
        success = fields.Boolean()
        ip_address = fields.String(allow_none=True)
        error_code = fields.String(allow_none=True)
        metadata = fields.Dict(allow_none=True)
        created_at = fields.String()
    
    @blp.arguments(AuditQuerySchema, location="query")
    @blp.response(200, AuditEntrySchema(many=True))
    @login_required
    @admin_required
    def get(self, args):
        """Get audit log entries."""
        audit_log = ModuleWebAuthn.get_audit_log(
            user_id=args.get("user_id"),
            action=args.get("action"),
            limit=args.get("limit", 100),
            offset=args.get("offset", 0),
        )
        return audit_log


# ---------------------------------------------------------------------------
# Register Blueprints
# ---------------------------------------------------------------------------

def register_webauthn_blueprints(api):
    """Register WebAuthn blueprints with the Flask-Smorest API."""
    api.register_blueprint(blp)
    api.register_blueprint(blp_admin)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    'blp',
    'blp_admin',
    'register_webauthn_blueprints',
    'ApiWebAuthnStatus',
    'ApiWebAuthnRegistrationChallenge',
    'ApiWebAuthnRegister',
    'ApiWebAuthnLoginChallenge',
    'ApiWebAuthnLogin',
    'ApiWebAuthnCredentials',
    'ApiWebAuthnCredentialDetail',
]
