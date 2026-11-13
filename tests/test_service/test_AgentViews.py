"""Behavioral coverage for every agent facade view module.

Complements ``test_AgentSpecContract`` (traceability + headline contracts) by
drilling into the branches the headline suite leaves untested: AI-assist
endpoints, calendar freebusy/slots/detail/delete, mail search/drafts/pagination
edge paths, contacts CRUD, per-view scope enforcement and the lazy interface
factories. Fake interfaces only — no backend required.

Invocation note: views decorated with ``@blp.arguments`` consume the JSON body
from the pushed request context — call them with only the non-body args
(``.post()`` / ``.post(slot_id=...)``) and put the payload in ``_agent_ctx``.
"""
from __future__ import annotations

import contextlib
import json
import types

import pytest
from flask import Flask, g

from app.api.v1.agent import ApiAgentAI, ApiAgentCalendar, ApiAgentContacts, ApiAgentMail
from app.utils import errors as err


@pytest.fixture()
def app():
    return Flask("agent-views")


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
    g.pop("process_settings", None)
    g.pop("user_domain_settings", None)
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
def _facade_client(app, blps, *, with_user: bool = True, token_scopes=None):
    """Test client with the given agent blueprints; optional scope injection."""
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
            if token_scopes is not None:
                g.token_scopes = list(token_scopes)

    yield app.test_client()


# ─────────────────────────────────────────────────────────────────────────────
# AI-assist views (summarize / suggest-reply / nl-search)
# ─────────────────────────────────────────────────────────────────────────────

def _mail_detail(contents):
    return {"data": {"contents": contents}}


class TestAIContracts:
    def test_summarize_happy_path(self, app, monkeypatch):
        seen = {}

        def fake_backend():
            class Backend:
                def summarize(self, text, max_sentences):
                    seen.update(text=text, max_sentences=max_sentences)
                    return "A short summary."
            return Backend()

        get_mail_detail, mail_calls = _capture("get_mail_detail", (
            _mail_detail([
                {"contentType": "text/plain", "content": "plain body here"},
                {"contentType": "text/html", "content": "<p>html body</p>"},
                {"contentType": "application/pdf", "content": "PDFBIN"},
            ]), 200))
        monkeypatch.setattr(ApiAgentAI, "mail_interface",
                            lambda: types.SimpleNamespace(get_mail_detail=get_mail_detail))
        monkeypatch.setattr(ApiAgentAI, "get_model_backend", fake_backend)
        with _agent_ctx(app, "/?account_id=7&folder=Sent"):
            body, status = ApiAgentAI.AgentAISummarize().post(mail_uid=42)
        assert status == 200
        assert body["data"] == {"summary": "A short summary."}
        assert seen["max_sentences"] == 3, "max_sentences defaults to 3"
        assert seen["text"] == "plain body here\n<p>html body</p>", "all text/* bodies feed the model, non-text is skipped"
        assert mail_calls[0][0] == ("7", "Sent", "42")

    def test_summarize_respects_max_sentences_and_truncates(self, app, monkeypatch):
        seen = {}

        def fake_backend():
            class Backend:
                def summarize(self, text, max_sentences):
                    seen.update(text=text, max_sentences=max_sentences)
                    return "short"
            return Backend()

        get_mail_detail, _ = _capture("get_mail_detail", (
            _mail_detail([{"contentType": "text/plain", "content": "a" * 9000}]), 200))
        monkeypatch.setattr(ApiAgentAI, "mail_interface",
                            lambda: types.SimpleNamespace(get_mail_detail=get_mail_detail))
        monkeypatch.setattr(ApiAgentAI, "get_model_backend", fake_backend)
        with _agent_ctx(app, "/", json={"max_sentences": 5}):
            _, status = ApiAgentAI.AgentAISummarize().post(mail_uid=1)
        assert status == 200
        assert seen["max_sentences"] == 5
        assert len(seen["text"]) == 4000, "snippet cap protects the model context"

    def test_summarize_mail_not_found(self, app, monkeypatch):
        get_mail_detail, _ = _capture("get_mail_detail", (None, 404))
        monkeypatch.setattr(ApiAgentAI, "mail_interface",
                            lambda: types.SimpleNamespace(get_mail_detail=get_mail_detail))
        with _agent_ctx(app, "/"):
            body, status = ApiAgentAI.AgentAISummarize().post(mail_uid=9)
        assert status == 404
        assert body["error_code"] == err.ERROR_NOT_FOUND.c

    def test_suggest_reply_happy_path(self, app, monkeypatch):
        seen = {}

        def fake_backend():
            class Backend:
                def suggest_reply(self, text, tone):
                    seen.update(text=text, tone=tone)
                    return "Draft reply"
            return Backend()

        get_mail_detail, _ = _capture("get_mail_detail", (_mail_detail(MAIL_CONTENTS), 200))
        monkeypatch.setattr(ApiAgentAI, "mail_interface",
                            lambda: types.SimpleNamespace(get_mail_detail=get_mail_detail))
        monkeypatch.setattr(ApiAgentAI, "get_model_backend", fake_backend)
        with _agent_ctx(app, "/", json={"tone": "casual"}):
            body, status = ApiAgentAI.AgentAISuggestReply().post(mail_uid=42)
        assert status == 200
        assert body["data"] == {"suggestion": "Draft reply"}
        assert seen["tone"] == "casual"

    def test_suggest_reply_mail_not_found(self, app, monkeypatch):
        get_mail_detail, _ = _capture("get_mail_detail", (None, 404))
        monkeypatch.setattr(ApiAgentAI, "mail_interface",
                            lambda: types.SimpleNamespace(get_mail_detail=get_mail_detail))
        with _agent_ctx(app, "/"):
            body, status = ApiAgentAI.AgentAISuggestReply().post(mail_uid=9)
        assert status == 404
        assert body["error_code"] == err.ERROR_NOT_FOUND.c

    def test_suggest_reply_default_tone(self, app, monkeypatch):
        seen = {}

        def fake_backend():
            class Backend:
                def suggest_reply(self, text, tone):
                    seen["tone"] = tone
                    return "x"
            return Backend()

        get_mail_detail, _ = _capture("get_mail_detail", (_mail_detail(MAIL_CONTENTS), 200))
        monkeypatch.setattr(ApiAgentAI, "mail_interface",
                            lambda: types.SimpleNamespace(get_mail_detail=get_mail_detail))
        monkeypatch.setattr(ApiAgentAI, "get_model_backend", fake_backend)
        with _agent_ctx(app, "/"):
            _, status = ApiAgentAI.AgentAISuggestReply().post(mail_uid=42)
        assert status == 200
        assert seen["tone"] == "professional"

    def test_nl_search_happy_path(self, app, monkeypatch):
        seen = {}

        def fake_backend():
            class Backend:
                def nl_to_search(self, query):
                    seen["query"] = query
                    return {"query": query, "unseen_only": True}
            return Backend()

        monkeypatch.setattr(ApiAgentAI, "get_model_backend", fake_backend)
        with _agent_ctx(app, "/", json={"query": "unread from Alice"}):
            body, status = ApiAgentAI.AgentAINlSearch().post()
        assert status == 200
        assert body["data"] == {"search_params": {"query": "unread from Alice", "unseen_only": True}}
        assert seen["query"] == "unread from Alice"


