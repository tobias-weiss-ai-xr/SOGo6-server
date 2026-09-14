"""Server-Sent Events endpoint for real-time UI updates.

Provides a Server-Sent Events endpoint at /api/sse that the frontend connects to
for live updates (new mail, calendar changes, etc.).

Authentication is self-contained: the token is read from the Authorization Bearer
header OR from the ?token=<jwt> query parameter (browser EventSource cannot send
headers).

New-mail detection: each connection polls its INBOX message count once per tick
(alongside the heartbeat). When the count grows, the newest mail is fetched and
pushed as a `mail:received` event.

# ponytail: per-connection 20s IMAP STATUS poll — fine for homelab scale;
# upgrade path is a shared IMAP IDLE worker or Stalwart JMAP push → Redis.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable

from flask import Blueprint, Response, request
from flask.typing import ResponseReturnValue

from app.config.init_config import (
    init_get_system_and_default_domain_settings,
    init_get_user_domain_settings,
)
from app.config.settings.DomainSettings import MailSettings, MailSettingsObj
from app.config.settings.ProcessSetting import process_config
from app.interface.auth.InterfaceAuthUser import InterfaceAuthUser
from app.module.mail.ModuleMail import ModuleMail
from app.auth.service.VoucherUserService import VoucherUserService
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.api.paginate_sort_filter import CollectionPaginateArgs
import app.utils.errors as err

logger = logging.getLogger(__name__)

MAIL_POLL_INTERVAL_S = 20

blp = Blueprint("Live Updates", __name__, url_prefix="/api")


def _build_mail_module_factory(user) -> Callable[[], ModuleMail]:
    """Return a factory building a ModuleMail for the SSE connection's user."""

    def factory() -> ModuleMail:
        user_domain_settings = init_get_user_domain_settings(user)
        mail_settings = MailSettingsObj(user_domain_settings[MailSettings.subparent])
        return ModuleMail(user, mail_settings, process_config)

    return factory


def _inbox_sse_generator(user, module_factory: Callable[[], ModuleMail]):
    """Heartbeat + INBOX new-mail poll for one SSE connection.

    Emits:
    - `event: connected` once,
    - unnamed heartbeat data events every MAIL_POLL_INTERVAL_S,
    - `event: mail:received` whenever the INBOX message count grows.
    """
    module: ModuleMail | None = None
    last_count: int | None = None

    try:
        yield f"event: connected\ndata: {json.dumps({'status': 'connected'})}\n\n"

        while True:
            time.sleep(MAIL_POLL_INTERVAL_S)

            # New-mail poll (best-effort; must never kill the stream)
            try:
                if module is None:
                    module = module_factory()
                folder = module.get_one_folder("0", "INBOX")
                count = folder.get("message_count")
                if last_count is not None and count is not None and count > last_count:
                    try:
                        # page=1, page_size=1: the folder fetch yields newest-first,
                        # so the first item of page 1 is the newest mail
                        mails, _ = module.get_folder_mails(
                            "0",
                            "INBOX",
                            CollectionPaginateArgs(
                                page=1, page_size=1,
                                fields="contents", fields_action="exclude",
                            ),
                        )
                        m = mails[0] if mails else {}
                        payload = {
                            "id": str(m.get("uid", "")),
                            "subject": m.get("subject", ""),
                            "from": m.get("from") or {},
                            "receivedAt": m.get("date"),
                            "preview": "",
                        }
                    except Exception:
                        logger.exception("SSE mail:received payload fetch failed")
                        payload = {"id": f"inbox-{int(time.time())}"}
                    yield f"event: mail:received\ndata: {json.dumps(payload)}\n\n"
                if count is not None:
                    last_count = count
            except Exception:
                # IMAP/DB hiccup: drop the module so the next tick rebuilds it
                logger.exception("SSE inbox poll failed, will retry next tick")
                module = None

            epoch_time = int(time.time())
            yield f"data: {json.dumps({'type': 'heartbeat', 'time': epoch_time})}\n\n"

    except GeneratorExit:
        # Client disconnected cleanly
        pass


@blp.route("/sse")
def sse() -> ResponseReturnValue:
    """Server-Sent Events endpoint for real-time updates."""

    # Extract token from Authorization header or query parameter
    token = None
    auth_header = request.authorization
    if auth_header and auth_header.type == "bearer":
        token = auth_header.token
    if not token:
        token = request.args.get("token")

    # Validate the token
    if not token:
        return create_api_base_response(
            error=err.ERROR_AUTHENTICATED_ROUTE,
            status_code=401
        )

    try:
        user = VoucherUserService(process_config).generate_user_from_voucher(token)
    except Exception:
        return create_api_base_response(
            error=err.ERROR_AUTHENTICATED_ROUTE,
            status_code=401
        )

    # Fill the user profile (IMAP credentials etc.) exactly like the
    # request-time auth layer does — the raw voucher user carries no
    # mail-server password, so mail polling would fail to login.
    try:
        system_settings, _ = init_get_system_and_default_domain_settings()
        user_domain_settings = init_get_user_domain_settings(user)
        auth_inter = InterfaceAuthUser(process_config, system_settings, user_domain_settings)
        creds_ok, user = auth_inter.check_user_and_fill_info(user)
    except Exception:
        logger.exception("SSE user profile fill failed")
        creds_ok = False
    if not creds_ok:
        return create_api_base_response(
            error=err.ERROR_AUTHENTICATED_ROUTE,
            status_code=401
        )

    return Response(
        _inbox_sse_generator(user, _build_mail_module_factory(user)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
