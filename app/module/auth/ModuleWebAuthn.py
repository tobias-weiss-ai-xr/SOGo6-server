"""
ModuleWebAuthn.py - WebAuthn/Passkeys Module

This module implements WebAuthn (FIDO2) support for passwordless authentication
using device-based credentials (biometrics, PIN, security keys).

Features:
- Passkey registration
- Passkey authentication
- Credential management
- Challenge/response handling
- Audit logging

Dependencies:
- python-webauthn (pip install webauthn)
- MySQL/MariaDB or PostgreSQL for persistent storage
- Redis for challenge caching (optional, falls back to DB)

Author: SOGo6 Team
Created: 2025-08-21
Spec: .openspec/specs/webauthn-passkeys.spec.md
"""

import base64
import os
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
from uuid import uuid4

from webauthn import (
    generate_registration_options,
    generate_authentication_options,
    verify_authentication_response,
)
from webauthn.helpers import (
    bytes_to_base64url,
    base64url_to_bytes,
)
from webauthn.helpers.structs import (
    AuthenticationCredential,
    AuthenticatorAssertionResponse,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialUserEntity,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.orm import PydanticBaseModel
from app.utils.db.UtlDatabase import UtlDatabase as Db

from app.utils import errors

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Relying Party ID (usually domain)
RP_ID = "sogo6.local"
RP_NAME = "SOGo6"
ORIGIN = os.environ.get("SOGO_WCH_ORIGIN", f"https://{RP_ID}")

# Supported algorithms
SUPPORTED_ALGORITHMS = [
    -7,   # ES256
    -35,  # ES384
    -36,  # ES521
    -257, # RS256
    -258, # RS384
    -259, # RS512
    -37,  # PS256
    -38,  # PS384
    -39,  # PS512
    -8,   # EdDSA (Ed25519)
]

# Timeout for challenges (5 minutes)
CHALLENGE_TIMEOUT_MINUTES = 5

# Maximum credentials per user
MAX_CREDENTIALS_PER_USER = 50

# ---------------------------------------------------------------------------
# Error Codes
# ---------------------------------------------------------------------------

class WebAuthnError(errors.SOGo6Error):
    """Base class for WebAuthn errors."""
    error_code_prefix = "WEBAUTHN"


# Specific error classes
class WebAuthnNotSupportedError(WebAuthnError):
    """WebAuthn is not supported by the browser."""
    http_status = 400
    error_code = "WEBAUTHN_NOT_SUPPORTED"
    message = "WebAuthn is not supported by your browser"


class WebAuthnChallengeExpiredError(WebAuthnError):
    """The challenge has expired."""
    http_status = 400
    error_code = "WEBAUTHN_CHALLENGE_EXPIRED"
    message = "WebAuthn challenge has expired"


class WebAuthnChallengeAlreadyUsedError(WebAuthnError):
    """The challenge has already been used."""
    http_status = 400
    error_code = "WEBAUTHN_CHALLENGE_USED"
    message = "WebAuthn challenge has already been used"


class WebAuthnInvalidResponseError(WebAuthnError):
    """The WebAuthn response is invalid."""
    http_status = 400
    error_code = "WEBAUTHN_INVALID_RESPONSE"
    message = "Invalid WebAuthn response"


class WebAuthnUserNotFoundError(WebAuthnError):
    """The user was not found."""
    http_status = 404
    error_code = "WEBAUTHN_USER_NOT_FOUND"
    message = "User not found"


class WebAuthnCredentialNotFoundError(WebAuthnError):
    """The credential was not found."""
    http_status = 404
    error_code = "WEBAUTHN_CREDENTIAL_NOT_FOUND"
    message = "WebAuthn credential not found"


class WebAuthnMaxCredentialsError(WebAuthnError):
    """Maximum number of credentials reached."""
    http_status = 400
    error_code = "WEBAUTHN_MAX_CREDENTIALS"
    message = f"Maximum of {MAX_CREDENTIALS_PER_USER} credentials per user reached"


class WebAuthnInvalidRPError(WebAuthnError):
    """The relying party ID is invalid."""
    http_status = 400
    error_code = "WEBAUTHN_INVALID_RP"
    message = "Invalid relying party ID"


# ---------------------------------------------------------------------------
# Table Names
# ---------------------------------------------------------------------------

TABLE_WEBAUTHN_CREDENTIALS = "sogo6_webauthn_credentials"
TABLE_WEBAUTHN_CHALLENGES = "sogo6_webauthn_challenges"
TABLE_WEBAUTHN_AUDIT_LOG = "sogo6_webauthn_audit_log"
TABLE_WEBAUTHN_POLICIES = "sogo6_webauthn_policies"


# ---------------------------------------------------------------------------
# Column Names
# ---------------------------------------------------------------------------

# Credentials table
COL_WC_ID = "id"
COL_WC_USER_ID = "user_id"
COL_WC_CREDENTIAL_ID = "credential_id"
COL_WC_PUBLIC_KEY_COSE = "public_key_cose"
COL_WC_ATTESTATION_TYPE = "attestation_type"
COL_WC_NAME = "name"
COL_WC_IS_DEFAULT = "is_default"
COL_WC_SIGN_COUNT = "sign_count"
COL_WC_LAST_USED_AT = "last_used_at"
COL_WC_CREATED_AT = "created_at"

# Challenges table
COL_WCH_ID = "id"
COL_WCH_USER_ID = "user_id"
COL_WCH_CHALLENGE_TYPE = "challenge_type"
COL_WCH_CHALLENGE = "challenge"
COL_WCH_RP_ID = "rp_id"
COL_WCH_USED = "used"
COL_WCH_EXPIRES_AT = "expires_at"
COL_WCH_CREATED_AT = "created_at"

# Audit log table
COL_WA_ID = "id"
COL_WA_USER_ID = "user_id"
COL_WA_ACTION = "action"
COL_WA_CREDENTIAL_ID = "credential_id"
COL_WA_SUCCESS = "success"
COL_WA_IP_ADDRESS = "ip_address"
COL_WA_ERROR_CODE = "error_code"
COL_WA_METADATA = "metadata"
COL_WA_CREATED_AT = "created_at"

# Policies table
COL_WP_ID = "id"
COL_WP_REQUIRE_WEBAUTHN = "require_webauthn"
COL_WP_ALLOW_PASSWORD_FALLBACK = "allow_password_fallback"
COL_WP_USER_VERIFICATION = "user_verification"
COL_WP_ATTESTATION_REQUIREMENT = "attestation_requirement"
COL_WP_TIMEOUT_SECONDS = "timeout_seconds"
COL_WP_CREATED_AT = "created_at"
COL_WP_UPDATED_AT = "updated_at"


# ---------------------------------------------------------------------------
# Database Schema Setup
# ---------------------------------------------------------------------------

def _db_type() -> str:
    """Return 'MySQL' or 'PostgreSQL' based on process config."""
    from app.config.settings.ProcessSetting import process_config
    return process_config.SOGO_P_DB_TYPE


def create_tables_if_not_exist():
    """Create WebAuthn tables if they don't exist.

    Uses BLOB instead of BYTEA, JSON instead of JSONB, VARCHAR(45)
    instead of INET, and INSERT IGNORE instead of ON CONFLICT for
    MySQL/MariaDB compatibility.
    """
    is_pg = _db_type() == "PostgreSQL"
    blob_type = "BYTEA" if is_pg else "LONGBLOB"
    json_type = "JSONB" if is_pg else "JSON"
    inet_type = "INET" if is_pg else "VARCHAR(45)"
    boolean_type = "BOOLEAN" if is_pg else "TINYINT(1)"

    # Credentials table
    sql_credentials = f"""
    CREATE TABLE IF NOT EXISTS {TABLE_WEBAUTHN_CREDENTIALS} (
        {COL_WC_ID} VARCHAR(36) PRIMARY KEY,
        {COL_WC_USER_ID} VARCHAR(255) NOT NULL,
        {COL_WC_CREDENTIAL_ID} {blob_type} NOT NULL UNIQUE,
        {COL_WC_PUBLIC_KEY_COSE} {blob_type} NOT NULL,
        {COL_WC_ATTESTATION_TYPE} VARCHAR(50),
        {COL_WC_NAME} VARCHAR(255),
        {COL_WC_IS_DEFAULT} {boolean_type} DEFAULT FALSE,
        {COL_WC_SIGN_COUNT} INTEGER DEFAULT 0,
        {COL_WC_LAST_USED_AT} TIMESTAMP NULL DEFAULT NULL,
        {COL_WC_CREATED_AT} TIMESTAMP DEFAULT NOW()
    );
    """
    # Note: foreign key to sogo6_users(uid) removed — sogo6_users may not
    # exist (LDAP-only setups), and cascade deletes can be handled at app level.

    sql_idx_cred_user = f"CREATE INDEX IF NOT EXISTS idx_webauthn_credentials_user ON {TABLE_WEBAUTHN_CREDENTIALS}({COL_WC_USER_ID});"
    sql_idx_cred_created = f"CREATE INDEX IF NOT EXISTS idx_webauthn_credentials_created ON {TABLE_WEBAUTHN_CREDENTIALS}({COL_WC_CREATED_AT});"

    # Challenges table
    sql_challenges = f"""
    CREATE TABLE IF NOT EXISTS {TABLE_WEBAUTHN_CHALLENGES} (
        {COL_WCH_ID} VARCHAR(36) PRIMARY KEY,
        {COL_WCH_USER_ID} VARCHAR(255),
        {COL_WCH_CHALLENGE_TYPE} VARCHAR(20) NOT NULL,
        {COL_WCH_CHALLENGE} {blob_type} NOT NULL,
        {COL_WCH_RP_ID} VARCHAR(255) NOT NULL,
        {COL_WCH_USED} {boolean_type} DEFAULT FALSE,
        {COL_WCH_EXPIRES_AT} TIMESTAMP NOT NULL,
        {COL_WCH_CREATED_AT} TIMESTAMP DEFAULT NOW()
    );
    """
    sql_idx_ch_expires = f"CREATE INDEX IF NOT EXISTS idx_webauthn_challenges_expires ON {TABLE_WEBAUTHN_CHALLENGES}({COL_WCH_EXPIRES_AT});"
    sql_idx_ch_user = f"CREATE INDEX IF NOT EXISTS idx_webauthn_challenges_user ON {TABLE_WEBAUTHN_CHALLENGES}({COL_WCH_USER_ID});"

    # Audit log table
    sql_audit = f"""
    CREATE TABLE IF NOT EXISTS {TABLE_WEBAUTHN_AUDIT_LOG} (
        {COL_WA_ID} VARCHAR(36) PRIMARY KEY,
        {COL_WA_USER_ID} VARCHAR(255),
        {COL_WA_ACTION} VARCHAR(50) NOT NULL,
        {COL_WA_CREDENTIAL_ID} VARCHAR(36),
        {COL_WA_SUCCESS} {boolean_type} NOT NULL,
        {COL_WA_IP_ADDRESS} {inet_type},
        {COL_WA_ERROR_CODE} VARCHAR(50),
        {COL_WA_METADATA} {json_type},
        {COL_WA_CREATED_AT} TIMESTAMP DEFAULT NOW()
    );
    """
    sql_idx_aud_user = f"CREATE INDEX IF NOT EXISTS idx_webauthn_audit_user ON {TABLE_WEBAUTHN_AUDIT_LOG}({COL_WA_USER_ID});"
    sql_idx_aud_action = f"CREATE INDEX IF NOT EXISTS idx_webauthn_audit_action ON {TABLE_WEBAUTHN_AUDIT_LOG}({COL_WA_ACTION});"
    sql_idx_aud_created = f"CREATE INDEX IF NOT EXISTS idx_webauthn_audit_created ON {TABLE_WEBAUTHN_AUDIT_LOG}({COL_WA_CREATED_AT});"

    # Policies table
    sql_policies = f"""
    CREATE TABLE IF NOT EXISTS {TABLE_WEBAUTHN_POLICIES} (
        {COL_WP_ID} VARCHAR(36) PRIMARY KEY,
        {COL_WP_REQUIRE_WEBAUTHN} {boolean_type} DEFAULT FALSE,
        {COL_WP_ALLOW_PASSWORD_FALLBACK} {boolean_type} DEFAULT TRUE,
        {COL_WP_USER_VERIFICATION} VARCHAR(20) DEFAULT 'preferred',
        {COL_WP_ATTESTATION_REQUIREMENT} VARCHAR(20) DEFAULT 'none',
        {COL_WP_TIMEOUT_SECONDS} INTEGER DEFAULT 300,
        {COL_WP_CREATED_AT} TIMESTAMP DEFAULT NOW(),
        {COL_WP_UPDATED_AT} TIMESTAMP DEFAULT NOW()
    );
    """

    # Execute all
    db = Db()
    db.execute_write(sql_credentials)
    db.execute_write(sql_idx_cred_user)
    db.execute_write(sql_idx_cred_created)
    db.execute_write(sql_challenges)
    db.execute_write(sql_idx_ch_expires)
    db.execute_write(sql_idx_ch_user)
    db.execute_write(sql_audit)
    db.execute_write(sql_idx_aud_user)
    db.execute_write(sql_idx_aud_action)
    db.execute_write(sql_idx_aud_created)
    db.execute_write(sql_policies)

    # Insert default policy — MySQL uses INSERT IGNORE, PostgreSQL ON CONFLICT
    if is_pg:
        default_policy = f"""
        INSERT INTO {TABLE_WEBAUTHN_POLICIES} ({COL_WP_ID}, {COL_WP_REQUIRE_WEBAUTHN},
            {COL_WP_ALLOW_PASSWORD_FALLBACK}, {COL_WP_USER_VERIFICATION},
            {COL_WP_ATTESTATION_REQUIREMENT}, {COL_WP_TIMEOUT_SECONDS})
        VALUES ('default', FALSE, TRUE, 'preferred', 'none', 300)
        ON CONFLICT ({COL_WP_ID}) DO NOTHING;
        """
    else:
        default_policy = f"""
        INSERT IGNORE INTO {TABLE_WEBAUTHN_POLICIES} ({COL_WP_ID}, {COL_WP_REQUIRE_WEBAUTHN},
            {COL_WP_ALLOW_PASSWORD_FALLBACK}, {COL_WP_USER_VERIFICATION},
            {COL_WP_ATTESTATION_REQUIREMENT}, {COL_WP_TIMEOUT_SECONDS})
        VALUES ('default', FALSE, TRUE, 'preferred', 'none', 300);
        """
    db.execute_write(default_policy)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class WebAuthnCredential(PydanticBaseModel):
    """Represents a WebAuthn credential."""
    
    id: str
    user_id: str
    credential_id: bytes
    public_key_cose: bytes
    attestation_type: Optional[str]
    name: Optional[str]
    is_default: bool = False
    sign_count: int = 0
    last_used_at: Optional[datetime]
    created_at: datetime
    
    @classmethod
    def from_row(cls, row: Dict) -> "WebAuthnCredential":
        return cls(
            id=row[COL_WC_ID],
            user_id=row[COL_WC_USER_ID],
            credential_id=row[COL_WC_CREDENTIAL_ID],
            public_key_cose=row[COL_WC_PUBLIC_KEY_COSE],
            attestation_type=row.get(COL_WC_ATTESTATION_TYPE),
            name=row.get(COL_WC_NAME),
            is_default=row.get(COL_WC_IS_DEFAULT, False),
            sign_count=row.get(COL_WC_SIGN_COUNT, 0),
            last_used_at=row.get(COL_WC_LAST_USED_AT),
            created_at=row[COL_WC_CREATED_AT],
        )
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "is_default": self.is_default,
            "sign_count": self.sign_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "created_at": self.created_at.isoformat(),
        }
    
    def to_webauthn_credential(self) -> dict:
        """Convert to webauthn PublicKeyCredentialDescriptor format."""
        return {
            "id": bytes_to_base64url(self.credential_id),
            "type": "public-key",
            "transports": ["internal", "hybrid"],
        }


