"""JMAP protocol tests.

The JMAP endpoints should behave as a protocol: correct RFC 8620 envelope,
RFC 8621 method payloads, and honest errors -- all backed by a configurable
store gateway (injected here as a fake; production uses the real IMAP store
via JmapMailGateway).
"""
from __future__ import annotations

import pytest

from app import create_app
from app.utils import constants as cs

JMAP_URL = "/api/user/v1/jmap"
JMAP_CORE = "urn:ietf:params:jmap:core"
JMAP_MAIL = "urn:ietf:params:jmap:mail"


@pytest.fixture()
def authed_client(monkeypatch):
    """JMAP is a user mail protocol mounted under the BASIC (user) API.

    The app must run in the initialized (SOGO_OK) state or the user API
    412-blocks everything; the DB-backed config resolution (system/domain
    settings, mail-credential check) is stubbed so no live DB is needed.
    """
    from app.auth.User import User

    app = create_app(cs.SOGO_OK)
    app.config["TESTING"] = True

    class FakeAuthUser:
        def __init__(self, *a, **k):
            pass

        def check_user_and_fill_info(self, user):
            return True, user

    monkeypatch.setattr("app.init_get_system_and_default_domain_settings", lambda: ({}, {}))
    monkeypatch.setattr("app.init_get_user_domain_settings", lambda user: {})
    monkeypatch.setattr("app.InterfaceAuthUser", FakeAuthUser)
    monkeypatch.setattr("app.VoucherUserService.__init__", lambda self, ps: None)
    monkeypatch.setattr(
        "app.VoucherUserService.generate_user_from_voucher",
        staticmethod(lambda token: User("testuser@example.org", cn="Test User", domain="example.org")),
    )
    client = app.test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = "Bearer test-token"
    return client


class FakeGateway:
    def __init__(self, rows=None, mails=None):
        self.rows = rows or [
            {cs.FOLDER_PATH: "INBOX", cs.FOLDER_NAME: "INBOX", cs.FOLDER_TYPE: "inbox",
             cs.FOLDER_COUNT: 2, cs.FOLDER_UNSEEN: 1},
            {cs.FOLDER_PATH: "Sent", cs.FOLDER_NAME: "Sent", cs.FOLDER_TYPE: "sent",
             cs.FOLDER_COUNT: 0, cs.FOLDER_UNSEEN: 0},
        ]
        self.mails = mails or {
            "INBOX": [
                {"uid": "101", "subject": "Hello JMAP", "from_": {"name": "Ada", "email": "ada@example.org"},
                 "to": [{"name": "", "email": "bob@example.org"}], "cc": [],
                 "date": "2026-08-01T10:00:00Z", "size": 1234, "seen": False, "flagged": False,
                 "has_attachment": False,
                 "contents": [{"contentType": "text/plain", "content": "hi"}],
                 "attachments": [], "flags": {}},
                {"uid": "3", "subject": "Second", "flags": {}, "date": None, "size": 88,
                 "seen": True, "contents": [], "from_": None, "to": [], "cc": [],
                 "has_attachment": False, "attachments": []},
            ],
            "Sent": [],
        }
        self.call_log = []

    def list_mailbox_rows(self, account_id):
        self.call_log.append(("list_mailbox_rows", account_id))
        return self.rows

    def get_mail(self, account_id, folder, uid):
        self.call_log.append(("get_mail", account_id, folder, uid))
        for m in self.mails.get(folder, []):
            if str(m["uid"]) == str(uid):
                return m
        from app.utils.exceptions import RequestException
        raise RequestException(f"mail {uid} not found")

    def get_mails(self, account_id, folder, limit, offset=0):
        self.call_log.append(("get_mails", account_id, folder, limit))
        items = self.mails.get(folder, [])
        return [m for m in items if str(m["uid"]) != "1"], len(items)

    def create_mailbox(self, account_id, name, parent_path=""):
        self.call_log.append(("create_mailbox", account_id, name, parent_path))
        return {cs.FOLDER_PATH: name, cs.FOLDER_NAME: name, cs.FOLDER_TYPE: None,
                cs.FOLDER_COUNT: 0, cs.FOLDER_UNSEEN: 0}

    def delete_mailbox(self, account_id, folder_path):
        self.call_log.append(("delete_mailbox", account_id, folder_path))
        if folder_path == "INBOX":
            from app.utils.exceptions import RequestException
            raise RequestException("cannot delete INBOX")

    def destroy_mail(self, account_id, folder_path, mail_uid):
        self.call_log.append(("destroy_mail", account_id, folder_path, mail_uid))

    def move_mail(self, account_id, from_folder, mail_uid, to_folder):
        self.call_log.append(("move_mail", account_id, from_folder, mail_uid, to_folder))


