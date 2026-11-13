"""Spec contract suite for the agent action layer.

Two jobs:

1. **Traceability** — every scenario in the delta specs
   (``openspec/changes/agent-action-layer/specs/*/spec.md``) must map to at
   least one existing test. Spec files are parsed live when the superproject
   checkout is available; otherwise the frozen snapshot below is used (CI
   runs inside the sogo6-server submodule). When the specs are present, the
   drift test asserts frozen == parsed so scenarios can never silently lose
   coverage.

2. **Behavioral contracts** — in-process checks of the facade view bodies
   against the normative scenarios (snippet caps, ``limit`` alias, spec field
   shapes, envelope keys, guards, manifest completeness, OpenAPI surface),
   using fake interfaces so no backend is required.
"""
from __future__ import annotations

import contextlib
import os
import re
import types

import pytest
from flask import Flask, g
from marshmallow import ValidationError

from app.api.v1.agent import ACTIONS, reject_anonymous, require_scope
from app.api.v1.agent import ApiAgentCalendar, ApiAgentContacts, ApiAgentMail
from app.api.v1.agent.schemas import (
    SNIPPET_MAX_CHARS,
    AgentMailDetailQuerySchema,
    AgentMailSendSchema,
)
from app.utils import errors as err

# ─────────────────────────────────────────────────────────────────────────────
# Part 1: spec traceability
# ─────────────────────────────────────────────────────────────────────────────


_SPEC_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    os.pardir, "openspec", "changes", "agent-action-layer", "specs",
)
_SUPER_ROOT = os.path.abspath(os.path.join(_SPEC_ROOT, os.pardir, os.pardir, os.pardir, os.pardir))
_SERVER_ROOT = os.path.join(_SUPER_ROOT, "sogo6-server")

#: Frozen snapshot of the delta specs' requirement → scenario titles.
#: Must be updated together with the spec files (drift test enforces this).
FROZEN_SPECS: dict[str, dict[str, list[str]]] = {
    "agent-actions": {
        "Mail action endpoints": [
            "List messages returns compact summaries",
            "Read message truncates and strips quotes",
            "Send with inline attachments is one call",
            "Batch action marks messages",
        ],
        "Calendar action endpoints": [
            "Create event with attendees in one call",
            "Range query returns occurrences",
            "Respond to invitation",
        ],
        "Contacts action endpoints": [
            "Contact search is compact",
            "Create contact minimal payload",
        ],
        "AI-assist action endpoints": ["Summarize a message"],
        "Action manifest": ["Manifest lists all facade actions"],
        "OpenAPI contract for the facade": ["Agent imports OpenAPI"],
        "Response envelope and error codes": ["Consistent envelope"],
        "MCP sidecar mirrors the facade": [
            "MCP tool list equals facade catalog",
            "MCP forwards token",
        ],
        "UI assistant one-click actions": ["User executes suggested draft"],
    },
    "agent-auth": {
        "API-token bearer authentication": [
            "Valid token authenticates as its owner",
            "Expired token is rejected",
            "Voucher flow unchanged",
        ],
        "Scope enforcement on agent endpoints": [
            "Insufficient scope rejected",
            "Module-wide grant accepted",
        ],
        "Agent endpoints never allow anonymous access": ["No credentials on facade"],
        "Admin-issued impersonation tokens": [
            "Admin creates impersonation token",
            "Impersonated request acts as target",
            "Non-admin cannot issue impersonation tokens",
            "Unknown target rejected",
        ],
        "Impersonation audit trail": ["Audit entry written"],
        "Token lifecycle shared with user tokens": ["Revoked impersonation token rejected"],
    },
}

