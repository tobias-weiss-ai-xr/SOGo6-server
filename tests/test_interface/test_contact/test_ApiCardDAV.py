"""Structural tests for the CardDAV / WebDAV protocol API.

Fixture-free by design (no client/auth fixtures — those only exist under
``tests/test_integration/conftest.py``), matching the project convention for
``test_interface`` structural tests.
"""
import pytest


class TestCardDavBlueprint:
    """Verify blueprint registration and route dispatch."""

    def test_blueprint_name_and_prefix(self):
        from app.api.v1.carddav.ApiCardDAV import blp
        assert blp.name == "CardDAV"
        assert blp.url_prefix == "/carddav"

    def test_blueprint_routes_exist(self):
        from app.api.v1.carddav.ApiCardDAV import blp
        assert len(blp.deferred_functions) > 0

    def test_dispatch_handles_webdav_methods(self):
        from app import create_app
        from app.utils import constants as cs

        app = create_app(cs.SOGO_OK)
        carddav_rule = next(
            r for r in app.url_map.iter_rules()
            if r.rule == "/carddav/<path:resource_path>"
        )
        for method in (
            "OPTIONS", "PROPFIND", "PROPPATCH", "MKCOL",
            "GET", "PUT", "DELETE", "HEAD", "REPORT",
        ):
            assert method in carddav_rule.methods

    def test_report_handlers_defined(self):
        from app.api.v1.carddav import ApiCardDAV
        for name in (
            "_report_addressbook_query",
            "_report_addressbook_multiget",
        ):
            assert hasattr(ApiCardDAV, name)

    def test_propfind_builders_defined(self):
        from app.api.v1.carddav import ApiCardDAV
        for name in (
            "_build_root_props",
            "_build_principals_props",
            "_build_principal_props",
            "_build_addressbook_home_props",
            "_build_addressbook_props",
            "_build_contact_props",
        ):
            assert hasattr(ApiCardDAV, name)

    def test_dav_header_capabilities(self):
        from app.api.v1.carddav.ApiCardDAV import DAV_HEADER
        assert "addressbook" in DAV_HEADER


class TestWellKnownCarddav:
    """Verify the .well-known/carddav discovery redirect is registered."""

    def test_well_known_route_registered(self):
        from app import create_app
        from app.utils import constants as cs

        app = create_app(cs.SOGO_OK)
        rules = {r.rule for r in app.url_map.iter_rules()}
        assert "/.well-known/carddav" in rules
        assert "/carddav/" in rules
        assert "/carddav/<path:resource_path>" in rules