# ─────────────────────────────────────────────────────────────────────────────
# Calendar views
# ─────────────────────────────────────────────────────────────────────────────

class FakeCache:
    def __init__(self, store=None):
        self.store = store or {}

    def get(self, key, default=None):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value


class TestCalendarViewCoverage:
    def test_events_get_passes_calendar_and_search(self, app, monkeypatch):
        get_events, calls = _capture("get_events", ({"data": []}, 200))
        monkeypatch.setattr(ApiAgentCalendar, "calendar_interface",
                            lambda: types.SimpleNamespace(get_events=get_events))
        with _agent_ctx(app, "/?calendar_key=cal-2&from=2026-01-01T00:00:00Z&to=2026-01-02T00:00:00Z&search=team"):
            _, status = ApiAgentCalendar.AgentCalendarEvents().get()
        assert status == 200
        key, query = calls[0][0]
        assert key == "cal-2"
        assert query["search"] == "team"

    def test_events_post_explicit_calendar_key_skips_resolution(self, app, monkeypatch):
        get_all_calendars, gac_calls = _capture("get_all_calendars", ({"data": {"calendars": []}}, 200))
        create_event, calls = _capture("create_event", ({"error_code": "S000000"}, 201))
        monkeypatch.setattr(ApiAgentCalendar, "calendar_interface",
                            lambda: types.SimpleNamespace(get_all_calendars=get_all_calendars,
                                                          create_event=create_event))
        with _agent_ctx(app, "/", json={"title": "t", "start": "s", "end": "e", "calendar_key": "cal-9"}):
            _, status = ApiAgentCalendar.AgentCalendarEvents().post()
        assert status == 201
        assert not gac_calls, "explicit calendar_key must skip default resolution"
        assert calls[0][0][0] == "cal-9"

    def test_events_post_default_resolution_via_dict_and_missing(self, app, monkeypatch):
        # calendars returned as a dict → values() fallback path
        create_event, calls = _capture("create_event", ({"error_code": "S000000"}, 201))
        monkeypatch.setattr(ApiAgentCalendar, "calendar_interface",
                            lambda: types.SimpleNamespace(
                                get_all_calendars=lambda: ({"data": {"calendars": {"k-1": {"key": "k-1"}}}}, 200),
                                create_event=create_event))
        with _agent_ctx(app, "/", json={"title": "t", "start": "s", "end": "e"}):
            _, status = ApiAgentCalendar.AgentCalendarEvents().post()
        assert status == 201
        assert calls[0][0][0] == "k-1"

        # no calendars at all → 404
        monkeypatch.setattr(ApiAgentCalendar, "calendar_interface",
                            lambda: types.SimpleNamespace(
                                get_all_calendars=lambda: ({"data": {"calendars": []}}, 200),
                                create_event=lambda *a, **k: (None, 500)))
        with _agent_ctx(app, "/", json={"title": "t", "start": "s", "end": "e"}):
            body, status = ApiAgentCalendar.AgentCalendarEvents().post()
        assert status == 404
        assert body["error_code"] == err.ERROR_NOT_FOUND.c

    def test_events_post_resolution_error_404(self, app, monkeypatch):
        monkeypatch.setattr(ApiAgentCalendar, "calendar_interface",
                            lambda: types.SimpleNamespace(
                                get_all_calendars=lambda: (None, 500),
                                create_event=lambda *a, **k: (None, 500)))
        with _agent_ctx(app, "/", json={"title": "t", "start": "s", "end": "e"}):
            body, status = ApiAgentCalendar.AgentCalendarEvents().post()
        assert status == 404
        assert body["error_code"] == err.ERROR_NOT_FOUND.c

    def test_event_detail_get_patch_delete(self, app, monkeypatch):
        get_event, _ = _capture("get_event", ({"data": {"key": "ev-1"}}, 200))
        patch_event, patch_calls = _capture("patch_event", ({"error_code": "S000000"}, 200))
        delete_event, del_calls = _capture("delete_event", ({"error_code": "S000000"}, 200))
        monkeypatch.setattr(ApiAgentCalendar, "calendar_interface",
                            lambda: types.SimpleNamespace(get_event=get_event,
                                                          patch_event=patch_event,
                                                          delete_event=delete_event))

        with _agent_ctx(app, "/"):
            body, status = ApiAgentCalendar.AgentCalendarEventDetail().get(event_key="ev-1")
        assert status == 200 and body["data"]["key"] == "ev-1"

        with _agent_ctx(app, "/", json={"title": "renamed"}):
            _, status = ApiAgentCalendar.AgentCalendarEventDetail().patch(event_key="ev-1")
        assert status == 200
        assert patch_calls[0][0] == ("ev-1", {"title": "renamed"})

        with _agent_ctx(app, "/?recurrence_id=2026-03-01"):
            _, status = ApiAgentCalendar.AgentCalendarEventDetail().delete(event_key="ev-1")
        assert status == 200
        assert del_calls[0][0][0] == "ev-1"
        recurrence_id = del_calls[0][1]["recurrence_id"]
        assert recurrence_id.isoformat().startswith("2026-03-01")

    def test_freebusy_happy_and_missing_args(self, app, monkeypatch):
        get_freebusy, calls = _capture("get_freebusy", ({"data": {"busy": []}}, 200))
        monkeypatch.setattr(ApiAgentCalendar, "calendar_interface",
                            lambda: types.SimpleNamespace(get_freebusy=get_freebusy))
        with _agent_ctx(app, "/?uids=alice@example.org, bob@example.org ,&from=2026-01-01T00:00:00Z&to=2026-01-01T23:59:59Z"):
            _, status = ApiAgentCalendar.AgentCalendarFreebusy().get()
        assert status == 200
        sent = calls[0][0][0]
        assert sent["target_uids"] == ["alice@example.org", "bob@example.org"]
        assert sent["start"] == "2026-01-01T00:00:00Z"

        with _agent_ctx(app, "/?uids=a@example.org&from=2026-01-01T00:00:00Z"):  # no ?to=
            body, status = ApiAgentCalendar.AgentCalendarFreebusy().get()
        assert status == 400
        assert body["error_code"] == err.ERROR_VALIDATION_FAILED.c

    def test_slots_list_filters_bad_json(self, app, monkeypatch):
        cache = FakeCache({
            "appt_slot:index:max@example.org": ["s-1", "s-2"],
            "appt_slot:s-1": json.dumps({"id": "s-1", "title": "Consult"}),
            "appt_slot:s-2": "{broken json",
        })
        monkeypatch.setattr(ApiAgentCalendar, "sogo_cache", lambda: cache)
        with _agent_ctx(app, "/"):
            body, status = ApiAgentCalendar.AgentCalendarSlots().get()
        assert status == 200
        assert body["data"]["slots"] == [{"id": "s-1", "title": "Consult"}]

    def test_slots_list_empty(self, app, monkeypatch):
        monkeypatch.setattr(ApiAgentCalendar, "sogo_cache", lambda: FakeCache())
        with _agent_ctx(app, "/"):
            body, status = ApiAgentCalendar.AgentCalendarSlots().get()
        assert status == 200 and body["data"]["slots"] == []

    def test_slot_book_happy_path(self, app, monkeypatch):
        cache = FakeCache({"appt_slot:slot-1": json.dumps({"id": "slot-1", "title": "Consult"})})
        monkeypatch.setattr(ApiAgentCalendar, "sogo_cache", lambda: cache)
        with _agent_ctx(app, "/", json={"date": "2026-02-01", "time": "10:30"}):
            body, status = ApiAgentCalendar.AgentCalendarSlotBook().post(slot_id="slot-1")
        assert status == 200
        booking_id = body["data"]["booking_id"]
        assert len(booking_id) == 24
        booking = json.loads(cache.store[f"appt_booking:{booking_id}"])
        assert booking["name"] == "Max" and booking["email"] == "max@example.org"
        assert booking["date"] == "2026-02-01" and booking["time"] == "10:30"
        assert cache.store["appt_booking:index:slot-1"] == [booking_id]

    def test_slot_book_unknown_slot(self, app, monkeypatch):
        monkeypatch.setattr(ApiAgentCalendar, "sogo_cache", lambda: FakeCache())
        with _agent_ctx(app, "/", json={"date": "2026-02-01", "time": "10:30"}):
            body, status = ApiAgentCalendar.AgentCalendarSlotBook().post(slot_id="nope")
        assert status == 404
        assert body["error_code"] == err.ERROR_NOT_FOUND.c

    def test_slots_list_single_slot(self, app, monkeypatch):
        cache = FakeCache({
            "appt_slot:index:max@example.org": ["s-1"],
            "appt_slot:s-1": json.dumps({"id": "s-1"}),
        })
        monkeypatch.setattr(ApiAgentCalendar, "sogo_cache", lambda: cache)
        with _agent_ctx(app, "/"):
            body, _ = ApiAgentCalendar.AgentCalendarSlots().get()
        assert body["data"]["slots"] == [{"id": "s-1"}]