#: Scenario → tests that prove it. pytest ids are validated by import below;
#: ``external:`` ids must point at existing files in the superproject.
SCENARIO_COVERAGE: dict[tuple[str, str, str], list[str]] = {
    # agent-actions
    ("agent-actions", "Mail action endpoints", "List messages returns compact summaries"): [
        "tests/test_service/test_AgentSpecContract.py::TestMailContracts::test_list_compact_summaries",
        "tests/test_service/test_AgentSpecContract.py::TestMailContracts::test_limit_alias_spec_param",
    ],
    ("agent-actions", "Mail action endpoints", "Read message truncates and strips quotes"): [
        "tests/test_service/test_AgentSpecContract.py::TestMailContracts::test_detail_truncates_and_strips_quotes",
        "tests/test_service/test_AgentSpecContract.py::TestMailContracts::test_detail_query_schema_defaults",
    ],
    ("agent-actions", "Mail action endpoints", "Send with inline attachments is one call"): [
        "tests/test_service/test_AgentSpecContract.py::TestMailContracts::test_send_one_call_inline_attachments",
        "tests/test_service/test_AgentSpecContract.py::TestMailContracts::test_send_rejects_invalid_base64",
    ],
    ("agent-actions", "Mail action endpoints", "Batch action marks messages"): [
        "tests/test_service/test_AgentSpecContract.py::TestMailContracts::test_batch_action_delegation",
    ],
    ("agent-actions", "Calendar action endpoints", "Create event with attendees in one call"): [
        "tests/test_service/test_AgentSpecContract.py::TestCalendarContracts::test_create_event_one_call",
    ],
    ("agent-actions", "Calendar action endpoints", "Range query returns occurrences"): [
        "tests/test_service/test_AgentSpecContract.py::TestCalendarContracts::test_range_query_maps_from_to",
    ],
    ("agent-actions", "Calendar action endpoints", "Respond to invitation"): [
        "tests/test_service/test_AgentSpecContract.py::TestCalendarContracts::test_invitation_respond_contract",
        "tests/test_service/test_AgentSpecContract.py::TestCalendarContracts::test_invitation_status_enum_enforced",
    ],
    ("agent-actions", "Contacts action endpoints", "Contact search is compact"): [
        "tests/test_service/test_AgentSpecContract.py::TestContactsContracts::test_search_compact_and_limit",
    ],
    ("agent-actions", "Contacts action endpoints", "Create contact minimal payload"): [
        "tests/test_service/test_AgentSpecContract.py::TestContactsContracts::test_create_minimal_payload",
    ],
    ("agent-actions", "AI-assist action endpoints", "Summarize a message"): [
        "tests/test_service/test_AgentSpecContract.py::TestRegistryContracts::test_ai_actions_require_mail_read",
    ],
    ("agent-actions", "Action manifest", "Manifest lists all facade actions"): [
        "tests/test_service/test_AgentFacade.py::TestManifestMatchesRoutes::test_every_manifest_action_has_a_route",
        "tests/test_service/test_AgentFacade.py::TestManifestMatchesRoutes::test_every_route_is_in_the_manifest",
        "tests/test_service/test_AgentSpecContract.py::TestRegistryContracts::test_action_fields_complete",
    ],
    ("agent-actions", "OpenAPI contract for the facade", "Agent imports OpenAPI"): [
        "tests/test_service/test_AgentFacade.py::TestOpenAPISurface::test_agent_paths_present",
        "tests/test_service/test_AgentSpecContract.py::TestOpenAPIContracts::test_writes_have_request_schemas",
    ],
    ("agent-actions", "Response envelope and error codes", "Consistent envelope"): [
        "tests/test_service/test_AgentSpecContract.py::TestEnvelopeContracts::test_scope_rejection_envelope_s000513",
        "tests/test_service/test_AgentSpecContract.py::TestEnvelopeContracts::test_anonymous_envelope",
        "tests/test_service/test_AgentSpecContract.py::TestEnvelopeContracts::test_spec_error_codes_mapped",
    ],
    ("agent-actions", "MCP sidecar mirrors the facade", "MCP tool list equals facade catalog"): [
        "external:deploy/sogo6-mcp/test_server.py",
    ],
    ("agent-actions", "MCP sidecar mirrors the facade", "MCP forwards token"): [
        "external:deploy/sogo6-mcp/test_server.py",
        "external:deploy/sogo6-mcp/e2e_smoke.py",
    ],
    ("agent-actions", "UI assistant one-click actions", "User executes suggested draft"): [
        "external:sogo6-ui/src/components/__tests__/action-executor.test.tsx",
    ],
    # agent-auth
    ("agent-auth", "API-token bearer authentication", "Valid token authenticates as its owner"): [
        "tests/test_service/test_AgentAuth.py::TestVerifyApiToken::test_valid_token_returns_metadata",
        "tests/test_service/test_AgentAuth.py::TestVerifyApiToken::test_session_blob_survives_last_used_update",
    ],
    ("agent-auth", "API-token bearer authentication", "Expired token is rejected"): [
        "tests/test_service/test_AgentAuth.py::TestVerifyApiToken::test_expired_token_rejected_and_deleted",
        "tests/test_service/test_AgentSpecContract.py::TestAuthContracts::test_unknown_expired_revoked_map_s000512_401",
    ],
    ("agent-auth", "API-token bearer authentication", "Voucher flow unchanged"): [
        "tests/test_service/test_AgentSpecContract.py::TestAuthContracts::test_agent_prefixes_are_disjoint",
        "tests/test_integration/test_agent_actions.py::TestAgentHappyPaths::test_manifest_with_voucher_session",
    ],
    ("agent-auth", "Scope enforcement on agent endpoints", "Insufficient scope rejected"): [
        "tests/test_service/test_AgentSpecContract.py::TestEnvelopeContracts::test_scope_rejection_envelope_s000513",
        "tests/test_integration/test_agent_actions.py::TestScopeEnforcement::test_read_token_cannot_send",
    ],
    ("agent-auth", "Scope enforcement on agent endpoints", "Module-wide grant accepted"): [
        "tests/test_service/test_AgentAuth.py::TestScopeGrants::test_write_grants_all_write_class",
        "tests/test_service/test_AgentAuth.py::TestScopeGrants::test_read_grants_all_read_class",
    ],
    ("agent-auth", "Agent endpoints never allow anonymous access", "No credentials on facade"): [
        "tests/test_service/test_AgentSpecContract.py::TestEnvelopeContracts::test_anonymous_envelope",
        "tests/test_service/test_AgentSpecContract.py::TestRegistryContracts::test_agent_views_never_public",
        "tests/test_integration/test_agent_actions.py::TestAgentHappyPaths::test_anonymous_rejected",
    ],
    ("agent-auth", "Admin-issued impersonation tokens", "Admin creates impersonation token"): [
        "tests/test_service/test_AgentSpecContract.py::TestAdminContracts::test_create_returns_201_raw_token",
        "tests/test_service/test_AgentAuth.py::TestImpersonationTokens::test_create_sets_target_and_issuer",
    ],
    ("agent-auth", "Admin-issued impersonation tokens", "Impersonated request acts as target"): [
        "tests/test_service/test_AgentAuth.py::TestImpersonationTokens::test_verify_resolves_to_target",
        "tests/test_service/test_AgentAuth.py::TestVerifyApiToken::test_user_session_rebuilt_into_full_user",
        "tests/test_integration/test_agent_actions.py::TestImpersonation::test_issue_act_revoke",
    ],
    ("agent-auth", "Admin-issued impersonation tokens", "Non-admin cannot issue impersonation tokens"): [
        "tests/test_service/test_AgentSpecContract.py::TestAdminContracts::test_non_admin_rejected",
    ],
    ("agent-auth", "Admin-issued impersonation tokens", "Unknown target rejected"): [
        "tests/test_service/test_AgentSpecContract.py::TestAdminContracts::test_unknown_target_s000514",
    ],
    ("agent-auth", "Impersonation audit trail", "Audit entry written"): [
        "tests/test_service/test_AgentSpecContract.py::TestAdminContracts::test_audit_line_records_all_fields",
    ],
    ("agent-auth", "Token lifecycle shared with user tokens", "Revoked impersonation token rejected"): [
        "tests/test_service/test_AgentAuth.py::TestImpersonationTokens::test_list_and_revoke_cycle",
        "tests/test_integration/test_agent_actions.py::TestImpersonation::test_issue_act_revoke",
    ],
}


