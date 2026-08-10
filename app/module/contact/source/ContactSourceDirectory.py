from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.module.contact.model.CardAddressBook import CardAddressBook
from app.module.contact.model.CardContact import CardContact
from app.module.contact.model.CardContactSyncMeta import CardContactSyncMeta
from app.module.contact.model.CardEmail import CardEmail
from app.module.contact.model.CardPhone import CardPhone
from app.module.contact.source.ContactSource import ContactSource
from app.utils import errors as err
from app.utils.db.Condition import Order
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_contact
from app.utils.module.importManager import import_and_instantiate_manager

if TYPE_CHECKING:
    from app.config.settings.DomainSettings import UserSourceSettingsObj
    from app.manager.user_source.ClientUserSource import ClientUserSource
    from app.module.contact.model.CardList import CardList

# Map of US_TYPE to client module path and class name (mirrors ModuleUserSource).
MAP_KEY_CLASS: dict[str, str] = {
    "ldap": "ClientLdap",
    "mysql": "ClientMySQL",
    "postgresql": "ClientPostgreSQL",
}

MAP_KEY_PATH: dict[str, str] = {
    "ldap": "app.manager.ldap",
    "mysql": "app.manager.db",
    "postgresql": "app.manager.db",
}

# Attribute name on the entry dict for the DN / row identifier.
_KEY_ATTR: str = "dn"


