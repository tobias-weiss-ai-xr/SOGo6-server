"""Unit tests for the CalDAV server protocol engine.

Fixture-free by design — ModuleCalDAV is a pure in-memory engine, no DB, no
client/auth fixtures required.
"""
import pytest

from app.module.caldav.ModuleCalDAV import (
    CalDavEvent,
    CalDavResource,
    ModuleCalDAV,
)
from app.utils.exceptions import RequestException

SAMPLE_EVENT = """BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//SOGo//SOGo 6//EN\r
BEGIN:VEVENT\r
UID:event-123\r
SUMMARY:Team meeting\r
DTSTART:20250115T140000Z\r
DTEND:20250115T150000Z\r
END:VEVENT\r
END:VCALENDAR\r
"""



def event_ics(uid: str) -> str:
    """Sample iCalendar whose UID matches the resource uid."""
    return SAMPLE_EVENT.replace("event-123", uid)



class TestPathResolution:
    def test_root(self):
        module = ModuleCalDAV()
        res = module.resolve("/caldav/")
        assert res.kind == "root"
        assert res.href == "/caldav/"

    def test_principals_collection(self):
        module = ModuleCalDAV()
        res = module.resolve("/caldav/principals/")
        assert res.kind == "principals"
        assert res.href == "/caldav/principals/"

    def test_user_principal(self):
        module = ModuleCalDAV()
        res = module.resolve("/caldav/principals/user/user@example.com/")
        assert res.kind == "principal"
        assert res.email == "user@example.com"
        assert res.href == "/caldav/principals/user/user@example.com/"

    def test_calendar_home(self):
        module = ModuleCalDAV()
        res = module.resolve("/caldav/calendars/user@example.com/")
        assert res.kind == "calendar_home"
        assert res.email == "user@example.com"

    def test_calendar_collection(self):
        module = ModuleCalDAV()
        res = module.resolve("/caldav/calendars/user@example.com/personal/")
        assert res.kind == "calendar"
        assert res.calendar_name == "personal"

    def test_event_resource_strips_ics_suffix(self):
        module = ModuleCalDAV()
        res = module.resolve("/caldav/calendars/user@example.com/personal/event-123.ics")
        assert res.kind == "event"
        assert res.uid == "event-123"
        assert res.href == "/caldav/calendars/user@example.com/personal/event-123.ics"

    def test_unknown_path_raises(self):
        module = ModuleCalDAV()
        with pytest.raises(RequestException):
            module.resolve("/caldav/unknown/segment/here/extra")


class TestPrincipals:
    def test_register_user(self):
        module = ModuleCalDAV()
        principal = module.register_user("User@Example.COM", "Alice")
        assert principal["email"] == "user@example.com"
        assert principal["display_name"] == "Alice"
        assert module.principal_exists("USER@example.com")

    def test_list_principal_emails_sorted(self):
        module = ModuleCalDAV()
        module.register_user("b@example.com")
        module.register_user("a@example.com")
        assert module.list_principal_emails() == ["a@example.com", "b@example.com"]