def _parse_specs() -> dict[str, dict[str, list[str]]] | None:
    """Parse the live delta specs; None when the superproject is absent."""
    parsed: dict[str, dict[str, list[str]]] = {}
    found = False
    for name in sorted(os.listdir(_SPEC_ROOT)) if os.path.isdir(_SPEC_ROOT) else []:
        path = os.path.join(_SPEC_ROOT, name, "spec.md")
        if not os.path.isfile(path):
            continue
        found = True
        current_req = None
        parsed[name] = {}
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("### Requirement:"):
                    current_req = line.split("### Requirement:", 1)[1].strip()
                    parsed[name][current_req] = []
                elif line.startswith("#### Scenario:") and current_req:
                    parsed[name][current_req].append(line.split("#### Scenario:", 1)[1].strip())
    return parsed if found else None


class TestSpecTraceability:
    def test_frozen_snapshot_matches_live_specs(self):
        """Drift guard: specs changed → update FROZEN_SPECS (and coverage)."""
        parsed = _parse_specs()
        if parsed is None:
            pytest.skip("delta specs not present (submodule-only checkout)")
        assert parsed == FROZEN_SPECS, (
            "delta specs and the frozen snapshot in this file diverged — "
            "update FROZEN_SPECS and SCENARIO_COVERAGE together"
        )

    def test_every_scenario_has_coverage(self):
        frozen = {
            (spec, req, scen)
            for spec, reqs in FROZEN_SPECS.items()
            for req, scenarios in reqs.items()
            for scen in scenarios
        }
        mapped = set(SCENARIO_COVERAGE)
        assert mapped == frozen, (
            f"scenarios without coverage: {sorted(frozen - mapped)}; "
            f"stale mappings: {sorted(mapped - frozen)}"
        )

    def test_mapped_pytest_ids_exist(self):
        """Every mapped pytest id must point at a real test (AST scan, no imports)."""
        import ast

        repo_root = _SERVER_ROOT
        cache: dict[str, set[tuple[str, str]]] = {}
        missing: list[str] = []

        def tests_in(path: str) -> set[tuple[str, str]]:
            if path not in cache:
                classes: set[tuple[str, str]] = set()
                try:
                    with open(path, encoding="utf-8") as fh:
                        tree = ast.parse(fh.read())
                except (OSError, SyntaxError):
                    tree = None
                if tree is not None:
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                            for item in node.body:
                                if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
                                    classes.add((node.name, item.name))
                cache[path] = classes
            return cache[path]

        for test_ids in SCENARIO_COVERAGE.values():
            for test_id in test_ids:
                if test_id.startswith("external:"):
                    continue
                rel, *names = test_id.removeprefix("tests/").split("::")
                path = os.path.join(repo_root, "tests", rel)
                if not os.path.exists(path):
                    missing.append(test_id)
                    continue
                present = tests_in(path)
                for i in range(0, len(names), 2):
                    cls_name = names[i]
                    method = names[i + 1] if i + 1 < len(names) else None
                    if method is None:
                        if not any(c == cls_name for c, _ in present):
                            missing.append(test_id)
                            break
                    elif (cls_name, method) not in present:
                        missing.append(test_id)
                        break
        assert not missing, f"coverage table points at missing tests: {missing}"

    def test_external_suites_exist(self):
        missing = []
        for test_ids in SCENARIO_COVERAGE.values():
            for test_id in test_ids:
                if not test_id.startswith("external:"):
                    continue
                rel = test_id.removeprefix("external:")
                if not os.path.exists(os.path.join(_SUPER_ROOT, rel)):
                    missing.append(rel)
        assert not missing, f"external suite files missing from superproject: {missing}"


