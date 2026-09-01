"""Hybrid SQL+LDAP contact list service (BACKEND-GAPS F3, subsection 1).

Presents every addressable contact list to callers as a single namespace and
routes member operations by list ID type via :mod:`app.utils.id_resolver`:

- ``ldap:<cn>`` / ``cn=<cn>,ou=groups,...`` -> LDAP ``groupOfNames``
  distribution groups (handled by :class:`LDAPGroupService`)
- numeric / any other id -> SQL-backed address books (handled by an injected
  *SQL provider*)

The SQL side is injected as a duck-typed provider so unit tests never need a
live database. The provider must expose:

- ``books(user_sources=None) -> list[dict]``  (hybrid listing entries)
- ``get_members(list_id, user_sources=None) -> list[str]``
- ``add_member(list_id, contact_id, user_sources=None) -> str``
- ``remove_member(list_id, contact_id, user_sources=None) -> str``

:class:`ModuleSQLListProvider` adapts :class:`~app.module.contact.ModuleContact`
to that contract for production wiring; tests inject fakes instead.

The LDAP connection is optional (injected ``client`` or built through the
factories). ``list_lists()`` degrades gracefully when no live LDAP source is
configured: it then returns the SQL address books only instead of failing the
whole listing.
"""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from app.module.contact.LdapGroupService import LDAPGroupService
from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.id_resolver import is_ldap_group
from app.utils.logger.logger import logger_ldap

if TYPE_CHECKING:
    from app.config.settings.DomainSettings import UserSourceSettingsObj
    from app.utils.api.paginate_sort_filter import CollectionPaginateArgs

# Normalized list entry source marker for LDAP groups.
_SOURCE_LDAP = "ldap"
# Normalized list entry source marker for SQL address books.
_SOURCE_SQL = "sql"


class ModuleSQLListProvider:
    """Adapts :class:`ModuleContact` to the ``sql_provider`` contract.

    A SQL *list* is an address book: ``books()`` yields the user's address books
    (with a contact member_count), ``get_members()`` returns the contact UIDs of
    one book. SQL address books have no mutable ``member`` attribute of their
    own - membership is managed through the distribution-list API
    (``PATCH /addressbooks/<key>/lists/<list_key>``) - so direct
    ``add_member`` / ``remove_member`` on a SQL book are rejected with
    ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED.
    """

    def __init__(self, module: Any, user: Any) -> None:
        """Wrap a contact module (needs ``get_all_addressbooks`` / ``get_contacts``) and a user."""
        self._module = module
        self._user = user

    def books(
        self,
        user_sources: dict[str, UserSourceSettingsObj] | None = None,
        collection_param: Any | None = None,
    ) -> list[dict]:
        """Return the user's SQL address books as normalized list entries.

        Member counts are derived from a single transverse contact scan (one
        query) instead of one count query per book.

        Pagination is applied to the SQL address books before merging with LDAP groups.
        When ``collection_param`` is provided, the SQL books are sorted and paginated
        according to the parameters. When omitted, all books are returned.

        :param user_sources: Domain user sources (passed through to the contact module).
        :param collection_param: Optional pagination arguments (page, page_size, sort_by, sort_order).
        :return: Normalized list entries for SQL address books.
        """
        from app.module.contact.model.CardAddressBook import CardAddressBook

        counts: Counter = self._contact_counts(user_sources)
        entries: list[dict[str, Any]] = []
        
        # Get all address books
        all_books = self._module.get_all_addressbooks(self._user, user_sources)
        
        # Convert to list for sorting/pagination
        books_list = list(all_books)
        
        # Apply sorting if requested
        if collection_param and collection_param.sort_by:
            books_list = sorted(
                books_list,
                key=lambda b: getattr(b, collection_param.sort_by, "") or "",
                reverse=(collection_param.sort_order == "desc")
            )
        
        # Apply pagination if requested
        if collection_param:
            offset = (collection_param.page - 1) * collection_param.page_size
            limit = collection_param.page_size
            books_list = books_list[offset:offset + limit]
        
        for book in books_list:
            key: str | None = book.key
            entries.append({
                "source": _SOURCE_SQL,
                "id": key or "",
                "name": book.name,
                "description": book.description,
                "member_count": counts.get(key, 0) if key else 0,
                "members": [],
            })
        return entries

    def _contact_counts(self, user_sources: dict[str, UserSourceSettingsObj] | None) -> Counter:
        """Count non-deleted contacts per address book key in one transverse scan."""
        contacts, _total = self._module.get_contacts(
            self._user, None, limit=0,
            resolve_ab=False, resolve_images=False, user_sources=user_sources,
        )
        return Counter(contact.addressbook_key for contact in contacts if contact.addressbook_key)

    def get_members(self, list_id: str, user_sources: dict[str, UserSourceSettingsObj] | None = None) -> list[str]:
        """Return the contact UIDs of a SQL address book (its *members*)."""
        contacts, _total = self._module.get_contacts(
            self._user, list_id, limit=0,
            resolve_ab=False, resolve_images=False, user_sources=user_sources,
        )
        return [contact.uid for contact in contacts if contact.uid]

    def add_member(self, list_id: str, contact_id: str, user_sources: dict[str, UserSourceSettingsObj] | None = None) -> str:
        """SQL address books have no mutable member attribute; reject with a typed error.

        Distribution-list membership on SQL books is managed through the
        ``/addressbooks/<key>/lists/<list_key>`` API, not through a member
        attribute operation on the provider.
        """
        raise RequestException(
            f"SQL address book {list_id} does not support direct member addition",
            error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED,
        )

    def remove_member(self, list_id: str, contact_id: str, user_sources: dict[str, UserSourceSettingsObj] | None = None) -> str:
        """SQL address books have no mutable member attribute; reject with a typed error."""
        raise RequestException(
            f"SQL address book {list_id} does not support direct member removal",
            error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED,
        )