# ─────────────────────────────────────────────────────────────────────────────
# Mail views
# ─────────────────────────────────────────────────────────────────────────────

MAIL_CONTENTS = [
    {"contentType": "text/plain", "content": "plain body here"},
    {"contentType": "text/html", "content": "<p>html body</p>"},
]


class TestMailViewCoverage:
    def test_page_args_parsing_and_cap(self, app):
        from app.api.v1.agent.ApiAgentMail import AGENT_MAX_PAGE_SIZE, _page_args

        with _agent_ctx(app, "/?page=3&limit=999"):
            assert _page_args() == (3, AGENT_MAX_PAGE_SIZE)
        with _agent_ctx(app, "/?page=0&page_size=-5"):
            assert _page_args() == (1, 1)
        with _agent_ctx(app, "/?page=abc"):
            assert _page_args() is None
        with _agent_ctx(app, "/"):
            assert _page_args() == (1, 20)

    def test_page_args_value_error_rejected(self, app, monkeypatch):
        with _agent_ctx(app, "/?page=abc"):
            body, status = ApiAgentMail.AgentMailMessages().get()
        assert status == 400
        assert body["error_code"] == err.ERROR_VALIDATION_FAILED.c

    def test_snippet_falls_back_to_any_text(self):
        from app.api.v1.agent.ApiAgentMail import _text_snippet

        mail = {"contents": [{"contentType": "text/html", "content": "<p>no plain part</p>"}]}
        assert _text_snippet(mail, 20) == "<p>no plain part</p>"
        assert _text_snippet(mail, 4) == "<p>n"
        assert _text_snippet({"contents": []}, 10) == ""

    def test_list_upstream_error_passthrough(self, app, monkeypatch):
        get_mail_list, _ = _capture("get_mail_list", (0, {"error_code": "X"}, 500))
        monkeypatch.setattr(ApiAgentMail, "mail_interface",
                            lambda: types.SimpleNamespace(get_mail_list=get_mail_list))
        with _agent_ctx(app, "/?folder=INBOX"):
            body, status = ApiAgentMail.AgentMailMessages().get()
        assert status == 500 and body == {"error_code": "X"}

    def test_detail_skips_non_text_contents(self, app, monkeypatch):
        """application/pdf + text parts → only text/* lands in the body map."""
        get_mail_detail, _ = _capture("get_mail_detail", (
            {"data": {"uid": 2,
                       "contents": [{"contentType": "text/plain", "content": "text"},
                                     {"contentType": "text/html", "content": "<p>html</p>"},
                                     {"contentType": "application/pdf", "content": "PDFBIN"}]}}, 200))
        monkeypatch.setattr(ApiAgentMail, "mail_interface",
                            lambda: types.SimpleNamespace(get_mail_detail=get_mail_detail))
        with _agent_ctx(app, "/"):
            body, status = ApiAgentMail.AgentMailMessageDetail().get(mail_uid=2)
        assert status == 200
        assert set(body["data"]["body"]) == {"text/plain", "text/html"}
        assert "application/pdf" not in body["data"]["body"]

    def test_detail_upstream_error_passthrough(self, app, monkeypatch):
        get_mail_detail, _ = _capture("get_mail_detail", ({"error_code": "X"}, 503))
        monkeypatch.setattr(ApiAgentMail, "mail_interface",
                            lambda: types.SimpleNamespace(get_mail_detail=get_mail_detail))
        with _agent_ctx(app, "/"):
            body, status = ApiAgentMail.AgentMailMessageDetail().get(mail_uid=1)
        assert status == 503

    def test_send_from_fallbacks(self, app, monkeypatch):
        send_mail, calls = _capture("send_mail", ({"error_code": "S000000"}, 200))
        monkeypatch.setattr(ApiAgentMail, "mail_send_interface",
                            lambda: types.SimpleNamespace(send_mail=send_mail))
        with _agent_ctx(app, "/", json={"to": ["a@example.org"], "from": "boss@example.org", "is_html": True}):
            _, status = ApiAgentMail.AgentMailSend().post()
        assert status == 200
        assert calls[0][0][1]["from_addr"] == "boss@example.org"
        assert calls[0][0][1]["is_html"] is True

        # no from_addr + no user mail → uid fallback
        with _agent_ctx(app, "/", json={"to": ["a@example.org"]}):
            g.user.mail = None
            _, status = ApiAgentMail.AgentMailSend().post()
        assert status == 200
        assert calls[-1][0][1]["from_addr"] == "max@example.org"

    def test_send_attachment_default_content_type(self, app, monkeypatch):
        import base64

        send_mail, calls = _capture("send_mail", ({"error_code": "S000000"}, 200))
        monkeypatch.setattr(ApiAgentMail, "mail_send_interface",
                            lambda: types.SimpleNamespace(send_mail=send_mail))
        payload = {"to": ["a@example.org"],
                   "attachments": [{"filename": "x.bin", "content_b64": base64.b64encode(b"\x00\x01").decode()}]}
        with _agent_ctx(app, "/", json=payload):
            _, status = ApiAgentMail.AgentMailSend().post()
        assert status == 200
        att = calls[0][0][1]["attachments"][0]
        assert att["content_type"] == "application/octet-stream"
        assert att["data"] == b"\x00\x01"

    def test_search_happy_path_and_compact(self, app, monkeypatch):
        mails = [{"uid": 1, "folder": "INBOX", "from": {"email": "a@example.org"},
                  "subject": "Hi", "date": "d", "seen": True, "flagged": False,
                  "has_attachment": False,
                  "contents": [{"contentType": "text/plain", "content": "hello world"}]}]
        search_mails, calls = _capture("search_mails", (1, {"data": mails}, 200))
        monkeypatch.setattr(ApiAgentMail, "mail_interface",
                            lambda: types.SimpleNamespace(search_mails=search_mails))
        with _agent_ctx(app, "/?query=hello&unseen_only=true&limit=5&page=2"):
            body, status = ApiAgentMail.AgentMailSearch().get()
        assert status == 200
        params = calls[0][0][1]
        assert params["query"] == "hello"
        assert params["unseen_only"] == "true"
        assert params["page"] == 2 and params["per_page"] == 5
        message = body["data"]["messages"][0]
        assert set(message) == {"uid", "folder", "from", "subject", "date", "snippet",
                                "flags", "has_attachments"}
        assert message["snippet"] == "hello world"

    def test_search_dict_response_and_bad_page(self, app, monkeypatch):
        search_mails, calls = _capture("search_mails",
                                       (2, {"data": {"mails": [{"uid": 9, "subject": "S"}]}}, 200))
        monkeypatch.setattr(ApiAgentMail, "mail_interface",
                            lambda: types.SimpleNamespace(search_mails=search_mails))
        with _agent_ctx(app, "/?query=x&page=notanint"):
            body, _ = ApiAgentMail.AgentMailSearch().get()
        assert body["data"]["total"] == 2
        params = calls[0][0][1]
        assert params["page"] == 1
        assert params["per_page"] == 20

    def test_search_upstream_error_passthrough(self, app, monkeypatch):
        search_mails, _ = _capture("search_mails", (0, {"error_code": "X"}, 502))
        monkeypatch.setattr(ApiAgentMail, "mail_interface",
                            lambda: types.SimpleNamespace(search_mails=search_mails))
        with _agent_ctx(app, "/?query=x"):
            body, status = ApiAgentMail.AgentMailSearch().get()
        assert status == 502

    def test_folders_error_and_string_entries(self, app, monkeypatch):
        get_folder_list, _ = _capture(
            "get_folder_list",
            ({"data": {
                "folders": [
                    {"name": "INBOX", "path": "/INBOX", "unseen": 2, "exists": 10},
                    "ARCHIVE",
                ]
            }}, 200))
        monkeypatch.setattr(ApiAgentMail, "mail_folder_interface",
                            lambda: types.SimpleNamespace(get_folder_list=get_folder_list))
        with _agent_ctx(app, "/"):
            body, status = ApiAgentMail.AgentMailFolders().get()
        assert status == 200
        folders = body["data"]["folders"]
        assert folders[0] == {"name": "INBOX", "path": "/INBOX", "unread": 2, "total": 10}
        assert folders[1] == {"name": "ARCHIVE"}

        get_folder_list_err, _ = _capture("get_folder_list", ({"error_code": "X"}, 500))
        monkeypatch.setattr(ApiAgentMail, "mail_folder_interface",
                            lambda: types.SimpleNamespace(get_folder_list=get_folder_list_err))
        with _agent_ctx(app, "/"):
            body, status = ApiAgentMail.AgentMailFolders().get()
        assert status == 500

    def test_drafts_create(self, app, monkeypatch):
        save_draft, calls = _capture("save_draft", ({"error_code": "S000000", "data": {"key": "draft-1"}}, 200))
        monkeypatch.setattr(ApiAgentMail, "mail_send_interface",
                            lambda: types.SimpleNamespace(save_draft=save_draft))
        with _agent_ctx(app, "/?account_id=3", json={"to": ["a@example.org"], "subject": "Draft"}):
            body, status = ApiAgentMail.AgentMailDrafts().post()
        assert status == 200
        account_id, mail_data = calls[0][0]
        assert account_id == "3"
        assert mail_data["from_addr"] == "max@example.org"
        assert mail_data["subject"] == "Draft"
        assert calls[0][1] == {"key": None, "close": False}

    def test_drafts_create_uid_fallback(self, app, monkeypatch):
        save_draft, calls = _capture("save_draft", ({"error_code": "S000000"}, 200))
        monkeypatch.setattr(ApiAgentMail, "mail_send_interface",
                            lambda: types.SimpleNamespace(save_draft=save_draft))
        with _agent_ctx(app, "/", json={"to": ["a@example.org"]}):
            g.user.mail = None
            _, status = ApiAgentMail.AgentMailDrafts().post()
        assert status == 200
        assert calls[0][0][1]["from_addr"] == "max@example.org"

    def test_draft_send_by_key(self, app, monkeypatch):
        send_mail, calls = _capture("send_mail", ({"error_code": "S000000"}, 200))
        monkeypatch.setattr(ApiAgentMail, "mail_send_interface",
                            lambda: types.SimpleNamespace(send_mail=send_mail))
        with _agent_ctx(app, "/"):
            _, status = ApiAgentMail.AgentMailDraftSend().post(key="tmp-123")
        assert status == 200
        account_id, mail_data = calls[0][0]
        assert calls[0][1] == {"key": "tmp-123"}
        assert mail_data == {"from_addr": "max@example.org", "to": []}