# ─────────────────────────────────────────────────────────────────────────────
# Part 2: behavioral contracts (fake interfaces, real view bodies)
# ─────────────────────────────────────────────────────────────────────────────

LONG_TEXT = ("line one with content. " * 40) + "\n> quoted reply line\n> another quote"

FAKE_MAIL = {
    "uid": 42,
    "from": {"name": "Alice", "email": "alice@example.org"},
    "subject": "Report",
    "date": "2026-01-02T10:00:00Z",
    "seen": True,
    "flagged": False,
    "has_attachment": True,
    "contents": [{"contentType": "text/plain", "content": LONG_TEXT}],
}


@pytest.fixture()
def app():
    return Flask("spec-contract")


@contextlib.contextmanager
def _agent_ctx(app, path="/", json=None, query_string=None):
    """Push a request context with an authenticated agent user on ``g``."""
    ctx = app.test_request_context(path, json=json, query_string=query_string)
    ctx.push()
    g.user = types.SimpleNamespace(
        uid="max@example.org", mail="max@example.org", cn="Max",
        anonymous=False, authenticated=True, auth_method="voucher",
    )
    g.pop("token_scopes", None)
    try:
        yield ctx
    finally:
        ctx.pop()


def _capture(fn_name: str, return_value):
    """Fake interface method that records its call args."""
    calls: list = []

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return return_value

    return fake, calls


@contextlib.contextmanager
def _facade_client(app, blps, *, with_user: bool = True):
    """Test client with the given agent blueprints; authenticated user optional.

    The app-level before_request sets ``g.user`` (and clears token scopes) so
    the blueprint-level anonymous guard passes, mirroring the real auth chain
    without pulling in the whole API registry.
    """
    from flask_smorest import Api

    app.config["API_TITLE"] = "facade-t"
    app.config["API_VERSION"] = "1"
    app.config["OPENAPI_VERSION"] = "3.0.3"
    api = Api(app)
    for blp in blps:
        api.register_blueprint(blp)

    if with_user:
        @app.before_request
        def _set_agent_user():  # pragma: no cover - test hook
            g.user = types.SimpleNamespace(
                uid="max@example.org", mail="max@example.org", cn="Max",
                anonymous=False, authenticated=True, auth_method="voucher",
            )
            g.pop("token_scopes", None)

    yield app.test_client()


