"""Exchange ActiveSync endpoint tests.

The EAS surface must be real protocol: WBXML 1.3 bytes out, store-backed
folders/mails/attachments, real change deltas in Sync, and honest error
statuses when no mail context exists.  The store is faked at the
``_gateway()`` seam; production uses ActiveSyncGateway over ModuleMail.
"""
from __future__ import annotations

import base64

import pytest

from app import create_app
from app.service.activesync.Wbxml import WbxmlDecoder
from app.utils import constants as cs

EAS = "/api/admin/v1/Microsoft-Server-ActiveSync"
DEVICE = "test-device-0001"


@pytest.fixture()
def authed_client(monkeypatch):
    from app.auth.Admin import Admin

    app = create_app(cs.SOGO_NOT_INIT)
    app.config["TESTING"] = True
    monkeypatch.setattr("app.VoucherAdminService.__init__", lambda self, ps: None)
    monkeypatch.setattr(
        "app.VoucherAdminService.generate_admin_from_voucher",
        staticmethod(lambda token: Admin("smoke-admin")),
    )
    client = app.test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = "Bearer test-token"
    client.environ_base["HTTP_X_MS_DEVICEID"] = DEVICE
    return client


class FakeGateway:
    def __init__(self, folders=None, mails=None):
        self.folders = folders or [
            {cs.FOLDER_PATH: "INBOX", cs.FOLDER_NAME: "INBOX", cs.FOLDER_TYPE: "INBOX",
             cs.FOLDER_COUNT: 2, cs.FOLDER_UNSEEN: 1},
            {cs.FOLDER_PATH: "Sent", cs.FOLDER_NAME: "Sent", cs.FOLDER_TYPE: "SENT",
             cs.FOLDER_COUNT: 0, cs.FOLDER_UNSEEN: 0},
        ]
        self.mails = mails if mails is not None else {"INBOX": [
            {"uid": "101", "subject": "hi", "from_": {"mail": "a@x.org", "name": "A"},
             "to": [{"email": "b@x.org"}], "date": "2026-08-01T10:00:00Z",
             "raw": "From: a@x.org\r\nSubject: hi\r\n\r\nbody"},
            {"uid": "3", "subject": "second", "from_": {"mail": "c@x.org", "name": ""},
             "to": [], "date": None, "raw": "From: c@x.org\r\nSubject: second\r\n\r\nb2"},
        ]}
        self.sent: list = []
        self.call_log: list = []

    def list_mailbox_rows(self, account_id):
        self.call_log.append(("list_mailbox_rows", account_id))
        return self.folders

    def get_folder_mails(self, account_id, folder, limit, offset=0):
        self.call_log.append(("get_folder_mails", account_id, folder, limit))
        items = self.mails.get(folder, [])
        return items, len(items)

    def get_mail_detail(self, account_id, folder, uid):
        self.call_log.append(("get_mail_detail", account_id, folder, uid))
        for m in self.mails.get(folder, []):
            if str(m["uid"]) == str(uid):
                return m
        from app.utils.exceptions import RequestException
        raise RequestException("not found")

    def get_mail_raw(self, account_id, folder, uid):
        self.call_log.append(("get_mail_raw", account_id, folder, uid))
        for m in self.mails.get(folder, []):
            if str(m["uid"]) == str(uid):
                return m["raw"]
        from app.utils.exceptions import RequestException
        raise RequestException("not found")

    def destroy_mail(self, account_id, folder, uid):
        self.call_log.append(("destroy_mail", account_id, folder, uid))

    def send_message(self, account_id, message):
        self.call_log.append(("send_message", account_id))
        self.sent.append(message)


def install(monkeypatch, gateway):
    monkeypatch.setattr("app.api.v1.admin.ApiActiveSync._gateway", lambda: gateway)
    return gateway


def _text(payload, name):
    for node, p in (payload or []):
        if node == name:
            for inner, value in (p or []):
                if inner == "$text":
                    return value
            return None
    return None


def _payload(tree, name):
    for node, p in tree:
        if node == name:
            return p
    raise AssertionError(f"element {name} missing in {tree}")


def _provision(client) -> str:
    """Provision the fixture device and return its policy key."""
    resp = client.post(f"{EAS}/Provision", json={"PolicyType": "basic"})
    assert resp.status_code == 200
    assert resp.content_type == "application/vnd.ms-sync.wbxml"
    (name, payload), = WbxmlDecoder.decode(resp.data)
    assert name == "Provision"
    policies = _payload(payload, "Policies")
    policy = _payload(policies, "Policy")
    return _text(policy, "PolicyKey")


# ---------------------------------------------------------------- #
# wire format + status
# ---------------------------------------------------------------- #