# ─────────────────────────────────────────────────────────────────────────────
# Contacts views
# ─────────────────────────────────────────────────────────────────────────────

class TestContactsViewCoverage:
    def test_search_empty_query(self, app, monkeypatch):
        autocomplete, calls = _capture("autocomplete", ({"data": {"suggestions": []}}, 200))
        monkeypatch.setattr(ApiAgentContacts, "contact_interface",
                            lambda: types.SimpleNamespace(autocomplete=autocomplete))
        with _agent_ctx(app, "/?q=%20%20"):
            body, status = ApiAgentContacts.AgentContactsSearch().get()
        assert status == 200
        assert body["data"] == {"suggestions": []}
        assert not calls, "blank query must not hit the interface"

    def test_search_upstream_error_passthrough(self, app, monkeypatch):
        autocomplete, _ = _capture("autocomplete", ({"error_code": "X"}, 500))
        monkeypatch.setattr(ApiAgentContacts, "contact_interface",
                            lambda: types.SimpleNamespace(autocomplete=autocomplete))
        with _agent_ctx(app, "/?q=smith"):
            body, status = ApiAgentContacts.AgentContactsSearch().get()
        assert status == 500

    def test_search_phone_fallbacks(self):
        from app.api.v1.agent.ApiAgentContacts import _compact_suggestion

        assert _compact_suggestion({"contact_key": "k1", "name": "N", "email": "e@x", "primary_phone": "+1"}) == {
            "key": "k1", "name": "N", "email": "e@x", "primary_phone": "+1"}
        assert _compact_suggestion({"key": "k2", "name": "N", "email": "e@x", "phone": "+2"}) == {
            "key": "k2", "name": "N", "email": "e@x", "primary_phone": "+2"}

    def test_create_explicit_book_and_missing_default(self, app, monkeypatch):
        create_contact, calls = _capture("create_contact", ({"error_code": "S000000"}, 201))
        get_all_addressbooks, gac_calls = _capture("get_all_addressbooks",
                                                   ({"data": {"addressbooks": [{"key": "b-1"}]}}, 200))
        monkeypatch.setattr(ApiAgentContacts, "contact_interface",
                            lambda: types.SimpleNamespace(create_contact=create_contact,
                                                          get_all_addressbooks=get_all_addressbooks))
        with _agent_ctx(app, "/", json={"first_name": "A", "addressbook_key": "b-9"}):
            _, status = ApiAgentContacts.AgentContactsCreate().post()
        assert status == 201
        assert not gac_calls and calls[0][0][0] == "b-9"

        monkeypatch.setattr(ApiAgentContacts, "contact_interface",
                            lambda: types.SimpleNamespace(
                                create_contact=lambda *a, **k: (None, 500),
                                get_all_addressbooks=lambda: ({"data": {"addressbooks": []}}, 200)))
        with _agent_ctx(app, "/", json={"first_name": "A"}):
            body, status = ApiAgentContacts.AgentContactsCreate().post()
        assert status == 404 and body["error_code"] == err.ERROR_NOT_FOUND.c

    def test_create_dict_addressbooks_resolution(self, app, monkeypatch):
        create_contact, calls = _capture("create_contact", ({"error_code": "S000000"}, 201))
        get_all_addressbooks, _ = _capture(
            "get_all_addressbooks", ({"data": {"addressbooks": {"b-1": {"key": "b-1"}}}}, 200))
        monkeypatch.setattr(ApiAgentContacts, "contact_interface",
                            lambda: types.SimpleNamespace(create_contact=create_contact,
                                                          get_all_addressbooks=get_all_addressbooks))
        with _agent_ctx(app, "/", json={"first_name": "A"}):
            _, status = ApiAgentContacts.AgentContactsCreate().post()
        assert status == 201 and calls[0][0][0] == "b-1"

    def test_create_addressbook_resolution_error_404(self, app, monkeypatch):
        monkeypatch.setattr(ApiAgentContacts, "contact_interface",
                            lambda: types.SimpleNamespace(
                                create_contact=lambda *a, **k: (None, 500),
                                get_all_addressbooks=lambda: (None, 500)))
        with _agent_ctx(app, "/", json={"first_name": "A"}):
            body, status = ApiAgentContacts.AgentContactsCreate().post()
        assert status == 404
        assert body["error_code"] == err.ERROR_NOT_FOUND.c

    def test_contact_detail_get_patch_delete(self, app, monkeypatch):
        get_contact, g_calls = _capture("get_contact", ({"data": {"key": "c-1"}}, 200))
        patch_contact, p_calls = _capture("patch_contact", ({"error_code": "S000000"}, 200))
        delete_contact, d_calls = _capture("delete_contact", ({"error_code": "S000000"}, 200))
        monkeypatch.setattr(ApiAgentContacts, "contact_interface",
                            lambda: types.SimpleNamespace(get_contact=get_contact,
                                                          patch_contact=patch_contact,
                                                          delete_contact=delete_contact))
        with _agent_ctx(app, "/?addressbook_key=b-1"):
            body, status = ApiAgentContacts.AgentContactDetail().get(key="c-1")
        assert status == 200 and g_calls[0][0] == ("b-1", "c-1")

        with _agent_ctx(app, "/?addressbook_key=b-1", json={"company": "ACME"}):
            _, status = ApiAgentContacts.AgentContactDetail().patch(key="c-1")
        assert status == 200 and p_calls[0][0] == ("b-1", "c-1", {"company": "ACME"})

        with _agent_ctx(app, "/?addressbook_key=b-1"):
            _, status = ApiAgentContacts.AgentContactDetail().delete(key="c-1")
        assert status == 200 and d_calls[0][0] == ("b-1", "c-1")

    def test_addressbooks_list(self, app, monkeypatch):
        get_all_addressbooks, calls = _capture("get_all_addressbooks",
                                               ({"data": {"addressbooks": [{"key": "b-1"}]}}, 200))
        monkeypatch.setattr(ApiAgentContacts, "contact_interface",
                            lambda: types.SimpleNamespace(get_all_addressbooks=get_all_addressbooks))
        with _agent_ctx(app, "/"):
            _, status = ApiAgentContacts.AgentAddressbooks().get()
        assert status == 200 and calls