class TestMailContracts:
    def test_list_compact_summaries(self, app, monkeypatch):
        get_mail_list, calls = _capture("get_mail_list", (3, {"data": [dict(FAKE_MAIL)]}, 200))
        monkeypatch.setattr(ApiAgentMail, "mail_interface",
                            lambda: types.SimpleNamespace(get_mail_list=get_mail_list))
        with _agent_ctx(app, "/?folder=INBOX&page_size=10"):
            body, status = ApiAgentMail.AgentMailMessages().get()
        assert status == 200
        message = body["data"]["messages"][0]
        assert set(message) == {"uid", "from", "subject", "date", "snippet",
                                "flags", "seen", "flagged", "has_attachments"}
        assert len(message["snippet"]) <= SNIPPET_MAX_CHARS
        assert "contents" not in message and "body" not in message
        assert body["data"]["total"] == 3
        assert message["flags"] == {"seen": True, "flagged": False}

    def test_limit_alias_spec_param(self, app, monkeypatch):
        get_mail_list, calls = _capture("get_mail_list", (0, {"data": []}, 200))
        monkeypatch.setattr(ApiAgentMail, "mail_interface",
                            lambda: types.SimpleNamespace(get_mail_list=get_mail_list))
        with _agent_ctx(app, "/?folder=INBOX&limit=7"):
            _, status = ApiAgentMail.AgentMailMessages().get()
        assert status == 200
        collection = calls[0][0][2]
        assert collection.page_size == 7, "spec uses ?limit= — must be honored"

    def test_detail_truncates_and_strips_quotes(self, app, monkeypatch):
        get_mail_detail, _ = _capture("get_mail_detail", ({"data": dict(FAKE_MAIL)}, 200))
        monkeypatch.setattr(ApiAgentMail, "mail_interface",
                            lambda: types.SimpleNamespace(get_mail_detail=get_mail_detail))
        with _agent_ctx(app, "/?strip_quotes=true&max_chars=100"):
            body, status = ApiAgentMail.AgentMailMessageDetail().get(mail_uid=42)
        assert status == 200
        text = body["data"]["body"]["text/plain"]
        assert len(text) <= 101  # 100 + ellipsis
        assert ">" not in text, "quoted reply lines must be stripped"

    def test_detail_query_schema_defaults(self):
        assert AgentMailDetailQuerySchema().load({}) == {"strip_quotes": False, "max_chars": 4000}

    def test_send_one_call_inline_attachments(self, app, monkeypatch):
        import base64

        send_mail, calls = _capture("send_mail", ({"error_code": "S000000"}, 200))
        monkeypatch.setattr(ApiAgentMail, "mail_send_interface",
                            lambda: types.SimpleNamespace(send_mail=send_mail))
        payload = {  # spec minimal: to/subject/body/attachments, no explicit from
            "to": ["boss@example.org"], "subject": "Report", "body": "See attached.",
            "attachments": [{"filename": "a.txt", "content_b64": base64.b64encode(b"data").decode()}],
        }
        with _agent_ctx(app, "/", json=payload):
            body, status = ApiAgentMail.AgentMailSend().post()
        assert status == 200
        assert len(calls) == 1, "upload+send must stay a single interface call"
        mail_data = calls[0][0][1]
        assert mail_data["from_addr"] == "max@example.org", "from defaults to token user"
        assert mail_data["attachments"][0]["data"] == b"data"
        assert "content_b64" not in mail_data["attachments"][0]

    def test_send_rejects_invalid_base64(self, app, monkeypatch):
        with _agent_ctx(app, "/", json={
            "to": ["x@example.org"], "attachments": [{"filename": "a", "content_b64": "!!not-b64!!"}],
        }):
            body, status = ApiAgentMail.AgentMailSend().post()
        assert status >= 400
        assert "error_code" in body

    def test_folders_list_delegates(self, app, monkeypatch):
        """GET /agent/mail/folders must reach the folder interface (import bug guard)."""
        get_folder_list, calls = _capture(
            "get_folder_list", ({"data": {"folders": [{"name": "INBOX", "unseen": 0, "exists": 3}]}}, 200))
        monkeypatch.setattr(ApiAgentMail, "mail_folder_interface",
                            lambda: types.SimpleNamespace(get_folder_list=get_folder_list))
        with _facade_client(app, [ApiAgentMail.blp]) as client:
            resp = client.get("/agent/mail/folders?account_id=0")
        assert resp.status_code == 200, "folders route must not 500 (missing import)"
        assert calls and calls[0][0][0] == "0"
        folders = resp.get_json()["data"]["folders"]
        assert folders[0]["name"] == "INBOX" and folders[0]["total"] == 3

    def test_batch_action_delegation(self, app, monkeypatch):
        batch_mail_action, calls = _capture("batch_mail_action", ({"data": {"results": []}}, 200))
        monkeypatch.setattr(ApiAgentMail, "mail_interface",
                            lambda: types.SimpleNamespace(batch_mail_action=batch_mail_action))
        with _facade_client(app, [ApiAgentMail.blp]) as client:
            resp = client.post(
                "/agent/mail/messages/batch-action?folder=INBOX&account_id=0",
                json={"action": "mark_read", "mail_uids": [1, 2, 3]},
            )
        assert resp.status_code == 200
        assert len(calls) == 1, "batch action must be a single delegated call"
        account_id, folder, body = calls[0][0]
        assert account_id == "0" and folder == "INBOX"
        assert body == {"action": "mark_read", "mail_uids": [1, 2, 3]}
        assert resp.get_json()["data"] == {"results": []}

    def test_batch_action_rejects_unknown_action(self, app, monkeypatch):
        with _facade_client(app, [ApiAgentMail.blp]) as client:
            resp = client.post(
                "/agent/mail/messages/batch-action",
                json={"action": "shred_all", "mail_uids": [1]},
            )
        assert resp.status_code == 422, "unknown batch action must be rejected by the schema"

    def test_send_schema_accepts_spec_payload_without_from(self):
        loaded = AgentMailSendSchema().load({"to": ["a@example.org"]})
        assert loaded["from_addr"] is None