class TestCalendarCollections:
    def test_create_and_get_calendar(self):
        module = ModuleCalDAV()
        etag = module.create_calendar(
            "user@example.com", "Personal", display_name="Personal Calendar",
            description="My calendar", timezone="Europe/Paris",
        )
        assert etag.startswith('"')
        cal = module.get_calendar("user@example.com", "personal")
        assert cal["displayname"] == "Personal Calendar"
        assert cal["timezone"] == "Europe/Paris"

    def test_create_duplicate_raises(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "Personal")
        with pytest.raises(RequestException):
            module.create_calendar("u@example.com", "PERSONAL")

    def test_list_calendars_sorted(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "work")
        module.create_calendar("u@example.com", "personal")
        module.create_calendar("other@example.com", "ignored")
        names = [c["name"] for c in module.list_calendars("u@example.com")]
        assert names == ["personal", "work"]

    def test_delete_calendar_removes_events(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        module.put_event("u@example.com", "personal", "event-1", event_ics("event-1"))
        assert module.event_count("u@example.com", "personal") == 1
        module.delete_calendar("u@example.com", "personal")
        assert not module.calendar_exists("u@example.com", "personal")

    def test_update_calendar_props(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        results = module.update_calendar_props(
            "u@example.com", "personal", {"displayname": "Renamed"}
        )
        assert results[0][1] == "200 OK"
        assert module.get_calendar("u@example.com", "personal")["displayname"] == "Renamed"

    def test_update_readonly_prop_returns_403(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        results = module.update_calendar_props(
            "u@example.com", "personal", {"resourcetype": "nope"}
        )
        assert results[0][1] == "403 Forbidden"


class TestEventCrud:
    def test_put_event_creates(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        etag, created = module.put_event("u@example.com", "personal", "event-123", SAMPLE_EVENT)
        assert created is True
        assert etag.startswith('"')

    def test_put_event_update(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        etag1, _ = module.put_event("u@example.com", "personal", "event-1", event_ics("event-1"))
        etag2, created = module.put_event("u@example.com", "personal", "event-1", event_ics("event-1"))
        assert created is False
        assert etag2 != etag1

    def test_put_event_requires_calendar(self):
        module = ModuleCalDAV()
        with pytest.raises(RequestException):
            module.put_event("u@example.com", "missing", "event-1", SAMPLE_EVENT)

    def test_put_event_invalid_ical(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        with pytest.raises(RequestException):
            module.put_event("u@example.com", "personal", "event-1", "NOT ICAL DATA")

    def test_put_event_uid_mismatch(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        with pytest.raises(RequestException):
            module.put_event("u@example.com", "personal", "event-other", SAMPLE_EVENT)

    def test_if_match_matching_etag_succeeds(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        etag, _ = module.put_event("u@example.com", "personal", "event-1", event_ics("event-1"))
        _, created = module.put_event(
            "u@example.com", "personal", "event-1", event_ics("event-1"), if_match=etag
        )
        assert created is False

    def test_if_match_stale_etag_412(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        module.put_event("u@example.com", "personal", "event-1", event_ics("event-1"))
        with pytest.raises(RequestException):
            module.put_event(
                "u@example.com", "personal", "event-1", SAMPLE_EVENT, if_match='"stale"'
            )

    def test_if_none_match_star_on_existing_412(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        module.put_event("u@example.com", "personal", "event-1", event_ics("event-1"))
        with pytest.raises(RequestException):
            module.put_event(
                "u@example.com", "personal", "event-1", SAMPLE_EVENT, if_none_match="*"
            )

    def test_get_event(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        module.put_event("u@example.com", "personal", "event-1", event_ics("event-1"))
        event = module.get_event("u@example.com", "personal", "event-1")
        assert isinstance(event, CalDavEvent)
        assert "BEGIN:VEVENT" in event.ical

    def test_get_event_missing_404(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        with pytest.raises(RequestException):
            module.get_event("u@example.com", "personal", "nope")

    def test_delete_event(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        etag, _ = module.put_event("u@example.com", "personal", "event-1", event_ics("event-1"))
        module.delete_event("u@example.com", "personal", "event-1", if_match=etag)
        assert module.event_count("u@example.com", "personal") == 0

    def test_delete_event_missing_404(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        with pytest.raises(RequestException):
            module.delete_event("u@example.com", "personal", "nope")

    def test_delete_event_stale_etag_412(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        module.put_event("u@example.com", "personal", "event-1", event_ics("event-1"))
        with pytest.raises(RequestException):
            module.delete_event("u@example.com", "personal", "event-1", if_match='"stale"')

    def test_list_events_sorted(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        for uid in ("b-event", "a-event"):
            module.put_event("u@example.com", "personal", uid, SAMPLE_EVENT.replace("event-123", uid))
        uids = [e.uid for e in module.list_events("u@example.com", "personal")]
        assert uids == ["a-event", "b-event"]


class TestSyncCollection:
    def test_full_sync_with_token_0(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        module.put_event("u@example.com", "personal", "event-1", event_ics("event-1"))
        changed, deleted, token = module.sync_changes("u@example.com", "personal", "0")
        assert len(changed) == 1
        assert deleted == []
        assert token.startswith("urn:x-sogo6:sync:")

    def test_incremental_sync_returns_delta(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        module.put_event("u@example.com", "personal", "event-1", event_ics("event-1"))
        _, _, token = module.sync_changes("u@example.com", "personal", None)

        # mutate: update e1, add e2, delete e3
        module.put_event("u@example.com", "personal", "event-1", event_ics("event-1"))
        module.put_event("u@example.com", "personal", "event-2", SAMPLE_EVENT.replace("event-123", "event-2"))
        module.put_event("u@example.com", "personal", "event-3", SAMPLE_EVENT.replace("event-123", "event-3"))
        module.delete_event("u@example.com", "personal", "event-3")

        changed, deleted, token2 = module.sync_changes("u@example.com", "personal", token)
        uids = sorted(e.uid for e in changed)
        assert uids == ["event-1", "event-2"]
        assert deleted == ["event-3"]
        assert token2 != token

    def test_sync_token_roundtrip(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        module.put_event("u@example.com", "personal", "event-1", event_ics("event-1"))
        token = module.sync_token("u@example.com", "personal")
        # decode to a seq
        seq = module._decode_token(token)
        assert seq >= 1

    def test_invalid_token_raises(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        with pytest.raises(RequestException):
            module.sync_changes("u@example.com", "personal", "garbage!!!")

    def test_resurrected_event_not_tombstoned(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        module.put_event("u@example.com", "personal", "event-1", event_ics("event-1"))
        _, _, token = module.sync_changes("u@example.com", "personal", "0")
        module.delete_event("u@example.com", "personal", "event-1")
        module.put_event("u@example.com", "personal", "event-1", event_ics("event-1"))
        changed, deleted, _ = module.sync_changes("u@example.com", "personal", token)
        assert [e.uid for e in changed] == ["event-1"]
        assert deleted == []


class TestFreeBusy:
    def test_free_busy_report(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        module.put_event("u@example.com", "personal", "event-1", event_ics("event-1"))
        from datetime import datetime, timezone
        start = datetime(2025, 1, 15, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 16, 0, 0, tzinfo=timezone.utc)
        periods = module.free_busy_report("u@example.com", "personal", start, end)
        assert len(periods) == 1
        assert periods[0]["type"] == "busy"

    def test_free_busy_outside_range_empty(self):
        module = ModuleCalDAV()
        module.create_calendar("u@example.com", "personal")
        module.put_event("u@example.com", "personal", "event-1", event_ics("event-1"))
        from datetime import datetime, timezone
        start = datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)
        assert module.free_busy_report("u@example.com", "personal", start, end) == []
