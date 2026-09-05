# pylint: disable=invalid-sequence-index
"""Functional tests for the AuthUserApi blueprint (auth mode/login/callback/saml2/logout)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest
from flask import Flask, g

from app.api.v1.auth.AuthUserApi import blp

MOD = "app.api.v1.auth.AuthUserApi"


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
        g.system_settings = {}
        g.default_domain_settings = {}
        g.user = FakeUser()

    with mock.patch(f"{MOD}.InterfaceAuthUser") as iface_cls:
        iface = iface_cls.return_value
        yield app.test_client(), iface


@pytest.fixture
def proc():
    p = mock.MagicMock()
    p.SOGO_P_DB_TYPE = "MySQL"
    p.SOGO_P_PUBLIC_BASE_URL = "http://localhost:3000"
    p.SOGO_SAML2_CLOCK_SKEW = 0
    p.get_db_settings.return_value = {"host": "db"}
    with mock.patch("app.config.settings.ProcessSetting.process_config", p):
        yield p


@pytest.fixture
def sso(proc):
    with mock.patch(
        "app.interface.auth.InterfaceAuthSSO.InterfaceAuthSSO"
    ) as sso_cls:
        yield sso_cls.return_value


@pytest.fixture
def init_ret(proc):
    with mock.patch(
        "app.config.init_config.init_get_system_and_default_domain_settings",
        return_value=({}, {}),
    ):
        yield


class TestMode:
    def test_get_login_mech(self, client):
        c, iface = client
        iface.get_login_mech.return_value = {"mode": "plain", "url": ""}
        resp = c.get("/auth/mode?username=u@x.org&redirect=http://r")
        assert resp.status_code == 200
        iface.get_login_mech.assert_called_once_with("u@x.org", "http://r")

    def test_missing_username_400(self, client):
        c, iface = client
        resp = c.get("/auth/mode")
        assert resp.status_code == 400
        iface.get_login_mech.assert_not_called()


class TestLogin:
    def test_plain_login(self, client):
        c, iface = client
        iface.plain_login.return_value = {"data": {"jwt_token": "abc"}}
        with mock.patch("app.service.sogo_cache") as cache, \
                mock.patch("app.utils.api.login_rate_limiter.LoginRateLimiter") as L:
            limiter = L.return_value
            limiter.is_ip_rate_limited.return_value = False
            resp = c.post("/auth/login", json={
                "username": "u@x.org", "password": "p", "mfa_code": "123456",
            })
        assert resp.status_code == 200
        cache.assert_called_once()
        limiter.is_ip_rate_limited.assert_called_once()
        iface.plain_login.assert_called_once()
        body = iface.plain_login.call_args.args[0]
        assert body["username"] == "u@x.org"
        assert body["mfa_code"] == "123456"

    def test_missing_fields_400(self, client):
        c, iface = client
        resp = c.post("/auth/login", json={})
        assert resp.status_code == 400
        iface.plain_login.assert_not_called()

    def test_rate_limited_returns_error(self, client):
        c, iface = client
        with mock.patch("app.service.sogo_cache"), \
                mock.patch("app.utils.api.login_rate_limiter.LoginRateLimiter") as L:
            L.return_value.is_ip_rate_limited.return_value = True
            resp = c.post("/auth/login", json={"username": "u", "password": "p"})
        assert resp.status_code == 401
        iface.plain_login.assert_not_called()


class TestCallbackGet:
    def test_get_query_params_forwarded(self, client, sso, init_ret):
        # route requires a non-empty domain segment; query args forwarded
        c, iface = client
        sso.handle_callback.return_value = ({"data": {"state": "x"}, "error_code": ""}, 200)
        resp = c.get("/auth/callback/example.org?code=abc&state=xyz")
        assert resp.status_code == 200
        params = sso.handle_callback.call_args.args[2]
        assert params == {"code": "abc", "state": "xyz"}

    def test_get_domain_without_db_result_uses_default(self, client, sso, init_ret):
        c, iface = client
        sso.handle_callback.return_value = ({"data": {}, "error_code": ""}, 200)
        db = mock.MagicMock()
        db.select_from_table.return_value = []
        with mock.patch(
            "app.utils.module.importManager.import_and_instantiate_manager",
            return_value=db,
        ):
            resp = c.get("/auth/callback/example.org")
        assert resp.status_code == 200
        domain_auth = sso.handle_callback.call_args.args[1]
        assert domain_auth.SOGO_D_AUTH_TYPE == "plain"

    def test_get_redirects_on_jwt(self, client, sso, init_ret):
        c, iface = client
        sso.handle_callback.return_value = ({"data": {"jwt_token": "tok123"}, "error_code": ""}, 200)
        resp = c.get("/auth/callback/example.org")
        assert resp.status_code == 302
        assert resp.headers["Location"] == "http://localhost:3000/auth/callback#token=tok123"

    def test_get_loads_domain_settings(self, client, sso, init_ret):
        c, iface = client
        sso.handle_callback.return_value = ({"data": {"status": "ok"}, "error_code": ""}, 200)
        db = mock.MagicMock()
        db.select_from_table.return_value = [
            ({"AUTH_SETTINGS": {"SOGO_D_AUTH_TYPE": "saml2"}},),
        ]
        with mock.patch(
            "app.utils.module.importManager.import_and_instantiate_manager",
            return_value=db,
        ):
            resp = c.get("/auth/callback/example.org")
        assert resp.status_code == 200
        domain_auth = sso.handle_callback.call_args.args[1]
        assert domain_auth.SOGO_D_AUTH_TYPE == "saml2"

    def test_get_domain_error_uses_default(self, client, sso, init_ret):
        c, iface = client
        sso.handle_callback.return_value = ({"data": {}, "error_code": ""}, 200)
        with mock.patch(
            "app.utils.module.importManager.import_and_instantiate_manager",
            side_effect=RuntimeError("db down"),
        ):
            resp = c.get("/auth/callback/example.org")
        assert resp.status_code == 200
        domain_auth = sso.handle_callback.call_args.args[1]
        assert domain_auth.SOGO_D_AUTH_TYPE == "plain"


class TestCallbackPost:
    def test_post_form_data(self, client, sso, init_ret):
        c, iface = client
        sso.handle_callback.return_value = ({"data": {"ok": 1}, "error_code": ""}, 200)
        resp = c.post("/auth/callback/example.org",
                      data={"SAMLResponse": "resp", "RelayState": "st"})
        assert resp.status_code == 200
        params = sso.handle_callback.call_args.args[2]
        assert params == {"SAMLResponse": "resp", "RelayState": "st"}

    def test_post_raw_xml(self, client, sso, init_ret):
        c, iface = client
        sso.handle_callback.return_value = ({"data": {}, "error_code": ""}, 200)
        resp = c.post("/auth/callback/example.org",
                      data="<samlp:Response>...</samlp:Response>",
                      content_type="application/xml")
        assert resp.status_code == 200
        params = sso.handle_callback.call_args.args[2]
        assert params["SAMLResponse"].startswith("<")

    def test_post_urlencoded_raw(self, client, sso, init_ret):
        c, iface = client
        sso.handle_callback.return_value = ({"data": {}, "error_code": ""}, 200)
        resp = c.post("/auth/callback/example.org",
                      data="SAMLResponse=YWIyMw==&RelayState=rs",
                      content_type="text/plain")
        assert resp.status_code == 200
        params = sso.handle_callback.call_args.args[2]
        assert params["SAMLResponse"] == "YWIyMw=="

    def test_post_jwt_redirect(self, client, sso, init_ret):
        c, iface = client
        sso.handle_callback.return_value = ({"data": {"jwt_token": "tok"}, "error_code": ""}, 200)
        resp = c.post("/auth/callback/example.org", data={"SAMLResponse": "x"})
        assert resp.status_code == 302
        assert resp.headers["Location"] == "http://localhost:3000/auth/callback#token=tok"

    def test_post_plain_string_body(self, client, sso, init_ret):
        c, iface = client
        sso.handle_callback.return_value = ("no valid SAML", 400)
        resp = c.post("/auth/callback/example.org", data={"SAMLResponse": "x"})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "no valid SAML"


class TestMetadata:
    def test_metadata_xml(self, client, sso, init_ret):
        c, iface = client
        saml = mock.MagicMock()
        saml.get_sp_metadata.return_value = "<md:EntityDescriptor/>"
        sso._build_saml.return_value = saml
        resp = c.get("/auth/saml2/metadata")
        assert resp.status_code == 200
        assert b"EntityDescriptor" in resp.data
        assert resp.mimetype == "application/xml"

    def test_metadata_domain(self, client, sso, init_ret):
        c, iface = client
        saml = mock.MagicMock()
        saml.get_sp_metadata.return_value = "<xml/>"
        sso._build_saml.return_value = saml
        resp = c.get("/auth/saml2/metadata/example.org")
        assert resp.status_code == 200
        assert sso._build_saml.call_args.args[1] == "example.org"

    def test_metadata_error(self, client, sso, init_ret):
        c, iface = client
        sso._build_saml.side_effect = RuntimeError("no saml")
        resp = c.get("/auth/saml2/metadata")
        assert resp.status_code == 412
        assert resp.get_json()["error_code"] == "S001210"


class TestSamlStart:
    def test_start_redirect(self, client, sso, init_ret):
        c, iface = client
        saml = mock.MagicMock()
        saml.create_login_request.return_value = "http://idp/sso?req=1"
        sso._build_saml.return_value = saml
        resp = c.get("/auth/saml2/start?domain=example.org&relay_state=rs")
        assert resp.status_code == 302
        assert resp.headers["Location"] == "http://idp/sso?req=1"
        saml.create_login_request.assert_called_once_with(relay_state="rs")

    def test_start_error(self, client, sso, init_ret):
        c, iface = client
        sso._build_saml.side_effect = ValueError("boom")
        resp = c.get("/auth/saml2/start")
        assert resp.status_code == 412


class TestAcs:
    def test_acs_form_jwt_redirect(self, client, sso, init_ret, proc):
        c, iface = client
        sso.handle_callback.return_value = ({"data": {"jwt_token": "t"}, "error_code": ""}, 200)
        resp = c.post("/auth/saml2/acs",
                      data={"SAMLResponse": "x", "RelayState": "example.org"})
        assert resp.status_code == 302
        assert resp.headers["Location"] == "http://localhost:3000/auth/callback#token=t"
        assert sso.handle_callback.call_args.args[0] == "example.org"

    def test_acs_no_jwt(self, client, sso, init_ret):
        c, iface = client
        sso.handle_callback.return_value = ({"data": {"status": "nok"}, "error_code": "E1"}, 400)
        resp = c.post("/auth/saml2/acs", data={"SAMLResponse": "x"})
        # ACS rewraps through create_api_base_response (ignores status int)
        assert resp.status_code == 200
        assert resp.get_json()["data"] == {"status": "nok"}


class TestDiscoveryGet:
    def test_wayf_redirect(self, client, init_ret):
        c, iface = client
        with mock.patch(
            "app.config.init_config.init_get_system_and_default_domain_settings",
            return_value=(
                {},
                {"AUTH_SETTINGS": {"SOGO_D_SAML2_DISCOVERY_SERVICE_URL": "https://wayf.example"}},
            ),
        ):
            resp = c.get("/auth/saml2/discovery")
        assert resp.status_code == 302
        assert resp.headers["Location"] == "https://wayf.example"

    def test_idp_list_from_metadata_and_db(self, client, sso, proc, init_ret):
        c, iface = client
        with mock.patch("app.module.auth.Saml2Metadata.Saml2Metadata") as sm, \
                mock.patch("app.module.auth.ModuleSaml2Provider.ModuleSaml2Provider") as mp:
            sm.return_value.get_federation_idps.return_value = [
                {"entity_id": "e1", "name": "IdP1", "sso_url": "u1", "logo_url": "l1"},
            ]
            mp.return_value.list_providers.return_value = [
                {"entity_id": "e1"},
                {"entity_id": "e2", "name": "IdP2", "sso_url": "u2"},
            ]
            resp = c.get("/auth/saml2/discovery")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["total"] == 2
        ids = [i["entity_id"] for i in data["idps"]]
        assert ids == ["e1", "e2"]

    def test_idp_metadata_error_continues(self, client, sso, proc, init_ret):
        c, iface = client
        with mock.patch("app.module.auth.Saml2Metadata.Saml2Metadata") as sm, \
                mock.patch("app.module.auth.ModuleSaml2Provider.ModuleSaml2Provider") as mp:
            sm.return_value.get_federation_idps.side_effect = RuntimeError("down")
            mp.return_value.list_providers.side_effect = RuntimeError("down too")
            resp = c.get("/auth/saml2/discovery")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["total"] == 0


class TestDiscoveryPost:
    def test_missing_entity_id(self, client, sso, init_ret, proc):
        c, iface = client
        resp = c.post("/auth/saml2/discovery", json={})
        assert resp.status_code == 412

    def test_provider_not_found(self, client, sso, init_ret, proc):
        c, iface = client
        with mock.patch("app.module.auth.ModuleSaml2Provider.ModuleSaml2Provider") as mp:
            mp.return_value.get_provider_by_entity_id.return_value = None
            resp = c.post("/auth/saml2/discovery", json={"entity_id": "eX"})
        assert resp.status_code == 404

    def test_discovery_success(self, client, sso, init_ret, proc):
        c, iface = client
        provider = {"entity_id": "e1", "sso_url": "http://idp/sso", "certificate": "CERT"}
        saml = mock.MagicMock()
        saml.create_login_request.return_value = "http://idp/sso?req=abc"
        with mock.patch("app.module.auth.ModuleSaml2Provider.ModuleSaml2Provider") as mp, \
                mock.patch("app.module.auth.ModuleSAML2.ModuleSAML2") as ms, \
                mock.patch("app.module.auth.Saml2Keypair.Saml2Keypair") as mk:
            mp.return_value.get_provider_by_entity_id.return_value = provider
            mk.return_value.load_keypair.return_value = ("SPCERT", "SPKEY")
            ms.return_value = saml
            resp = c.post("/auth/saml2/discovery",
                          json={"entity_id": "e1", "relay_state": "rs", "domain": ""})
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["redirect_url"] == "http://idp/sso?req=abc"
        ms.assert_called_once()
        kw = ms.call_args.kwargs
        assert kw["idp_sso_url"] == "http://idp/sso"
        assert kw["x509_cert"] == "SPCERT"

    def test_discovery_exception(self, client, sso, init_ret, proc):
        c, iface = client
        with mock.patch("app.module.auth.ModuleSaml2Provider.ModuleSaml2Provider",
                        side_effect=RuntimeError("kaboom")):
            resp = c.post("/auth/saml2/discovery", json={"entity_id": "e1"})
        assert resp.status_code == 401
        assert resp.get_json()["error_code"] == "S001211"


class TestLogout:
    def test_logout_with_token(self, client):
        c, iface = client
        iface.logout.return_value = {"data": {"logged_out": True}}
        resp = c.post("/auth/logout", headers={"Authorization": "Bearer vouch123"})
        assert resp.status_code == 200
        iface.logout.assert_called_once_with("vouch123")

    def test_logout_without_token_passes_empty(self, client):
        c, iface = client
        iface.logout.return_value = {"data": {}}
        resp = c.post("/auth/logout", content_type="application/json", json={})
        assert resp.status_code == 200
        assert iface.logout.call_args.args == ("",)


class TestCallbackPostMore:
    def test_post_domain_error_uses_default(self, client, sso, init_ret):
        c, iface = client
        sso.handle_callback.return_value = ({"data": {}, "error_code": ""}, 200)
        with mock.patch(
            "app.utils.module.importManager.import_and_instantiate_manager",
            side_effect=RuntimeError("db down"),
        ):
            resp = c.post("/auth/callback/example.org", data={"SAMLResponse": "x"})
        assert resp.status_code == 200
        domain_auth = sso.handle_callback.call_args.args[1]
        assert domain_auth.SOGO_D_AUTH_TYPE == "plain"


class TestMetadataMore:
    def test_metadata_domain_with_db_result(self, client, sso, proc, init_ret):
        c, iface = client
        saml = mock.MagicMock()
        saml.get_sp_metadata.return_value = "<xml/>"
        sso._build_saml.return_value = saml
        db = mock.MagicMock()
        db.select_from_table.return_value = [
            ({"AUTH_SETTINGS": {"SOGO_D_AUTH_TYPE": "saml2"}},),
        ]
        with mock.patch(
            "app.utils.module.importManager.import_and_instantiate_manager",
            return_value=db,
        ):
            resp = c.get("/auth/saml2/metadata/example.org")
        assert resp.status_code == 200
        domain_auth = sso._build_saml.call_args.args[0]
        assert domain_auth.SOGO_D_AUTH_TYPE == "saml2"


class TestSamlStartMore:
    def test_start_with_domain_db(self, client, sso, proc, init_ret):
        c, iface = client
        saml = mock.MagicMock()
        saml.create_login_request.return_value = "http://idp/req"
        sso._build_saml.return_value = saml
        db = mock.MagicMock()
        db.select_from_table.return_value = [
            ({"AUTH_SETTINGS": {"SOGO_D_AUTH_TYPE": "saml2"}},),
        ]
        with mock.patch(
            "app.utils.module.importManager.import_and_instantiate_manager",
            return_value=db,
        ):
            resp = c.get("/auth/saml2/start?domain=example.org")
        assert resp.status_code == 302
        domain_auth = sso._build_saml.call_args.args[0]
        assert domain_auth.SOGO_D_AUTH_TYPE == "saml2"


class TestAcsMore:
    def test_acs_raw_xml(self, client, sso, init_ret):
        c, iface = client
        sso.handle_callback.return_value = ({"data": {}, "error_code": ""}, 200)
        resp = c.post("/auth/saml2/acs?domain=example.org",
                      data="<samlp:Response/>",
                      content_type="application/xml")
        assert resp.status_code == 200
        params = sso.handle_callback.call_args.args[2]
        assert params["SAMLResponse"].startswith("<")

    def test_acs_urlencoded_raw(self, client, sso, init_ret):
        c, iface = client
        sso.handle_callback.return_value = ({"data": {}, "error_code": ""}, 200)
        resp = c.post("/auth/saml2/acs",
                      data="SAMLResponse=YWJj&RelayState=example.org",
                      content_type="text/plain")
        assert resp.status_code == 200
        assert sso.handle_callback.call_args.args[0] == "example.org"
        params = sso.handle_callback.call_args.args[2]
        assert params["SAMLResponse"] == "YWJj"

    def test_acs_domain_error_uses_default(self, client, sso, init_ret):
        c, iface = client
        sso.handle_callback.return_value = ({"data": {}, "error_code": ""}, 200)
        with mock.patch(
            "app.utils.module.importManager.import_and_instantiate_manager",
            side_effect=RuntimeError("down"),
        ):
            resp = c.post("/auth/saml2/acs?domain=example.org",
                          data={"SAMLResponse": "x"})
        assert resp.status_code == 200
        domain_auth = sso.handle_callback.call_args.args[1]
        assert domain_auth.SOGO_D_AUTH_TYPE == "plain"


class TestDiscoveryGetMore:
    def test_idp_federation_metadata(self, client, sso, proc):
        c, iface = client
        with mock.patch(
            "app.config.init_config.init_get_system_and_default_domain_settings",
            return_value=(
                {},
                {"AUTH_SETTINGS": {
                    "SOGO_D_SAML2_FEDERATION_METADATA_URL": "https://fed.example/meta",
                    "SOGO_D_SAML2_DISCOVERY_SERVICE_URL": "",
                }},
            ),
        ), mock.patch("app.module.auth.Saml2Metadata.Saml2Metadata") as sm, \
                mock.patch("app.module.auth.ModuleSaml2Provider.ModuleSaml2Provider") as mp:
            sm.return_value.get_federation_idps.return_value = [
                {"entity_id": "f1", "name": "Fed", "sso_url": "usso", "logo_url": "ul"},
            ]
            mp.return_value.list_providers.return_value = []
            resp = c.get("/auth/saml2/discovery")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["total"] == 1
        assert data["idps"][0]["name"] == "Fed"
        assert data["idps"][0]["logo_url"] == "ul"


class TestDiscoveryPostMore:
    def test_discovery_with_domain_settings(self, client, sso, proc, init_ret):
        c, iface = client
        db = mock.MagicMock()
        db.select_from_table.return_value = [
            ({"AUTH_SETTINGS": {"SOGO_D_AUTH_TYPE": "saml2",
                                "SOGO_D_SAML2_SP_ENTITY_ID": "urn:sp"}},),
        ]
        provider = {"entity_id": "e1", "sso_url": "http://idp/sso", "certificate": "C"}
        saml = mock.MagicMock()
        saml.create_login_request.return_value = "http://idp/sso?req=1"
        with mock.patch(
            "app.utils.module.importManager.import_and_instantiate_manager",
            return_value=db,
        ), mock.patch("app.module.auth.ModuleSaml2Provider.ModuleSaml2Provider") as mp, \
                mock.patch("app.module.auth.ModuleSAML2.ModuleSAML2") as ms, \
                mock.patch("app.module.auth.Saml2Keypair.Saml2Keypair") as mk:
            mp.return_value.get_provider_by_entity_id.return_value = provider
            mk.return_value.load_keypair.return_value = ("C", "K")
            ms.return_value = saml
            resp = c.post("/auth/saml2/discovery",
                          json={"entity_id": "e1", "domain": "example.org"})
        assert resp.status_code == 200
        assert ms.call_args.kwargs["entity_id"] == "urn:sp"
        assert ms.call_args.kwargs["idp_entity_id"] == "e1"


class TestCoverageClosure:
    def test_post_loads_domain_settings(self, client, sso, init_ret):
        c, iface = client
        sso.handle_callback.return_value = ({"data": {"ok": 1}, "error_code": ""}, 200)
        db = mock.MagicMock()
        db.select_from_table.return_value = [
            ({"AUTH_SETTINGS": {"SOGO_D_AUTH_TYPE": "saml2"}},),
        ]
        with mock.patch(
            "app.utils.module.importManager.import_and_instantiate_manager",
            return_value=db,
        ):
            resp = c.post("/auth/callback/example.org", data={"SAMLResponse": "x"})
        assert resp.status_code == 200
        domain_auth = sso.handle_callback.call_args.args[1]
        assert domain_auth.SOGO_D_AUTH_TYPE == "saml2"

    def test_metadata_domain_error(self, client, sso, init_ret):
        c, iface = client
        sso._build_saml.side_effect = RuntimeError("no")
        resp = c.get("/auth/saml2/metadata/example.org")
        assert resp.status_code == 412
        assert resp.get_json()["error_code"] == "S001210"

    def test_acs_loads_domain_settings(self, client, sso, init_ret):
        c, iface = client
        sso.handle_callback.return_value = ({"data": {}, "error_code": ""}, 200)
        db = mock.MagicMock()
        db.select_from_table.return_value = [
            ({"AUTH_SETTINGS": {"SOGO_D_AUTH_TYPE": "saml2"}},),
        ]
        with mock.patch(
            "app.utils.module.importManager.import_and_instantiate_manager",
            return_value=db,
        ):
            resp = c.post("/auth/saml2/acs?domain=example.org",
                          data={"SAMLResponse": "x"})
        assert resp.status_code == 200
        domain_auth = sso.handle_callback.call_args.args[1]
        assert domain_auth.SOGO_D_AUTH_TYPE == "saml2"

    def test_discovery_federation_error_continues(self, client, sso, proc):
        c, iface = client
        with mock.patch(
            "app.config.init_config.init_get_system_and_default_domain_settings",
            return_value=(
                {},
                {"AUTH_SETTINGS": {
                    "SOGO_D_SAML2_FEDERATION_METADATA_URL": "https://fed.example/meta",
                    "SOGO_D_SAML2_DISCOVERY_SERVICE_URL": "",
                }},
            ),
        ), mock.patch("app.module.auth.Saml2Metadata.Saml2Metadata") as sm, \
                mock.patch("app.module.auth.ModuleSaml2Provider.ModuleSaml2Provider") as mp:
            sm.return_value.get_federation_idps.side_effect = RuntimeError("fed down")
            mp.return_value.list_providers.return_value = [
                {"entity_id": "e1", "name": "IdP1", "sso_url": "u1"},
            ]
            resp = c.get("/auth/saml2/discovery")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["total"] == 1
        assert data["idps"][0]["entity_id"] == "e1"

    def test_discovery_post_domain_error(self, client, sso, proc, init_ret):
        c, iface = client
        with mock.patch(
            "app.utils.module.importManager.import_and_instantiate_manager",
            side_effect=RuntimeError("db down"),
        ), mock.patch("app.module.auth.ModuleSaml2Provider.ModuleSaml2Provider") as mp,                 mock.patch("app.module.auth.Saml2Keypair.Saml2Keypair",
                           side_effect=RuntimeError("no key")) as mk:
            mp.return_value.get_provider_by_entity_id.return_value = {
                "entity_id": "e1", "sso_url": "http://idp/sso", "certificate": "C",
            }
            resp = c.post("/auth/saml2/discovery",
                          json={"entity_id": "e1", "domain": "example.org"})
        assert resp.status_code == 401
        mk.assert_called_once()
