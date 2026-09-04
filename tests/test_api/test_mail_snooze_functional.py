# pylint: disable=invalid-sequence-index
"""Functional + unit tests for ApiMailSnooze blueprint and helpers."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest
from flask import Flask, g

from app.api.v1.mail.ApiMailSnooze import _resolve_snooze_time, blp
from app.utils import errors as err
from app.utils.exceptions import RequestException


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = False  # let unhandled RequestException -> 500
    app.register_blueprint(blp)

    class FakeUser:
        uid = "user@example.org"

    @app.before_request
    def _set_g():
        g.process_settings = mock.MagicMock()
        g.user = FakeUser()

    db = mock.MagicMock()
    with mock.patch(
        "app.utils.module.importManager.import_and_instantiate_manager",
        return_value=db,
    ), mock.patch("app.api.v1.mail.ApiMailSnooze.ModuleSnooze") as module_cls:
        module_cls.parse_preset.return_value = {"days": 1}
        module_cls.return_value = mock.MagicMock()
        yield app.test_client(), module_cls.return_value


S = "app.api.v1.mail.ApiMailSnooze"


class TestList:
    def test_list_snoozed(self, client):
        c, module = client
        module.list_snoozed.return_value = [{"id": 1, "mail_uid": "10"}]
        resp = c.get("/snooze/")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["snoozed"] == [{"id": 1, "mail_uid": "10"}]
        module.list_snoozed.assert_called_once_with("user@example.org")


class TestCreate:
    def test_post_with_snooze_until(self, client):
        c, module = client
        module.snooze.return_value = {"id": 1}
        resp = c.post("/snooze/", json={
            "account_id": "0",
            "mail_uids": ["10", "11"],
            "folder": "INBOX",
            "snooze_until": "2026-01-16T09:00:00Z",
        })
        assert resp.status_code == 200
        assert module.snooze.call_count == 2
        kwargs = module.snooze.call_args.kwargs
        assert kwargs["user_uid"] == "user@example.org"
        assert kwargs["account_id"] == "0"
        assert kwargs["mail_uid"] == "11"
        assert kwargs["folder"] == "INBOX"
        assert kwargs["snooze_until"].isoformat().startswith("2026-01-16T09:00:00")

    def test_post_with_preset(self, client):
        c, module = client
        module.snooze.return_value = {"id": 2}
        before = datetime.now(timezone.utc)
        resp = c.post("/snooze/", json={
            "account_id": "0", "mail_uids": ["5"], "folder": "INBOX",
            "preset": "tomorrow",
        })
        assert resp.status_code == 200
        kw = module.snooze.call_args.kwargs["snooze_until"]
        assert kw > before

    def test_post_missing_fields_400(self, client):
        c, module = client
        resp = c.post("/snooze/", json={})
        assert resp.status_code == 400
        module.snooze.assert_not_called()

    def test_post_invalid_preset_400(self, client):
        c, module = client
        resp = c.post("/snooze/", json={
            "account_id": "0", "mail_uids": ["5"], "folder": "INBOX",
            "preset": "not-a-preset",
        })
        assert resp.status_code == 400
        module.snooze.assert_not_called()

    def test_post_missing_time_is_500(self, client):
        c, module = client
        resp = c.post("/snooze/", json={
            "account_id": "0", "mail_uids": ["5"], "folder": "INBOX",
        })
        assert resp.status_code == 500


class TestDetail:
    def test_delete_unsnooze(self, client):
        c, module = client
        module.unsnooze.return_value = {"id": 3, "folder": "INBOX"}
        resp = c.delete("/snooze/3")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["restored"] == {"id": 3, "folder": "INBOX"}
        module.unsnooze.assert_called_once_with("user@example.org", 3)


class TestResolveTime:
    def test_direct_iso(self):
        out = _resolve_snooze_time({"snooze_until": "2026-01-16T09:00:00Z"})
        assert out == datetime(2026, 1, 16, 9, 0, tzinfo=timezone.utc)

    def test_preset_days(self):
        before = datetime.now(timezone.utc)
        with mock.patch(f"{S}.ModuleSnooze.parse_preset", return_value={"days": 1}):
            out = _resolve_snooze_time({"preset": "tomorrow"})
        assert out > before

    def test_preset_hours(self):
        before = datetime.now(timezone.utc)
        with mock.patch(f"{S}.ModuleSnooze.parse_preset", return_value={"hours": 3}):
            out = _resolve_snooze_time({"preset": "later_today"})
        assert out > before

    def test_preset_parse_none_falls_through(self):
        with mock.patch(f"{S}.ModuleSnooze.parse_preset", return_value=None):
            with pytest.raises(RequestException) as exc:
                _resolve_snooze_time({"preset": "tomorrow"})
        assert exc.value.error.c == err.ERROR_VALIDATION_FAILED.c

    def test_invalid_iso_raises(self):
        with pytest.raises(RequestException) as exc:
            _resolve_snooze_time({"snooze_until": "not-a-date"})
        assert exc.value.error.c == err.ERROR_VALIDATION_FAILED.c

    def test_missing_both_raises(self):
        with pytest.raises(RequestException) as exc:
            _resolve_snooze_time({})
        assert exc.value.error.c == err.ERROR_VALIDATION_FAILED.c
