from __future__ import annotations

from app.module.contact.source.ContactSourceDb import ContactSourceDb


class ContactSourceCardDav(ContactSourceDb):
    """DB-backed source for external CardDAV address books.

    Contacts are stored locally in sogo6_contacts and populated by the CardDAV sync engine.
    Write restrictions are enforced by ContactAclEngine at the module level, not by the source
    itself. This subclass exists for future CardDAV-specific behavior (etag tracking, sync
    metadata, custom fetch pipeline).
    """
