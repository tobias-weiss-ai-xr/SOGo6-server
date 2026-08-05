"""
User API v1 - Blueprint registration and initialization.

This module contains all user-facing API endpoints for SOGo6 v1.
"""

from flask_smorest import Api


def register_user_blueprints(api: Api):
    """Register all user v1 blueprints."""
    # Import all user API modules to register them
    from app.api.v1.user import ApiWebAuthn
    ApiWebAuthn.register_webauthn_blueprints(api)
