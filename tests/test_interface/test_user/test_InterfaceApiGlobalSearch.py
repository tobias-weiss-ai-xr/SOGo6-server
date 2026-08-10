"""Unit tests for InterfaceApiGlobalSearch — unified Cmd+K search."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.interface.user.InterfaceApiGlobalSearch import InterfaceApiGlobalSearch


def _make_iface() -> InterfaceApiGlobalSearch:
    iface = InterfaceApiGlobalSearch.__new__(InterfaceApiGlobalSearch)
    iface.user = MagicMock()
    iface.user.uid = "user@example.org"
    iface.contact_module = MagicMock()
    iface.calendar_module = MagicMock()
    iface.user_module = MagicMock()
    return iface


class TestGlobalSearch:
    def test_short_query_returns_empty(self):
        iface = _make_iface()
        resp, status = iface.global_search("a")
        assert status == 200
        assert resp["data"] == {"contacts": [], "events": [], "users": []}
        iface.contact_module.get_contacts.assert_not_called()

    def test_aggregates_all_sections(self):
        iface = _make_iface()

        class FakeContact:
            key = "c1"
            addressbook_key = "ab1"
            fullname = "Alice Doe"
            emails = ["alice@example.org"]

        class FakeEvent:
            key = "e1"
            calendar_key = "cal1"
            title = "Weekly sync"
            require_date_start = None
            require_date_end = None

        iface.contact_module.get_contacts.return_value = ([FakeContact()], 1)

        with patch(
            "app.interface.user.InterfaceApiGlobalSearch.CalendarUser",
            return_value=MagicMock(),
        ), patch(
            "app.interface.user.InterfaceApiGlobalSearch.datetime",
        ) as mock_dt:
            mock_dt.now.return_value = MagicMock()
            mock_dt.timedelta.return_value = MagicMock()
            iface.calendar_module.get_all_events.return_value = [FakeEvent()]
            iface.user_module.list_users.return_value = (
                1,
                [{"uid": "bob", "cn": "Bob", "mail": "bob@example.org"}],
            )

            resp, status = iface.global_search("alice")

        assert status == 200
        data = resp["data"]
        assert len(data["contacts"]) == 1
        assert data["contacts"][0]["fullname"] == "Alice Doe"
        assert data["contacts"][0]["email"] == "alice@example.org"
        assert len(data["events"]) == 1
        assert data["events"][0]["title"] == "Weekly sync"
        assert len(data["users"]) == 1
        assert data["users"][0]["uid"] == "bob"
        iface.calendar_module.get_all_events.assert_called_once()

    def test_section_failures_are_isolated(self):
        iface = _make_iface()
        iface.contact_module.get_contacts.side_effect = RuntimeError("db down")
        iface.calendar_module.get_all_events.side_effect = RuntimeError("calendar down")
        iface.user_module.list_users.side_effect = RuntimeError("ldap down")

        with patch(
            "app.interface.user.InterfaceApiGlobalSearch.CalendarUser",
            return_value=MagicMock(),
        ), patch("app.interface.user.InterfaceApiGlobalSearch.datetime") as mock_dt:
            mock_dt.now.return_value = MagicMock()
            mock_dt.timedelta.return_value = MagicMock()
            resp, status = iface.global_search("anything")

        assert status == 200
        assert resp["data"] == {"contacts": [], "events": [], "users": []}

    def test_event_payload_includes_dates(self):
        iface = _make_iface()

        class FakeEvent:
            key = "e1"
            calendar_key = "cal1"
            title = "Planning"
            require_date_start = MagicMock()
            require_date_start.isoformat.return_value = "2026-08-07T09:00:00+00:00"
            require_date_end = MagicMock()
            require_date_end.isoformat.return_value = "2026-08-07T10:00:00+00:00"

        iface.contact_module.get_contacts.return_value = ([], 0)
        with patch(
            "app.interface.user.InterfaceApiGlobalSearch.CalendarUser",
            return_value=MagicMock(),
        ), patch("app.interface.user.InterfaceApiGlobalSearch.datetime") as mock_dt:
            mock_dt.now.return_value = MagicMock()
            mock_dt.timedelta.return_value = MagicMock()
            iface.calendar_module.get_all_events.return_value = [FakeEvent()]
            iface.user_module.list_users.return_value = (0, [])
            resp, _ = iface.global_search("planning")

        event = resp["data"]["events"][0]
        assert event["date_start"] == "2026-08-07T09:00:00+00:00"
        assert event["date_end"] == "2026-08-07T10:00:00+00:00"
