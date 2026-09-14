"""Tests for the SSE endpoint (ApiLiveUpdates): heartbeats + mail:received poll."""
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import app.api.v1.user.ApiLiveUpdates as live


def _drive(gen, nexts):
    """Consume `nexts` chunks of the SSE generator with time.sleep stubbed."""
    chunks = []
    with patch.object(live.time, "sleep"):
        for _ in range(nexts):
            chunks.append(next(gen))
    return chunks


def _module_with_counts(counts, newest_mail=None):
    """ModuleMail mock whose get_one_folder yields `counts` in order."""
    mod = MagicMock()
    mod.get_one_folder.side_effect = [
        {"message_count": c, "unseen_count": c} for c in counts
    ]
    if newest_mail is not None:
        mod.get_folder_mails.return_value = ([newest_mail], counts[-1])
    return mod


def _generate(module_mock, nexts):
    user = SimpleNamespace(domain="example.org")
    gen = live._inbox_sse_generator(user, lambda: module_mock)
    return _drive(gen, nexts)


class TestEndpoint:
    def test_sse_view_is_registered(self):
        assert callable(live.sse)

    def test_poll_interval_is_twenty_seconds(self):
        assert live.MAIL_POLL_INTERVAL_S == 20


class TestMailReceivedPoll:
    def test_connected_then_heartbeats_no_mail_on_baseline(self):
        mod = _module_with_counts([5, 5])
        chunks = _generate(mod, nexts=4)
        assert chunks[0].startswith("event: connected")
        assert not any("mail:received" in c for c in chunks)
        assert sum("heartbeat" in c for c in chunks) == 3

    def test_count_increase_emits_mail_received_with_mapped_payload(self):
        newest = {
            "uid": "42",
            "subject": "Hello",
            "from": {"name": "Alice", "email": "alice@example.org"},
            "date": "2026-09-14T10:00:00Z",
        }
        mod = _module_with_counts([5, 6], newest_mail=newest)
        chunks = _generate(mod, nexts=4)

        # t1: baseline heartbeat; t2: increase → mail:received, then heartbeat
        assert sum("heartbeat" in c for c in chunks) == 2
        events = [c for c in chunks if "mail:received" in c]
        assert len(events) == 1
        assert events[0].startswith("event: mail:received\ndata: ")
        payload = json.loads(events[0].split("data: ", 1)[1])
        assert payload["id"] == "42"
        assert payload["subject"] == "Hello"
        assert payload["from"]["email"] == "alice@example.org"
        assert payload["receivedAt"] == "2026-09-14T10:00:00Z"

        # page=1, page_size=1 → the fetch yields newest-first: mails[0] is newest
        args = mod.get_folder_mails.call_args[0][2]
        assert (args.page, args.page_size) == (1, 1)

    def test_payload_fetch_failure_still_emits_event_with_fallback_id(self):
        mod = _module_with_counts([5, 6])
        mod.get_folder_mails.side_effect = RuntimeError("imap gone")
        chunks = _generate(mod, nexts=4)

        events = [c for c in chunks if "mail:received" in c]
        assert len(events) == 1
        payload = json.loads(events[0].split("data: ", 1)[1])
        assert payload["id"].startswith("inbox-")

    def test_count_decrease_does_not_emit(self):
        mod = _module_with_counts([5, 3])
        chunks = _generate(mod, nexts=4)
        assert not any("mail:received" in c for c in chunks)

    def test_poll_failure_rebuilds_module_and_stream_survives(self):
        mod = MagicMock()
        mod.get_one_folder.side_effect = [RuntimeError("imap dropped"), {"message_count": 5}]
        chunks = _generate(mod, nexts=3)
        # stream still alive after the failure tick: connected + 2 heartbeats
        assert chunks[0].startswith("event: connected")
        assert sum("heartbeat" in c for c in chunks) == 2


class TestBuildFactory:
    def test_factory_builds_module_from_user_domain_settings(self):
        user = SimpleNamespace(domain="example.org")
        module_instance = MagicMock()
        with patch.object(live, "init_get_user_domain_settings", return_value={
            live.MailSettings.subparent: {"k": "v"}
        }) as m_settings, patch.object(live, "MailSettingsObj", return_value="ms") as m_obj, \
            patch.object(live, "ModuleMail", return_value=module_instance) as m_mod:
            factory = live._build_mail_module_factory(user)
            result = factory()

        m_settings.assert_called_once_with(user)
        m_obj.assert_called_once_with({"k": "v"})
        m_mod.assert_called_once_with(user, "ms", live.process_config)
        assert result is module_instance
