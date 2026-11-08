"""Unit tests for IcsFetcher."""
from unittest.mock import patch

import pytest
import urllib.error

from app.module.calendar.sync.IcsFetcher import IcsFetcher
from app.utils.errors import ERROR_CALENDAR_ICS_FETCH_FAILED
from app.utils.exceptions import RequestException


def test_fetch_url_error():
    with patch("urllib.request.OpenerDirector.open", side_effect=urllib.error.URLError("connection refused")):
        with pytest.raises(RequestException) as exc_info:
            IcsFetcher.fetch("https://example.com/cal.ics")
    assert exc_info.value.error == ERROR_CALENDAR_ICS_FETCH_FAILED


def test_fetch_http_error():
    http_err = urllib.error.HTTPError(url=None, code=404, msg="Not Found", hdrs=None, fp=None)
    with patch("urllib.request.OpenerDirector.open", side_effect=http_err):
        with pytest.raises(RequestException) as exc_info:
            IcsFetcher.fetch("https://example.com/cal.ics")
    assert exc_info.value.error == ERROR_CALENDAR_ICS_FETCH_FAILED


def test_validate_rejects_ftp_scheme():
    with pytest.raises(RequestException):
        IcsFetcher._validate_url("ftp://example.com/cal.ics")


def test_validate_rejects_empty_hostname():
    with pytest.raises(RequestException):
        IcsFetcher._validate_url("https:///cal.ics")


# --- CalDAV REPORT mirror (external calendars) ---

MULTISTATUS_TWO_EVENTS = (
    '<?xml version="1.0"?>'
    '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    '<d:response><d:href>/dav/booking/ev1.ics</d:href><d:propstat><d:prop>'
    '<d:getetag>"abc"</d:getetag>'
    "<c:calendar-data>BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n"
    "BEGIN:VEVENT\r\nUID:ev1\r\nDTSTART:20261109T090000Z\r\nSUMMARY:Mirror One\r\n"
    "END:VEVENT\r\nEND:VCALENDAR\r\n</c:calendar-data>"
    '</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
    '<d:response><d:href>/dav/booking/ev2.ics</d:href><d:propstat><d:prop>'
    '<d:getetag>"def"</d:getetag>'
    "<c:calendar-data>BEGIN:VEVENT\r\nUID:ev2\r\nDTSTART:20261109T100000Z\r\n"
    "SUMMARY:Mirror Two\r\nEND:VEVENT\r\n</c:calendar-data>"
    '</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
    '</d:multistatus>'
)


def test_parse_calendar_query_response_two_events():
    """REPORT multistatus with calendar-data payloads yields both VEVENTs."""
    blocks = IcsFetcher._parse_calendar_query_response(MULTISTATUS_TWO_EVENTS)
    assert len(blocks) == 2
    assert "UID:ev1" in blocks[0]
    assert "UID:ev2" in blocks[1]


def test_parse_calendar_query_response_bare_vevents():
    """Bare VEVENT blocks (no calendar-data wrapper) are also extracted."""
    body = "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:x1\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    blocks = IcsFetcher._parse_calendar_query_response(body)
    assert blocks and "UID:x1" in blocks[0]


def test_parse_calendar_query_response_empty():
    """Empty multistatus yields no blocks (caller builds a valid empty VCALENDAR)."""
    assert IcsFetcher._parse_calendar_query_response(
        '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:"/>'
    ) == []


def test_fetch_caldav_stitches_mirror(monkeypatch):
    """GET rejected (403) -> REPORT on the collection returns a merged VCALENDAR."""

    def fake_http_get(url, pinned_ip, username=None, password=None):
        raise urllib.error.HTTPError(url=None, code=403, msg="Forbidden", hdrs=None, fp=None)

    def fake_report(url, pinned_ip, body, username=None, password=None):
        assert "calendar-query" in body
        return MULTISTATUS_TWO_EVENTS

    def fake_validate(url):
        return "1.2.3.4"

    monkeypatch.setattr(IcsFetcher, "_http_get", staticmethod(fake_http_get))
    monkeypatch.setattr(IcsFetcher, "_http_report", staticmethod(fake_report))
    monkeypatch.setattr(IcsFetcher, "_validate_url", staticmethod(fake_validate))

    result = IcsFetcher.fetch("https://calendar.example/dav/booking/", "u", "p")
    assert result.startswith("BEGIN:VCALENDAR")
    assert "UID:ev1" in result
    assert "UID:ev2" in result
    assert result.rstrip().endswith("END:VCALENDAR")


