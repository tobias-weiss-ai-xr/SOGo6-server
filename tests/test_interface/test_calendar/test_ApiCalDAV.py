"""Structural tests for the CalDAV / WebDAV protocol API.

Fixture-free by design (no client/auth fixtures — those only exist under
``tests/test_integration/conftest.py``), matching the project convention for
``test_interface`` structural tests.
"""
import pytest


class TestCalDavBlueprint:
    """Verify blueprint registration and route dispatch."""

    def test_blueprint_name_and_prefix(self):
        from app.api.v1.caldav.ApiCalDAV import blp
        assert blp.name == "CalDAV"
        assert blp.url_prefix == "/caldav"

    def test_blueprint_routes_exist(self):
        from app.api.v1.caldav.ApiCalDAV import blp
        assert len(blp.deferred_functions) > 0

    def test_dispatch_handles_webdav_methods(self):
        from app import create_app
        from app.utils import constants as cs

        app = create_app(cs.SOGO_OK)
        caldav_rule = next(
            r for r in app.url_map.iter_rules()
            if r.rule == "/caldav/<path:resource_path>"
        )
        for method in (
            "OPTIONS", "PROPFIND", "PROPPATCH", "MKCALENDAR", "MKCOL",
            "GET", "PUT", "DELETE", "HEAD", "REPORT",
        ):
            assert method in caldav_rule.methods

    def test_report_handlers_defined(self):
        from app.api.v1.caldav import ApiCalDAV
        for name in (
            "_report_sync_collection",
            "_report_calendar_query",
            "_report_calendar_multiget",
            "_report_free_busy",
        ):
            assert hasattr(ApiCalDAV, name)

    def test_propfind_builders_defined(self):
        from app.api.v1.caldav import ApiCalDAV
        for name in (
            "_build_root_props",
            "_build_principals_props",
            "_build_principal_props",
            "_build_calendar_home_props",
            "_build_calendar_props",
            "_build_event_props",
        ):
            assert hasattr(ApiCalDAV, name)

    def test_dav_header_capabilities(self):
        from app.api.v1.caldav.ApiCalDAV import DAV_HEADER
        assert "calendar-access" in DAV_HEADER
        assert "extended-mkcol" in DAV_HEADER


class TestWellKnownCaldav:
    """Verify the .well-known/caldav discovery redirect is registered."""

    def test_well_known_route_registered(self):
        from app import create_app
        from app.utils import constants as cs

        app = create_app(cs.SOGO_OK)
        rules = {r.rule for r in app.url_map.iter_rules()}
        assert "/.well-known/caldav" in rules
        assert "/caldav/" in rules
        assert "/caldav/<path:resource_path>" in rules