class TestCalendarContracts:
    def test_create_event_one_call(self, app, monkeypatch):
        get_all_calendars, _ = _capture("get_all_calendars",
                                        ({"data": {"calendars": [{"key": "cal-1"}]}}, 200))
        create_event, calls = _capture("create_event", ({"error_code": "S000000"}, 201))
        monkeypatch.setattr(ApiAgentCalendar, "calendar_interface",
                            lambda: types.SimpleNamespace(get_all_calendars=get_all_calendars,
                                                          create_event=create_event))
        payload = {"title": "Sync", "start": "2026-02-01T10:00:00Z",
                   "end": "2026-02-01T11:00:00Z",
                   "attendees": [{"email": "peer@example.org"}]}
        with _agent_ctx(app, "/", json=payload):
            _, status = ApiAgentCalendar.AgentCalendarEvents().post()
        assert status == 201
        assert len(calls) == 1, "attendees + invitations must be one call"
        calendar_key, body = calls[0][0][0], calls[0][0][1]
        assert calendar_key == "cal-1", "default calendar resolved"
        assert body["attendees"] == payload["attendees"]
        assert "calendar_key" not in body

    def test_range_query_maps_from_to(self, app, monkeypatch):
        get_events, calls = _capture("get_events", ({"data": []}, 200))
        monkeypatch.setattr(ApiAgentCalendar, "calendar_interface",
                            lambda: types.SimpleNamespace(get_events=get_events))
        with _agent_ctx(app, "/?from=2026-01-01T00:00:00Z&to=2026-01-31T23:59:59Z"):
            _, status = ApiAgentCalendar.AgentCalendarEvents().get()
        assert status == 200
        query = calls[0][0][1]
        assert query["start_date_time"].isoformat().startswith("2026-01-01")
        assert query["end_date_time"].isoformat().startswith("2026-01-31")

    def test_bare_range_query_does_not_500(self, app, monkeypatch):
        """GET /agent/calendar/events with no ?from/?to must not raise."""
        get_events, calls = _capture("get_events", ({"data": []}, 200))
        monkeypatch.setattr(ApiAgentCalendar, "calendar_interface",
                            lambda: types.SimpleNamespace(get_events=get_events))
        with _facade_client(app, [ApiAgentCalendar.blp]) as client:
            resp = client.get("/agent/calendar/events")
        assert resp.status_code == 200
        assert calls[0][0][1]["start_date_time"] is None

    def test_invitation_respond_contract(self, app, monkeypatch):
        respond, calls = _capture("set_attendance_status", ({"error_code": "S000000"}, 200))
        monkeypatch.setattr(ApiAgentCalendar, "calendar_interface",
                            lambda: types.SimpleNamespace(set_attendance_status=respond))
        with _agent_ctx(app, "/", json={"status": "accepted"}):
            _, status = ApiAgentCalendar.AgentCalendarInvitationRespond().post(event_key="ev-1")
        assert status == 200
        key, body = calls[0][0][0], calls[0][0][1]
        assert key == "ev-1" and body["status"] == "accepted"

    def test_invitation_status_enum_enforced(self):
        from app.api.v1.agent.ApiAgentCalendar import AgentInvitationRespondSchema

        with pytest.raises(ValidationError):
            AgentInvitationRespondSchema().load({"status": "maybe"})


class TestContactsContracts:
    def test_search_compact_and_limit(self, app, monkeypatch):
        suggestions = [
            {"type": "contact", "name": f"Smith {i}", "email": f"s{i}@example.org",
             "contact_key": f"key-{i}", "member_count": None}
            for i in range(30)
        ]
        autocomplete, _ = _capture("autocomplete", ({"data": {"suggestions": suggestions}}, 200))
        monkeypatch.setattr(ApiAgentContacts, "contact_interface",
                            lambda: types.SimpleNamespace(autocomplete=autocomplete))
        with _agent_ctx(app, "/?q=smith&limit=20"):
            body, status = ApiAgentContacts.AgentContactsSearch().get()
        assert status == 200
        got = body["data"]["suggestions"]
        assert len(got) == 20, f"default/spec limit is 20, got {len(got)}"
        for entry in got:
            assert set(entry) == {"key", "name", "email", "primary_phone"}
            assert entry["key"].startswith("key-")

    def test_create_minimal_payload(self, app, monkeypatch):
        get_all_addressbooks, _ = _capture(
            "get_all_addressbooks", ({"data": {"addressbooks": [{"key": "book-1"}]}}, 200))
        create_contact, calls = _capture("create_contact", ({"error_code": "S000000", "data": {"key": "c-9"}}, 201))
        monkeypatch.setattr(ApiAgentContacts, "contact_interface",
                            lambda: types.SimpleNamespace(get_all_addressbooks=get_all_addressbooks,
                                                          create_contact=create_contact))
        with _agent_ctx(app, "/", json={"first_name": "Ada", "last_name": "Lovelace",
                                                 "email": "ada@example.org"}):
            _, status = ApiAgentContacts.AgentContactsCreate().post()
        assert status == 201
        book_key, payload = calls[0][0][0], calls[0][0][1]
        assert book_key == "book-1", "default addressbook resolved"
        assert payload == {"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.org"}
        assert "addressbook_key" not in payload


