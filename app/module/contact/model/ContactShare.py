from __future__ import annotations

from dataclasses import dataclass

from app.module.contact.model.enums.ContactShareLevel import ContactShareLevel


@dataclass
class ContactShare:
    """Represents a sharing rule for an address book.

    Maps an address book to a user it is shared with. The single share_level
    (ContactShareLevel) applies to all contacts in the book - no per-visibility
    classes like calendar shares.
    """

    user_uid: str = ""
    addressbook_key: str = ""
    share_level: ContactShareLevel = ContactShareLevel.VIEW