def _post(client, method_calls, using=None, account_id="u1"):
    body = {"using": using or [JMAP_CORE, JMAP_MAIL], "accountId": account_id,
            "methodCalls": method_calls}
    resp = client.post(JMAP_URL, json=body)
    return resp


def _mailbox_id(path):
    import base64
    return base64.urlsafe_b64encode(("mailbox:" + path).encode()).decode("ascii")


def _email_id(folder, uid):
    import base64
    return base64.urlsafe_b64encode(f"{folder}\x00{uid}".encode()).decode("ascii")


# ---------------------------------------------------------------- #
# session / envelope
# ---------------------------------------------------------------- #

def test_session_capabilities(authed_client):
    resp = authed_client.get(f"{JMAP_URL}/session")
    assert resp.status_code == 200
    data = resp.get_json()
    assert JMAP_CORE in data["capabilities"]
    assert JMAP_MAIL in data["capabilities"]
    assert data["apiUrl"] == "/jmap"


def test_status_endpoint_reports_store(authed_client, monkeypatch):
    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: None)
    resp = authed_client.get(f"{JMAP_URL}/status")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["enabled"] is True
    assert data["store"] == "unconfigured"


def test_unsupported_capability_is_jmap_error(authed_client):
    """RFC 8620 §2.1: unknown capability surfaces as a method error, HTTP 200."""
    resp = _post(authed_client, [["Echo", {"x": 1}, "c0"]], using=["urn:ietf:params:jmap:core", "urn:does:not:exist"])
    assert resp.status_code == 200
    (method, args, call), = resp.get_json()["methodResponses"]
    assert method == "error"
    assert args["type"] == "unknownCapability"
    assert "urn:does:not:exist" in args["description"]


def test_missing_core_capability_is_jmap_error(authed_client):
    resp = _post(authed_client, [["Echo", {}, "c0"]], using=["urn:ietf:params:jmap:mail"])
    assert resp.status_code == 200
    (method, args, call), = resp.get_json()["methodResponses"]
    assert args["type"] == "unknownCapability"


def test_echo_method(authed_client):
    resp = _post(authed_client, [["Echo", {"hello": "world"}, "c1"]])
    assert resp.status_code == 200
    (method, args, call_id), = resp.get_json()["methodResponses"]
    assert method == "Echo"
    assert args == {"hello": "world"}
    assert call_id == "c1"


# ---------------------------------------------------------------- #
# honest failure when no mail account is configured
# ---------------------------------------------------------------- #

def test_mailbox_get_without_account_returns_account_not_found(authed_client, monkeypatch):
    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: None)
    resp = _post(authed_client, [["Mailbox/get", {"accountId": "x"}, "c1"]])
    assert resp.status_code == 200
    (method, args, call), = resp.get_json()["methodResponses"]
    assert method == "error"
    assert args["type"] == "accountNotFound"


# ---------------------------------------------------------------- #
# Mailbox/get
# ---------------------------------------------------------------- #

def test_mailbox_get_lists_real_rows(authed_client, monkeypatch):
    gateway = FakeGateway()
    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: gateway)
    resp = _post(authed_client, [["Mailbox/get", {}, "c0"]])
    assert resp.status_code == 200
    (method, args, call), = resp.get_json()["methodResponses"]
    assert method == "Mailbox/get"
    assert args["notFound"] == []
    assert gateway.call_log == [("list_mailbox_rows", "u1")]
    inbox = next(m for m in args["list"] if m["name"] == "INBOX")
    assert inbox["role"] == "inbox"
    assert inbox["totalEmails"] == 2
    assert inbox["unreadEmails"] == 1
    sent = next(m for m in args["list"] if m["name"] == "Sent")
    assert sent["role"] == "sent"
    assert sent["totalEmails"] == 0


def test_mailbox_get_missing_id_in_not_found(authed_client, monkeypatch):
    gateway = FakeGateway()
    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: gateway)
    resp = _post(authed_client, [["Mailbox/get", {"ids": ["nope", _mailbox_id("INBOX")]}, "c0"]])
    (method, args, call), = resp.get_json()["methodResponses"]
    assert method == "Mailbox/get"
    assert "nope" in args["notFound"]
    assert len(args["list"]) == 1
    assert args["list"][0]["id"] == _mailbox_id("INBOX")


