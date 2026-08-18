from flask_smorest import Blueprint

from .AuthUserApi import blp as user_auth_api
from .ApiAppPassword import blp as app_password_api
from .ApiMFA import blp as mfa_api
from .ApiPasswordReset import blp as password_reset_api
from .ApiWebAuthn import blp as webauthn_api

user_auth_apis : list[Blueprint] = [user_auth_api, app_password_api, mfa_api, password_reset_api, webauthn_api]
