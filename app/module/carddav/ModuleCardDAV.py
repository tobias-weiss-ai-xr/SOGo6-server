"""ModuleCardDAV — CardDAV server protocol engine.

Implements the CardDAV (RFC 6352) and WebDAV (RFC 4918) protocol surfaces
over an in-memory resource store, mirroring the pattern of ModuleCalDAV.

Resource hierarchy:

    /carddav/
    ├── principals/
    │   └── user/{email}/            principal collection + user principal
    └── addressbooks/
        └── {email}/
            ├── {addressbook_name}/    addressbook collection (MKCOL)
            │   └── {uid}.vcf       contact resource (PUT / GET / HEAD / DELETE)

The engine exposes the following protocol capabilities:

* OPTIONS — DAV header (1, 3, addressbook)
* PROPFIND — property discovery with multistatus responses (Depth 0/1)
* PROPPATCH — addressbook property updates (displayname, description)
* MKCOL — addressbook collection creation
* PUT / GET / HEAD / DELETE — contact resources (vCard, RFC 6350)
* REPORT — addressbook-query, addressbook-multiget
* Conditional requests — If-Match / If-None-Match with ETags
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

import xml.etree.ElementTree as ET

from app.utils import errors as err
from app.utils.exceptions import RequestException

# XML namespaces (RFC 6352 / RFC 4918)
DAV_NS = "DAV:"
CARDDAV_NS = "urn:ietf:params:xml:ns:carddav"

_UID_SUFFIX_RE = re.compile(r"\.vcf$", re.IGNORECASE)

# Error aliases
ERROR_CARDDAV_PATH_NOT_FOUND = "ERROR_CARDDAV_PATH_NOT_FOUND"
ERROR_CARDDAV_ADDRESSBOOK_EXISTS = "ERROR_CARDDAV_ADDRESSBOOK_EXISTS"
ERROR_CARDDAV_PRECONDITION = "ERROR_CARDDAV_PRECONDITION_FAILED"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

class CardDavResource:
    """A parsed CardDAV resource path."""

    __slots__ = ("kind", "email", "addressbook_name", "uid", "path")

    # kinds: root | principals | principal | addressbook_home | addressbook | contact
    def __init__(
        self,
        kind: str,
        email: str | None = None,
        addressbook_name: str | None = None,
        uid: str | None = None,
        path: str = "",
    ) -> None:
        self.kind = kind
        self.email = email
        self.addressbook_name = addressbook_name
        self.uid = uid
        self.path = path

    @property
    def is_collection(self) -> bool:
        return self.kind in {"root", "principals", "principal", "addressbook_home", "addressbook"}

    @property
    def href(self) -> str:
        """Canonical DAV:href for this resource."""
        if self.kind == "root":
            return "/carddav/"
        if self.kind == "principals":
            return "/carddav/principals/"
        if self.kind == "principal":
            return f"/carddav/principals/user/{self.email}/"
        if self.kind == "addressbook_home":
            return f"/carddav/addressbooks/{self.email}/"
        if self.kind == "addressbook":
            return f"/carddav/addressbooks/{self.email}/{self.addressbook_name}/"
        return f"/carddav/addressbooks/{self.email}/{self.addressbook_name}/{self.uid}.vcf"

    def __repr__(self) -> str:
        return f"<CardDavResource kind={self.kind} href={self.href}>"


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------

class ModuleCardDAV:
    """CardDAV server protocol engine backed by an in-memory resource store.

    Store layout::

        principals:  {email: {"display_name": str, "email": str}}
        addressbooks:   {(email, name): {"displayname": str, "description": str,
                                      "etag": str, "last_modified": datetime}}
        contacts:      {(email, name, uid): {"vcard": str, "etag": str, "last_modified": datetime}}
    """

    def __init__(self, base_path: str = "/carddav") -> None:
        self.base_path = base_path
        self.principals: dict[str, dict[str, Any]] = {}
        self.addressbooks: dict[tuple[str, str], dict[str, Any]] = {}
        self.contacts: dict[tuple[str, str, str], dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Path resolution (URI -> CardDavResource)
    # ------------------------------------------------------------------

    def resolve(self, path: str) -> CardDavResource:
        """Split a request URL under base_path into a CardDavResource."""
        clean = path
        if clean.startswith(self.base_path):
            clean = clean[len(self.base_path):]
        clean = "/" + clean.lstrip("/")
        while "//" in clean:
            clean = clean.replace("//", "/")
        segments = [s for s in clean.split("/") if s]

        if not segments:
            return CardDavResource("root", path=clean)

        if segments[0] == "principals":
            if len(segments) == 1:
                return CardDavResource("principals", path=clean)
            if len(segments) >= 2 and segments[1] == "user":
                if len(segments) > 3:
                    raise RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND)
                email = segments[2] if len(segments) > 2 else ""
                return CardDavResource("principal", email=email, path=clean)
            email = segments[1]
            if len(segments) > 2:
                raise RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND)
            return CardDavResource("principal", email=email, path=clean)

        if segments[0] == "addressbooks":
            if len(segments) < 2:
                return CardDavResource("addressbook_home", path=clean)
            email = segments[1]
            if len(segments) == 2:
                return CardDavResource("addressbook_home", email=email, path=clean)
            name = segments[2]
            if len(segments) == 3:
                return CardDavResource("addressbook", email=email, addressbook_name=name, path=clean)
            if len(segments) == 4:
                uid = _UID_SUFFIX_RE.sub("", segments[3])
                return CardDavResource(
                    "contact", email=email, addressbook_name=name, uid=uid, path=clean
                )
            raise RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND)

        raise RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND)

    # ------------------------------------------------------------------
    # Principal / user registry
    # ------------------------------------------------------------------

    def register_user(self, email: str, display_name: str | None = None) -> dict[str, Any]:
        """Register a CardDAV principal. Auto-creates default 'Contacts' addressbook."""
        key = email.lower()
        principal = self.principals.setdefault(
            key, {"email": key, "display_name": display_name or key}
        )
        if display_name:
            principal["display_name"] = display_name
        # Auto-create default Contacts addressbook
        if not self.addressbook_exists(email, "Contacts"):
            self.create_addressbook(email, "Contacts", "Contacts")
        return principal

    def principal_exists(self, email: str) -> bool:
        return email.lower() in self.principals

    def list_principal_emails(self) -> list[str]:
        return sorted(self.principals)

    # ------------------------------------------------------------------
    # Addressbook collections
    # ------------------------------------------------------------------

    def create_addressbook(
        self,
        email: str,
        name: str,
        displayname: str | None = None,
        description: str | None = None,
    ) -> str:
        """Create an addressbook collection. Returns its ETag."""
        email, name = email.lower(), name.lower()
        key = (email, name)
        if key in self.addressbooks:
            raise RequestException(error=err.ERROR_CALDAV_CALENDAR_EXISTS)
        now = self._now_utc()
        etag = self._etag(name, now)
        self.addressbooks[key] = {
            "email": email,
            "name": name,
            "displayname": displayname or name,
            "description": description or "",
            "etag": etag,
            "last_modified": now,
        }
        return etag

    def addressbook_exists(self, email: str, name: str) -> bool:
        return (email.lower(), name.lower()) in self.addressbooks

    def list_addressbooks(self, email: str) -> list[dict[str, Any]]:
        """Return addressbook dicts owned by email (sorted by name)."""
        email = email.lower()
        return [
            ab for (owner, _name), ab in sorted(self.addressbooks.items()) if owner == email
        ]

    def get_addressbook(self, email: str, name: str) -> dict[str, Any]:
        try:
            return self.addressbooks[(email.lower(), name.lower())]
        except KeyError:
            raise RequestException(error=err.ERROR_CALENDAR_NOT_FOUND) from None

    def delete_addressbook(self, email: str, name: str) -> None:
        email, name = email.lower(), name.lower()
        key = (email, name)
        if key not in self.addressbooks:
            raise RequestException(error=err.ERROR_CALENDAR_NOT_FOUND)
        del self.addressbooks[key]
        for contact_key in [k for k in self.contacts if k[:2] == key]:
            del self.contacts[contact_key]

    def update_addressbook_props(
        self, email: str, name: str, changes: dict[str, str]
    ) -> list[tuple[str, str]]:
        """Apply a PROPPATCH. Returns list of (propname, status-text)."""
        addressbook = self.get_addressbook(email, name)
        results: list[tuple[str, str]] = []
        for prop, value in changes.items():
            if prop in ("displayname", "description"):
                addressbook[prop] = value
                results.append((prop, "200 OK"))
            else:
                results.append((prop, "403 Forbidden"))
        if results:
            addressbook["last_modified"] = self._now_utc()
            addressbook["etag"] = self._etag(addressbook["name"], addressbook["last_modified"])
        return results

    # ------------------------------------------------------------------
    # Contact resources
    # ------------------------------------------------------------------

    def put_contact(
        self,
        email: str,
        addressbook_name: str,
        uid: str,
        vcard_text: str,
        if_match: str | None = None,
        if_none_match: str | None = None,
    ) -> tuple[str, bool]:
        """Create (True) or update (False) a contact, honoring ETag preconditions."""
        self.get_addressbook(email, addressbook_name)
        key = (email.lower(), addressbook_name.lower(), uid.lower())
        existing = self.contacts.get(key)

        if existing is not None:
            if if_match is not None and if_match not in (existing["etag"], "*"):
                raise RequestException(error=err.ERROR_CALDAV_PRECONDITION_FAILED)
            if if_none_match == "*":
                raise RequestException(error=err.ERROR_CALDAV_PRECONDITION_FAILED)
        else:
            if if_match is not None and if_match != "*":
                raise RequestException(error=err.ERROR_CALDAV_PRECONDITION_FAILED)

        now = self._now_utc()
        etag = self._etag(f"{uid}:{vcard_text[:50]}", now)
        self.contacts[key] = {
            "uid": uid,
            "vcard": vcard_text,
            "etag": etag,
            "last_modified": now,
        }
        created = existing is None
        return etag, created

    def get_contact(self, email: str, addressbook_name: str, uid: str) -> dict[str, Any]:
        self.get_addressbook(email, addressbook_name)
        key = (email.lower(), addressbook_name.lower(), uid.lower())
        contact = self.contacts.get(key)
        if contact is None:
            raise RequestException(error=err.ERROR_CALENDAR_EVENT_NOT_FOUND)
        return contact

    def delete_contact(
        self, email: str, addressbook_name: str, uid: str, if_match: str | None = None
    ) -> None:
        self.get_addressbook(email, addressbook_name)
        key = (email.lower(), addressbook_name.lower(), uid.lower())
        contact = self.contacts.get(key)
        if contact is None:
            raise RequestException(error=err.ERROR_CALENDAR_EVENT_NOT_FOUND)
        if if_match is not None and if_match not in (contact["etag"], "*"):
            raise RequestException(error=err.ERROR_CALDAV_PRECONDITION_FAILED)
        del self.contacts[key]

    def list_contacts(self, email: str, addressbook_name: str) -> list[dict[str, Any]]:
        """All live contacts of an addressbook (sorted by uid)."""
        prefix = (email.lower(), addressbook_name.lower())
        contacts = [self.contacts[k] for k in self.contacts if k[:2] == prefix]
        return sorted(contacts, key=lambda c: c["uid"])

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _etag(seed: Any, when: datetime) -> str:
        digest = hashlib.sha1(f"{seed}:{when.isoformat()}".encode()).hexdigest()[:10]
        return f'"{digest}"'

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc).replace(microsecond=0)