class ContactSourceDirectory(ContactSource):  # pylint: disable=unused-argument
    """Contact source backed by a domain user source (the directory / annuaire), SQL or LDAP.

    Surfaces the domain directory as a synthetic, domain-wide address book so its entries
    contribute to transverse search and recipient autocompletion alongside the user's personal
    contacts. The backend is abstracted by the user source layer (US_TYPE = sql | ldap); this class
    adapts directory entries to CardContact.

    The address book is synthetic (not persisted in the DB) and read-only: directory entries are
    derived from the user source every query, never written through this adapter.
    """

    def __init__(self, addressbook: CardAddressBook, user_source: UserSourceSettingsObj) -> None:
        super().__init__(addressbook)
        self._user_source: UserSourceSettingsObj = user_source
        self._us_type: str = user_source.US_TYPE

    # ------------------------------------------------------------------
    # Backend client helpers
    # ------------------------------------------------------------------

    def _build_client(self) -> ClientUserSource:
        """Instantiate and connect the appropriate backend client (LDAP or SQL).

        Uses the same dynamic import mechanism as ModuleUserSource.
        """
        us_config: dict[str, Any] = self._user_source.get_user_source_settings(self._us_type)
        client: ClientUserSource = import_and_instantiate_manager(
            module_path=MAP_KEY_PATH[self._us_type],
            module_and_class_name=MAP_KEY_CLASS[self._us_type],
            module_args=us_config,
        )
        client.connect()
        return client

    def _get_search_fields(self) -> list[str]:
        """Return the list of attribute/column names to search against.

        Falls back to ``US_SEARCH``, or ``[US_DISPLAY_NAME] + US_MAIL`` when not configured.
        """
        search: list[str] = self._user_source.US_SEARCH
        if search:
            return search
        fields: list[str] = []
        if self._user_source.US_DISPLAY_NAME:
            fields.append(self._user_source.US_DISPLAY_NAME)
        fields.extend(self._user_source.US_MAIL)
        return fields or ["cn", "mail"]

    def _get_display_name_field(self) -> str:
        """Return the attribute/column to use as the display name (FN).

        Falls back to ``US_LDAP_CN`` for LDAP, or ``\"display_name\"`` for SQL.
        """
        if self._user_source.US_DISPLAY_NAME:
            return self._user_source.US_DISPLAY_NAME
        if self._us_type == "ldap":
            return self._user_source.US_LDAP_CN or "cn"
        return "display_name"

    def _get_uid_field(self) -> str:
        """Return the attribute/column that holds the user's unique identifier."""
        if self._us_type == "ldap":
            return self._user_source.US_LDAP_UID or "uid"
        return "uid"

    def _get_attributes_to_fetch(self) -> list[str]:
        """Return the list of attribute names to fetch from the backend.

        Includes display name, mail fields, uid, and any extra contact info fields.
        """
        attrs: set[str] = set()
        # UID field
        attrs.add(self._get_uid_field())
        # Display name
        attrs.add(self._get_display_name_field())
        # Mail fields
        attrs.update(self._user_source.US_MAIL)
        # Search fields
        attrs.update(self._get_search_fields())
        # Extra contact info
        if self._user_source.US_EXTRA_CONTACT_INFO:
            attrs.add(self._user_source.US_EXTRA_CONTACT_INFO)
        # For LDAP, always fetch cn as fallback
        if self._us_type == "ldap":
            attrs.add("cn")
            attrs.add("sn")
            attrs.add("givenName")
            attrs.add("telephoneNumber")
            attrs.add("title")
            attrs.add("o")
            attrs.add("ou")
        return list(attrs)

    # ------------------------------------------------------------------
    # LDAP-specific helpers
    # ------------------------------------------------------------------

    def _build_ldap_filter(self, search: str | None) -> str | None:
        """Build an LDAP filter string from a search query.

        When search is None or empty, returns the configured US_LDAP_FILTER (or None).
        Otherwise builds ``(|(field1=*query*)(field2=*query*)...)`` and ANDs it with
        the configured filter.
        """
        from app.manager.ldap.ClientLdap import ldap_escape

        parts: list[str] = []
        if self._user_source.US_LDAP_FILTER:
            parts.append(self._user_source.US_LDAP_FILTER)
        else:
            # Default: only real person entries (objectClass=inetOrgPerson or posixAccount)
            parts.append("(|(objectClass=inetOrgPerson)(objectClass=posixAccount)(objectClass=person))")

        if search:
            search_escaped: str = ldap_escape(search)
            search_fields: list[str] = self._get_search_fields()
            if search_fields:
                sub_filters: list[str] = []
                for field in search_fields:
                    sub_filters.append(f"({field}=*{search_escaped}*)")
                joined_subs = "".join(sub_filters)
                parts.append(f"(|{joined_subs})")

        if len(parts) == 1:
            return parts[0]
        joined_parts = "".join(parts)
        return f"(&{joined_parts})"

    def _ldap_entry_to_contact(self, entry: dict[str, list[str]]) -> CardContact | None:
        """Map a raw LDAP entry dict to a CardContact.

        Returns None if the entry should be skipped (hidden user).
        """
        uid_val: str | None = self._get_first(entry, self._get_uid_field())
        if not uid_val:
            return None

        # Check hidden users
        if self._user_source.US_HIDDEN_USER and uid_val in self._user_source.US_HIDDEN_USER:
            return None

        display_name: str = self._get_first(entry, self._get_display_name_field()) or ""
        if not display_name:
            display_name = self._get_first(entry, "cn") or uid_val

        # Parse structured name
        first_name: str = self._get_first(entry, "givenName") or ""
        last_name: str = self._get_first(entry, "sn") or ""
        if not first_name and not last_name:
            # Split display name into first/last by first space
            parts: list[str] = display_name.split(" ", 1)
            first_name = parts[0] if parts else ""
            last_name = parts[1] if len(parts) > 1 else ""

        # Build email list
        emails: list[CardEmail] = []
        for mail_field in self._user_source.US_MAIL:
            for mail_val in entry.get(mail_field, []):
                emails.append(CardEmail(email=mail_val))

        # Phone
        phones_raw: list[str] = entry.get("telephoneNumber", [])
        phones: list = [CardPhone(phone=p) for p in phones_raw]

        # Organization
        organization: str = self._get_first(entry, "o") or ""
        department: str = self._get_first(entry, "ou") or ""

        # Job title
        job_title: str = self._get_first(entry, "title") or ""

        # Build a stable opaque key from the DN or uid
        dn: str = self._get_first(entry, "dn") or ""
        if dn:
            # Use a hash of the DN as the key so lookups are reproducible
            import hashlib
            key: str = f"dir:{self._user_source.US_UID}:{hashlib.sha256(dn.encode()).hexdigest()[:16]}"
        else:
            key = f"dir:{self._user_source.US_UID}:{uid_val}"

        contact: CardContact = CardContact(
            uid=f"dir-{self._user_source.US_UID}-{uid_val}",
            key=key,
            display_name=display_name,
            first_name=first_name,
            last_name=last_name,
            organization=organization or None,
            department=department or None,
            job_title=job_title or None,
            emails=emails,
            phones=phones,
            rev=datetime.utcnow(),
            addressbook_key=self._addressbook.require_key,
        )
        return contact

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_first(entry: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
        """Return the first value from an entry dict for the given key, or default."""
        values: list[str] | None = entry.get(key)
        if values and len(values) > 0:
            return values[0]
        return default

    def _query_directory(
        self, search: str | None = None, offset: int = 0, limit: int = 0,
        sort_by: str | None = None, order: Order = Order.ASC,
    ) -> tuple[list[CardContact], int]:
        """Query the directory backend and return (page, total)."""
        if self._us_type == "ldap":
            return self._query_ldap(search, offset, limit, sort_by, order)
        if self._us_type in ("mysql", "postgresql"):
            return self._query_sql(search, offset, limit, sort_by, order)
        logger_contact.error("Unsupported user source type for directory: %s", self._us_type)
        return [], 0

    def _query_ldap(
        self, search: str | None = None, offset: int = 0, limit: int = 0,
        sort_by: str | None = None, order: Order = Order.ASC,
    ) -> tuple[list[CardContact], int]:
        """Query the LDAP directory, map entries to CardContact, paginate and sort."""
        try:
            client = self._build_client()
        except Exception as exc:
            logger_contact.error("Failed to connect to LDAP directory (%s): %s",
                                 self._user_source.US_LDAP_HOSTNAME, exc)
            return [], 0

        try:
            l_filter: str | None = self._build_ldap_filter(search)
            attributes: list[str] = self._get_attributes_to_fetch()
            # LDAP returns results as list[dict[str, list[str]]]
            raw_entries: list[dict[str, list[str]]] = client.search_entries(
                base_dn=self._user_source.US_LDAP_BASE_DN,
                l_filter=l_filter,
                attributes=attributes,
            )
        except Exception as exc:
            logger_contact.error("LDAP directory search failed (%s): %s",
                                 self._user_source.US_LDAP_HOSTNAME, exc)
            return [], 0
        finally:
            try:
                client.close()
            except Exception:
                pass  # best-effort: keep fallback/default value on failure

        contacts: list[CardContact] = []
        for raw in raw_entries:
            contact = self._ldap_entry_to_contact(raw)
            if contact is not None:
                contacts.append(contact)

        # Sort
        self._sort_contacts(contacts, sort_by, order)

        # Apply US_AUTO_QUERY_LIMIT
        auto_limit: int = self._user_source.US_AUTO_QUERY_LIMIT
        effective_limit: int = limit if limit > 0 else (auto_limit if auto_limit > 0 else 0)

        total: int = len(contacts)
        if effective_limit > 0:
            page: list[CardContact] = contacts[offset:offset + effective_limit]
        else:
            page = contacts[offset:]
        return page, total

    def _query_sql(
        self, search: str | None = None, offset: int = 0, limit: int = 0,
        sort_by: str | None = None, order: Order = Order.ASC,
    ) -> tuple[list[CardContact], int]:
        """Query the SQL user source table and map rows to CardContact.

        .. warning::

           SQL-backed directories are not yet implemented. The LDAP path is fully
           functional; SQL support requires a query adapter that translates contact
           search fields (US_SEARCH, US_DISPLAY_NAME, US_MAIL) into a SQL query on
           the user source table referenced by US_SQL_USER_FILTER.

        Until that adapter is built, this method logs a warning and returns empty.
        """
        logger_contact.warning(
            "SQL-based directory address books are not yet implemented "
            "(source_uid=%s, type=%s). Returning empty results.",
            self._user_source.US_UID, self._us_type,
        )
        return [], 0

    @staticmethod
    def _sort_contacts(contacts: list[CardContact], sort_by: str | None, order: Order) -> None:
        """Sort contacts in-place by the given field."""
        sort_key: str = (sort_by or "display_name").lower()
        reverse: bool = order == Order.DESC

        def _key(c: CardContact) -> str:
            if sort_key == "last_name":
                return (c.last_name or c.display_name or "").casefold()
            if sort_key == "first_name":
                return (c.first_name or c.display_name or "").casefold()
            if sort_key == "email":
                if c.emails:
                    return c.emails[0].email.casefold()
                return ""
            return (c.display_name or "").casefold()

        contacts.sort(key=_key, reverse=reverse)

    # ------------------------------------------------------------------
    # ContactSource abstract methods
    # ------------------------------------------------------------------

    def is_writable(self) -> bool:
        """Directory sources are read-only by default.

        SQL-based system sources MAY be writable by configured modifiers in the future,
        but the write path has not been designed yet.
        """
        return False

    def save_addressbook(self, addressbook: CardAddressBook) -> CardAddressBook:
        """The directory address book is synthetic and cannot be persisted."""
        raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED)

    def update_addressbook(self, addressbook: CardAddressBook) -> None:
        """The directory address book is synthetic and cannot be updated."""
        raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED)

    def delete_addressbook(self, hard_delete: bool = False) -> None:
        """The directory address book is synthetic and cannot be deleted."""
        raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED)

    def get_contacts(
        self, search: str | None = None, offset: int = 0, limit: int = 0,
        sort_by: str | None = None, order: Order = Order.ASC,
    ) -> list[CardContact]:
        """Return directory entries matching the search, paginated and sorted."""
        page, _ = self._query_directory(search, offset, limit, sort_by, order)
        return page

    def count_contacts(self, search: str | None = None) -> int:
        """Return the total number of directory entries matching the search."""
        _, total = self._query_directory(search)
        return total

    def get_contact_by_key(self, key: str) -> CardContact | None:
        """Resolve a directory entry by its opaque ``dir:<source_uid>:<hash>`` key.

        The key format is ``dir:<source_uid>:<sha256_prefix>``. We extract the uid
        by scanning all directory entries for a matching hash. For performance,
        the hash is computed from the dn (LDAP) or uid (SQL).
        """
        # Key format: dir:<source_uid>:<hash>
        if not key or not key.startswith("dir:"):
            return None
        parts: list[str] = key.split(":", 2)
        if len(parts) < 3:
            return None
        # parts[0] = "dir", parts[1] = source_uid, parts[2] = hash
        if parts[1] != self._user_source.US_UID:
            return None
        _ = parts[2]

        # Fetch all entries and find the one with matching key
        all_contacts, _ = self._query_directory()
        for contact in all_contacts:
            if contact.key == key:
                return contact
        return None

    def get_contact_by_uid(self, uid: str) -> CardContact | None:
        """Resolve a directory entry by its vCard-style UID (``dir-<source_uid>-<uid_val>``)."""
        if not uid or not uid.startswith("dir-"):
            return None
        # uid format: dir-<source_uid>-<uid_val>
        expected_prefix: str = f"dir-{self._user_source.US_UID}-"
        if not uid.startswith(expected_prefix):
            return None
        uid_val: str = uid[len(expected_prefix):]

        if self._us_type == "ldap":
            return self._get_ldap_contact_by_uid(uid_val)
        return self._get_sql_contact_by_uid(uid_val)

    def _get_ldap_contact_by_uid(self, uid_val: str) -> CardContact | None:
        """Query LDAP for a single entry by its UID."""
        try:
            client = self._build_client()
        except Exception as exc:
            logger_contact.error("Failed to connect to LDAP for uid lookup: %s", exc)
            return None

        try:
            uid_field: str = self._get_uid_field()
            l_filter: str = f"({uid_field}={uid_val})"
            attributes: list[str] = self._get_attributes_to_fetch()
            raw: list[dict[str, list[str]]] = client.search_entries(
                base_dn=self._user_source.US_LDAP_BASE_DN,
                l_filter=l_filter,
                attributes=attributes,
            )
            if not raw:
                return None
            contact: CardContact | None = self._ldap_entry_to_contact(raw[0])
            return contact
        except Exception as exc:
            logger_contact.error("LDAP uid lookup failed for %s: %s", uid_val, exc)
            return None
        finally:
            try:
                client.close()
            except Exception:
                pass  # best-effort: keep fallback/default value on failure

    def _get_sql_contact_by_uid(self, uid_val: str) -> CardContact | None:
        """Query SQL for a single entry by its UID.

        .. warning::

           SQL-backed directories are not yet implemented; this method logs a
           warning and returns None.
        """
        logger_contact.warning(
            "SQL-based directory address books are not yet implemented "
            "(source_uid=%s, type=%s). Cannot look up contact by uid.",
            self._user_source.US_UID, self._us_type,
        )
        return None

    def insert_contact(self, contact: CardContact) -> CardContact:
        """Directory is read-only; contacts cannot be inserted."""
        raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED)

    def update_contact(self, contact: CardContact) -> None:
        """Directory is read-only; contacts cannot be updated."""
        raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED)

    def delete_contact(self, key: str) -> None:
        """Directory is read-only; contacts cannot be deleted."""
        raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED)

    def get_lists(
        self, search: str | None = None, offset: int = 0, limit: int = 0,
        sort_by: str | None = None, order: Order = Order.ASC,
    ) -> list[CardList]:
        """A directory has no distribution lists."""
        return []

    def count_lists(self, search: str | None = None) -> int:
        """A directory has no distribution lists."""
        return 0

    def get_list_by_key(self, key: str) -> CardList | None:
        """A directory has no distribution lists."""
        return None

    def get_list_by_uid(self, uid: str) -> CardList | None:
        """A directory has no distribution lists."""
        return None

    def insert_list(self, card_list: CardList) -> CardList:
        """Directory is read-only; lists cannot be inserted."""
        raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED)

    def update_list(self, card_list: CardList) -> None:
        """Directory is read-only; lists cannot be updated."""
        raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED)

    def delete_list(self, key: str) -> None:
        """Directory is read-only; lists cannot be deleted."""
        raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED)

    def delete_by_key(self, key: str) -> None:
        """Directory is read-only; contacts cannot be deleted."""
        raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED)

    def get_sync_metadata(self) -> list[CardContactSyncMeta]:
        """Directory entries are live-queried every time; sync metadata is not applicable."""
        return []
