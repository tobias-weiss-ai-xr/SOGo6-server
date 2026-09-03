"""
Unit tests for ModuleMailOutgoing — outgoing-mail configuration resolution and
the RFC 5322 message building used by every send path.

Pins down:
  * _get_outgoing_conf: main identity (smtp / sendmail), system master
    credentials, shared-mailbox resolution (member/not-member/not-found),
    external-account resolution and its 404
  * _open_client_for: manager dispatch to the REGISTRY_MANAGER class and the
    connect/login contract (incl. do_login=False)
  * send_mail: header assembly (Cc/Bcc/priority/reply-to/return-receipt,
    Message-ID generation, Date refresh, extra-header injection that cannot
    overwrite protected headers), multipart vs plain bodies, attachments and
    their error path
  * send_mime_message: MIME passthrough (Message/str/bytes/callable) with
    To/Subject/From/Message-ID/Date bookkeeping
  * send_raw_message: client handoff + logging

All external dependencies (DB manager import, shared mailbox module, password
decryption, outgoing SMTP client) are replaced with fakes.
"""
from __future__ import annotations

import re
from email import message_from_string
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.module.mail.ModuleMailOutgoing import (
    REGISTRY_MANAGER,
    ModuleMailOutgoing,
)
from app.utils import constants as cs
from app.utils import errors as err
from app.utils.exceptions import RequestException


class FakeProfile:
    def __init__(self, external_accounts=None, p_db_type="PostgreSQL"):
        self.external_accounts = external_accounts or {}
        self.p_db_type = p_db_type

    def get_db_settings(self):
        return {"db_settings": True}


class FakeUser:
    def __init__(self, uid="u1", login="user@example.org", password="pw", external_accounts=None):
        self.uid = uid
        self.login_mail_outgoing = login
        self.password = password
        self.profile = FakeProfile(external_accounts)


