"""Unit tests for the CardDAV server protocol engine."""
import pytest

from app.module.carddav.ModuleCardDAV import (
    CardDavResource,
    ModuleCardDAV,
)
from app.utils.exceptions import RequestException

SAMPLE_VCARD = """BEGIN:VCARD
VERSION:4.0
UID:contact-123
FN:John Doe
EMAIL;TYPE=work:john@example.com
END:VCARD
"""


def vcard_text(uid: str) -> str:
    """Sample vCard whose UID matches the resource uid."""
    return SAMPLE_VCARD.replace("contact-123", uid)


class TestPathResolution:
    """Test path resolution for CardDAV resources."""

    def test_root(self):
        module = ModuleCardDAV()
        res = module.resolve("/carddav/")
        assert res.kind == "root"
        assert res.href == "/carddav/"

    def test_principals_collection(self):
        module = ModuleCardDAV()
        res = module.resolve("/carddav/principals/")
        assert res.kind == "principals"
        assert res.href == "/carddav/principals/"

    def test_user_principal(self):
        module = ModuleCardDAV()
        res = module.resolve("/carddav/principals/user/user@example.com/")
        assert res.kind == "principal"
        assert res.email == "user@example.com"
        assert res.href == "/carddav/principals/user/user@example.com/"

    def test_addressbook_home(self):
        module = ModuleCardDAV()
        res = module.resolve("/carddav/addressbooks/user@example.com/")
        assert res.kind == "addressbook_home"
        assert res.email == "user@example.com"

    def test_addressbook_collection(self):
        module = ModuleCardDAV()
        res = module.resolve("/carddav/addressbooks/user@example.com/contacts/")
        assert res.kind == "addressbook"
        assert res.addressbook_name == "contacts"

    def test_contact_resource_strips_vcf_suffix(self):
        module = ModuleCardDAV()
        res = module.resolve("/carddav/addressbooks/user@example.com/contacts/contact-123.vcf")
        assert res.kind == "contact"
        assert res.uid == "contact-123"
        assert res.href == "/carddav/addressbooks/user@example.com/contacts/contact-123.vcf"

    def test_unknown_path_raises(self):
        module = ModuleCardDAV()
        with pytest.raises(RequestException):
            module.resolve("/carddav/unknown/segment/here/extra")


class TestPrincipals:
    """Test principal/user registration."""

    def test_register_user(self):
        module = ModuleCardDAV()
        principal = module.register_user("User@Example.COM", "Alice")
        assert principal["email"] == "user@example.com"
        assert principal["display_name"] == "Alice"
        assert module.principal_exists("USER@example.com")

    def test_list_principal_emails_sorted(self):
        module = ModuleCardDAV()
        module.register_user("b@example.com")
        module.register_user("a@example.com")
        assert module.list_principal_emails() == ["a@example.com", "b@example.com"]

    def test_register_user_auto_creates_contacts_addressbook(self):
        module = ModuleCardDAV()
        module.register_user("user@example.com", "Alice")
        assert module.addressbook_exists("user@example.com", "Contacts")


class TestAddressBooks:
    """Test addressbook collections."""

    def test_create_and_get_addressbook(self):
        module = ModuleCardDAV()
        etag = module.create_addressbook(
            "user@example.com", "Personal", displayname="Personal Addressbook",
            description="My contacts",
        )
        assert etag.startswith('"')
        ab = module.get_addressbook("user@example.com", "personal")
        assert ab["displayname"] == "Personal Addressbook"
        assert ab["description"] == "My contacts"

    def test_create_duplicate_raises(self):
        module = ModuleCardDAV()
        module.create_addressbook("u@example.com", "Personal")
        with pytest.raises(RequestException):
            module.create_addressbook("u@example.com", "PERSONAL")

    def test_list_addressbooks_sorted(self):
        module = ModuleCardDAV()
        module.register_user("u@example.com")
        module.create_addressbook("u@example.com", "work")
        module.create_addressbook("u@example.com", "personal")
        module.create_addressbook("other@example.com", "ignored")
        names = [ab["name"] for ab in module.list_addressbooks("u@example.com")]
        assert "contacts" in names
        assert "personal" in names
        assert "work" in names
        assert "ignored" not in names

    def test_delete_addressbook_removes_contacts(self):
        module = ModuleCardDAV()
        module.register_user("u@example.com")
        module.put_contact("u@example.com", "Contacts", "contact-1", SAMPLE_VCARD)
        assert len(module.list_contacts("u@example.com", "Contacts")) == 1
        module.delete_addressbook("u@example.com", "Contacts")
        assert not module.addressbook_exists("u@example.com", "Contacts")

    def test_update_addressbook_props(self):
        module = ModuleCardDAV()
        module.register_user("u@example.com")
        results = module.update_addressbook_props(
            "u@example.com", "Contacts", {"displayname": "Renamed"}
        )
        assert results[0][1] == "200 OK"
        assert module.get_addressbook("u@example.com", "Contacts")["displayname"] == "Renamed"

    def test_update_readonly_prop_returns_403(self):
        module = ModuleCardDAV()
        module.register_user("u@example.com")
        results = module.update_addressbook_props(
            "u@example.com", "Contacts", {"resourcetype": "nope"}
        )
        assert results[0][1] == "403 Forbidden"


