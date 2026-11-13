"""Facade consistency: manifest == registered routes, action budget, uniqueness."""
import re

import pytest
from flask import Flask

from app.api.v1.agent import ACTIONS
from app.api.v1.agent import (
    agent_ai_blp,
    agent_calendar_blp,
    agent_contacts_blp,
    agent_mail_blp,
    agent_manifest_blp,
)


@pytest.fixture(scope="module")
def routes():
    """Normalized (method, path) pairs of all registered agent facade routes."""
    app = Flask("agent-facade-test")
    for blp in (agent_manifest_blp, agent_mail_blp, agent_calendar_blp, agent_contacts_blp, agent_ai_blp):
        app.register_blueprint(blp)
    found = set()
    for rule in app.url_map.iter_rules():
        path = rule.rule
        if path.startswith("/static"):  # Flask default rule
            continue
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            found.add((method, _normalize(f"/api/user/v1{path}")))
    return found


_PARAM = re.compile(r"<[^>]+>|\{[^}]+\}")


def _normalize(path: str) -> str:
    """Collapse path params: '<int:mail_uid>' and '{uid}' both → '{}'."""
    return _PARAM.sub("{}", path)


class TestManifestMatchesRoutes:
    def test_every_manifest_action_has_a_route(self, routes):
        for action in ACTIONS:
            expected = (_to_method(action["method"]), _normalize(action["path"]))
            assert expected in routes, f"manifest action {action['id']} has no route {expected}"

    def test_every_route_is_in_the_manifest(self, routes):
        manifest = {(_to_method(a["method"]), _normalize(a["path"])) for a in ACTIONS}
        for method, path in routes:
            assert (method, path) in manifest, f"route {method} {path} missing from manifest"

    def test_action_count_within_budget(self):
        assert len(ACTIONS) <= 30, "spec cap: facade must not exceed 30 actions"

    def test_manifest_paths_unique(self):
        seen = set()
        for action in ACTIONS:
            key = (action["method"], action["path"])
            assert key not in seen, f"duplicate action {key}"
            seen.add(key)

    def test_module_registration_complete(self):
        """Importing the agent package registers all five facade modules."""
        import importlib

        module = importlib.import_module("app.api.v1.agent")
        for name in ("agent_mail_blp", "agent_calendar_blp", "agent_contacts_blp", "agent_ai_blp", "agent_manifest_blp"):
            assert hasattr(module, name), f"missing blueprint export {name}"


class TestOpenAPISurface:
    """Agent facade appears in the OpenAPI document with full schemas."""

    def _spec(self) -> dict:
        from flask_smorest import Api

        app = Flask("agent-openapi-test")
        app.config["BASIC_OPENAPI_URL_PREFIX"] = "/openapi-basic"
        app.config["BASIC_API_TITLE"] = "Agent facade test"
        app.config["BASIC_API_VERSION"] = "v1"
        app.config["BASIC_OPENAPI_VERSION"] = "3.0.3"
        api = Api(app, config_prefix="BASIC_")
        for blp in (agent_manifest_blp, agent_mail_blp, agent_calendar_blp, agent_contacts_blp, agent_ai_blp):
            api.register_blueprint(blp)
        return api.spec.to_dict()

    def test_agent_paths_present(self):
        paths = self._spec()["paths"]
        for expected in (
            "/agent/mail/messages",
            "/agent/mail/send",
            "/agent/calendar/events",
            "/agent/contacts/search",
            "/agent/ai/nl-search",
            "/agent/manifest",
        ):
            assert expected in paths, f"{expected} missing from OpenAPI"

    def test_agent_send_has_request_schema(self):
        spec = self._spec()
        send = spec["paths"]["/agent/mail/send"]["post"]
        body = send.get("requestBody", {}).get("content", {}).get("application/json", {})
        assert body, "send endpoint must document its request body"
        ref = body.get("schema", {}).get("$ref", "")
        assert "AgentMailSend" in ref or "Schema" in ref, ref
        components = spec.get("components", {}).get("schemas", {})
        if "AgentMailSend" in ref.split("/")[-1]:
            assert "attachments" in components["AgentMailSend"]["properties"], "inline attachments must be documented"

    def test_agent_tag_present(self):
        spec = self._spec()
        agent_paths = [p for p in spec["paths"] if p.startswith("/agent/")]
        assert len(agent_paths) >= 20, f"expected >=20 agent paths, got {len(agent_paths)}"
        operations = sum(
            1
            for p, ops in spec["paths"].items()
            if p.startswith("/agent/")
            for m in ("get", "post", "patch", "delete", "put")
            if m in ops
        )
        assert operations >= 26, f"expected >=26 agent operations, got {operations}"


def _to_method(name: str) -> str:
    return {"GET": "GET", "POST": "POST", "PATCH": "PATCH", "DELETE": "DELETE", "PUT": "PUT"}[name.upper()]