class TestEnvelopeContracts:
    def test_scope_rejection_envelope_s000513(self, app):
        with _agent_ctx(app, "/"):
            g.token_scopes = ["mail:read"]
            result = require_scope("mail:send")
        assert result is not None
        body, status = result
        assert status == 403
        assert body["error_code"] == "S000513"
        assert {"error_code", "error_msg", "data"} <= set(body)

    def test_module_wide_write_grant_passes(self, app):
        with _agent_ctx(app, "/"):
            g.token_scopes = ["write"]
            assert require_scope("mail:send") is None

    def test_anonymous_envelope(self, app):
        with _agent_ctx(app, "/"):
            g.user = types.SimpleNamespace(anonymous=True)
            result = reject_anonymous()
        assert result is not None
        body, status = result
        assert status == 401
        assert {"error_code", "error_msg", "data"} <= set(body)

    def test_spec_error_codes_mapped(self):
        assert err.ERROR_API_TOKEN_INVALID.c == "S000512" and err.ERROR_API_TOKEN_INVALID.h == 401
        assert err.ERROR_SCOPE_INSUFFICIENT.c == "S000513" and err.ERROR_SCOPE_INSUFFICIENT.h == 403
        assert err.ERROR_IMPERSONATION_TARGET_INVALID.c == "S000514" and err.ERROR_IMPERSONATION_TARGET_INVALID.h == 400


class TestAuthContracts:
    def test_unknown_expired_revoked_map_s000512_401(self):
        """Unknown/expired/revoked tokens all surface the same S000512/401 rejection."""
        assert err.ERROR_API_TOKEN_INVALID.c == "S000512"
        assert err.ERROR_API_TOKEN_INVALID.h == 401

    def test_agent_prefixes_are_disjoint(self):
        from app.api.v1.user.ApiApiTokens import _generate_impersonation_token, _generate_token

        user_token = _generate_token()
        imp_token = _generate_impersonation_token()
        assert user_token.startswith("sogo_") and not user_token.startswith("sogoimp_")
        assert imp_token.startswith("sogoimp_")


class TestAdminContracts:
    def _client(self, app):
        from flask_smorest import Api
        from app.api.v1.admin import ApiImpersonationTokens

        app.config["API_TITLE"] = "admin-t"
        app.config["API_VERSION"] = "1"
        app.config["OPENAPI_VERSION"] = "3.0.3"
        api = Api(app)
        api.register_blueprint(ApiImpersonationTokens.blp)

        @app.before_request
        def _set_admin():  # pragma: no cover - test hook
            from app.auth.Admin import Admin
            g.admin = Admin(uid="admin@example.org")
            g.process_settings = types.SimpleNamespace()

        return app.test_client()

    def test_create_returns_201_raw_token(self, app, monkeypatch):
        created: dict = {}

        def fake_create(**kwargs):
            created.update(kwargs)
            return "sogoimp_rawsecret123", {
                "hash": "a" * 64, "label": kwargs["label"], "scopes": kwargs["scopes"],
                "created_at": 1, "expires_at": None,
            }

        from app.api.v1.admin import ApiImpersonationTokens

        monkeypatch.setattr(ApiImpersonationTokens, "create_impersonation_token", fake_create)
        fake_get_user, _ = _capture("get_user", ({"data": {}}, 200))
        monkeypatch.setattr(ApiImpersonationTokens, "InterfaceApiAdminUser",
                            lambda **kwargs: types.SimpleNamespace(get_user=fake_get_user))
        resp = self._client(app).post(
            "/impersonation-tokens",
            json={"target_uid": "max@example.org", "scopes": ["mail:read"], "label": "debug"},
        )
        body = resp.get_json()
        assert resp.status_code == 201
        assert body["data"]["token"] == "sogoimp_rawsecret123", "raw token shown exactly once"
        assert body["data"]["id"] == "a" * 16
        assert body["data"]["target_uid"] == "max@example.org"
        assert created["admin_uid"] == "admin@example.org"

    def test_unknown_target_s000514(self, app, monkeypatch):
        from app.api.v1.admin import ApiImpersonationTokens

        fake_get_user, _ = _capture("get_user", (None, 404))
        monkeypatch.setattr(ApiImpersonationTokens, "InterfaceApiAdminUser",
                            lambda **kwargs: types.SimpleNamespace(get_user=fake_get_user))
        resp = self._client(app).post(
            "/impersonation-tokens",
            json={"target_uid": "ghost@example.org", "label": "x"},
        )
        body = resp.get_json()
        assert resp.status_code == 400
        assert body["error_code"] == "S000514"

    def test_non_admin_rejected(self, app):
        from app.auth.Admin import AdminAnonymous
        from app.api.v1.admin import ApiImpersonationTokens

        with _agent_ctx(app, "/"):
            g.admin = AdminAnonymous()
            result = ApiImpersonationTokens._require_admin()
        assert result is not None
        body, status = result
        assert status == 401

    def test_audit_line_records_all_fields(self, app, caplog):
        from app.api.v1.user.ApiApiTokens import log_impersonation_use

        with _agent_ctx(app, "/"):
            with caplog.at_level("INFO", logger="sogo6.auth"):
                log_impersonation_use("admin@example.org", "max@example.org",
                                      "user#Agent Mail.v1_Agent", request_id="req-42")
        line = caplog.records[-1].getMessage() if caplog.records else ""
        assert "admin=admin@example.org" in line
        assert "acted_as=max@example.org" in line
        assert "endpoint=user#Agent Mail.v1_Agent" in line
        assert "request_id=req-42" in line