def test_mailbox_get_has_ids_roundtrip(authed_client, monkeypatch):
    """The id we hand clients must be decodable back to the folder path."""
    gateway = FakeGateway()
    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: gateway)
    resp = _post(authed_client, [["Mailbox/get", {}, "c0"]])
    (_, args, _), = resp.get_json()["methodResponses"]
    for m in args["list"]:
        import base64
        raw = base64.urlsafe_b64decode(m["id"]).decode()
        assert raw.startswith("mailbox:")

# ---------------------------------------------------------------- #
# Mailbox/set create/destroy
# ---------------------------------------------------------------- #

def test_mailbox_set_create_calls_gateway(authed_client, monkeypatch):
    gateway = FakeGateway()
    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: gateway)
    resp = _post(authed_client, [["Mailbox/set", {"create": {"k1": {"name": "Archive"}}}, "c0"]])
    assert resp.status_code == 200
    (method, args, call), = resp.get_json()["methodResponses"]
    assert method == "Mailbox/set"
    assert list(args["created"].keys()) == ["k1"]
    assert args["created"]["k1"]["name"] == "Archive"
    assert gateway.call_log[-1] == ("create_mailbox", "u1", "Archive", "")


def test_mailbox_set_destroy_calls_gateway(authed_client, monkeypatch):
    gateway = FakeGateway()
    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: gateway)
    resp = _post(authed_client, [["Mailbox/set", {"destroy": [_mailbox_id("Trash"), _mailbox_id("INBOX")]}, "c0"]])
    (_, args, _), = resp.get_json()["methodResponses"]
    assert args["destroyed"] == [_mailbox_id("Trash")]
    assert _mailbox_id("INBOX") in args["notDestroyed"]
    assert "cannot delete INBOX" in args["notDestroyed"][_mailbox_id("INBOX")]["description"]
    assert gateway.call_log == [("delete_mailbox", "u1", "Trash"), ("delete_mailbox", "u1", "INBOX")]


def test_mailbox_set_empty_name_is_invalid(authed_client, monkeypatch):
    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: FakeGateway())
    resp = _post(authed_client, [["Mailbox/set", {"create": {"c1": {}}}, "c0"]])
    (_, args, _), = resp.get_json()["methodResponses"]
    assert args["notCreated"]["c1"]["type"] == "invalidArguments"
    assert args["created"] == {}


# ---------------------------------------------------------------- #
# Email/get
# ---------------------------------------------------------------- #

def test_email_get_maps_store_mail(authed_client, monkeypatch):
    gateway = FakeGateway()
    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: gateway)
    resp = _post(authed_client, [["Email/get", {"ids": [_email_id("INBOX", "101")]}, "c0"]])
    assert resp.status_code == 200
    (method, args, call), = resp.get_json()["methodResponses"]
    assert method == "Email/get"
    assert args["notFound"] == []
    email = args["list"][0]
    assert email["subject"] == "Hello JMAP"
    assert email["from"] == [{"name": "Ada", "email": "ada@example.org"}]
    assert email["keywords"]["$seen"] is False
    assert email["size"] == 1234
    assert email["mailboxIds"] == {_mailbox_id("INBOX"): True}
    assert gateway.call_log == [("get_mail", "u1", "INBOX", "101")]


def test_email_get_unknown_id_in_not_found(authed_client, monkeypatch):
    gateway = FakeGateway()
    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: gateway)
    resp = _post(authed_client, [["Email/get", {"ids": ["bogus!"]}, "c0"]])
    (_, args, _), = resp.get_json()["methodResponses"]
    assert "bogus!" in args["notFound"]
    assert args["list"] == []


def test_email_get_missing_from_store_is_not_found(authed_client, monkeypatch):
    gateway = FakeGateway()
    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: gateway)
    resp = _post(authed_client, [["Email/get", {"ids": [_email_id("INBOX", "9999")]}, "c0"]])
    (_, args, _), = resp.get_json()["methodResponses"]
    assert args["list"] == []
    assert len(args["notFound"]) == 1


