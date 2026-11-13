"""Agent Action Layer — semantic facade over mail/calendar/contacts/AI.

Every view is a thin controller delegating to the existing ``Interface*``
layer. Compact, agent-oriented shapes keep responses token-efficient. The
blueprints are mounted under ``/api/v1/agent/`` and accept either a session
voucher (UI AI panel) or a ``sogo_``/``sogoimp_`` API token (agents).
"""
from flask import g
from flask_smorest import Blueprint

from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response


# ── Action registry (single source of truth for manifest + MCP) ─────────────

ACTIONS: list[dict] = []


def register_action(action_id: str, method: str, path: str, description: str, scope: str) -> None:
    ACTIONS.append({
        "id": action_id,
        "method": method,
        "path": path,
        "description": description,
        "scope": scope,
    })


# ── Guards ──────────────────────────────────────────────────────────────────

def require_scope(scope: str):
    """Enforce the API-token scope for a facade view.

    Returns ``None`` when the request may proceed, otherwise a ready-to-return
    403 response. Voucher-authenticated sessions (UI AI panel) carry no
    ``g.token_scopes`` and are treated as the full user session.

    :param scope: Required module scope, e.g. ``mail:send``.
    """
    scopes = getattr(g, "token_scopes", None)
    if scopes is None:
        return None
    from app.api.v1.user.ApiApiTokens import token_scope_satisfies
    if token_scope_satisfies(scopes, scope):
        return None
    return create_api_base_response(None, err.ERROR_SCOPE_INSUFFICIENT)


def reject_anonymous():
    """The facade is never anonymous — 401 response or None."""
    user = getattr(g, "user", None)
    if user is None or getattr(user, "anonymous", False):
        return create_api_base_response(None, err.ERROR_AUTHENTICATED_ROUTE)
    return None


def agent_blueprint(name: str, url_prefix: str, description: str) -> Blueprint:
    """Create a blueprint with the anonymous guard pre-attached."""
    blp = Blueprint(name, __name__, url_prefix=url_prefix, description=description)

    @blp.before_request
    def _agent_must_be_authenticated():  # pylint: disable=unused-variable
        return reject_anonymous()

    return blp


# ── Interface helpers ───────────────────────────────────────────────────────

def mail_interface():
    from app.interface.mail.InterfaceApiMailMail import InterfaceApiMailMail
    return InterfaceApiMailMail(
        process_setting=g.process_settings,
        user_domain_settings=g.user_domain_settings,
        user=g.user,
    )


def mail_send_interface():
    from app.interface.mail.InterfaceApiMailSend import InterfaceApiMailSend
    return InterfaceApiMailSend(
        process_setting=g.process_settings,
        user_domain_settings=g.user_domain_settings,
        user=g.user,
    )


def mail_folder_interface():
    from app.interface.mail.InterfaceApiMailFolder import InterfaceApiMailFolder
    return InterfaceApiMailFolder(
        process_setting=g.process_settings,
        user_domain_settings=g.user_domain_settings,
        user=g.user,
    )


def calendar_interface():
    from app.interface.calendar.InterfaceApiCalendarCalendar import InterfaceApiCalendarCalendar
    return InterfaceApiCalendarCalendar(
        process_setting=g.process_settings,
        user_domain_settings=g.user_domain_settings,
        user=g.user,
    )


def contact_interface():
    from app.interface.contact.InterfaceApiContactContact import InterfaceApiContactContact
    return InterfaceApiContactContact(
        process_setting=g.process_settings,
        user_domain_settings=g.user_domain_settings,
        user=g.user,
    )


# Import the facade modules after the helpers so ACTIONS registration happens
# on package import and the blueprints below are discoverable.
from .ApiAgentManifest import blp as agent_manifest_blp  # noqa: E402
from .ApiAgentMail import blp as agent_mail_blp  # noqa: E402
from .ApiAgentCalendar import blp as agent_calendar_blp  # noqa: E402
from .ApiAgentContacts import blp as agent_contacts_blp  # noqa: E402
from .ApiAgentAI import blp as agent_ai_blp  # noqa: E402

agent_apis: list = [
    agent_manifest_blp,
    agent_mail_blp,
    agent_calendar_blp,
    agent_contacts_blp,
    agent_ai_blp,
]