class TestContacts:
    """Test contact resources."""

    def test_put_contact_creates(self):
        module = ModuleCardDAV()
        module.register_user("u@example.com")
        etag, created = module.put_contact("u@example.com", "Contacts", "contact-123", SAMPLE_VCARD)
        assert created is True
        assert etag.startswith('"')

    def test_put_contact_update(self):
        module = ModuleCardDAV()
        module.register_user("u@example.com")
        etag1, _ = module.put_contact("u@example.com", "Contacts", "contact-1", vcard_text("contact-1"))
        etag2, created = module.put_contact("u@example.com", "Contacts", "contact-1", vcard_text("contact-1-updated"))
        assert created is False
        assert etag2 != etag1

    def test_put_contact_requires_addressbook(self):
        module = ModuleCardDAV()
        module.register_user("u@example.com")
        with pytest.raises(RequestException):
            module.put_contact("u@example.com", "missing", "contact-1", SAMPLE_VCARD)

    def test_if_match_matching_etag_succeeds(self):
        module = ModuleCardDAV()
        module.register_user("u@example.com")
        etag, _ = module.put_contact("u@example.com", "Contacts", "contact-1", vcard_text("contact-1"))
        _, created = module.put_contact(
            "u@example.com", "Contacts", "contact-1", vcard_text("contact-1"), if_match=etag
        )
        assert created is False

    def test_if_match_stale_etag_412(self):
        module = ModuleCardDAV()
        module.register_user("u@example.com")
        module.put_contact("u@example.com", "Contacts", "contact-1", vcard_text("contact-1"))
        with pytest.raises(RequestException):
            module.put_contact(
                "u@example.com", "Contacts", "contact-1", SAMPLE_VCARD, if_match='"stale"'
            )

    def test_if_none_match_star_on_existing_412(self):
        module = ModuleCardDAV()
        module.register_user("u@example.com")
        module.put_contact("u@example.com", "Contacts", "contact-1", vcard_text("contact-1"))
        with pytest.raises(RequestException):
            module.put_contact(
                "u@example.com", "Contacts", "contact-1", SAMPLE_VCARD, if_none_match="*"
            )

    def test_if_none_match_star_on_missing_succeeds(self):
        module = ModuleCardDAV()
        module.register_user("u@example.com")
        etag, created = module.put_contact(
            "u@example.com", "Contacts", "contact-new", SAMPLE_VCARD, if_none_match="*"
        )
        assert created is True
        assert etag.startswith('"')

    def test_get_contact(self):
        module = ModuleCardDAV()
        module.register_user("u@example.com")
        module.put_contact("u@example.com", "Contacts", "contact-1", SAMPLE_VCARD)
        contact = module.get_contact("u@example.com", "Contacts", "contact-1")
        assert contact["vcard"] == SAMPLE_VCARD
        assert contact["uid"] == "contact-1"

    def test_get_contact_not_found(self):
        module = ModuleCardDAV()
        module.register_user("u@example.com")
        with pytest.raises(RequestException):
            module.get_contact("u@example.com", "Contacts", "missing")

    def test_delete_contact(self):
        module = ModuleCardDAV()
        module.register_user("u@example.com")
        module.put_contact("u@example.com", "Contacts", "contact-1", SAMPLE_VCARD)
        assert len(module.list_contacts("u@example.com", "Contacts")) == 1
        module.delete_contact("u@example.com", "Contacts", "contact-1")
        assert len(module.list_contacts("u@example.com", "Contacts")) == 0

    def test_delete_contact_requires_etag(self):
        module = ModuleCardDAV()
        module.register_user("u@example.com")
        module.put_contact("u@example.com", "Contacts", "contact-1", SAMPLE_VCARD)
        contact = module.get_contact("u@example.com", "Contacts", "contact-1")
        module.delete_contact("u@example.com", "Contacts", "contact-1", if_match=contact["etag"])
        with pytest.raises(RequestException):
            module.get_contact("u@example.com", "Contacts", "contact-1")

    def test_delete_contact_stale_etag_412(self):
        module = ModuleCardDAV()
        module.register_user("u@example.com")
        module.put_contact("u@example.com", "Contacts", "contact-1", SAMPLE_VCARD)
        with pytest.raises(RequestException):
            module.delete_contact("u@example.com", "Contacts", "contact-1", if_match='"stale"')

    def test_list_contacts(self):
        module = ModuleCardDAV()
        module.register_user("u@example.com")
        module.put_contact("u@example.com", "Contacts", "a", vcard_text("a"))
        module.put_contact("u@example.com", "Contacts", "b", vcard_text("b"))
        contacts = module.list_contacts("u@example.com", "Contacts")
        assert len(contacts) == 2
        assert contacts[0]["uid"] == "a"
        assert contacts[1]["uid"] == "b"