class WebAuthnChallenge(PydanticBaseModel):
    """Represents a WebAuthn challenge."""
    
    id: str
    user_id: Optional[str]
    challenge_type: str  # 'register' or 'login'
    challenge: bytes
    rp_id: str
    used: bool = False
    expires_at: datetime
    created_at: datetime
    
    @classmethod
    def from_row(cls, row: Dict) -> "WebAuthnChallenge":
        return cls(
            id=row[COL_WCH_ID],
            user_id=row.get(COL_WCH_USER_ID),
            challenge_type=row[COL_WCH_CHALLENGE_TYPE],
            challenge=row[COL_WCH_CHALLENGE],
            rp_id=row[COL_WCH_RP_ID],
            used=row.get(COL_WCH_USED, False),
            expires_at=row[COL_WCH_EXPIRES_AT],
            created_at=row[COL_WCH_CREATED_AT],
        )
    
    def is_expired(self) -> bool:
        return datetime.now() > self.expires_at
    
    def is_valid(self) -> bool:
        return not self.used and not self.is_expired()


class WebAuthnPolicy(PydanticBaseModel):
    """Represents WebAuthn policy settings."""
    
    id: str
    require_webauthn: bool = False
    allow_password_fallback: bool = True
    user_verification: str = "preferred"  # preferred, required, discouraged
    attestation_requirement: str = "none"  # none, self, attested
    timeout_seconds: int = 300
    created_at: datetime
    updated_at: datetime
    
    @classmethod
    def from_row(cls, row: Dict) -> "WebAuthnPolicy":
        return cls(
            id=row[COL_WP_ID],
            require_webauthn=row.get(COL_WP_REQUIRE_WEBAUTHN, False),
            allow_password_fallback=row.get(COL_WP_ALLOW_PASSWORD_FALLBACK, True),
            user_verification=row.get(COL_WP_USER_VERIFICATION, "preferred"),
            attestation_requirement=row.get(COL_WP_ATTESTATION_REQUIREMENT, "none"),
            timeout_seconds=row.get(COL_WP_TIMEOUT_SECONDS, 300),
            created_at=row[COL_WP_CREATED_AT],
            updated_at=row[COL_WP_UPDATED_AT],
        )


