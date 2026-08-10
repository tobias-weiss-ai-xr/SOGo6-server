from __future__ import annotations

from typing import TYPE_CHECKING

from app.module.contact.model.enums.ContactShareLevel import ContactShareLevel
from app.utils import errors as err
from app.utils.exceptions import RequestException

if TYPE_CHECKING:
    from app.auth.User import User
    from app.module.contact.model.CardAddressBook import CardAddressBook
    from app.module.contact.repository.RepositoryContactShare import RepositoryContactShare


class ContactAclEngine:
    """Resolves and enforces address book permissions.

    Centralizes contact ACL logic: access-level resolution and action checks.
    Owner gets MODIFY on their own books. Non-owners are looked up in the share
    repository (if available) or denied.
    """

    def __init__(self, share_repo: RepositoryContactShare | None = None) -> None:
        """Optionally inject a share repository for resolving shared-user permissions."""
        self._share_repo = share_repo

    def get_share_level(self, addressbook: CardAddressBook, user: User) -> ContactShareLevel | None:
        """Resolve the acting user's access level on an address book, or None when denied.

        The owner gets MODIFY on their own books. Non-owners are looked up in the share
        repository (if available) or denied.
        """
        if addressbook.user_uid == user.uid:
            return ContactShareLevel.MODIFY
        return self._lookup_share(addressbook, user)

    def _lookup_share(self, addressbook: CardAddressBook, user: User) -> ContactShareLevel | None:
        """Look up a share entry for the acting user on this address book."""
        if self._share_repo is None:
            return None
        share = self._share_repo.find_by_addressbook_and_user(
            addressbook.require_key, user.uid,
        )
        if share is not None:
            return share.share_level
        return None

    def check_permission(self, level: ContactShareLevel | None, required: ContactShareLevel) -> None:
        """Raise ERROR_CONTACT_ACCESS_DENIED when the resolved level is below the required one.

        A None level (no access) always denies. ContactShareLevel is ordered VIEW < MODIFY, so a
        VIEW level satisfies a VIEW requirement but not a MODIFY one.
        """
        if level is None or level < required:
            raise RequestException(error=err.ERROR_CONTACT_ACCESS_DENIED)
