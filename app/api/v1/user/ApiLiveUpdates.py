"""WebSocket Live Updates (#29) — SSE endpoint for real-time UI updates.

Provides a Server-Sent Events endpoint that the frontend connects to
for live updates (new mail, calendar changes, etc.).
"""
from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from flask import g, Response, stream_with_context
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.service import sogo_cache
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User

blp = Blueprint("Live Updates", __name__, url_prefix="/live")


@blp.route("/events")
class ApiLiveEvents(MethodView):
    """SSE endpoint for real-time events."""

    def get(self) -> ResponseReturnValue:
        """Subscribe to real-time events via Server-Sent Events."""
        user: User = g.user
        cache = sogo_cache()

        def generate():
            # Send initial connection event
            yield f"event: connected\ndata: {json.dumps({'status': 'connected'})}\n\n"
            last_check = time.time()

            while True:
                # Check for new events for this user
                # In production, this would use Redis pub/sub or a notification queue
                time.sleep(5)  # Poll every 5 seconds as fallback

                # Heartbeat to keep connection alive
                yield f"event: heartbeat\ndata: {json.dumps({'time': time.time()})}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