def test_email_get_list_flags_shape_does_not_server_fail(authed_client, monkeypatch):
    """Regression: the real store (_parse_mail) returns ``flags`` as a LIST of
    IMAP flag strings, not a dict. ``_mail_to_jmap`` must tolerate that shape
    instead of crashing into a serverFail error for an otherwise valid message
    (observed live on the demo: every Email/get on a real message 500'd)."""
    gateway = FakeGateway()
    # uid "88" mirrors the real _parse_mail output for a seen+flagged message.
    gateway.mails.setdefault("INBOX", []).append({
        "uid": "88",
        "subject": "List-flags mail",
        "from_": {"name": "Ada", "mail": "ada@example.org"},
        "to": [{"name": "Bob", "mail": "bob@example.org"}],
        "cc": [],
        "date": "2026-08-01T11:00:00Z",
        "size": 256,
        "seen": False,
        "flagged": False,
        "has_attachment": False,
        "contents": [{"contentType": "text/plain", "content": "body"}],
        "attachments": [],
        "flags": ["\\Seen", "\\Flagged"],
    })
    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: gateway)
    resp = _post(authed_client, [["Email/get", {"ids": [_email_id("INBOX", "88")]}, "c0"]])
    assert resp.status_code == 200
    (method, args, call), = resp.get_json()["methodResponses"]
    assert method == "Email/get"
    assert args["notFound"] == []
    email = args["list"][0]
    assert email["subject"] == "List-flags mail"
    assert email["keywords"] == {"$seen": True, "$flagged": True}


# ---------------------------------------------------------------- #
# Email/query
# ---------------------------------------------------------------- #

def test_email_query_returns_encoded_ids(authed_client, monkeypatch):
    gateway = FakeGateway()
    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: gateway)
    resp = _post(authed_client, [["Email/query", {"filter": {"inMailboxes": [_mailbox_id("INBOX")]}}, "c0"]])
    (method, args, call), = resp.get_json()["methodResponses"]
    assert method == "Email/query"
    assert gateway.call_log == [("get_mails", "u1", "INBOX", 100)]
    assert len(args["ids"]) == 2
    assert _email_id("INBOX", "101") in args["ids"]
    assert args["total"] == 2


def test_email_query_no_filter_scans_all_mailboxes(authed_client, monkeypatch):
    gateway = FakeGateway()
    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: gateway)
    resp = _post(authed_client, [["Email/query", {}, "c0"]])
    (_, args, _), = resp.get_json()["methodResponses"]
    assert ("list_mailbox_rows", "u1") in gateway.call_log
    assert any(call[0] == "get_mails" for call in gateway.call_log)


# ---------------------------------------------------------------- #
# Email/set destroy/move
# ---------------------------------------------------------------- #

def test_email_set_destroy_calls_gateway(authed_client, monkeypatch):
    gateway = FakeGateway()
    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: gateway)
    resp = _post(authed_client, [["Email/set", {"destroy": [_email_id("INBOX", "101")]}, "c0"]])
    (_, args, _), = resp.get_json()["methodResponses"]
    assert args["destroyed"] == [_email_id("INBOX", "101")]
    assert gateway.call_log == [("destroy_mail", "u1", "INBOX", "101")]


def test_email_set_create_is_honest_refusal(authed_client, monkeypatch):
    gateway = FakeGateway()
    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: gateway)
    resp = _post(authed_client, [["Email/set", {"create": {"c1": {"mailboxIds": {_mailbox_id("INBOX"): True}}}}, "c0"]])
    (_, args, _), = resp.get_json()["methodResponses"]
    assert args["created"] == {}
    assert args["notCreated"]["c1"]["type"] == "invalidArguments"
    assert "not implemented" in args["notCreated"]["c1"]["description"]


def test_email_set_update_move(authed_client, monkeypatch):
    gateway = FakeGateway()
    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: gateway)
    resp = _post(authed_client, [["Email/set", {"update": {
        _email_id("INBOX", "3"): {"mailboxIds": {_mailbox_id("Archive"): True}}}}, "c0"]])
    (_, args, _), = resp.get_json()["methodResponses"]
    assert _email_id("INBOX", "3") in args["updated"]
    assert gateway.call_log == [("move_mail", "u1", "INBOX", 3, "Archive")]


# ---------------------------------------------------------------- #
# Error surfaces
# ---------------------------------------------------------------- #

def test_unknown_method_returns_unknown_method_error(authed_client, monkeypatch):
    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: FakeGateway())
    resp = _post(authed_client, [["Nope/get", {}, "c9"]])
    (method, args, call), = resp.get_json()["methodResponses"]
    assert method == "error"
    assert args["type"] == "unknownMethod"
    assert call == "c9"


def test_last_response_never_500s_on_gateway_error(authed_client, monkeypatch):
    class Boom(FakeGateway):
        def list_mailbox_rows(self, account_id):
            raise RuntimeError("boom")

    monkeypatch.setattr("app.api.v1.admin.ApiJmapProtocol._gateway", lambda: Boom())
    resp = _post(authed_client, [["Mailbox/get", {}, "c0"]])
    assert resp.status_code == 200
    (method, args, call), = resp.get_json()["methodResponses"]
    assert method == "error"
    assert args["type"] == "serverFail"
