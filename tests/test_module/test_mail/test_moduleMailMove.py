"""
Unit regression tests for ModuleMail.move_mails — the RFC 4315 "move does not
leave a ghost" semantics fixed in a873f33 (client.uid_expunge after flagging)
and c195470/operator patch (uid_copy must SELECT the source folder; source
copies are flagged \\Deleted then expunged).

These tests pin down the exact client interaction contract of move_mails:

  * modern path:  uid_copy(uid_list, to, source_folder=from)
                  add_flags_to_mail(from, uid_list, ['\\Deleted'])
                  uid_expunge(from, uid_list)     <- RFC 4315, exact UIDs
  * fallback 1:   no uid_expunge  -> expunge_folder(from, do_subfolders=False)
  * fallback 2:   no uid_copy     -> per-mail copy_mail_to_mailbox loop (still
                                     appended then expunged afterwards)
  * empty input   -> {"moved_ids": []}, zero client interaction
  * missing/invalid to_folder -> RequestException
"""
import pytest

from app.module.mail.ModuleMail import ModuleMail
from app.utils.exceptions import RequestException
from unittest.mock import MagicMock


class _Base:
    """Shared fake client surface (no uid_copy / no uid_expunge here).
    Subclasses add exactly the primitives they emulate so that the module's
    hasattr() capability checks behave like on real servers."""

    def __init__(self, fail_copy=False):
        self.calls = []  # (method, args)
        self.fail_copy = fail_copy
        self.fail_expunge = False

    def add_flags_to_mail(self, folder_name, mail_uid, flags):
        self.calls.append(("add_flags", (folder_name, list(mail_uid), list(flags))))

    def copy_mail_to_mailbox(self, src_folder, mail_uid, dest_folder, create_dest=False):
        self.calls.append(("copy_one", (src_folder, str(mail_uid), dest_folder)))

    def expunge_folder(self, folder_path, do_subfolders=True):
        self.calls.append(("expunge_folder", (folder_path, do_subfolders)))

    def _uid_copy(self, uid_list, to_folder, source_folder=None):
        self.calls.append(("uid_copy", (list(uid_list), to_folder, source_folder)))
        if self.fail_copy:
            raise RequestException("copy failed")

    def _uid_expunge(self, folder_path, mail_uids):
        self.calls.append(("uid_expunge", (folder_path, list(mail_uids))))
        if self.fail_expunge:
            raise RequestException("expunge failed")


class ModernClient(_Base):
    """A modern ClientImap-like fake: has uid_copy + uid_expunge + flags."""

    uid_copy = _Base._uid_copy
    uid_expunge = _Base._uid_expunge


class FolderExpungeClient(_Base):
    """A client WITHOUT uid_expunge (RFC 4315 UIDPLUS unsupported) -> the
    folder-wide expunge fallback. uid_expunge is genuinely absent: hasattr is
    False and move_mails picks expunge_folder."""

    uid_copy = _Base._uid_copy


class LoopClient(_Base):
    """A client WITHOUT uid_copy -> the per-mail fallback loop. uid_copy is
    genuinely absent: hasattr is False."""

    uid_expunge = _Base._uid_expunge


def _make_module(monkeypatch, client):
    mock_user = MagicMock()
    mock_user.login_mail_server = "user@example.com"
    mock_user.uid = "u1"
    module = ModuleMail(user=mock_user, mail_settings=MagicMock(), process_setting=MagicMock())
    monkeypatch.setattr(module, "_open_client_for", lambda account_id, do_login=True: client)
    return module


def test_move_mails_modern_path_copies_flags_then_expunges_exact_uids(monkeypatch):
    client = ModernClient()
    module = _make_module(monkeypatch, client)

    result = module.move_mails("0", "INBOX", [10, 11, 12], "Archive")

    assert result == {"moved_ids": [10, 11, 12]}
    methods = [c[0] for c in client.calls]
    # uid_copy first with source_folder; flags second; uid_expunge last (RFC 4315 exact UIDs)
    assert methods == ["uid_copy", "add_flags", "uid_expunge"]
    assert client.calls[0][1] == (["10", "11", "12"], "Archive", "INBOX")
    assert client.calls[1][1] == ("INBOX", ["10", "11", "12"], ["\\Deleted"])
    assert client.calls[2][1] == ("INBOX", ["10", "11", "12"])


def test_move_mails_modern_path_preserves_order_copy_before_flags_before_expunge(monkeypatch):
    """Regression: expunge must run AFTER the \\Deleted flag + copy, never before."""
    client = ModernClient()
    module = _make_module(monkeypatch, client)
    module.move_mails("0", "INBOX", [7], "Archive")
    seq = [c[0] for c in client.calls]
    assert seq.index("uid_copy") < seq.index("add_flags") < seq.index("uid_expunge")


def test_move_mails_falls_back_to_folder_wide_expunge_without_uid_expunge(monkeypatch):
    client = FolderExpungeClient()
    module = _make_module(monkeypatch, client)
    result = module.move_mails("0", "INBOX", [1, 2], "Archive")
    assert result == {"moved_ids": [1, 2]}
    assert client.calls[-1] == ("expunge_folder", ("INBOX", False))


def test_move_mails_falls_back_to_per_mail_loop_without_uid_copy_still_expunges(monkeypatch):
    client = LoopClient()
    module = _make_module(monkeypatch, client)
    result = module.move_mails("0", "INBOX", [3, 4], "Archive")
    assert result == {"moved_ids": [3, 4]}
    copies = [c for c in client.calls if c[0] == "copy_one"]
    assert copies == [
        ("copy_one", ("INBOX", "3", "Archive")),
        ("copy_one", ("INBOX", "4", "Archive")),
    ]
    flags = [c for c in client.calls if c[0] == "add_flags"]
    assert flags == [("add_flags", ("INBOX", ["3"], ["\\Deleted"])),
                     ("add_flags", ("INBOX", ["4"], ["\\Deleted"]))]
    # expunge still happens (per fixed move: no ghost left behind)
    assert client.calls[-1][0] == "uid_expunge"
    assert client.calls[-1][1] == ("INBOX", ["3", "4"])


def test_move_mails_empty_uids_no_client_interaction(monkeypatch):
    client = ModernClient()
    module = _make_module(monkeypatch, client)
    assert module.move_mails("0", "INBOX", [], "Archive") == {"moved_ids": []}
    assert client.calls == []


def test_move_mails_missing_destination_raises(monkeypatch):
    client = ModernClient()
    module = _make_module(monkeypatch, client)
    with pytest.raises(RequestException):
        module.move_mails("0", "INBOX", [1], None)
    assert client.calls == []


def test_move_mails_copy_failure_aborts_before_flags_and_expunge(monkeypatch):
    """If the destination copy fails, no \\Deleted flag / expunge may be issued."""
    client = ModernClient(fail_copy=True)
    module = _make_module(monkeypatch, client)
    with pytest.raises(RequestException):
        module.move_mails("0", "INBOX", [5], "Archive")
    assert client.calls == [c for c in client.calls if c[0] == "uid_copy"]


def test_move_mails_expunge_failure_propagates(monkeypatch):
    """An expunge failure must not be silently swallowed (source may still ghost)."""
    client = ModernClient()
    client.fail_expunge = True
    module = _make_module(monkeypatch, client)
    with pytest.raises(RequestException):
        module.move_mails("0", "INBOX", [9], "Archive")
