"""
User API v1 - Blueprint registration and initialization.

This module contains all user-facing API endpoints for SOGo6 v1.
"""

from flask_smorest import Api, Blueprint


def register_user_blueprints(api: Api):
    """Register all user v1 blueprints."""
    # Import all user API modules to register them
    from app.api.v1.user import ApiWebAuthn
    ApiWebAuthn.register_webauthn_blueprints(api)


# Also export the WebAuthn blueprints for direct registration
from app.api.v1.user.ApiWebAuthn import blp as webauthn_blp, blp_admin as webauthn_blp_admin

# List of blueprints to be added to v1_basic_apis
user_auth_apis: list[Blueprint] = []
