from __future__ import annotations

from typing import TYPE_CHECKING

from app.config.db import tables as tbl
from app.module.contact.model.CardAddressBook import CardAddressBook
from app.module.contact.model.enums.CardSourceType import CardSourceType
from app.module.contact.repository.RepositoryAddressBook import RepositoryAddressBook
from app.module.contact.repository.RepositoryContact import RepositoryContact
from app.module.contact.repository.RepositoryContactList import RepositoryContactList
from app.module.contact.repository.RepositoryContactShare import RepositoryContactShare
from app.module.contact.source.ContactSourceCardDav import ContactSourceCardDav
from app.module.contact.source.ContactSourceDb import SORTABLE_COLUMNS, ContactSourceDb
from app.module.contact.source.ContactSourceDirectory import ContactSourceDirectory
from app.utils import errors as err
from app.utils.db.Condition import Order
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_contact

if TYPE_CHECKING:
    from app.config.settings.DomainSettings import UserSourceSettingsObj
    from app.manager.db.ClientSQL import ClientSQL
    from app.manager.storage.ClientStorage import ClientStorage
    from app.module.contact.model.CardContact import CardContact
    from app.module.contact.model.CardList import CardList
    from app.module.contact.source.ContactSource import ContactSource


class ContactSources:
    """Factory and lookup for ContactSource instances.

    Single entry point for all address book access - ModuleContact never touches
    RepositoryAddressBook directly. All reads are scoped to a user_uid.

    The optional user_sources threaded through the read methods are the domain's user sources
    (keyed by source_uid). When None, only the local DB address books are served; when provided,
    the ones flagged US_IS_ADDRESSBOOK are surfaced as read-only directory address books - the seam
    for the annuaire (SQL or LDAP), one ContactSourceDirectory per source.
    """

    def __init__(
        self,
        db: ClientSQL,
        share_repo: RepositoryContactShare | None = None,
    ) -> None:
        self._db = db
        self._repo_addressbook = RepositoryAddressBook(db)
        self._share_repo = share_repo

    def purge_orphans(self, file_store: ClientStorage) -> int:
        """Physically remove soft-deleted rows, dangling list memberships and orphan media; return total reclaimed.

        Global sweep (not scoped to one book): deleting an address book detaches its contacts and lists
        (addressbook_key NULL), so only an is_deleted purge reaches those tombstones. Orphan membership
        rows and blobs no contact references any more are then reclaimed.
        """
        contact_repo: RepositoryContact = RepositoryContact(self._db)
        list_repo: RepositoryContactList = RepositoryContactList(self._db)
        purged: int = contact_repo.purge_deleted() + list_repo.purge_deleted()
        purged += list_repo.purge_orphan_members(list_repo.all_keys(), contact_repo.all_keys())
        referenced: set[str] = {value for value in contact_repo.all_photo_values() if file_store.is_reference(value)}
        purged += file_store.purge_orphans(referenced)
        return purged

    def get(self, addressbook: CardAddressBook, user_sources: dict[str, UserSourceSettingsObj] | None = None) -> ContactSource:
        """Return the appropriate ContactSource for the given address book.

        Local books are served from the DB, CardDAV books from the sync engine.
        Directory books (synthetic, read-only) are backed by the matching
        US_IS_ADDRESSBOOK entry in user_sources.
        """
        if addressbook.source_type == CardSourceType.LOCAL:
            return ContactSourceDb(self._db, addressbook)

        if addressbook.source_type == CardSourceType.CARDDAV:
            return ContactSourceCardDav(self._db, addressbook)

        if addressbook.source_type == CardSourceType.DIRECTORY:
            if user_sources is None:
                raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED)
            source_uid: str | None = _parse_directory_key(addressbook.key)
            if source_uid is None:
                raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED)
            user_source: UserSourceSettingsObj | None = user_sources.get(source_uid)
            if user_source is None:
                logger_contact.error(
                    "Directory address book %s references unknown user source %s",
                    addressbook.key, source_uid)
                raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED)
            return ContactSourceDirectory(addressbook, user_source)

        logger_contact.error("Unknown source_type=%s for address book key=%s", addressbook.source_type, addressbook.key)
        raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED)

    def get_all(self, user_uid: str, user_sources: dict[str, UserSourceSettingsObj] | None = None) -> list[ContactSource]:
        """Return a source for every address book visible to user_uid.

        Includes address books OWNED by user_uid, books SHARED WITH user_uid
        (from sogo6_contacts_shares), and synthetic directory address books for each
        user source flagged with US_IS_ADDRESSBOOK. Per-book permissions are enforced
        downstream by ContactAclEngine.get_share_level().
        """
        owned: list[CardAddressBook] = self._repo_addressbook.find_all(user_uid)
        seen_keys: set[str | None] = {book.key for book in owned}
        if self._share_repo is not None:
            shared_keys: list[str] = self._share_repo.find_addressbook_keys_for_user(user_uid)
            for key in shared_keys:
                if key not in seen_keys:
                    seen_keys.add(key)
                    book = self._repo_addressbook.find_by_key_unscoped(key)
                    if book is not None:
                        owned.append(book)

        # Add synthetic directory books from US_IS_ADDRESSBOOK user sources
        if user_sources is not None:
            for source_uid, us_cfg in user_sources.items():
                if us_cfg.US_IS_ADDRESSBOOK:
                    dir_key: str = f"dir:{source_uid}"
                    if dir_key not in seen_keys:
                        seen_keys.add(dir_key)
                        dir_book: CardAddressBook = _make_directory_book(source_uid, us_cfg, user_uid)
                        owned.append(dir_book)

        return [self.get(book, user_sources) for book in owned]

    def update_sync_config(self, addressbook: CardAddressBook) -> None:
        """Persist sync_config changes for an external address book."""
        self._repo_addressbook.update(addressbook)

    def get_default(self, user_uid: str) -> ContactSource | None:
        """Return the default address book source for user_uid, or None if the user has none."""
        book: CardAddressBook | None = self._repo_addressbook.get_default_for_user(user_uid)
        return self.get(book) if book is not None else None

    def get_by_key(
        self, user_uid: str, key: str, user_sources: dict[str, UserSourceSettingsObj] | None = None,
    ) -> ContactSource | None:
        """Return the source for a specific address book, or None if not found.

        Directory books carry a reserved "dir:<source_uid>" prefix (a raw UUID never
        starts with it), so the branch is unambiguous: strip the prefix, look the
        source_uid up in user_sources, build a synthetic directory book. A plain UUID
        falls through to the DB lookup below.
        """
        if key.startswith("dir:") and user_sources is not None:
            source_uid = _parse_directory_key(key)
            if source_uid and source_uid in user_sources:
                us_cfg: UserSourceSettingsObj = user_sources[source_uid]
                if us_cfg.US_IS_ADDRESSBOOK:
                    book: CardAddressBook = _make_directory_book(source_uid, us_cfg, user_uid)
                    return self.get(book, user_sources)
            return None

        book = self._repo_addressbook.find_by_key(user_uid, key)
        if book is None:
            book = self._repo_addressbook.find_by_key_unscoped(key)
        return self.get(book, user_sources) if book is not None else None

    def get_contacts(  # pylint: disable=too-many-locals
        self, user_uid: str, search: str | None = None, offset: int = 0, limit: int = 0,
        sort_by: str | None = None, order: Order = Order.ASC, addressbook_key: str | None = None,
        user_sources: dict[str, UserSourceSettingsObj] | None = None, resolve_ab: bool = True,
    ) -> tuple[list[CardContact], int]:
        """Return a page of contacts plus the total count.

        When addressbook_key is given, the query is scoped to that single address book (DB-level
        pagination). When None, contacts from every source of the user are merged, sorted by display
        name and paginated in memory - the seam through which the LDAP directory will also contribute.

        When resolve_ab is True, each returned contact is stamped with its originating address book
        name (display only) from a local key->name cache built from the sources already loaded - no
        extra query, no Redis. Callers that do not need the provenance can pass resolve_ab=False.

        :param user_uid: Owner of the address books to query.
        :param search: Optional full-text query.
        :param offset: Number of contacts to skip (pagination).
        :param limit: Maximum number of contacts to return (0 = no limit).
        :param sort_by: Sort column applied at the DB level for the single-book case.
        :param order: Sort direction (ascending or descending).
        :param addressbook_key: Restrict to one book, or None to span all the user's books.
        :param user_sources: Domain user sources keyed by source_uid; the US_IS_ADDRESSBOOK ones are surfaced as directory books (None = local DB only).
        :param resolve_ab: When True, stamp each contact with its address book name for the response.
        :return: A tuple (contacts page, total count matching the filter).
        """
        if addressbook_key is not None:
            source = self.get_by_key(user_uid, addressbook_key, user_sources)
            if source is None:
                raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND)
            page: list[CardContact] = source.get_contacts(search, offset, limit, sort_by, order)
            if resolve_ab:
                self._stamp_addressbook_name(page, {source.addressbook.key: source.addressbook.name})
            return page, source.count_contacts(search)

        sources = self.get_all(user_uid, user_sources)
        book_names: dict[str | None, str] = {src.addressbook.key: src.addressbook.name for src in sources}

        if all(isinstance(src, ContactSourceDb) for src in sources):
            # Single DB query across every book, paginated and sorted at the DB level (no full load).
            book_keys: list[str] = [src.addressbook.require_key for src in sources]
            sort_column: str = sort_by if sort_by in SORTABLE_COLUMNS else tbl.COL_CT_DISPLAY_NAME.name
            repo: RepositoryContact = RepositoryContact(self._db)
            page = repo.find_by_addressbooks(book_keys, search, offset, limit, sort_column, order)
            if resolve_ab:
                self._stamp_addressbook_name(page, book_names)
            return page, repo.count_by_addressbooks(book_keys, search)

        # Mixed sources (a directory contributes): merge and paginate in memory.
        contacts: list[CardContact] = []
        for source in sources:
            contacts.extend(source.get_contacts(search))
        contacts.sort(key=lambda contact: (contact.display_name or "").casefold(), reverse=order == Order.DESC)
        total: int = len(contacts)
        page = contacts[offset:offset + limit] if limit else contacts[offset:]
        if resolve_ab:
            self._stamp_addressbook_name(page, book_names)
        return page, total

    def search_all_lists(
        self, user_uid: str, search: str | None = None, limit: int = 0,
        user_sources: dict[str, UserSourceSettingsObj] | None = None, resolve_ab: bool = True,
    ) -> list[CardList]:
        """Return the user's distribution lists across every book (transverse), for autocomplete.

        Lists from every source are merged, sorted by name, then capped to limit (the cap is on the
        number of lists, not on members). Each surviving list is stamped with its originating address
        book name and has its members fully resolved to their CardContact (exhaustively, so a
        suggestion can expand to every recipient); resolution stays within the list's own book.
        """
        sources = self.get_all(user_uid, user_sources)
        source_by_book: dict[str | None, ContactSource] = {src.addressbook.key: src for src in sources}
        lists: list[CardList] = []
        for source in sources:
            lists.extend(source.get_lists(search))
        lists.sort(key=lambda card_list: (card_list.name or "").casefold())
        if limit:
            lists = lists[:limit]
        for card_list in lists:
            list_source: ContactSource | None = source_by_book.get(card_list.addressbook_key)
            if list_source is None:
                continue
            if resolve_ab:
                card_list.addressbook_name = list_source.addressbook.name
            card_list.member_contacts = [
                contact for contact in (list_source.get_contact_by_key(key) for key in card_list.members)
                if contact is not None
            ]
        return lists

    @staticmethod
    def _stamp_addressbook_name(contacts: list[CardContact], book_names: dict[str | None, str]) -> None:
        """Stamp each contact's originating address book name (display only) from a key->name cache."""
        for contact in contacts:
            contact.addressbook_name = book_names.get(contact.addressbook_key)


def _parse_directory_key(key: str) -> str | None:
    """Extract the source_uid from a ``dir:<source_uid>`` key, or None if the key format is invalid."""
    if not key or not key.startswith("dir:"):
        return None
    parts: list[str] = key.split(":", 2)
    if len(parts) < 2:
        return None
    return parts[1]


def _make_directory_book(source_uid: str, us_cfg: UserSourceSettingsObj, user_uid: str) -> CardAddressBook:
    """Build a synthetic CardAddressBook representing the domain directory backed by *source_uid*.

    The book is not persisted in the DB; it exists only as a runtime object so the
    contact source layer can dispatch queries to ContactSourceDirectory.
    """
    return CardAddressBook(
        user_uid=user_uid,
        key=f"dir:{source_uid}",
        name=us_cfg.US_NAME or "Domain Directory",
        description=us_cfg.US_NAME or "",
        is_default=False,
        source_type=CardSourceType.DIRECTORY,
    )