# ─────────────────────────────────────────────────────────────────────────────
# Manifest route + per-view scope enforcement
# ─────────────────────────────────────────────────────────────────────────────

class TestManifestRoute:
    def test_authenticated_manifest_sorted_27(self, app):
        from app.api.v1.agent import ACTIONS, ApiAgentManifest

        with _facade_client(app, [ApiAgentManifest.blp]) as client:
            resp = client.get("/agent/manifest")
        assert resp.status_code == 200
        payload = resp.get_json()["data"]
        assert payload["version"] == ApiAgentManifest.MANIFEST_VERSION
        ids = [a["id"] for a in payload["actions"]]
        assert ids == sorted(a["id"] for a in ACTIONS)
        assert len(ids) <= 30


GUARDED_ROUTES = [
    ("get", "/agent/mail/messages", None),
    ("get", "/agent/mail/messages/1", None),
    ("post", "/agent/mail/send", {"to": ["a@example.org"]}),
    ("get", "/agent/mail/search?query=x", None),
    ("post", "/agent/mail/messages/batch-action", {"action": "mark_read", "mail_uids": [1]}),
    ("get", "/agent/mail/folders", None),
    ("post", "/agent/mail/drafts", {"to": ["a@example.org"]}),
    ("post", "/agent/mail/drafts/d1/send", None),
    ("get", "/agent/calendar/events", None),
    ("post", "/agent/calendar/events",
     {"title": "t", "start": "2026-01-01T00:00:00Z", "end": "2026-01-01T01:00:00Z"}),
    ("get", "/agent/calendar/events/ev-1", None),
    ("patch", "/agent/calendar/events/ev-1", {}),
    ("delete", "/agent/calendar/events/ev-1", None),
    ("get", "/agent/calendar/freebusy?uids=a@example.org&from=x&to=y", None),
    ("get", "/agent/calendar/slots", None),
    ("post", "/agent/calendar/slots/s-1/book", {"date": "d", "time": "t"}),
    ("post", "/agent/calendar/invitations/ev-1/respond", {"status": "accepted"}),
    ("get", "/agent/contacts/search?q=x", None),
    ("post", "/agent/contacts", {"first_name": "A"}),
    ("get", "/agent/contacts/c-1?addressbook_key=b-1", None),
    ("patch", "/agent/contacts/c-1", {"first_name": "B"}),
    ("delete", "/agent/contacts/c-1", None),
    ("get", "/agent/contacts/addressbooks", None),
    ("post", "/agent/ai/summarize/1", None),
    ("post", "/agent/ai/suggest-reply/1", None),
    ("post", "/agent/ai/nl-search", {"query": "unread"}),
]