class TestCalDavModuleIntegration:
    """End-to-end protocol smoke tests through the Flask test client."""

    @pytest.fixture()
    def client(self):
        from app import create_app
        from app.utils import constants as cs

        app = create_app(cs.SOGO_OK)
        app.config["TESTING"] = True
        return app.test_client()

    def test_well_known_redirect(self, client):
        response = client.get("/.well-known/caldav")
        assert response.status_code == 301
        assert response.headers["Location"] == "/caldav/"

    def test_options_root(self, client):
        response = client.open("/caldav/", method="OPTIONS")
        assert response.status_code == 200
        assert "calendar-access" in response.headers["DAV"]
        assert "PROPFIND" in response.headers["Allow"]

    def test_propfind_root(self, client):
        response = client.open(
            "/caldav/", method="PROPFIND", data=b"<d:propfind xmlns:d='DAV:'><d:prop><d:resourcetype/></d:prop></d:propfind>",
            headers={"Depth": "0", "Content-Type": "application/xml"},
        )
        assert response.status_code == 207
        assert b"multistatus" in response.data

    def test_mkcalendar_and_event_lifecycle(self, client):
        # create calendar
        response = client.open(
            "/caldav/calendars/user@example.com/personal/",
            method="MKCALENDAR",
            data=b"<c:mkcalendar xmlns:c='urn:ietf:params:xml:ns:caldav'><d:set xmlns:d='DAV:'><d:prop><d:displayname>Personal</d:displayname></d:prop></d:set></c:mkcalendar>",
            headers={"Content-Type": "application/xml"},
        )
        assert response.status_code == 201
        assert response.headers.get("ETag")

        # put event
        ical = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//SOGo//SOGo 6//EN\r\n"
            "BEGIN:VEVENT\r\nUID:event-123\r\nSUMMARY:Team meeting\r\n"
            "DTSTART:20250115T140000Z\r\nDTEND:20250115T150000Z\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        response = client.put(
            "/caldav/calendars/user@example.com/personal/event-123.ics",
            data=ical.encode(),
            content_type="text/calendar; charset=utf-8",
        )
        assert response.status_code == 201
        etag = response.headers["ETag"]
        assert etag.startswith('"')

        # get event
        response = client.get("/caldav/calendars/user@example.com/personal/event-123.ics")
        assert response.status_code == 200
        assert b"BEGIN:VEVENT" in response.data
        assert response.headers["ETag"] == etag

        # head event
        response = client.head("/caldav/calendars/user@example.com/personal/event-123.ics")
        assert response.status_code == 200
        assert response.headers["ETag"] == etag

        # propfind calendar with depth 1 shows the event
        response = client.open(
            "/caldav/calendars/user@example.com/personal/",
            method="PROPFIND",
            data=b"<d:propfind xmlns:d='DAV:'><d:prop><d:getetag/><d:resourcetype/></d:prop></d:propfind>",
            headers={"Depth": "1", "Content-Type": "application/xml"},
        )
        assert response.status_code == 207
        assert b"event-123.ics" in response.data

        # sync collection full
        response = client.open(
            "/caldav/calendars/user@example.com/personal/",
            method="REPORT",
            data=b"<c:sync-collection xmlns:c='urn:ietf:params:xml:ns:caldav' xmlns:d='DAV:'><d:prop><d:getetag/></d:prop><c:sync-token>0</c:sync-token></c:sync-collection>",
            headers={"Content-Type": "application/xml"},
        )
        assert response.status_code == 207
        assert b"sync-token" in response.data

        # conditional put with stale etag → 412
        response = client.put(
            "/caldav/calendars/user@example.com/personal/event-123.ics",
            data=ical.encode(),
            content_type="text/calendar; charset=utf-8",
            headers={"If-Match": '"stale-etag"'},
        )
        assert response.status_code == 412

        # delete event
        response = client.delete(
            "/caldav/calendars/user@example.com/personal/event-123.ics",
            headers={"If-Match": etag},
        )
        assert response.status_code == 204

        # get deleted → 404
        response = client.get("/caldav/calendars/user@example.com/personal/event-123.ics")
        assert response.status_code == 404

        # delete calendar
        response = client.delete("/caldav/calendars/user@example.com/personal/")
        assert response.status_code == 204

    def test_proppatch_calendar(self, client):
        client.open(
            "/caldav/calendars/user@example.com/work/",
            method="MKCALENDAR",
            data=b"<c:mkcalendar xmlns:c='urn:ietf:params:xml:ns:caldav'><d:set xmlns:d='DAV:'><d:prop><d:displayname>Work</d:displayname></d:prop></d:set></c:mkcalendar>",
            headers={"Content-Type": "application/xml"},
        )
        response = client.open(
            "/caldav/calendars/user@example.com/work/",
            method="PROPPATCH",
            data=b"<d:propertyupdate xmlns:d='DAV:'><d:set><d:prop><d:displayname>Renamed Work</d:displayname></d:prop></d:set></d:propertyupdate>",
            headers={"Content-Type": "application/xml"},
        )
        assert response.status_code == 207
        assert b"Renamed Work" in response.data

    def test_free_busy_report(self, client):
        client.open(
            "/caldav/calendars/user@example.com/fb/",
            method="MKCALENDAR",
            data=b"<c:mkcalendar xmlns:c='urn:ietf:params:xml:ns:caldav'><d:set xmlns:d='DAV:'><d:prop><d:displayname>FB</d:displayname></d:prop></d:set></c:mkcalendar>",
            headers={"Content-Type": "application/xml"},
        )
        ical = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:meet\r\n"
            "SUMMARY:Meet\r\nDTSTART:20250115T140000Z\r\nDTEND:20250115T150000Z\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        client.put(
            "/caldav/calendars/user@example.com/fb/meet.ics",
            data=ical.encode(),
            content_type="text/calendar; charset=utf-8",
        )
        response = client.open(
            "/caldav/calendars/user@example.com/fb/",
            method="REPORT",
            data=b"<c:free-busy-query xmlns:c='urn:ietf:params:xml:ns:caldav'><c:time-range start='20250115T000000Z' end='20250116T000000Z'/></c:free-busy-query>",
            headers={"Content-Type": "application/xml"},
        )
        assert response.status_code == 200
        assert b"VFREEBUSY" in response.data

    def test_principal_discovery(self, client):
        # register a user by creating a calendar first
        client.open(
            "/caldav/calendars/user@example.com/discovery/",
            method="MKCALENDAR",
            data=b"<c:mkcalendar xmlns:c='urn:ietf:params:xml:ns:caldav'><d:set xmlns:d='DAV:'><d:prop><d:displayname>D</d:displayname></d:prop></d:set></c:mkcalendar>",
            headers={"Content-Type": "application/xml"},
        )
        response = client.open(
            "/caldav/principals/user/user@example.com/",
            method="PROPFIND",
            data=b"<d:propfind xmlns:d='DAV:'><d:prop><d:resourcetype/><c:calendar-home-set xmlns:c='urn:ietf:params:xml:ns:caldav'/></d:prop></d:propfind>",
            headers={"Depth": "0", "Content-Type": "application/xml"},
        )
        assert response.status_code == 207
        assert b"calendar-home-set" in response.data
