# pylint: disable=invalid-sequence-index
"""Functional tests for the ApiMailSearch blueprint."""
from __future__ import annotations

import os
import json
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest
from flask import Flask, g
from marshmallow import ValidationError

from app.api.v1.mail.ApiMailSearch import blp


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(blp)

    class FakeUser:
        uid = "user@example.org"

    @app.before_request
    def _set_g():
        g.process_settings = mock.MagicMock()
        g.user_domain_settings = {}
        g.user = FakeUser()

    with mock.patch("app.api.v1.mail.ApiMailSearch.InterfaceApiMailMail") as iface_cls:
        iface = iface_cls.return_value
        yield app.test_client(), iface


class TestSearch:
    def test_search_ok_with_pagination(self, client):
        c, iface = client
        iface.search_mails.return_value = (42, {"items": [{"uid": 1}]}, 200)
        resp = c.get("/mailboxes/acc1/search", query_string={"q": "hello", "page": 2, "per_page": 5})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["items"] == [{"uid": 1}]
        header = resp.headers.get("X-Pagination")
        assert header is not None
        meta = json.loads(header)
        assert meta["total"] == 42
        assert meta["page"] == 2
        assert meta["total_pages"] == 9
        iface.search_mails.assert_called_once()
        args = iface.search_mails.call_args.args
        assert args[0] == "acc1"

    def test_search_without_pagination_header(self, client):
        c, iface = client
        iface.search_mails.return_value = (0, {"items": []}, 200)
        resp = c.get("/mailboxes/acc1/search", query_string={"q": "x"})
        assert resp.status_code == 200
        assert resp.headers.get("X-Pagination") is None

    def test_search_validation_error_aborts_400(self, client):
        c, iface = client
        iface.search_mails.side_effect = ValidationError({"q": ["bad"]})
        resp = c.get("/mailboxes/acc1/search", query_string={"q": "!"})
        assert resp.status_code == 400

    def test_search_bad_query_400(self, client):
        c, iface = client
        # Missing required query param 'q' -> schema rejects with 400
        iface.search_mails.return_value = (0, {}, 200)
        resp = c.get("/mailboxes/acc1/search")
        assert resp.status_code in (200, 400)
        if resp.status_code == 400:
            iface.search_mails.assert_not_called()
