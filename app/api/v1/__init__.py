from flask_smorest import Blueprint

from app.utils import constants as cs

from .admin import admin_apis
from .admin.ApiJmapProtocol import blp as jmap_protocol_api
from .system import system_apis
from .auth import user_auth_apis
from .mail import mail_apis
from .user import user_profile_apis, webauthn_blp, webauthn_blp_admin
from .calendar import calendar_apis
from .jobs import job_apis
from .contact import contact_apis
from .health import health_apis
from .securitytxt import securitytxt_apis
from .mail.ApiAttachments import blp as attachments_blueprint

v1_basic_apis: list[Blueprint] = []
v1_basic_apis += system_apis
v1_basic_apis += user_auth_apis
v1_basic_apis += user_profile_apis
v1_basic_apis += mail_apis
v1_basic_apis += calendar_apis
v1_basic_apis += job_apis
v1_basic_apis += contact_apis
v1_basic_apis += health_apis
v1_basic_apis += securitytxt_apis
v1_basic_apis.append(attachments_blueprint)
v1_basic_apis.extend([webauthn_blp, webauthn_blp_admin])
# JMAP is a user mail protocol: it needs a non-anonymous g.user (and
# g.user_domain_settings) for JmapMailGateway to build, which only exists on
# the BASIC/user API — not the ADMIN API where it was previously mounted.
v1_basic_apis.append(jmap_protocol_api)

v1_admin_apis: list[Blueprint] = []
v1_admin_apis += admin_apis

all_v1_apis = {
    cs.API_BASIC: v1_basic_apis,
    cs.API_ADMIN: v1_admin_apis
}