class LDAPListService:
    """Hybrid SQL+LDAP facade over every addressable contact list.

    :param process_settings: Process settings (kept for API compatibility).
    :param user_domain_settings: Domain settings dict (kept for compatibility).
    :param client: An optional already-connected LDAP client (duck-typed: needs
        ``ldap_conn`` and ``search_entries``); when omitted the LDAP side is
        unavailable and list_lists degrades to the SQL side only.
    :param groups_base: Base DN under which groups live (defaults to
        ``"ou=groups,{base_dn}"``).
    :param users_base: Base DN under which member users live (defaults to the
        client base_dn).
    :param sql_provider: Duck-typed SQL-side provider (see module docstring).
    :param redis_client: Optional Redis client for caching (duck-typed: needs
        ``get``, ``setex``, ``delete``). When omitted caching is disabled.
    """

    def __init__(
        self,
        process_settings: Any | None = None,
        user_domain_settings: dict | None = None,
        client: Any | None = None,
        redis_client: Any | None = None,
        groups_base: str | None = None,
        users_base: str | None = None,
        sql_provider: Any | None = None,
    ) -> None:
        self._groups: LDAPGroupService = LDAPGroupService(
            process_settings,
            user_domain_settings=user_domain_settings or {},
            client=client,
            redis_client=redis_client,
            groups_base=groups_base,
            users_base=users_base,
        )
        self._sql_provider: Any = sql_provider

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_user_source(
        cls,
        user_source: UserSourceSettingsObj,
        sql_provider: Any | None = None,
    ) -> LDAPListService:
        """Build a service bound to one LDAP domain user source.

        Delegates connection binding to :class:`LDAPGroupService.from_user_source`
        and reuses its bound client and bases.
        """
        groups = LDAPGroupService.from_user_source(user_source)
        return cls(
            process_settings=None,
            user_domain_settings=None,
            client=groups.client,
            groups_base=groups.groups_base,
            users_base=groups.users_base,
            sql_provider=sql_provider,
        )

    @classmethod
    def from_user_sources(
        cls,
        user_sources: dict[str, UserSourceSettingsObj] | None,
        sql_provider: Any | None = None,
    ) -> LDAPListService:
        """Build a service from the first LDAP source in ``user_sources``."""
        if not user_sources:
            raise RequestException("No LDAP user source configured", error=err.ERROR_LDAP_CANNOT_CONNECT)
        for user_source in user_sources.values():
            if user_source.US_TYPE == "ldap":
                return cls.from_user_source(user_source, sql_provider=sql_provider)
        raise RequestException("No LDAP user source configured", error=err.ERROR_LDAP_CANNOT_CONNECT)

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_lists(
        self,
        user_sources: dict[str, UserSourceSettingsObj] | None = None,
        collection_param: Any | None = None,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Return all addressable contact lists: SQL address books + LDAP groups.

        SQL entries come first (stable order from the provider), followed by LDAP
        groups. When no live LDAP client is configured the method degrades to the
        SQL side only instead of failing the whole listing.

        Pagination is applied after merging both backends. The total count includes
        all lists (SQL + LDAP), while the returned slice respects page/limit.

        :param user_sources: Domain user sources (passed through to the SQL provider).
        :param collection_param: Optional pagination arguments (page, page_size, sort_by, sort_order).
        :return: Tuple of (total_count, normalized list entries).
        """
        entries: list[dict[str, Any]] = []
        if self._sql_provider is not None:
            entries.extend(self._sql_provider.books(user_sources=user_sources, collection_param=collection_param))
        if self._groups.has_client:
            entries.extend(self._ldap_groups())

        # Apply pagination if requested (for combined SQL+LDAP results)
        if collection_param:
            total = len(entries)
            offset = (collection_param.page - 1) * collection_param.page_size
            limit = collection_param.page_size
            # Apply sorting if specified (overrides SQL-side sorting)
            if collection_param.sort_by:
                entries = sorted(
                    entries,
                    key=lambda x: x.get(collection_param.sort_by, "") or "",
                    reverse=(collection_param.sort_order == "desc")
                )
            paginated = entries[offset:offset + limit]
            return total, paginated

        return len(entries), entries

    def _ldap_groups(self) -> list[dict[str, Any]]:
        """Search the groups base and normalize each groupOfNames entry."""
        try:
            raw_entries = self._groups.list_groups()
        except RequestException:
            raise
        except Exception as e:  # pragma: no cover - defensive
            logger_ldap.error("Failed to list LDAP groups: %s", e)
            raise RequestException(f"Failed to list LDAP groups: {e}", error=err.ERROR_LDAP_CANNOT_SEARCH) from e

        groups: list[dict[str, Any]] = []
        for entry in raw_entries:
            cn_values: list[str] = entry.get("cn") or []
            if not cn_values:
                continue
            cn: str = cn_values[0]
            members: list[str] = list(entry.get("member") or [])
            description: str | None = (entry.get("description") or [None])[0]
            groups.append({
                "source": _SOURCE_LDAP,
                "id": f"ldap:{cn}",
                "name": cn,
                "description": description,
                "member_count": len(members),
                "members": members,
            })
        return groups

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def is_ldap(self, list_id: str) -> bool:
        """True when the id refers to an LDAP group (not a SQL address book)."""
        return is_ldap_group(list_id)

    def get_members(
        self, list_id: str, user_sources: dict[str, UserSourceSettingsObj] | None = None,
    ) -> list[str]:
        """Return the members of a list, routed by id type.

        LDAP groups return their member DNs; SQL address books return their
        contact UIDs via the SQL provider.
        """
        if self.is_ldap(list_id):
            return self._groups.get_members(list_id)
        return list(self._sql_call("get_members", list_id, user_sources))

    def add_member(
        self, list_id: str, contact_id: str,
        user_sources: dict[str, UserSourceSettingsObj] | None = None,
    ) -> str:
        """Add a member to a list, routed by id type.

        LDAP groups get a ``member`` MOD_ADD; SQL address books delegate to the
        SQL provider (which rejects direct member addition with a typed error).
        """
        if self.is_ldap(list_id):
            return self._groups.add_member(list_id, contact_id)
        return str(self._sql_call("add_member", list_id, user_sources, contact_id))

    def remove_member(
        self, list_id: str, contact_id: str,
        user_sources: dict[str, UserSourceSettingsObj] | None = None,
    ) -> str:
        """Remove a member from a list, routed by id type.

        LDAP groups get a ``member`` MOD_DELETE; SQL address books delegate to
        the SQL provider.
        """
        if self.is_ldap(list_id):
            return self._groups.remove_member(list_id, contact_id)
        return str(self._sql_call("remove_member", list_id, user_sources, contact_id))

    def _sql_call(self, method_name: str, list_id: str, user_sources, *args) -> Any:
        """Dispatch a member operation to the SQL provider, failing cleanly when absent.

        :raises RequestException: ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND when no SQL
            provider is configured (a SQL id cannot be served).
        """
        if self._sql_provider is None:
            raise RequestException(
                f"List {list_id} is not an LDAP group and no SQL provider is configured",
                error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND,
            )
        method = getattr(self._sql_provider, method_name)
        return method(list_id, *args, user_sources=user_sources)