# ---------------------------------------------------------------------------
# ModuleWebAuthn - Main Service Class
# ---------------------------------------------------------------------------

class ModuleWebAuthn:
    """
    Main WebAuthn service class.
    
    Implements passkey registration, authentication, and management
    according to FIDO2 WebAuthn specification.
    """
    
    # Instance of webauthn library
    # This will be set up with our configuration
    
    @staticmethod
    def get_webauthn_instance() -> None:
        """Backwards-compatibility stub for the old class-based webauthn API.

        The webauthn library 3.x uses stateless functions instead of a
        configured instance, so nothing needs to be constructed here.
        """
        return None
    
    @staticmethod
    def generate_registration_options(
        user_id: str,
        user_name: str,
        user_display_name: str,
        rp_id: Optional[str] = None,
        rp_name: Optional[str] = None,
        attestation: str = "none",
        user_verification: str = "preferred",
        authenticator_selection: Optional[Dict] = None,
        timeout: int = 300000,  # 5 minutes in ms
    ) -> Dict[str, Any]:
        """
        Generate registration options for a new passkey.
        
        Args:
            user_id: Unique user identifier
            user_name: User's username
            user_display_name: User's display name
            rp_id: Override the hardcoded Relying Party ID (defaults to RP_ID constant)
            rp_name: Override the Relying Party display name (defaults to RP_NAME constant)
            attestation: Attestation requirement (none, self, attested)
            user_verification: User verification requirement (preferred, required, discouraged)
            authenticator_selection: Authenticator selection criteria
            timeout: Challenge timeout in milliseconds
        
        Returns:
            Registration options as dict (ready for JSON serialization)
        """
        rp_id = rp_id or RP_ID
        rp_name = rp_name or RP_NAME
        # Create user model for webauthn
        _ = PublicKeyCredentialUserEntity(
            id=user_id.encode('utf-8'),
            name=user_name,
            display_name=user_display_name,
        )
        
        # Generate options
        options = generate_registration_options(
            rp_id=rp_id,
            rp_name=rp_name,
            user_name=user_name,
            user_id=user_id.encode('utf-8'),
            user_display_name=user_display_name,
            attestation=attestation,
            # the webauthn lib requires an AuthenticatorSelectionCriteria struct
            authenticator_selection=authenticator_selection or AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement(user_verification),
                require_resident_key=True,  # Prefer passkeys over roaming keys
            ),
            supported_pub_key_algs=SUPPORTED_ALGORITHMS,
            timeout=timeout,
        )
        
        # Convert to JSON-serializable dict
        return {
            "challenge": bytes_to_base64url(options.challenge),
            "rp": {
                "id": options.rp.id,
                "name": options.rp.name,
            },
            "user": {
                "id": bytes_to_base64url(options.user.id),
                "name": options.user.name,
                "displayName": options.user.display_name,
            },
            "pubKeyCredParams": [
                {"type": "public-key", "alg": alg} for alg in options.pub_key_cred_params
            ],
            "timeout": options.timeout,
            "attestation": getattr(options, "attestation", "none").value
            if hasattr(getattr(options, "attestation", "none"), "value") else getattr(options, "attestation", "none"),
            "userVerification": getattr(options, "user_verification", user_verification).value
            if hasattr(getattr(options, "user_verification", user_verification), "value")
            else getattr(options, "user_verification", user_verification),
            "authenticatorSelection": {
                "residentKey": "preferred",
                "userVerification": user_verification,
                "requireResidentKey": True,
            } if not authenticator_selection else authenticator_selection,
        }
    
    @staticmethod
    def generate_authentication_options(
        user_id: str,
        user_verification: str = "preferred",
        timeout: int = 300000,
        rp_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate authentication options for passkey login.
        
        Args:
            user_id: User's unique identifier
            user_verification: User verification requirement
            timeout: Challenge timeout in milliseconds
            rp_id: Override the hardcoded Relying Party ID (defaults to RP_ID constant)
        
        Returns:
            Authentication options as dict
        """
        rp_id = rp_id or RP_ID
        # Get existing credentials for this user
        credentials = ModuleWebAuthn.get_credentials_by_user(user_id)
        
        # Convert to webauthn format
        webauthn_credentials = [
            cred.to_webauthn_credential() for cred in credentials
        ]
        
        # Allow credentials without user ID (for username-less auth)
        allow_credentials = [
            {
                "id": cred.id,
                "type": "public-key",
                "transports": ["internal", "hybrid"],
            }
            for cred in webauthn_credentials
        ]
        
        options = generate_authentication_options(
            rp_id=rp_id,
            allow_credentials=allow_credentials,
            user_verification=user_verification,
            timeout=timeout,
        )
        
        # Convert to JSON-serializable dict
        return {
            "challenge": bytes_to_base64url(options.challenge),
            "rpId": options.rp_id,
            "allowCredentials": [
                {
                    "id": cred["id"],
                    "type": cred["type"],
                    "transports": cred.get("transports", []),
                }
                for cred in options.allow_credentials
            ],
            "timeout": options.timeout,
            "userVerification": options.user_verification,
        }
    
    @staticmethod
    def create_challenge(
        user_id: Optional[str],
        challenge_type: str,
        challenge_bytes: bytes,
        rp_id: str = RP_ID,
    ) -> WebAuthnChallenge:
        """Create and store a new challenge."""
        challenge = WebAuthnChallenge(
            id=str(uuid4()),
            user_id=user_id,
            challenge_type=challenge_type,
            challenge=challenge_bytes,
            rp_id=rp_id,
            used=False,
            expires_at=datetime.now() + timedelta(minutes=CHALLENGE_TIMEOUT_MINUTES),
            created_at=datetime.now(),
        )
        
        # Store in database
        ModuleWebAuthn._store_challenge(challenge)
        
        return challenge
    
    @staticmethod
    def _store_challenge(challenge: WebAuthnChallenge) -> None:
        """Store a challenge in the database."""
        sql = f"""
        INSERT INTO {TABLE_WEBAUTHN_CHALLENGES} 
            ({COL_WCH_ID}, {COL_WCH_USER_ID}, {COL_WCH_CHALLENGE_TYPE}, 
             {COL_WCH_CHALLENGE}, {COL_WCH_RP_ID}, {COL_WCH_USED}, 
             {COL_WCH_EXPIRES_AT}, {COL_WCH_CREATED_AT})
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            challenge.id,
            challenge.user_id,
            challenge.challenge_type,
            challenge.challenge,
            challenge.rp_id,
            challenge.used,
            challenge.expires_at,
            challenge.created_at,
        )
        Db().execute_write(sql, params)
    
    @staticmethod
    def get_challenge(challenge_id: str) -> Optional[WebAuthnChallenge]:
        """Retrieve a challenge by ID."""
        sql = f"""
        SELECT * FROM {TABLE_WEBAUTHN_CHALLENGES}
        WHERE {COL_WCH_ID} = %s
        """
        row = Db().execute_read_one(sql, (challenge_id,))
        if row:
            return WebAuthnChallenge.from_row(row)
        return None
    
    @staticmethod
    def mark_challenge_used(challenge_id: str) -> bool:
        """Mark a challenge as used."""
        sql = f"""
        UPDATE {TABLE_WEBAUTHN_CHALLENGES}
        SET {COL_WCH_USED} = TRUE
        WHERE {COL_WCH_ID} = %s
        """
        Db().execute_write(sql, (challenge_id,))
        row = Db().execute_read_one(
            f"SELECT {COL_WCH_ID} FROM {TABLE_WEBAUTHN_CHALLENGES} WHERE {COL_WCH_ID} = %s AND {COL_WCH_USED} = TRUE",
            (challenge_id,),
        )
        return row is not None

    @staticmethod
    def cleanup_expired_challenges() -> int:
        """Remove expired challenges. Returns number deleted."""
        sql = f"""
        DELETE FROM {TABLE_WEBAUTHN_CHALLENGES}
        WHERE {COL_WCH_EXPIRES_AT} < NOW()
        """
        return Db().execute_write(sql)
    
    @staticmethod
    def register_credential(
        user_id: str,
        credential: Dict[str, Any],
        name: Optional[str] = None,
        is_default: bool = False,
    ) -> WebAuthnCredential:
        """
        Register a new WebAuthn credential.
        
        Args:
            user_id: User's unique identifier
            credential: WebAuthn credential response
            name: Optional name for the credential
            is_default: Whether this is the default credential
        
        Returns:
            The stored credential
        """
        # Check if user already has too many credentials
        count = ModuleWebAuthn.count_credentials(user_id)
        if count >= MAX_CREDENTIALS_PER_USER:
            raise WebAuthnMaxCredentialsError()
        
        # Create credential record
        new_credential = WebAuthnCredential(
            id=str(uuid4()),
            user_id=user_id,
            credential_id=base64url_to_bytes(credential.get("credential_id") or credential.get("id")),
            public_key_cose=base64url_to_bytes(credential.get("public_key_cose") or credential.get("publicKey")),
            attestation_type=credential.get("attestation_type") or credential.get("attestationType"),
            name=name or f"Passkey {count + 1}",
            is_default=is_default or count == 0,  # First credential is default
            sign_count=0,
            last_used_at=None,
            created_at=datetime.now(),
        )
        
        # Store in database
        ModuleWebAuthn._store_credential(new_credential)
        
        # Log the registration
        ModuleWebAuthn._log_action(
            user_id=user_id,
            action="register",
            credential_id=new_credential.id,
            success=True,
            metadata={"credential_name": new_credential.name},
        )
        
        return new_credential
    
    @staticmethod
    def _store_credential(credential: WebAuthnCredential) -> None:
        """Store a credential in the database."""
        sql = f"""
        INSERT INTO {TABLE_WEBAUTHN_CREDENTIALS}
            ({COL_WC_ID}, {COL_WC_USER_ID}, {COL_WC_CREDENTIAL_ID}, 
             {COL_WC_PUBLIC_KEY_COSE}, {COL_WC_ATTESTATION_TYPE}, 
             {COL_WC_NAME}, {COL_WC_IS_DEFAULT}, {COL_WC_SIGN_COUNT}, 
             {COL_WC_LAST_USED_AT}, {COL_WC_CREATED_AT})
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            credential.id,
            credential.user_id,
            credential.credential_id,
            credential.public_key_cose,
            credential.attestation_type,
            credential.name,
            credential.is_default,
            credential.sign_count,
            credential.last_used_at,
            credential.created_at,
        )
        Db().execute_write(sql, params)
    
    @staticmethod
    def authenticate(
        challenge_id: str,
        credential: Dict[str, Any],
        ip_address: Optional[str] = None,
    ) -> Tuple[WebAuthnCredential, str]:
        """
        Authenticate a user with a WebAuthn credential.
        
        Args:
            challenge_id: The challenge ID
            credential: The authentication response
            ip_address: Optional IP address for audit logging
        
        Returns:
            Tuple of (credential, user_id)
        
        Raises:
            Various WebAuthnError exceptions for failures
        """
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
        
        # Get the stored credential
        stored_credential = ModuleWebAuthn.get_credential_by_id(
            bytes_to_base64url(credential.get("credential_id") or credential.get("id"))
        )
        
        if not stored_credential:
            raise WebAuthnCredentialNotFoundError()
        
        # Prepare verification data
        auth_credential = AuthenticationCredential(
            id=base64url_to_bytes(credential.get('id') or credential.get('credential_id')),
            raw_id=base64url_to_bytes(credential.get('rawId') or credential.get('id') or credential.get('credential_id')),
            type="public-key",
            response=AuthenticatorAssertionResponse(
                authenticator_data=base64url_to_bytes(credential.get('authenticatorData', '')),
                client_data_json=base64url_to_bytes(credential.get('clientDataJSON', '')),
                signature=base64url_to_bytes(credential.get('signature', '')),
                user_handle=base64url_to_bytes(credential['userHandle']) if credential.get('userHandle') else None,
            ),
        )

        verification = verify_authentication_response(
            credential=auth_credential,
            expected_challenge=challenge.challenge,
            expected_rp_id=RP_ID,
            expected_origin=[ORIGIN],
            credential_public_key=stored_credential.public_key_cose,
            credential_current_sign_count=stored_credential.sign_count,
            require_user_verification=False,
        )
        
        # Update sign count
        stored_credential.sign_count = verification.new_sign_count
        ModuleWebAuthn._update_credential_sign_count(
            stored_credential.id, verification.new_sign_count
        )
        
        # Update last used
        ModuleWebAuthn._update_credential_last_used(stored_credential.id)
        
        # Log the authentication
        ModuleWebAuthn._log_action(
            user_id=stored_credential.user_id,
            action="login",
            credential_id=stored_credential.id,
            success=True,
            ip_address=ip_address,
            metadata={"sign_count": verification.new_sign_count},
        )
        
        return stored_credential, stored_credential.user_id
    
    @staticmethod
    def _update_credential_sign_count(credential_id: str, sign_count: int) -> None:
        """Update the sign count for a credential."""
        sql = f"""
        UPDATE {TABLE_WEBAUTHN_CREDENTIALS}
        SET {COL_WC_SIGN_COUNT} = %s
        WHERE {COL_WC_ID} = %s
        """
        Db().execute_write(sql, (sign_count, credential_id))
    
    @staticmethod
    def _update_credential_last_used(credential_id: str) -> None:
        """Update the last used timestamp for a credential."""
        sql = f"""
        UPDATE {TABLE_WEBAUTHN_CREDENTIALS}
        SET {COL_WC_LAST_USED_AT} = NOW()
        WHERE {COL_WC_ID} = %s
        """
        Db().execute_write(sql, (credential_id,))
    
    @staticmethod
    def get_credential_by_id(credential_id: str) -> Optional[WebAuthnCredential]:
        """Get a credential by its ID."""
        sql = f"""
        SELECT * FROM {TABLE_WEBAUTHN_CREDENTIALS}
        WHERE {COL_WC_ID} = %s
        """
        row = Db().execute_read_one(sql, (credential_id,))
        if row:
            return WebAuthnCredential.from_row(row)
        return None
    
    @staticmethod
    def get_credentials_by_user(user_id: str) -> List[WebAuthnCredential]:
        """Get all credentials for a user."""
        sql = f"""
        SELECT * FROM {TABLE_WEBAUTHN_CREDENTIALS}
        WHERE {COL_WC_USER_ID} = %s
        ORDER BY {COL_WC_CREATED_AT} DESC
        """
        rows = Db().execute_read_all(sql, (user_id,))
        return [WebAuthnCredential.from_row(row) for row in rows]
    
    @staticmethod
    def get_default_credential(user_id: str) -> Optional[WebAuthnCredential]:
        """Get the default credential for a user."""
        sql = f"""
        SELECT * FROM {TABLE_WEBAUTHN_CREDENTIALS}
        WHERE {COL_WC_USER_ID} = %s AND {COL_WC_IS_DEFAULT} = TRUE
        LIMIT 1
        """
        row = Db().execute_read_one(sql, (user_id,))
        if row:
            return WebAuthnCredential.from_row(row)
        return None
    
    @staticmethod
    def count_credentials(user_id: str) -> int:
        """Count credentials for a user."""
        sql = f"""
        SELECT COUNT(*) as count FROM {TABLE_WEBAUTHN_CREDENTIALS}
        WHERE {COL_WC_USER_ID} = %s
        """
        row = Db().execute_read_one(sql, (user_id,))
        return row["count"] if row else 0
    
    @staticmethod
    def set_default_credential(user_id: str, credential_id: str) -> None:
        """Set a credential as the default for a user."""
        # First, unset all others
        sql_clear = f"""
        UPDATE {TABLE_WEBAUTHN_CREDENTIALS}
        SET {COL_WC_IS_DEFAULT} = FALSE
        WHERE {COL_WC_USER_ID} = %s
        """
        Db().execute_write(sql_clear, (user_id,))
        
        # Then set the new default
        sql_set = f"""
        UPDATE {TABLE_WEBAUTHN_CREDENTIALS}
        SET {COL_WC_IS_DEFAULT} = TRUE
        WHERE {COL_WC_ID} = %s AND {COL_WC_USER_ID} = %s
        """
        Db().execute_write(sql_set, (credential_id, user_id))
    
    @staticmethod
    def rename_credential(credential_id: str, user_id: str, new_name: str) -> None:
        """Rename a credential."""
        sql = f"""
        UPDATE {TABLE_WEBAUTHN_CREDENTIALS}
        SET {COL_WC_NAME} = %s
        WHERE {COL_WC_ID} = %s AND {COL_WC_USER_ID} = %s
        """
        Db().execute_write(sql, (new_name, credential_id, user_id))
    
    @staticmethod
    def remove_credential(credential_id: str, user_id: str) -> bool:
        """Remove a credential. Returns True if removed."""
        # Get the credential first for logging
        credential = ModuleWebAuthn.get_credential_by_id(credential_id)
        
        sql = f"""
        DELETE FROM {TABLE_WEBAUTHN_CREDENTIALS}
        WHERE {COL_WC_ID} = %s AND {COL_WC_USER_ID} = %s
        """
        affected = Db().execute_write(sql, (credential_id, user_id))
        
        if affected > 0:
            # Log the removal
            ModuleWebAuthn._log_action(
                user_id=user_id,
                action="remove",
                credential_id=credential_id,
                success=True,
                metadata={"credential_name": credential.name if credential else None},
            )
            return True
        return False
    
    @staticmethod
    def remove_all_credentials(user_id: str) -> int:
        """Remove all credentials for a user. Returns count removed."""
        # Get credentials for logging
        credentials = ModuleWebAuthn.get_credentials_by_user(user_id)
        
        sql = f"""
        DELETE FROM {TABLE_WEBAUTHN_CREDENTIALS}
        WHERE {COL_WC_USER_ID} = %s
        """
        count = Db().execute_write(sql, (user_id,))
        
        # Log removals
        for cred in credentials:
            ModuleWebAuthn._log_action(
                user_id=user_id,
                action="remove",
                credential_id=cred.id,
                success=True,
                metadata={"bulk": True, "credential_name": cred.name},
            )
        
        return count
    
    @staticmethod
    def get_policy() -> WebAuthnPolicy:
        """Get the current WebAuthn policy."""
        sql = f"""
        SELECT * FROM {TABLE_WEBAUTHN_POLICIES}
        WHERE {COL_WP_ID} = 'default'
        Limit 1
        """
        row = Db().execute_read_one(sql)
        if row:
            return WebAuthnPolicy.from_row(row)
        return WebAuthnPolicy(id="default")
    
    @staticmethod
    def set_policy(policy_data: Dict[str, Any]) -> WebAuthnPolicy:
        """Set the WebAuthn policy."""
        policy = ModuleWebAuthn.get_policy()
        
        # Update fields
        for key, value in policy_data.items():
            if hasattr(policy, key):
                setattr(policy, key, value)
        
        policy.updated_at = datetime.now()
        
        # Store in database
        sql = f"""
        UPDATE {TABLE_WEBAUTHN_POLICIES}
        SET {COL_WP_REQUIRE_WEBAUTHN} = %s,
            {COL_WP_ALLOW_PASSWORD_FALLBACK} = %s,
            {COL_WP_USER_VERIFICATION} = %s,
            {COL_WP_ATTESTATION_REQUIREMENT} = %s,
            {COL_WP_TIMEOUT_SECONDS} = %s,
            {COL_WP_UPDATED_AT} = %s
        WHERE {COL_WP_ID} = 'default'
        """
        params = (
            policy.require_webauthn,
            policy.allow_password_fallback,
            policy.user_verification,
            policy.attestation_requirement,
            policy.timeout_seconds,
            policy.updated_at,
        )
        Db().execute_write(sql, params)
        
        # Log the policy change
        ModuleWebAuthn._log_action(
            user_id=None,
            action="policy_update",
            credential_id=None,
            success=True,
            metadata={"policy": policy.to_dict()},
        )
        
        return ModuleWebAuthn.get_policy()
    
    @staticmethod
    def get_audit_log(
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Get audit log entries."""
        sql = f"""
        SELECT * FROM {TABLE_WEBAUTHN_AUDIT_LOG}
        """
        conditions = []
        params = []
        
        if user_id:
            conditions.append(f"{COL_WA_USER_ID} = %s")
            params.append(user_id)
        
        if action:
            conditions.append(f"{COL_WA_ACTION} = %s")
            params.append(action)
        
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        
        sql += f" ORDER BY {COL_WA_CREATED_AT} DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        rows = Db().execute_read_all(sql, tuple(params))
        
        return [
            {
                "id": row[COL_WA_ID],
                "user_id": row.get(COL_WA_USER_ID),
                "action": row[COL_WA_ACTION],
                "credential_id": row.get(COL_WA_CREDENTIAL_ID),
                "success": row[COL_WA_SUCCESS],
                "ip_address": str(row.get(COL_WA_IP_ADDRESS)) if row.get(COL_WA_IP_ADDRESS) else None,
                "error_code": row.get(COL_WA_ERROR_CODE),
                "metadata": row.get(COL_WA_METADATA),
                "created_at": row[COL_WA_CREATED_AT].isoformat() if isinstance(row[COL_WA_CREATED_AT], datetime) else str(row[COL_WA_CREATED_AT]),
            }
            for row in rows
        ]
    
    @staticmethod
    def _log_action(
        user_id: Optional[str],
        action: str,
        credential_id: Optional[str],
        success: bool,
        ip_address: Optional[str] = None,
        error_code: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> None:
        """Log an action to the audit log."""
        sql = f"""
        INSERT INTO {TABLE_WEBAUTHN_AUDIT_LOG}
            ({COL_WA_ID}, {COL_WA_USER_ID}, {COL_WA_ACTION}, 
             {COL_WA_CREDENTIAL_ID}, {COL_WA_SUCCESS}, 
             {COL_WA_IP_ADDRESS}, {COL_WA_ERROR_CODE}, {COL_WA_METADATA})
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            str(uuid4()),
            user_id,
            action,
            credential_id,
            success,
            ip_address,
            error_code,
            json.dumps(metadata) if metadata else None,
        )
        Db().execute_write(sql, params)
    
    @staticmethod
    def get_user_has_passkeys(user_id: str) -> bool:
        """Check if a user has any passkeys registered."""
        count = ModuleWebAuthn.count_credentials(user_id)
        return count > 0

    # Alias matching the legacy interface/login-flow usage
    has_enabled_credentials = get_user_has_passkeys

    
    @staticmethod
    def get_credential_for_authentication(
        credential_id_base64: str,
    ) -> Tuple[Optional[WebAuthnCredential], Optional[str]]:
        """
        Get a credential and its user for authentication.
        
        This is used when the credential ID is provided but not the user ID.
        Returns (credential, user_id) or (None, None)
        """
        sql = f"""
        SELECT c.* FROM {TABLE_WEBAUTHN_CREDENTIALS} c
        WHERE TO_BASE64(c.{COL_WC_CREDENTIAL_ID}) = %s
        LIMIT 1
        """
        row = Db().execute_read_one(sql, (credential_id_base64,))
        if row:
            credential = WebAuthnCredential.from_row(row)
            # user_id is stored directly in the credentials table (no JOIN needed)
            return credential, credential.user_id if credential else None
        return None, None


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def uint8array_to_base64url(data: bytes) -> str:
    """Convert bytes to base64url string."""
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')


def base64url_to_uint8array(data: str) -> bytes:
    """Convert base64url string to bytes."""
    # Add padding if needed
    padding = 4 - len(data) % 4
    if padding != 4:
        data += '=' * padding
    return base64.urlsafe_b64decode(data)


# ---------------------------------------------------------------------------
# Initialize
# ---------------------------------------------------------------------------

# Ensure tables exist on import
try:
    create_tables_if_not_exist()
except Exception as e:
    print(f"Warning: Could not create WebAuthn tables: {e}")


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    'ModuleWebAuthn',
    'WebAuthnCredential',
    'WebAuthnChallenge',
    'WebAuthnPolicy',
    'RP_ID',
    'RP_NAME',
    'WebAuthnError',
    'WebAuthnNotSupportedError',
    'WebAuthnChallengeExpiredError',
    'WebAuthnChallengeAlreadyUsedError',
    'WebAuthnInvalidResponseError',
    'WebAuthnUserNotFoundError',
    'WebAuthnCredentialNotFoundError',
    'WebAuthnMaxCredentialsError',
    'WebAuthnInvalidRPError',
]
