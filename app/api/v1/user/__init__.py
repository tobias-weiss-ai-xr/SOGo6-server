"""
User API v1 - Blueprint registration and initialization.

This module contains all user-facing API endpoints for SOGo6 v1.
"""

from flask_smorest import Api, Blueprint

from .ApiResourceBooking import blp as resource_booking_blueprint
from .ApiSharedMailboxes import blp as shared_mailboxes_blueprint
from .ApiUserProfile import blp as user_profile_blueprint
from .ApiUserPreferences import blp as user_preferences_blueprint
from .ApiUserCustomization import blp as user_customization_blueprint
from .ApiGlobalSearch import blp as global_search_blueprint


def register_user_blueprints(api: Api):
    """Register all user v1 blueprints."""
    # Import all user API modules to register them
    from app.api.v1.user import ApiWebAuthn
    ApiWebAuthn.register_webauthn_blueprints(api)


# Also export the WebAuthn blueprints for direct registration
from app.api.v1.user.ApiWebAuthn import blp as webauthn_blp, blp_admin as webauthn_blp_admin

# List of blueprints to be added to v1_basic_apis
user_auth_apis: list[Blueprint] = []

# User profile blueprints - basic APIs accessible to all users
user_profile_apis: list[Blueprint] = [
    resource_booking_blueprint,
    shared_mailboxes_blueprint,
    user_profile_blueprint,
    user_preferences_blueprint,
    user_customization_blueprint,
    global_search_blueprint,
]
