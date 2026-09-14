"""Server-Sent Events endpoint for real-time UI updates.

Provides a Server-Sent Events endpoint at /api/sse that the frontend connects to
for live updates (new mail, calendar changes, etc.).

Authentication is self-contained: the token is read from the Authorization Bearer
header OR from the ?token=<jwt> query parameter (browser EventSource cannot send
headers).
"""
from __future__ import annotations

import json
import time

from flask import Blueprint, Response, request
from flask.typing import ResponseReturnValue

from app.auth.service.VoucherUserService import VoucherUserService
from app.config.settings.ProcessSetting import process_config
from app.utils.api.ApiBaseResponse import create_api_base_response
import app.utils.errors as err

blp = Blueprint("Live Updates", __name__, url_prefix="/api")


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
        VoucherUserService(process_config).generate_user_from_voucher(token)
    except Exception:
        return create_api_base_response(
            error=err.ERROR_AUTHENTICATED_ROUTE,
            status_code=401
        )

    def generate():
        try:
            # Send initial connection event
            yield f"event: connected\ndata: {json.dumps({'status': 'connected'})}\n\n"

            while True:
                # Heartbeat every 20 seconds as unnamed event
                time.sleep(20)
                epoch_time = int(time.time())
                yield f"data: {json.dumps({'type': 'heartbeat', 'time': epoch_time})}\n\n"

        except GeneratorExit:
            # Client disconnected cleanly
            pass

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