def test_fetch_direct_report_preferred_over_discovery(monkeypatch):
    """REPORT on the collection URL is tried before PROPFIND discovery."""
    report_calls: list[str] = []

    def fake_http_get(url, pinned_ip, username=None, password=None):
        raise urllib.error.HTTPError(url=None, code=403, msg="Forbidden", hdrs=None, fp=None)

    def fake_report(url, pinned_ip, body, username=None, password=None):
        report_calls.append(url)
        return MULTISTATUS_TWO_EVENTS

    def fake_discover(url, pinned_ip, username=None, password=None):
        raise AssertionError("discovery must not run when direct REPORT works")

    def fake_validate(url):
        return "1.2.3.4"

    monkeypatch.setattr(IcsFetcher, "_http_get", staticmethod(fake_http_get))
    monkeypatch.setattr(IcsFetcher, "_http_report", staticmethod(fake_report))
    monkeypatch.setattr(IcsFetcher, "_discover_calendar_url", staticmethod(fake_discover))
    monkeypatch.setattr(IcsFetcher, "_validate_url", staticmethod(fake_validate))

    result = IcsFetcher.fetch("https://calendar.example/dav/booking/")
    assert "UID:ev1" in result
    assert report_calls == ["https://calendar.example/dav/booking/"]


def test_fetch_caldav_empty_calendar_is_valid_ics(monkeypatch):
    """Empty calendar still yields a valid (empty) VCALENDAR, not an error."""

    def fake_http_get(url, pinned_ip, username=None, password=None):
        raise urllib.error.HTTPError(url=None, code=403, msg="Forbidden", hdrs=None, fp=None)

    def fake_report(url, pinned_ip, body, username=None, password=None):
        return '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:"/>'

    def fake_validate(url):
        return "1.2.3.4"

    monkeypatch.setattr(IcsFetcher, "_http_get", staticmethod(fake_http_get))
    monkeypatch.setattr(IcsFetcher, "_http_report", staticmethod(fake_report))
    monkeypatch.setattr(IcsFetcher, "_validate_url", staticmethod(fake_validate))

    result = IcsFetcher.fetch("https://calendar.example/dav/booking-empty/")
    assert result.startswith("BEGIN:VCALENDAR")
    assert "BEGIN:VEVENT" not in result
    assert result.rstrip().endswith("END:VCALENDAR")


def test_fetch_404_still_fails(monkeypatch):
    """Hard 404 on the collection stays a FETCH_FAILED error (no CalDAV fallback)."""

    def fake_http_get(url, pinned_ip, username=None, password=None):
        raise urllib.error.HTTPError(url=None, code=404, msg="Not Found", hdrs=None, fp=None)

    def fake_validate(url):
        return "1.2.3.4"

    monkeypatch.setattr(IcsFetcher, "_http_get", staticmethod(fake_http_get))
    monkeypatch.setattr(IcsFetcher, "_validate_url", staticmethod(fake_validate))

    with pytest.raises(RequestException) as exc_info:
        IcsFetcher.fetch("https://calendar.example/dav/missing/")
    assert exc_info.value.error == ERROR_CALENDAR_ICS_FETCH_FAILED


def test_fetch_report_405_falls_back_to_get(monkeypatch):
    """REPORT 405 -> legacy GET of the discovered VEVENT-capable href."""

    calls: list[str] = []

    def fake_http_get(url, pinned_ip, username=None, password=None):
        calls.append(("GET", url))
        if url.endswith("/dav/booking/"):
            raise urllib.error.HTTPError(url=None, code=403, msg="Forbidden", hdrs=None, fp=None)
        return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:legacy\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"

    def fake_report(url, pinned_ip, body, username=None, password=None):
        calls.append(("REPORT", url))
        raise urllib.error.HTTPError(url=None, code=405, msg="Method Not Allowed", hdrs=None, fp=None)

    def fake_discover(url, pinned_ip, username=None, password=None):
        return "https://calendar.example/dav/booking/out.ics"

    def fake_validate(url):
        return "1.2.3.4"

    monkeypatch.setattr(IcsFetcher, "_http_get", staticmethod(fake_http_get))
    monkeypatch.setattr(IcsFetcher, "_http_report", staticmethod(fake_report))
    monkeypatch.setattr(IcsFetcher, "_discover_calendar_url", staticmethod(fake_discover))
    monkeypatch.setattr(IcsFetcher, "_validate_url", staticmethod(fake_validate))

    result = IcsFetcher.fetch("https://calendar.example/dav/booking/")
    assert "UID:legacy" in result
    assert ("GET", "https://calendar.example/dav/booking/out.ics") in calls