def test_status_reports_real_wbxml(authed_client, monkeypatch):
    monkeypatch.setattr("app.api.v1.admin.ApiActiveSync._gateway", lambda: None)
    resp = authed_client.get(f"{EAS}/status")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["wire_format"] == "wbxml-1.3"
    assert "FolderSync" in data["supported_commands"]


def test_provision_returns_wbxml_with_policy_key(authed_client):
    resp = authed_client.post(f"{EAS}/Provision", json={"PolicyType": "strict"})
    assert resp.status_code == 200
    assert resp.content_type == "application/vnd.ms-sync.wbxml"
    (name, payload), = WbxmlDecoder.decode(resp.data)
    assert name == "Provision"
    assert _text(payload, "Status") == "1"
    policy = _payload(_payload(payload, "Policies"), "Policy")
    assert _text(policy, "PolicyType") == "strict"
    assert _text(policy, "PolicyKey") != ""


# ---------------------------------------------------------------- #
# FolderSync
# ---------------------------------------------------------------- #

def test_foldersync_uses_real_store_rows(authed_client, monkeypatch):
    gateway = install(monkeypatch, FakeGateway())
    resp = authed_client.post(f"{EAS}/FolderSync", json={"SyncKey": "0"})
    assert resp.status_code == 200
    assert resp.content_type.startswith("application/vnd.ms-sync.wbxml")
    (name, payload), = WbxmlDecoder.decode(resp.data)
    assert name == "FolderSync"
    assert gateway.call_log == [("list_mailbox_rows", "default")]
    assert _text(payload, "Status") == "1"
    changes = _payload(payload, "Changes")
    count = int(_text(changes, "Count"))
    assert count == 2
    adds = _payload(changes, "Add")
    folders = [p for n, p in adds if n == "Folder"]
    inbox = next(f for f in folders if _text(f, "DisplayName") == "INBOX")
    assert _text(inbox, "Type") == "2"
    server_id = _text(inbox, "ServerId")
    assert base64.urlsafe_b64decode(server_id.encode()).startswith(b"f:")


def test_foldersync_without_store_is_server_failure(authed_client, monkeypatch):
    monkeypatch.setattr("app.api.v1.admin.ApiActiveSync._gateway", lambda: None)
    resp = authed_client.post(f"{EAS}/FolderSync", json={"SyncKey": "0"})
    (_, payload), = WbxmlDecoder.decode(resp.data)
    # server failure — no fabricated folders
    assert _text(payload, "Status") == "6"


# ---------------------------------------------------------------- #
# Sync
# ---------------------------------------------------------------- #

def test_sync_first_run_adds_all_uids(authed_client, monkeypatch):
    install(monkeypatch, FakeGateway())
    key = _provision(authed_client)
    resp = authed_client.post(
        f"{EAS}/Sync",
        headers={"MS-ASPolicyKey": key},
        json={"SyncKey": "0", "CollectionId": "INBOX"},
    )
    assert resp.status_code == 200
    (name, payload), = WbxmlDecoder.decode(resp.data)
    assert name == "Sync"
    assert _text(payload, "Status") == "1"
    commands = _payload(_payload(payload, "Collection"), "Commands")
    adds = [p for n, p in commands if n == "Add"]
    server_ids = {_text(a, "ServerId") for a in adds}
    assert server_ids == {"101", "3"}
    subjects = {_text(_payload(a, "ApplicationData"), "Subject") for a in adds}
    assert subjects == {"hi", "second"}
    # real raw MIME in the body transport
    body = _payload(_payload(adds[0], "ApplicationData"), "Body")
    data_payload = _payload(body, "Data")
    assert data_payload[0] == ("$opaque", b"From: a@x.org\r\nSubject: hi\r\n\r\nbody")


def test_sync_wrong_policy_key_is_449(authed_client, monkeypatch):
    install(monkeypatch, FakeGateway())
    resp = authed_client.post(
        f"{EAS}/Sync",
        headers={"MS-ASPolicyKey": "bogus"},
        json={"SyncKey": "0", "CollectionId": "INBOX"},
    )
    (_, payload), = WbxmlDecoder.decode(resp.data)
    assert _text(payload, "Status") == "449"


def test_sync_incremental_only_deltas(authed_client, monkeypatch):
    gateway = install(monkeypatch, FakeGateway())
    key = _provision(authed_client)
    headers = {"MS-ASPolicyKey": key}

    first = authed_client.post(f"{EAS}/Sync", headers=headers,
                               json={"SyncKey": "0", "CollectionId": "INBOX"})
    (_, payload), = WbxmlDecoder.decode(first.data)
    sync_key = _text(payload, "SyncKey")
    assert sync_key

    # the store gains a new mail between the two syncs
    gateway.mails["INBOX"].append({
        "uid": "777", "subject": "new", "from_": {"mail": "d@x.org", "name": ""},
        "to": [], "date": None, "raw": "From: d@x.org\r\nSubject: new\r\n\r\n",
    })

    second = authed_client.post(f"{EAS}/Sync", headers=headers,
                                json={"SyncKey": sync_key, "CollectionId": "INBOX"})
    (_, payload2), = WbxmlDecoder.decode(second.data)
    commands2 = _payload(_payload(payload2, "Collection"), "Commands")
    adds2 = [p for n, p in commands2 if n == "Add"]
    deletes2 = [p for n, p in commands2 if n == "Delete"]
    assert len(adds2) == 1
    assert _text(adds2[0], "ServerId") == "777"
    assert _text(_payload(adds2[0], "ApplicationData"), "Subject") == "new"
    assert deletes2 == []