class TestScopeEnforcement:
    @pytest.mark.parametrize("method,path,body", GUARDED_ROUTES,
                             ids=[f"{m} {p}" for m, p, _ in GUARDED_ROUTES])
    def test_all_views_403_without_scope(self, app, method, path, body):
        """Every facade route must 403 (S000513) when the token lacks the scope."""
        from app.api.v1.agent import agent_apis

        with _facade_client(app, agent_apis, token_scopes=["ssn:metrics_only"]) as client:
            resp = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
        assert resp.status_code == 403, f"{method.upper()} {path}"
        assert resp.get_json()["error_code"] == "S000513"


class TestImpersonationTokenAdminViews:
    """List + revoke endpoints of the admin impersonation token resource."""

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

    def test_list_returns_tokens(self, app, monkeypatch):
        from app.api.v1.admin import ApiImpersonationTokens

        monkeypatch.setattr(ApiImpersonationTokens, "list_impersonation_tokens",
                            lambda uid: [{"id": "tok-1", "label": "debug"}])
        resp = self._client(app).get("/impersonation-tokens")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["tokens"] == [{"id": "tok-1", "label": "debug"}]

    def test_revoke_happy_and_missing(self, app, monkeypatch):
        from app.api.v1.admin import ApiImpersonationTokens

        revoke = lambda uid, tok: uid == "admin@example.org" and tok == "tok-1"
        monkeypatch.setattr(ApiImpersonationTokens, "revoke_impersonation_token", revoke)
        client = self._client(app)

        resp = client.delete("/impersonation-tokens/tok-1")
        assert resp.status_code == 200
        assert resp.get_json()["data"] == {"status": "revoked"}

        resp = client.delete("/impersonation-tokens/tok-9")
        assert resp.status_code == 404
        assert resp.get_json()["error_code"] == err.ERROR_API_TOKEN_NOT_FOUND.c


