from __future__ import annotations

from typing import TYPE_CHECKING

from app.factory.share import RIGHT_EDIT, RIGHT_VIEW
from app.module.contact.model.enums.ContactShareLevel import ContactShareLevel
from app.utils import errors as err
from app.utils.exceptions import RequestException

if TYPE_CHECKING:
    from app.auth.User import User
    from app.factory.share import ShareContact
    from app.module.contact.model.CardAddressBook import CardAddressBook
    from app.module.contact.repository.RepositoryContactShare import RepositoryContactShare


class ContactAclEngine:
    """Resolves and enforces address book permissions.

    Centralizes contact ACL logic: access-level resolution and action checks.
    Owner gets MODIFY on their own books. Non-owners are looked up in the share
    repository (if available) or denied.

    Migration to the unified ACL system is in progress: when an optional ShareContact
    (app.factory.share, backed by sogo6_acl) is injected, non-owner shares resolve
    through it first, mapping the stored rights blob via ShareContact.has_right()
    (edit right -> MODIFY, view right -> VIEW); address books with no sogo6_acl
    entry yet fall back to the legacy RepositoryContactShare lookup.
    """

    def __init__(
        self,
        share_repo: RepositoryContactShare | None = None,
        share_contact: ShareContact | None = None,
    ) -> None:
        """Optionally inject a share repository and/or ShareContact for resolving shared-user permissions."""
        self._share_repo = share_repo
        self._share_contact = share_contact

    def set_share_contact(self, share_contact: ShareContact | None) -> None:
        """Inject or clear the optional ShareContact (unified sogo6_acl-backed engine)."""
        self._share_contact = share_contact

    def get_share_level(self, addressbook: CardAddressBook, user: User) -> ContactShareLevel | None:
        """Resolve the acting user's access level on an address book, or None when denied.

        The owner gets MODIFY on their own books. Non-owners are looked up in the share
        repository (if available) or denied.
        """
        if addressbook.user_uid == user.uid:
            return ContactShareLevel.MODIFY
        return self._lookup_share(addressbook, user)

    def _lookup_share(self, addressbook: CardAddressBook, user: User) -> ContactShareLevel | None:
        """Look up a share entry for the acting user on this address book.

        Unified path first: when a ShareContact is injected, resolve the user's sogo6_acl
        entry via ShareContact.has_right() (the owner already defaulted to MODIFY in
        get_share_level and never reaches here): holding the edit right maps to MODIFY,
        otherwise the view right maps to VIEW. When ShareContact reports no qualifying
        entry (address book not in sogo6_acl yet) or none was injected, fall back to the
        legacy RepositoryContactShare lookup, which returns the stored share level or
        None when denied.
        """
        if self._share_contact is not None:
            if self._share_contact.has_right(
                user.uid, addressbook.user_uid, addressbook.require_key, RIGHT_EDIT,
            ):
                return ContactShareLevel.MODIFY
            if self._share_contact.has_right(
                user.uid, addressbook.user_uid, addressbook.require_key, RIGHT_VIEW,
            ):
                return ContactShareLevel.VIEW
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
