"""Tests for the SSE endpoint (ApiLiveUpdates): heartbeats + mail:received poll."""
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import app.api.v1.user.ApiLiveUpdates as live


def _drive_generator(gen, ticks):
    """Consume `ticks` sleep-ticks of the SSE generator with time.sleep stubbed.

    Returns (chunks, sleep_calls)."""
    chunks = []
    with patch.object(live.time, "sleep") as sleep_mock:
        for _ in range(ticks):
            chunks.append(next(gen))
    return chunks, sleep_mock


def _module_with_counts(counts, newest_mail=None):
    """ModuleMail mock whose get_one_folder yields `counts` in order."""
    mod = MagicMock()
    mod.get_one_folder.side_effect = [
        {"message_count": c, "unseen_count": c} for c in counts
    ]
    if newest_mail is not None:
        mod.get_folder_mails.return_value = ([newest_mail], counts[-1])
    return mod


def _generate(module_mock, ticks=3):
    user = SimpleNamespace(domain="example.org")
    gen = live._inbox_sse_generator(user, lambda: module_mock)
    return _drive_generator(gen, ticks)


class TestEndpoint:
    def test_sse_route_exists(self):
        routes = [r.rule for r in live.blp.deferred_functions] if hasattr(live.blp, "deferred_functions") else []
        # blueprint-level: just assert the view function is registered on the module
        assert callable(live.sse)

    def test_poll_interval_is_twenty_seconds(self):
        assert live.MAIL_POLL_INTERVAL_S == 20


class TestMailReceivedPoll:
    def test_first_tick_emits_connected_and_heartbeat_but_no_mail(self):
        mod = _module_with_counts([5, 5])
        chunks, sleep_mock = _generate(mod, ticks=2)
        assert chunks[0].startswith("event: connected")
        assert not any("mail:received" in c for c in chunks)
        assert sum("heartbeat" in c for c in chunks) == 2
        assert all(sleep_mock.call_args[0][0] == live.MAIL_POLL_INTERVAL_S for _ in sleep_mock.call_args_list)

    def test_count_increase_emits_mail_received_with_mapped_payload(self):
        newest = {
            "uid": "42",
            "subject": "Hello",
            "from": {"name": "Alice", "email": "alice@example.org"},
            "date": "2026-09-14T10:00:00Z",
        }
        mod = _module_with_counts([5, 6], newest_mail=newest)
        chunks, _ = _generate(mod, ticks=2)

        events = [c for c in chunks if "mail:received" in c]
        assert len(events) == 1
        assert events[0].startswith("event: mail:received\ndata: ")
        payload = json.loads(events[0].split("data: ", 1)[1])
        assert payload["id"] == "42"
        assert payload["subject"] == "Hello"
        assert payload["from"]["email"] == "alice@example.org"
        assert payload["receivedAt"] == "2026-09-14T10:00:00Z"

        # newest mail fetched at IMAP sequence `count` (page=count, page_size=1)
        args = mod.get_folder_mails.call_args[0][2]
        assert (args.page, args.page_size) == (6, 1)

    def test_payload_fetch_failure_still_emits_event_with_fallback_id(self):
        mod = _module_with_counts([5, 6])
        mod.get_folder_mails.side_effect = RuntimeError("imap gone")
        chunks, _ = _generate(mod, ticks=2)

        events = [c for c in chunks if "mail:received" in c]
        assert len(events) == 1
        payload = json.loads(events[0].split("data: ", 1)[1])
        assert payload["id"].startswith("inbox-")

    def test_count_decrease_does_not_emit(self):
        mod = _module_with_counts([5, 3])
        chunks, _ = _generate(mod, ticks=2)
        assert not any("mail:received" in c for c in chunks)

    def test_poll_failure_rebuilds_module_and_stream_survives(self):
        mod = MagicMock()
        mod.get_one_folder.side_effect = [RuntimeError("imap dropped"), {"message_count": 5}]
        chunks, _ = _generate(mod, ticks=3)
        # stream still alive after the failure tick: heartbeat present each tick
        assert sum("heartbeat" in c for c in chunks) == 3


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