# ─────────────────────────────────────────────────────────────────────────────
# Lazy interface factories (construction path in agent/__init__)
# ─────────────────────────────────────────────────────────────────────────────

class TestInterfaceFactories:
    def test_factories_construct_from_g(self, app, monkeypatch):
        import sys
        from types import ModuleType, SimpleNamespace

        sentinel = type("FakeInterface", (), {
            "__init__": lambda self, **kw: setattr(self, "kwargs", kw)})
        factories = [
            ("app.interface.mail.InterfaceApiMailMail", "InterfaceApiMailMail"),
            ("app.interface.mail.InterfaceApiMailSend", "InterfaceApiMailSend"),
            ("app.interface.mail.InterfaceApiMailFolder", "InterfaceApiMailFolder"),
            ("app.interface.calendar.InterfaceApiCalendarCalendar", "InterfaceApiCalendarCalendar"),
            ("app.interface.contact.InterfaceApiContactContact", "InterfaceApiContactContact"),
        ]
        for mod_name, cls_name in factories:
            mod = ModuleType(mod_name)
            setattr(mod, cls_name, sentinel)
            monkeypatch.setitem(sys.modules, mod_name, mod)

        from app.api.v1 import agent as agent_module

        with _agent_ctx(app, "/"):
            g.process_settings = SimpleNamespace()
            g.user_domain_settings = SimpleNamespace()
            for factory in (agent_module.mail_interface, agent_module.mail_send_interface,
                            agent_module.mail_folder_interface, agent_module.calendar_interface,
                            agent_module.contact_interface):
                obj = factory()
                assert isinstance(obj, sentinel)
                assert obj.kwargs["process_setting"] is g.process_settings
                assert obj.kwargs["user_domain_settings"] is g.user_domain_settings
                assert obj.kwargs["user"] is g.user