class TestCardDavModuleIntegration:
    """End-to-end protocol smoke tests through the Flask test client."""

    @pytest.fixture()
    def client(self):
        from app import create_app
        from app.utils import constants as cs
        from unittest.mock import MagicMock
        import app.api.v1.carddav.ApiCardDAV as carddav_mod

        app = create_app(cs.SOGO_OK)
        app.config["TESTING"] = True
        # Bypass CardDAV Basic auth — unit tests have no LDAP backend.
        mock_auth = MagicMock()
        mock_user = MagicMock()
        mock_user.cn = "Test User"
        mock_user.mail = "test@example.com"
        mock_auth._check_login.return_value = (True, mock_user, None)
        carddav_mod._carddav_auth = mock_auth
        client = app.test_client()
        # Inject Basic auth header on every request (mock_auth accepts any creds)
        client.environ_base["HTTP_AUTHORIZATION"] = "Basic dGVzdDp0ZXN0"
        return client

    def test_well_known_redirect(self, client):
        response = client.get("/.well-known/carddav")
        assert response.status_code == 301
        assert response.headers["Location"] == "/carddav/"

    def test_options_root(self, client):
        response = client.open("/carddav/", method="OPTIONS")
        assert response.status_code == 200
        assert "addressbook" in response.headers["DAV"]
        assert "PROPFIND" in response.headers["Allow"]

    def test_propfind_root(self, client):
        response = client.open(
            "/carddav/", method="PROPFIND", data=b"<d:propfind xmlns:d='DAV:'><d:prop><d:resourcetype/></d:prop></d:propfind>",
            headers={"Depth": "0", "Content-Type": "application/xml"},
        )
        assert response.status_code == 207
        assert b"multistatus" in response.data

    def test_mkcol_addressbook(self, client):
        # create addressbook
        response = client.open(
            "/carddav/addressbooks/user@example.com/personal/",
            method="MKCOL",
            data=b"<c:mkcol xmlns:c='urn:ietf:params:xml:ns:carddav'><d:set xmlns:d='DAV:'><d:prop><d:displayname>Personal</d:displayname></d:prop></d:set></c:mkcol>",
            headers={"Content-Type": "application/xml"},
        )
        assert response.status_code == 201
        assert response.headers.get("ETag")

    def test_propfind_addressbook(self, client):
        # first ensure addressbook exists
        client.open(
            "/carddav/addressbooks/user@example.com/work/",
            method="MKCOL",
            data=b"<c:mkcol xmlns:c='urn:ietf:params:xml:ns:carddav'><d:set xmlns:d='DAV:'><d:prop><d:displayname>Work</d:displayname></d:prop></d:set></c:mkcol>",
            headers={"Content-Type": "application/xml"},
        )
        response = client.open(
            "/carddav/addressbooks/user@example.com/work/",
            method="PROPFIND",
            data=b"<d:propfind xmlns:d='DAV:'><d:prop><d:resourcetype/><d:displayname/></d:prop></d:propfind>",
            headers={"Depth": "0", "Content-Type": "application/xml"},
        )
        assert response.status_code == 207
        assert b"addressbook" in response.data
        assert b"Work" in response.data

    def test_put_contact(self, client):
        # ensure addressbook exists
        client.open(
            "/carddav/addressbooks/user@example.com/personal/",
            method="MKCOL",
            data=b"<c:mkcol xmlns:c='urn:ietf:params:xml:ns:carddav'><d:set xmlns:d='DAV:'><d:prop><d:displayname>Personal</d:displayname></d:prop></d:set></c:mkcol>",
            headers={"Content-Type": "application/xml"},
        )
        # put contact
        vcard = (
            "BEGIN:VCARD\r\nVERSION:4.0\r\nFN:John Doe\r\n"
            "UID:contact-123\r\nEMAIL;TYPE=work:john@example.com\r\n"
            "END:VCARD\r\n"
        )
        response = client.put(
            "/carddav/addressbooks/user@example.com/personal/contact-123.vcf",
            data=vcard.encode(),
            content_type="text/vcard; charset=utf-8",
        )
        assert response.status_code == 201
        etag = response.headers["ETag"]
        assert etag.startswith('"')

    def test_get_contact(self, client):
        # setup
        client.open(
            "/carddav/addressbooks/user@example.com/personal/",
            method="MKCOL",
            data=b"<c:mkcol xmlns:c='urn:ietf:params:xml:ns:carddav'><d:set xmlns:d='DAV:'><d:prop><d:displayname>Personal</d:displayname></d:prop></d:set></c:mkcol>",
            headers={"Content-Type": "application/xml"},
        )
        vcard = (
            "BEGIN:VCARD\r\nVERSION:4.0\r\nFN:Jane Doe\r\n"
            "UID:test-contact\r\nEMAIL;TYPE=work:jane@example.com\r\n"
            "END:VCARD\r\n"
        )
        client.put(
            "/carddav/addressbooks/user@example.com/personal/test-contact.vcf",
            data=vcard.encode(),
            content_type="text/vcard; charset=utf-8",
        )
        # get contact
        response = client.get("/carddav/addressbooks/user@example.com/personal/test-contact.vcf")
        assert response.status_code == 200
        assert b"BEGIN:VCARD" in response.data
        assert b"Jane Doe" in response.data
        assert response.headers["Content-Type"] == "text/vcard; charset=utf-8"
        assert response.headers["ETag"].startswith('"')

    def test_delete_contact(self, client):
        # setup
        client.open(
            "/carddav/addressbooks/user@example.com/personal/",
            method="MKCOL",
            data=b"<c:mkcol xmlns:c='urn:ietf:params:xml:ns:carddav'><d:set xmlns:d='DAV:'><d:prop><d:displayname>Personal</d:displayname></d:prop></d:set></c:mkcol>",
            headers={"Content-Type": "application/xml"},
        )
        vcard = "BEGIN:VCARD\r\nVERSION:4.0\r\nFN:Test\r\nUID:del-test\r\nEND:VCARD\r\n"
        put_resp = client.put(
            "/carddav/addressbooks/user@example.com/personal/del-test.vcf",
            data=vcard.encode(),
            content_type="text/vcard; charset=utf-8",
        )
        etag = put_resp.headers["ETag"]
        # delete contact
        response = client.delete(
            "/carddav/addressbooks/user@example.com/personal/del-test.vcf",
            headers={"If-Match": etag},
        )
        assert response.status_code == 204
        # verify deletion
        response = client.get("/carddav/addressbooks/user@example.com/personal/del-test.vcf")
        assert response.status_code == 404

    def test_principal_discovery(self, client):
        # register a user by creating an addressbook first
        client.open(
            "/carddav/addressbooks/user@example.com/discovery/",
            method="MKCOL",
            data=b"<c:mkcol xmlns:c='urn:ietf:params:xml:ns:carddav'><d:set xmlns:d='DAV:'><d:prop><d:displayname>D</d:displayname></d:prop></d:set></c:mkcol>",
            headers={"Content-Type": "application/xml"},
        )
        response = client.open(
            "/carddav/principals/user/user@example.com/",
            method="PROPFIND",
            data=b"<d:propfind xmlns:d='DAV:'><d:prop><d:resourcetype/><d:displayname/></d:prop></d:propfind>",
            headers={"Depth": "0", "Content-Type": "application/xml"},
        )
        assert response.status_code == 207
        assert b"principal" in response.data

    def test_proppatch_addressbook(self, client):
        client.open(
            "/carddav/addressbooks/user@example.com/work/",
            method="MKCOL",
            data=b"<c:mkcol xmlns:c='urn:ietf:params:xml:ns:carddav'><d:set xmlns:d='DAV:'><d:prop><d:displayname>Work</d:displayname></d:prop></d:set></c:mkcol>",
            headers={"Content-Type": "application/xml"},
        )
        response = client.open(
            "/carddav/addressbooks/user@example.com/work/",
            method="PROPPATCH",
            data=b"<d:propertyupdate xmlns:d='DAV:'><d:set><d:prop><d:displayname>Renamed Work</d:displayname></d:prop></d:set></d:propertyupdate>",
            headers={"Content-Type": "application/xml"},
        )
        assert response.status_code == 207
        assert b"Renamed Work" in response.data

    def test_propfind_addressbook_depth_1(self, client):
        # create addressbook and contact
        client.open(
            "/carddav/addressbooks/user@example.com/personal/",
            method="MKCOL",
            data=b"<c:mkcol xmlns:c='urn:ietf:params:xml:ns:carddav'><d:set xmlns:d='DAV:'><d:prop><d:displayname>Personal</d:displayname></d:prop></d:set></c:mkcol>",
            headers={"Content-Type": "application/xml"},
        )
        vcard = "BEGIN:VCARD\r\nVERSION:4.0\r\nFN:Test\r\nUID:depth-test\r\nEND:VCARD\r\n"
        client.put(
            "/carddav/addressbooks/user@example.com/personal/depth-test.vcf",
            data=vcard.encode(),
            content_type="text/vcard; charset=utf-8",
        )
        # propfind with depth 1 should show the contact
        response = client.open(
            "/carddav/addressbooks/user@example.com/personal/",
            method="PROPFIND",
            data=b"<d:propfind xmlns:d='DAV:'><d:prop><d:getetag/><d:resourcetype/></d:prop></d:propfind>",
            headers={"Depth": "1", "Content-Type": "application/xml"},
        )
        assert response.status_code == 207
        assert b"depth-test.vcf" in response.data