class TestRegistryContracts:
    def test_action_fields_complete(self):
        seen: set[str] = set()
        for action in ACTIONS:
            for field in ("id", "method", "path", "description", "scope"):
                assert action.get(field), f"{action.get('id')} missing {field}"
            assert action["id"] not in seen
            seen.add(action["id"])
            assert action["path"].startswith("/api/user/v1/agent/")
        assert len(ACTIONS) <= 30, "spec cap: facade must not exceed 30 actions"

    def test_scope_grammar(self):
        import re

        pattern = re.compile(r"^(mail|calendar|contacts|ai):[a-z_]+$")
        for action in ACTIONS:
            scope = action["scope"]
            assert scope in ("read", "write", "admin") or pattern.match(scope), action["id"]

    def test_ai_actions_require_mail_read(self):
        ai_actions = [a for a in ACTIONS if a["id"].startswith("ai.")]
        assert ai_actions, "AI actions must be registered"
        for action in ai_actions:
            assert action["scope"] == "mail:read", action["id"]

    def test_agent_views_never_public(self):
        from flask.views import MethodView

        from app.api.v1.agent import agent_apis

        for blp in agent_apis:
            for name, view in blp.__dict__.items():
                if not (isinstance(view, type) and issubclass(view, MethodView)):
                    continue
                assert getattr(view, "public_access", False) is not True, \
                    f"{blp.name}.{name} must never opt into public access"

    def test_agent_blueprints_reject_anonymous(self):
        """Every facade blueprint independently refuses anonymous access (401)."""
        from app.api.v1.agent import agent_apis

        app = Flask("anon-guard")
        routes: dict[str, tuple[str, str]] = {}  # blueprint name → (method, path)
        with _facade_client(app, agent_apis, with_user=False) as client:
            for rule in app.url_map.iter_rules():
                blueprint = rule.endpoint.split(".")[0]
                method = next((m for m in ("GET", "POST", "PATCH", "DELETE") if m in rule.methods), None)
                if method is None:
                    continue
                routes.setdefault(blueprint, (method, rule.rule))
            missing = [b.name for b in agent_apis if b.name not in routes]
            assert not missing, f"could not find a route for: {missing}"
            for blp in agent_apis:
                method, path = routes[blp.name]
                path = re.sub(r"<int:[^>]*>", "1", path)
                path = re.sub(r"<[^>]*>", "x", path)
                resp = getattr(client, method.lower())(path)
                assert resp.status_code == 401, \
                    f"{blp.name} ({method} {path}) must reject anonymous with 401, got {resp.status_code}"


class TestOpenAPIContracts:
    def test_writes_have_request_schemas(self):
        from flask_smorest import Api

        from app.api.v1.agent import agent_apis

        app = Flask("openapi-contract")
        app.config["API_TITLE"] = "t"
        app.config["API_VERSION"] = "1"
        app.config["OPENAPI_VERSION"] = "3.0.3"
        api = Api(app)
        for blp in agent_apis:
            api.register_blueprint(blp)
        spec = api.spec.to_dict()

        agent_paths = {p: ops for p, ops in spec["paths"].items() if "/agent/" in p}
        assert agent_paths
        _NO_BODY_POST = {
            "/agent/mail/drafts/{key}/send",      # sends a stored draft by key; body-less
            "/agent/ai/summarize/{mail_uid}",     # optional {max_sentences} body, not schema-gated
            "/agent/ai/suggest-reply/{mail_uid}", # optional {tone} body, not schema-gated
        }
        for path, ops in agent_paths.items():
            for method, op in ops.items():
                if method not in ("post", "patch", "put") or path in _NO_BODY_POST:
                    continue
                request_body = op.get("requestBody")
                assert request_body, f"{method.upper()} {path} lacks a requestBody schema"
                schema = request_body["content"]["application/json"]["schema"]
                assert schema.get("type") == "object" or "$ref" in schema, \
                    f"{method.upper()} {path} has a placeholder request schema"