def test_sync_incremental_reports_deletions(authed_client, monkeypatch):
    gateway = install(monkeypatch, FakeGateway())
    key = _provision(authed_client)
    headers = {"MS-ASPolicyKey": key}

    first = authed_client.post(f"{EAS}/Sync", headers=headers,
                               json={"SyncKey": "0", "CollectionId": "INBOX"})
    (_, payload), = WbxmlDecoder.decode(first.data)
    sync_key = _text(payload, "SyncKey")

    # a mail disappears from the store
    gateway.mails["INBOX"] = [m for m in gateway.mails["INBOX"] if m["uid"] != "101"]

    second = authed_client.post(f"{EAS}/Sync", headers=headers,
                                json={"SyncKey": sync_key, "CollectionId": "INBOX"})
    (_, payload2), = WbxmlDecoder.decode(second.data)
    commands2 = _payload(_payload(payload2, "Collection"), "Commands")
    adds2 = [p for n, p in commands2 if n == "Add"]
    deletes2 = [p for n, p in commands2 if n == "Delete"]
    assert adds2 == []
    assert len(deletes2) == 1
    assert _text(deletes2[0], "ServerId") == "101"


def test_sync_without_store_is_server_failure(authed_client, monkeypatch):
    monkeypatch.setattr("app.api.v1.admin.ApiActiveSync._gateway", lambda: None)
    key = _provision(authed_client)
    resp = authed_client.post(f"{EAS}/Sync", headers={"MS-ASPolicyKey": key},
                              json={"SyncKey": "0", "CollectionId": "INBOX"})
    (_, payload), = WbxmlDecoder.decode(resp.data)
    assert _text(payload, "Status") == "7"


# ---------------------------------------------------------------- #
# SendMail / GetAttachment
# ---------------------------------------------------------------- #

def test_sendmail_delivers_raw_rfc5322(authed_client, monkeypatch):
    gateway = install(monkeypatch, FakeGateway())
    raw = b"From: a@example.org\r\nTo: b@example.org\r\nSubject: real send\r\n\r\nhello"
    resp = authed_client.post(f"{EAS}/SendMail", data=raw,
                              content_type="application/octet-stream")
    assert resp.status_code == 200
    assert resp.data == b""
    assert len(gateway.sent) == 1
    assert gateway.sent[0]["Subject"] == "real send"


def test_sendmail_without_store_fails(authed_client, monkeypatch):
    monkeypatch.setattr("app.api.v1.admin.ApiActiveSync._gateway", lambda: None)
    resp = authed_client.post(f"{EAS}/SendMail", data=b"From: a\r\n\r\nx",
                              content_type="application/octet-stream")
    assert resp.status_code == 500


def test_getattachment_real_bytes(authed_client, monkeypatch):
    raw = (
        "From: a@example.org\r\nSubject: att\r\nMIME-Version: 1.0\r\n"
        "Content-Type: multipart/mixed; boundary=xyz\r\n\r\n"
        "--xyz\r\nContent-Type: text/plain\r\n\r\nbody text\r\n"
        "--xyz\r\nContent-Type: application/pdf\r\n"
        "Content-Disposition: attachment; filename=doc.pdf\r\n"
        "Content-Transfer-Encoding: base64\r\n\r\n"
        "JVBERi0xLg==\r\n--xyz--\r\n"
    )
    gateway = FakeGateway(mails={"INBOX": [{"uid": "9", "raw": raw}]})
    install(monkeypatch, gateway)

    attachment_id = base64.urlsafe_b64encode(b"att:INBOX\x009\x002").decode("ascii")
    resp = authed_client.get(f"{EAS}/GetAttachment", query_string={"AttachmentId": attachment_id})
    assert resp.status_code == 200
    assert resp.data == b"%PDF-1."
    assert resp.content_type == "application/pdf"


def test_getattachment_missing_is_404(authed_client, monkeypatch):
    install(monkeypatch, FakeGateway())
    bad = base64.urlsafe_b64encode(b"att:INBOX\x00999\x009").decode("ascii")
    resp = authed_client.get(f"{EAS}/GetAttachment", query_string={"AttachmentId": bad})
    assert resp.status_code == 404