"""Mailbox Debug Panel (#35) — raw email source, Sieve trace, IMAP session log.

Provides diagnostic information for troubleshooting mail delivery issues.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.module.mail.ModuleMail import ModuleMail
from app.config.settings.DomainSettings import MailSettingsObj
from app.config.settings.ProcessSetting import ProcessSetting
from app.auth.User import User


class AnonymousUser(User):
    """Minimal anonymous user for debug endpoints."""
    def __init__(self):
        self.uid = ""; self.cn = ""; self.mail = ""
        self.authenticated = False; self.password = ""; self.domain = ""

if TYPE_CHECKING:
    from app.auth.User import User

blp = Blueprint("Mailbox Debug", __name__, url_prefix="/mailbox-debug")


@blp.route("/<string:user_uid>/raw/<string:folder>/<string:mail_uid>")
class ApiMailboxDebugRaw(MethodView):
    """View raw email source."""

    def get(self, user_uid: str, folder: str, mail_uid: str) -> ResponseReturnValue:
        """Return the raw source of an email."""
        try:
            module = ModuleMail(
                process_settings=ProcessSetting(),
                mail_settings=MailSettingsObj(),
                user=AnonymousUser(),
            )
            raw = module.get_mail_raw("0", folder, mail_uid)
            return create_api_base_response({"raw": raw.get("raw", "")})
        except Exception:
            return create_api_base_response(None, err.ERROR_MAIL_DOWNLOAD_FAILED)


@blp.route("/<string:user_uid>/headers/<string:folder>/<string:mail_uid>")
class ApiMailboxDebugHeaders(MethodView):
    """View parsed email headers."""

    def get(self, user_uid: str, folder: str, mail_uid: str) -> ResponseReturnValue:
        """Return all email headers as key-value pairs."""
        try:
            module = ModuleMail(
                process_settings=ProcessSetting(),
                mail_settings=MailSettingsObj(),
                user=AnonymousUser(),
            )
            detail = module.get_mail_detail("0", folder, mail_uid)
            # Extract SMTP/IMAP trace info
            trace = {
                "received": detail.get("mail", {}).get("Received", []),
                "message_id": detail.get("message_id", ""),
                "authentication_results": detail.get("mail", {}).get("Authentication-Results", ""),
                "dkim_signature": detail.get("mail", {}).get("DKIM-Signature", ""),
                "spf_status": detail.get("mail", {}).get("Received-SPF", ""),
            }
            return create_api_base_response(trace)
        except Exception:
            return create_api_base_response(None, err.ERROR_MAIL_DOWNLOAD_FAILED)
