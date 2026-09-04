# pylint: disable=invalid-sequence-index
"""Functional tests for the ApiMFA blueprint (a registered blueprint)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest
from flask import Flask, g

from app.api.v1.auth.ApiMFA import blp
from app.utils.exceptions import RequestException


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(blp)

    class FakeUser:
        uid = "user@example.org"
        domain = "example.org"

    @app.before_request
    def _set_user():
        g.user = FakeUser()

    with mock.patch("app.api.v1.auth.ApiMFA.InterfaceMFA") as inter_cls, \
            mock.patch("app.config.settings.ProcessSetting.process_config"):
        inter = inter_cls.return_value
        yield app.test_client(), inter


class TestSetup:
    def test_get_secret(self, client):
        c, inter = client
        inter.setup.return_value = {
            "secret": "JBSWY3DPEHPK3PXP",
            "provisioning_uri": "otpauth://totp/...",
            "qr_svg": "<svg/>",
        }
        resp = c.get("/auth/mfa/setup")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["secret"] == "JBSWY3DPEHPK3PXP"
        inter.setup.assert_called_once()


class TestEnable:
    def test_enable_ok(self, client):
        c, inter = client
        resp = c.post("/auth/mfa/enable", json={"code": "123456"})
        assert resp.status_code == 200
        inter.enable.assert_called_once()
        args = inter.enable.call_args.args
        assert args[0].uid == "user@example.org"
        assert args[1] == "123456"

    def test_enable_request_exception(self, client):
        c, inter = client
        inter.enable.side_effect = RequestException("bad", mock.MagicMock(c="S000999", h=400, m="Bad"))
        resp = c.post("/auth/mfa/enable", json={"code": "000000"})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["error_code"] == "S000999"

    def test_enable_missing_code_400(self, client):
        c, inter = client
        resp = c.post("/auth/mfa/enable", json={})
        assert resp.status_code == 400
        inter.enable.assert_not_called()


class TestDisable:
    def test_disable_reauth_fail(self, client):
        c, inter = client
        with mock.patch("app.interface.auth.InterfaceAuthUser.InterfaceAuthUser") as aui_cls, \
                mock.patch("app.config.init_config.init_get_system_and_default_domain_settings",
                           return_value=({}, {})):
            aui = aui_cls.return_value
            aui._check_login.return_value = (False, None, None)
            resp = c.post("/auth/mfa/disable", json={"password": "wrong"})
        assert resp.status_code == err_h()
        assert resp.get_json()["error_code"] == "S000208"
        inter.disable.assert_not_called()

    def test_disable_reauth_request_exception(self, client):
        c, inter = client
        with mock.patch("app.interface.auth.InterfaceAuthUser.InterfaceAuthUser") as aui_cls, \
                mock.patch("app.config.init_config.init_get_system_and_default_domain_settings",
                           return_value=({}, {})):
            aui = aui_cls.return_value
            aui._check_login.side_effect = RequestException("x", mock.MagicMock(c="S000500", h=500, m="X"))
            resp = c.post("/auth/mfa/disable", json={"password": "x"})
        assert resp.status_code == 500
        assert resp.get_json()["error_code"] == "S000500"

    def test_disable_ok(self, client):
        c, inter = client
        with mock.patch("app.interface.auth.InterfaceAuthUser.InterfaceAuthUser") as aui_cls, \
                mock.patch("app.config.init_config.init_get_system_and_default_domain_settings",
                           return_value=({}, {})):
            aui = aui_cls.return_value
            aui._check_login.return_value = (True, mock.MagicMock(), None)
            resp = c.post("/auth/mfa/disable", json={"password": "correct"})
        assert resp.status_code == 200
        inter.disable.assert_called_once()
        assert inter.disable.call_args.args[0].uid == "user@example.org"

    def test_disable_request_exception(self, client):
        c, inter = client
        inter.disable.side_effect = RequestException("x", mock.MagicMock(c="S000501", h=500, m="X"))
        with mock.patch("app.interface.auth.InterfaceAuthUser.InterfaceAuthUser") as aui_cls, \
                mock.patch("app.config.init_config.init_get_system_and_default_domain_settings",
                           return_value=({}, {})):
            aui = aui_cls.return_value
            aui._check_login.return_value = (True, None, None)
            resp = c.post("/auth/mfa/disable", json={"password": "ok"})
        assert resp.status_code == 500
        assert resp.get_json()["error_code"] == "S000501"

    def test_disable_missing_password_400(self, client):
        c, inter = client
        resp = c.post("/auth/mfa/disable", json={})
        assert resp.status_code == 400


def err_h():
    from app.utils import errors as err
    return err.ERROR_LOGIN_FAILED.h