def make_settings(**overrides):
    base = {
        "SOGO_D_MAIL_OUTGOING_TYPE": "smtp",
        "SOGO_D_SMTP_SERVER": "smtp.example.org",
        "SOGO_D_SMTP_PORT": 587,
        "SOGO_D_SMTP_ENCRYPTION": "starttls",
        "SOGO_D_SMTP_AUTH_MECH": "plain",
        "SOGO_D_SMTP_MASTER_ENABLED": False,
        "SOGO_D_SMTP_MASTER_LOGIN": "master-login",
        "SOGO_D_SMTP_MASTER_PWD": "enc-master-pwd",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def make_module(user=None, settings=None):
    return ModuleMailOutgoing(
        user=user if user is not None else FakeUser(),
        mail_settings=settings if settings is not None else make_settings(),
    )


def external_identity():
    return {
        "type": "smtp",
        "username": "ext@example.org",
        "password": "enc-pw",
        "server": "smtp.ext.org",
        "port": 465,
        "encryption": "ssl",
        "auth_mech": "plain",
    }


# ---------------------------------------------------------------------------
# _get_outgoing_conf — main identity
# ---------------------------------------------------------------------------

def test_main_identity_smtp_uses_domain_settings():
    module = make_module()
    conf = module._get_outgoing_conf(cs.DEFAULT_IDENTITY_KEY_VALUE)
    assert conf["type"] == "smtp"
    assert conf["username"] == "user@example.org"
    assert conf["password"] == "pw"
    assert conf["authname"] == ""
    assert conf["args"] == {
        "server": "smtp.example.org",
        "port": 587,
        "encryption": "starttls",
        "auth_mech": "plain",
    }


def test_system_master_credentials_override(monkeypatch):
    module = make_module(settings=make_settings(SOGO_D_SMTP_MASTER_ENABLED=True))
    monkeypatch.setattr(
        "app.module.mail.ModuleMailOutgoing.decrypt_password", lambda s: f"dec-{s}")
    conf = module._get_outgoing_conf(cs.DEFAULT_IDENTITY_KEY_VALUE, is_system=True)
    assert conf["username"] == "master-login"
    assert conf["password"] == "dec-enc-master-pwd"
    # real sender stays the user's address
    assert conf["authname"] == "user@example.org"


def test_system_is_not_enough_when_master_disabled():
    module = make_module(settings=make_settings(SOGO_D_SMTP_MASTER_ENABLED=False))
    conf = module._get_outgoing_conf(cs.DEFAULT_IDENTITY_KEY_VALUE, is_system=True)
    assert conf["username"] == "user@example.org"
    assert conf["password"] == "pw"


def test_main_identity_sendmail_has_no_args():
    module = make_module(settings=make_settings(SOGO_D_MAIL_OUTGOING_TYPE="sendmail"))
    conf = module._get_outgoing_conf(cs.DEFAULT_IDENTITY_KEY_VALUE)
    assert conf["type"] == "sendmail"
    assert conf["args"] == {}
    assert conf["authname"] == ""


# ---------------------------------------------------------------------------
# _get_outgoing_conf — shared mailbox
# ---------------------------------------------------------------------------

def _fake_shared_infra(monkeypatch, mailbox, p_db_type="PostgreSQL"):
    """Patch the DB-manager import and ModuleSharedMailbox used by the shared path."""
    fake_db = MagicMock()
    shared_module = MagicMock()
    shared_module.get_by_id.return_value = mailbox
    monkeypatch.setattr(
        "app.utils.module.importManager.import_and_instantiate_manager",
        lambda module_path, module_and_class_name, module_args: fake_db,
    )
    monkeypatch.setattr(
        "app.module.admin.ModuleSharedMailbox.ModuleSharedMailbox",
        lambda db: shared_module,
    )
    return fake_db, shared_module


def test_shared_mailbox_member_uses_mailbox_email(monkeypatch):
    mailbox = {"email": "shared@example.org", "member_uids": ["u1"]}
    _fake_shared_infra(monkeypatch, mailbox)
    module = make_module(user=FakeUser(uid="u1"))
    conf = module._get_outgoing_conf("shared-mailbox-uuid")
    assert conf["username"] == "shared@example.org"
    assert conf["password"] == "pw"
    assert conf["type"] == "smtp"
    assert conf["args"]["server"] == "smtp.example.org"


def test_shared_mailbox_sendmail_has_no_args(monkeypatch):
    mailbox = {"email": "shared@example.org", "member_uids": ["u1"]}
    _fake_shared_infra(monkeypatch, mailbox)
    module = make_module(
        user=FakeUser(uid="u1"),
        settings=make_settings(SOGO_D_MAIL_OUTGOING_TYPE="sendmail"),
    )
    conf = module._get_outgoing_conf("shared-mailbox-uuid")
    assert conf["args"] == {}


def test_shared_mailbox_non_member_raises_403(monkeypatch):
    mailbox = {"email": "shared@example.org", "member_uids": ["someone-else"]}
    _fake_shared_infra(monkeypatch, mailbox)
    with pytest.raises(RequestException) as exc:
        make_module(user=FakeUser(uid="u1"))._get_outgoing_conf("shared-mailbox-uuid")
    assert exc.value.http_status == 403
    assert exc.value.error.c == err.ERROR_SHARED_MAILBOX_NOT_FOUND.c


def test_shared_mailbox_not_found_raises_404(monkeypatch):
    _fake_shared_infra(monkeypatch, None)
    with pytest.raises(RequestException) as exc:
        make_module(user=FakeUser(uid="u1"))._get_outgoing_conf("shared-mailbox-uuid")
    assert exc.value.http_status == 404
    assert exc.value.error.c == err.ERROR_SHARED_MAILBOX_NOT_FOUND.c


# ---------------------------------------------------------------------------
# _get_outgoing_conf — external accounts
# ---------------------------------------------------------------------------

def test_external_account_resolves_and_decrypts(monkeypatch):
    user = FakeUser(external_accounts={"ext-1": {"mail_outgoing": external_identity()}})
    monkeypatch.setattr(
        "app.module.mail.ModuleMailOutgoing.decrypt_password", lambda s: f"dec-{s}")
    conf = make_module(user=user)._get_outgoing_conf("ext-1")
    assert conf["username"] == "ext@example.org"
    assert conf["password"] == "dec-enc-pw"
    assert conf["type"] == "smtp"
    assert conf["args"]["server"] == "smtp.ext.org"
    assert conf["args"]["port"] == 465


def test_external_account_missing_raises_404():
    user = FakeUser(external_accounts={"ext-1": {"mail_outgoing": external_identity()}})
    with pytest.raises(RequestException) as exc:
        make_module(user=user)._get_outgoing_conf("ext-unknown")
    assert exc.value.http_status == 404
    assert exc.value.error.c == err.ERROR_EXTERNAL_ACCOUNT_NOT_FOUND.c


def test_external_accounts_absent_raises_404():
    user = FakeUser(external_accounts={})
    with pytest.raises(RequestException) as exc:
        make_module(user=user)._get_outgoing_conf("ext-1")
    assert exc.value.http_status == 404


# ---------------------------------------------------------------------------
# _open_client_for
# ---------------------------------------------------------------------------

def test_open_client_for_dispatches_connects_and_logins(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(
        "app.module.mail.ModuleMailOutgoing.import_and_instantiate_manager",
        lambda module_path, module_and_class_name, module_args: client,
    )
    module = make_module()
    result = module._open_client_for(cs.DEFAULT_IDENTITY_KEY_VALUE)
    assert result is client
    client.connect.assert_called_once()
    client.login.assert_called_once_with("user@example.org", "pw", "")
    assert REGISTRY_MANAGER["smtp"] == "ClientSmtp"
    assert REGISTRY_MANAGER["sendmail"] == "ClientSendmail"


def test_open_client_for_can_skip_login(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(
        "app.module.mail.ModuleMailOutgoing.import_and_instantiate_manager",
        lambda *a, **k: client,
    )
    make_module()._open_client_for(cs.DEFAULT_IDENTITY_KEY_VALUE, do_login=False)
    client.login.assert_not_called()
    client.connect.assert_called_once()


# ---------------------------------------------------------------------------
# send_mail — message building
# ---------------------------------------------------------------------------

def _install_client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(
        "app.module.mail.ModuleMailOutgoing.import_and_instantiate_manager",
        lambda *a, **k: client,
    )
    return client


def mail_data(**overrides):
    data = {
        "from_addr": "user@example.org",
        "to": ["a@example.org", "b@example.org"],
        "subject": "Hello",
        "body": "hi there",
        "is_html": True,
    }
    data.update(overrides)
    return data


def test_send_mail_builds_full_message(monkeypatch):
    client = _install_client(monkeypatch)
    module = make_module()
    message = module.send_mail(cs.DEFAULT_IDENTITY_KEY_VALUE, mail_data(
        cc=["cc@example.org"],
        bcc=["bcc@example.org"],
        priority=1,
        reply_to="reply@example.org",
        return_receipt=True,
    ))
    assert message["From"] == "user@example.org"
    assert message["To"] == "a@example.org, b@example.org"
    assert message["Cc"] == "cc@example.org"
    assert message["Bcc"] == "bcc@example.org"
    assert message["Subject"] == "Hello"
    assert message["X-Priority"] == "1"
    assert message["Reply-To"] == "reply@example.org"
    assert message["Disposition-Notification-To"] == "user@example.org"
    assert message["Return-Receipt-To"] == "user@example.org"
    assert re.match(r"<[^>]+@example\.org>", message["Message-ID"])
    assert message["Date"]
    # html → multipart/alternative with plain + html parts
    assert message.get_content_type() == "multipart/alternative"
    parts = list(message.iter_parts())
    assert parts[0].get_content_type() == "text/plain"
    assert parts[1].get_content_type() == "text/html"
    client.send_mail.assert_called_once_with(message)


def test_send_mail_plain_text_is_singlepart(monkeypatch):
    _install_client(monkeypatch)
    module = make_module()
    message = module.send_mail(cs.DEFAULT_IDENTITY_KEY_VALUE, mail_data(is_html=False))
    assert message.get_content_type() == "text/plain"
    assert message.get_content().rstrip("\n") == "hi there"


def test_send_mail_omits_optional_headers(monkeypatch):
    _install_client(monkeypatch)
    message = make_module().send_mail(cs.DEFAULT_IDENTITY_KEY_VALUE, mail_data())
    assert "Cc" not in message
    assert "Bcc" not in message
    assert "X-Priority" not in message
    assert "Reply-To" not in message
    assert "Disposition-Notification-To" not in message


def test_send_mail_adds_attachments(monkeypatch):
    _install_client(monkeypatch)
    attachments = [
        {"data": b"\x89PNG", "filename": "img.png"},
        {"data": b"%PDF", "filename": "doc.pdf"},
    ]
    message = make_module().send_mail(
        cs.DEFAULT_IDENTITY_KEY_VALUE, mail_data(attachments=attachments))
    attached = [p for p in message.walk() if p.get_filename()]
    assert [p.get_filename() for p in attached] == ["img.png", "doc.pdf"]


def test_send_mail_attachment_missing_data_raises(monkeypatch):
    _install_client(monkeypatch)
    with pytest.raises(RequestException) as exc:
        make_module().send_mail(
            cs.DEFAULT_IDENTITY_KEY_VALUE,
            mail_data(attachments=[{"filename": "broken.txt"}]),
        )
    assert exc.value.error.c == err.ERROR_MISSING_ACTION_DATA.c


def test_send_mail_extra_headers_cannot_overwrite_protected(monkeypatch):
    _install_client(monkeypatch)
    message = make_module().send_mail(
        cs.DEFAULT_IDENTITY_KEY_VALUE,
        mail_data(subject="Real subject"),
        extra_headers={
            "Subject": "Hijack attempt",
            "From": "evil@example.org",
            "Message-ID": "<evil@example.org>",
            "X-Custom": "custom-value",
        },
    )
    assert message["Subject"] == "Real subject"
    assert message["From"] == "user@example.org"
    assert not message["Message-ID"].startswith("<evil@")
    assert message["X-Custom"] == "custom-value"


def test_send_mail_injects_extra_threading_headers(monkeypatch):
    _install_client(monkeypatch)
    message = make_module().send_mail(
        cs.DEFAULT_IDENTITY_KEY_VALUE,
        mail_data(),
        extra_headers={"In-Reply-To": "<orig@example.org>", "References": "<a@example.org> <b@example.org>"},
    )
    assert message["In-Reply-To"] == "<orig@example.org>"
    assert message["References"] == "<a@example.org> <b@example.org>"


# ---------------------------------------------------------------------------
# send_raw_message / send_mime_message
# ---------------------------------------------------------------------------

def test_send_raw_message_opens_client_and_sends(monkeypatch):
    client = _install_client(monkeypatch)
    message = EmailMessage()
    message["Subject"] = "raw"
    make_module().send_raw_message(cs.DEFAULT_IDENTITY_KEY_VALUE, message)
    client.connect.assert_called_once()
    client.send_mail.assert_called_once_with(message)


def test_send_mime_message_keeps_existing_headers(monkeypatch):
    client = _install_client(monkeypatch)
    module = make_module()
    mime = message_from_string(
        "From: original@example.org\r\nSubject: Keep me\r\nTo: target@example.org\r\n"
        "Message-ID: <existing@example.org>\r\n\r\nbody")
    out = module.send_mime_message(["target@example.org"], "ignored-subject", mime)
    assert out["From"] == "original@example.org"
    assert out["Subject"] == "Keep me"
    assert out["To"] == "target@example.org"
    assert out["Message-ID"] == "<existing@example.org>"
    assert out["Date"]  # Date always refreshed
    client.send_mail.assert_called_once_with(out)


def test_send_mime_message_fills_missing_headers(monkeypatch):
    _install_client(monkeypatch)
    module = make_module()
    out = module.send_mime_message("to@example.org", "Filled", "<html></html>", from_addr="snd@example.org")
    assert out["To"] == "to@example.org"
    assert out["Subject"] == "Filled"
    assert out["From"] == "snd@example.org"
    assert re.match(r"<[^>]+@example\.org>", out["Message-ID"])


def test_send_mime_message_accepts_bytes(monkeypatch):
    _install_client(monkeypatch)
    raw = b"Subject: bytes\r\n\r\nhello"
    out = make_module().send_mime_message("t@example.org", "s", raw)
    assert out["Subject"] == "bytes"
    assert out["To"] == "t@example.org"


def test_send_mime_message_accepts_callable_lazy_build(monkeypatch):
    _install_client(monkeypatch)
    built = {"built": True}

    def lazy():
        msg = EmailMessage()
        msg["Subject"] = "lazy"
        setattr(msg, "marker", built)
        return msg

    out = make_module().send_mime_message("t@example.org", "s", lazy)
    assert out["Subject"] == "lazy"
    assert getattr(out, "marker") == built
    assert built["built"] is True


def test_send_mime_message_default_account_is_main(monkeypatch):
    client = _install_client(monkeypatch)
    make_module().send_mime_message("t@example.org", "s", "Subject: x\n\nb")
    # send_raw_message called with the default identity
    client.send_mail.assert_called_once()
