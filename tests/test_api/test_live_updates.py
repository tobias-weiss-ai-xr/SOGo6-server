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
    def test_sse_rejects_missing_token(self):
        from flask import Flask

        from app.api.v1.user import ApiLiveUpdates

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(ApiLiveUpdates.blp)
        with app.test_client() as c:
            resp = c.get("/api/sse")
        assert resp.status_code == 401

    def test_sse_rejects_bad_voucher(self):
        from flask import Flask

        from app.api.v1.user import ApiLiveUpdates

        app = Flask(__name__)
        app.config["TESTING"] = True
        # voucher validation raises -> 401 (not 500)
        with mock.patch.object(
            ApiLiveUpdates, "VoucherUserService", side_effect=RuntimeError("bad")
        ):
            app.register_blueprint(ApiLiveUpdates.blp)
            with app.test_client() as c:
                resp = c.get("/api/sse?token=invalid")
        assert resp.status_code == 401

    def test_streams_connected_event(self):
        from flask import Flask

        from app.api.v1.user import ApiLiveUpdates

        app = Flask(__name__)
        app.config["TESTING"] = True

        with (
            mock.patch.object(ApiLiveUpdates, "VoucherUserService") as vsvc,
            mock.patch.object(ApiLiveUpdates, "InterfaceAuthUser") as iau,
            mock.patch.object(
                ApiLiveUpdates,
                "init_get_system_and_default_domain_settings",
                return_value=(mock.MagicMock(), None),
            ),
            mock.patch.object(ApiLiveUpdates, "init_get_user_domain_settings"),
            mock.patch.object(ApiLiveUpdates, "_build_mail_module_factory") as fac,
        ):
            iau.return_value.check_user_and_fill_info.return_value = (
                True,
                mock.MagicMock(),
            )
            app.register_blueprint(ApiLiveUpdates.blp)
            with app.test_client() as c:
                resp = c.get("/api/sse?token=t", buffered=False)

        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert resp.headers["Cache-Control"] == "no-cache"
        # First emitted chunk is the connected event
        first = next(resp.response)
        assert b"event: connected" in first
        assert b"status" in first
        vsvc.assert_called_once()
        iau.return_value.check_user_and_fill_info.assert_called_once()
        fac.assert_called_once()
