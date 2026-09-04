# pylint: disable=invalid-sequence-index
"""Unit tests for ApiLiveUpdates (57% -> high)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest


class TestLiveEvents:
    def test_streams_connected_event(self):
        from flask import Flask, g
        from app.api.v1.user import ApiLiveUpdates

        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.before_request
        def _set_ctx():
            g.user = mock.MagicMock()

        with mock.patch("app.api.v1.user.ApiLiveUpdates.sogo_cache") as sc:
            app.register_blueprint(ApiLiveUpdates.blp)
            with app.test_client() as c:
                resp = c.get("/live/events", buffered=False)

        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert resp.headers["Cache-Control"] == "no-cache"
        # First emitted chunk is the connected event
        first = next(resp.response)
        assert b"event: connected" in first
        assert b"status" in first
        sc.assert_called_once()
