from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.config.settings.DomainSettings import (
    CalendarContactSettings,
    CalendarContactSettingsObj,
    UserModuleSettings,
    UserModuleSettingsObj,
    UserSourceSettings,
    UserSourceSettingsObj,
)
from app.module.contact.ContactConst import AUTOCOMPLETE_DEFAULT_LIMIT
from app.module.contact.LdapGroupService import LDAPGroupService
from app.module.contact.ModuleContact import ModuleContact
from app.module.contact.jobs.ContactJobKind import ContactJobKind
from app.module.contact.model.CardAddressBook import CardAddressBook
from app.module.contact.model.enums.CardSourceType import CardSourceType
from app.module.contact.model.ContactShare import ContactShare
from app.module.contact.model.enums.ContactExportFormat import ContactExportFormat
from app.module.contact.model.enums.ContactShareLevel import ContactShareLevel
from app.module.contact.serializer.CardAddressBookSerializerDict import CardAddressBookSerializerDict
from app.module.contact.serializer.CardAddressBooksSerializerList import CardAddressBooksSerializerList
from app.module.contact.serializer.CardContactAutocompleteSerializerList import CardContactAutocompleteSerializerList
from app.module.contact.serializer.CardListAutocompleteSerializerList import CardListAutocompleteSerializerList
from app.module.contact.serializer.CardContactDeserializerDict import CardContactDeserializerDict
from app.module.contact.serializer.CardListDeserializerDict import CardListDeserializerDict
from app.module.contact.serializer.CardListSerializerDict import CardListSerializerDict
from app.module.contact.serializer.CardListsSerializerList import CardListsSerializerList
from app.module.contact.serializer.CardContactSerializerDict import CardContactSerializerDict
from app.module.contact.serializer.CardContactsSerializerList import CardContactsSerializerList
from app.service import sogo_agent, sogo_cache
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.db.Condition import Order
from app.utils.errors import (
    ERROR_CONTACT_EXPORT_FORMAT_UNSUPPORTED,
    ERROR_CONTACT_JSON_PARSE_FAILED,
)
from app.utils.exceptions import RequestException
from app.auth.User import User
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.config.settings.ProcessSetting import ProcessSetting
    from app.module.contact.model.CardContact import CardContact
    from app.module.contact.model.CardList import CardList
    from app.module.contact.source.ContactSource import ContactSource

    from app.utils.api.paginate_sort_filter import CollectionPaginateArgs, CustomPaginateResponse


class InterfaceApiContactContact:  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """Interface for all contact operations (address books and contacts)."""

    def __init__(self, process_setting: ProcessSetting, user_domain_settings: dict, user: User) -> None:
        self.user: User = user
        self._process_setting: ProcessSetting = process_setting
        self._user_domain_settings: dict = user_domain_settings
        self.settings: CalendarContactSettingsObj = CalendarContactSettingsObj(
            user_domain_settings[CalendarContactSettings.subparent]
        )
        self._user_module_settings: UserModuleSettingsObj = UserModuleSettingsObj(
            user_domain_settings[UserModuleSettings.subparent]
        )
        # Build the user_sources dict from the domain's USER_SOURCE configuration.
        self._user_sources: dict[str, UserSourceSettingsObj] | None = None
        raw_sources: dict | None = user_domain_settings.get(UserSourceSettings.subparent)
        if raw_sources:
            self._user_sources = {
                src_uid: UserSourceSettingsObj(src_cfg)
                for src_uid, src_cfg in raw_sources.items()
            }
        self.module: ModuleContact = ModuleContact(process_setting, cache=sogo_cache(), agent=sogo_agent())
        self._addressbook_serializer: CardAddressBookSerializerDict = CardAddressBookSerializerDict()
        self._addressbooks_serializer: CardAddressBooksSerializerList = CardAddressBooksSerializerList()
        self._contact_serializer: CardContactSerializerDict = CardContactSerializerDict()
        self._contacts_serializer: CardContactsSerializerList = CardContactsSerializerList()
        self._contact_deserializer: CardContactDeserializerDict = CardContactDeserializerDict()
        self._autocomplete_serializer: CardContactAutocompleteSerializerList = CardContactAutocompleteSerializerList()
        self._list_autocomplete_serializer: CardListAutocompleteSerializerList = CardListAutocompleteSerializerList()
        self._list_serializer: CardListSerializerDict = CardListSerializerDict()
        self._lists_serializer: CardListsSerializerList = CardListsSerializerList()
        self._list_deserializer: CardListDeserializerDict = CardListDeserializerDict()

    #
    # Address books
    #
    def get_all_addressbooks(self) -> tuple[dict[str, Any], int]:
        """List the address books owned by the current user (includes directory books when user_sources set)."""
        try:
            books: list[CardAddressBook] = self.module.get_all_addressbooks(self.user, self._user_sources)
            serialized: list[dict[str, Any]] = self._addressbooks_serializer.serialize(books)
            return create_api_base_response({"addressbooks": serialized, "total_count": len(books)})
        except RequestException as ex:
            logger_api.error("get_all_addressbooks failed for user %s: %s", self.user.uid, ex)
            return create_api_base_response(None, ex.error)

    def get_addressbook(self, key: str) -> tuple[dict[str, Any], int]:
        """Get a single address book by its key."""
        try:
            source: ContactSource = self.module.get_addressbook(self.user, key, self._user_sources)
            return create_api_base_response(self._addressbook_serializer.serialize(source.addressbook))
        except RequestException as ex:
            logger_api.error("get_addressbook failed for user %s key %s: %s", self.user.uid, key, ex)
            return create_api_base_response(None, ex.error)

    def create_addressbook(self, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Create a new local address book."""
        try:
            book: CardAddressBook = CardAddressBook(
                user_uid=self.user.uid,
                name=body["name"],
                description=body.get("description"),
                source_type=CardSourceType.LOCAL,
            )
            created: CardAddressBook = self.module.create_addressbook(self.user, book)
            return create_api_base_response(self._addressbook_serializer.serialize(created), code=201)
        except RequestException as ex:
            logger_api.error("create_addressbook failed for user %s: %s", self.user.uid, ex)
            return create_api_base_response(None, ex.error)

    def update_addressbook(self, key: str, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Apply partial updates to an address book (mutable fields only)."""
        try:
            updated: CardAddressBook = self.module.update_addressbook(self.user, key, body)
            return create_api_base_response(self._addressbook_serializer.serialize(updated))
        except RequestException as ex:
            logger_api.error("update_addressbook failed for user %s key %s: %s", self.user.uid, key, ex)
            return create_api_base_response(None, ex.error)

    def delete_addressbook(self, key: str) -> tuple[dict[str, Any], int]:
        """Delete an address book and all its contacts."""
        try:
            self.module.delete_addressbook(self.user, key)
            return create_api_base_response(None)
        except RequestException as ex:
            logger_api.error("delete_addressbook failed for user %s key %s: %s", self.user.uid, key, ex)
            return create_api_base_response(None, ex.error)

    #
    # Sharing
    #
    def list_shares(self, key: str) -> tuple[dict[str, Any], int]:
        """List all shares for an address book."""
        try:
            shares: list[ContactShare] = self.module.list_shares(key)
            serialized: list[dict[str, Any]] = [
                {"user_uid": s.user_uid, "share_level": s.share_level.name.lower()}
                for s in shares
            ]
            return create_api_base_response({"shares": serialized, "total_count": len(shares)})
        except RequestException as ex:
            logger_api.error("list_shares failed for address book %s: %s", key, ex)
            return create_api_base_response(None, ex.error)

    @staticmethod
    def _parse_share_level(value: str | None, default: str = "view") -> ContactShareLevel:
        """Parse a share level from a JSON string, case-insensitive."""
        raw = (value or default).upper().replace("_", "")
        for member in ContactShareLevel:
            if member.name.replace("_", "") == raw:
                return member
        return ContactShareLevel[default.upper()]

    def add_share(self, key: str, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Add a share for a user on an address book."""
        try:
            share: ContactShare = ContactShare(
                addressbook_key=key,
                user_uid=body["user_uid"],
                share_level=self._parse_share_level(body.get("share_level"), "view"),
            )
            created: ContactShare = self.module.add_share(key, share)
            # 201 Created — matches the route's declared @blp.response(201, ...)
            return create_api_base_response(
                {"user_uid": created.user_uid, "share_level": created.share_level.name.lower()},
                status_code=201,
            )
        except RequestException as ex:
            logger_api.error("add_share failed for address book %s user %s: %s", key, body.get("user_uid"), ex)
            return create_api_base_response(None, ex.error)

    def remove_share(self, key: str, user_uid: str) -> tuple[dict[str, Any], int]:
        """Remove a share for a user on an address book."""
        try:
            self.module.remove_share(key, user_uid)
            return create_api_base_response(None)
        except RequestException as ex:
            logger_api.error("remove_share failed for address book %s user %s: %s", key, user_uid, ex)
            return create_api_base_response(None, ex.error)

    #
    # Contacts
    #
    def get_contacts(
        self, key: str | None, collection_param: CollectionPaginateArgs, search: str | None = None,
    ) -> CustomPaginateResponse:
        """List contacts, optionally scoped to one address book, with search, sort and pagination.

        Pagination, sort field and sort direction come from collection_param; the total count is
        surfaced through the X-Pagination header (built by the pagination decorator) rather than the
        response body. ``search`` is a separate full-text query argument.

        :param key: Address book key, or None to span all the user's books.
        :param collection_param: Parsed pagination and sort arguments from the request.
        :param search: Optional full-text query.
        :return: A tuple (total_count, API response dict, status code).
        """
        try:
            order: Order = Order.DESC if collection_param.sort_order == "desc" else Order.ASC
            contacts, total = self.module.get_contacts(
                self.user,
                addressbook_key=key,
                search=search,
                offset=collection_param.first_item,
                limit=collection_param.page_size,
                sort_by=collection_param.sort_by,
                order=order,
                user_sources=self._user_sources,
            )
            serialized: list[dict[str, Any]] = self._contacts_serializer.serialize(contacts)
            return total, *create_api_base_response({"contacts": serialized})
        except RequestException as ex:
            logger_api.error("get_contacts failed for user %s book %s: %s", self.user.uid, key, ex)
            return 0, *create_api_base_response(None, ex.error)

    def autocomplete(self, query: str) -> tuple[dict[str, Any], int]:
        """Return lightweight recipient suggestions (contacts one per email, plus distribution lists).

        Below the domain's autocompletion minimum length the result is an empty list rather than an
        error (standard autocomplete behaviour). The search spans all the user's address books (and
        the directory via ContactSourceDirectory); contacts and lists are each capped at
        AUTOCOMPLETE_DEFAULT_LIMIT. A list surfaces as a suggestion carrying its member_count instead
        of an email address.

        :param query: Partial name or email typed by the user.
        :return: API envelope with a ``suggestions`` list, plus HTTP status code.
        """
        try:
            if len(query.strip()) < self._user_module_settings.SOGO_D_AUTOCOMPLETION_MIN_LEN:
                return create_api_base_response({"suggestions": []})
            contacts, _ = self.module.get_contacts(
                self.user, search=query, limit=AUTOCOMPLETE_DEFAULT_LIMIT, resolve_images=False,
                user_sources=self._user_sources,
            )
            lists = self.module.search_all_lists(self.user, search=query, limit=AUTOCOMPLETE_DEFAULT_LIMIT,
                                                  user_sources=self._user_sources)
            suggestions: list[dict[str, Any]] = (
                self._autocomplete_serializer.serialize(contacts)
                + self._list_autocomplete_serializer.serialize(lists)
            )
            return create_api_base_response({"suggestions": suggestions})
        except RequestException as ex:
            logger_api.error("autocomplete failed for user %s: %s", self.user.uid, ex)
            return create_api_base_response(None, ex.error)

    def get_contact(self, addressbook_key: str, key: str) -> tuple[dict[str, Any], int]:
        """Get a single contact by key within an address book."""
        try:
            contact: CardContact = self.module.get_contact(self.user, addressbook_key, key,
                                                           user_sources=self._user_sources)
            return create_api_base_response(self._contact_serializer.serialize(contact))
        except RequestException as ex:
            logger_api.error("get_contact failed for user %s contact %s: %s", self.user.uid, key, ex)
            return create_api_base_response(None, ex.error)

    def create_contact(self, addressbook_key: str, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Create a new contact in the given address book."""
        try:
            contact: CardContact = self._contact_deserializer.deserialize(body)
            created: CardContact = self.module.create_contact(self.user, addressbook_key, contact,
                                                              user_sources=self._user_sources)
            return create_api_base_response(self._contact_serializer.serialize(created), code=201)
        except RequestException as ex:
            logger_api.error("create_contact failed for user %s book %s: %s", self.user.uid, addressbook_key, ex)
            return create_api_base_response(None, ex.error)
        except (ValueError, KeyError) as exc:
            logger_api.error("Failed to parse contact body for user %s book %s: %s", self.user.uid, addressbook_key, exc)
            return create_api_base_response(None, ERROR_CONTACT_JSON_PARSE_FAILED)

    def patch_contact(self, addressbook_key: str, key: str, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Apply partial updates to a contact within an address book."""
        try:
            existing: CardContact = self.module.get_contact(self.user, addressbook_key, key,
                                                            user_sources=self._user_sources)
            contact_update: CardContact = self._contact_deserializer.deserialize_with_update(existing, body)
            updated: CardContact = self.module.update_contact(self.user, addressbook_key, key, contact_update,
                                                              user_sources=self._user_sources)
            return create_api_base_response(self._contact_serializer.serialize(updated))
        except RequestException as ex:
            logger_api.error("patch_contact failed for user %s contact %s: %s", self.user.uid, key, ex)
            return create_api_base_response(None, ex.error)
        except (ValueError, KeyError) as exc:
            logger_api.error("Failed to parse patch body for user %s contact %s: %s", self.user.uid, key, exc)
            return create_api_base_response(None, ERROR_CONTACT_JSON_PARSE_FAILED)

    def delete_contact(self, addressbook_key: str, key: str) -> tuple[dict[str, Any], int]:
        """Delete a contact within an address book."""
        try:
            self.module.delete_contact(self.user, addressbook_key, key, user_sources=self._user_sources)
            return create_api_base_response(None)
        except RequestException as ex:
            logger_api.error("delete_contact failed for user %s contact %s: %s", self.user.uid, key, ex)
            return create_api_base_response(None, ex.error)

    #
    # Distribution lists
    #
    def get_lists(
        self, addressbook_key: str, collection_param: CollectionPaginateArgs, search: str | None = None,
    ) -> CustomPaginateResponse:
        """List the distribution lists of an address book, with search, sort and pagination.

        Lists are book-scoped (unlike the transverse contact listing). Pagination and sort come from
        collection_param; the total count is surfaced through the X-Pagination header.

        :param addressbook_key: Address book key holding the lists.
        :param collection_param: Parsed pagination and sort arguments from the request.
        :param search: Optional name filter.
        :return: A tuple (total_count, API response dict, status code).
        """
        try:
            order: Order = Order.DESC if collection_param.sort_order == "desc" else Order.ASC
            lists, total = self.module.get_all_lists(
                self.user,
                addressbook_key,
                search=search,
                offset=collection_param.first_item,
                limit=collection_param.page_size,
                sort_by=collection_param.sort_by,
                order=order,
                user_sources=self._user_sources,
            )
            serialized: list[dict[str, Any]] = self._lists_serializer.serialize(lists)
            return total, *create_api_base_response({"lists": serialized})
        except RequestException as ex:
            logger_api.error("get_lists failed for user %s book %s: %s", self.user.uid, addressbook_key, ex)
            return 0, *create_api_base_response(None, ex.error)

    def get_list(self, addressbook_key: str, key: str) -> tuple[dict[str, Any], int]:
        """Get a single distribution list by key within an address book."""
        try:
            card_list: CardList = self.module.get_list(self.user, addressbook_key, key,
                                                       user_sources=self._user_sources)
            return create_api_base_response(self._list_serializer.serialize(card_list))
        except RequestException as ex:
            logger_api.error("get_list failed for user %s list %s: %s", self.user.uid, key, ex)
            return create_api_base_response(None, ex.error)

    def create_list(self, addressbook_key: str, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Create a new distribution list in the given address book."""
        try:
            card_list: CardList = self._list_deserializer.deserialize(body)
            created: CardList = self.module.create_list(self.user, addressbook_key, card_list,
                                                        user_sources=self._user_sources)
            return create_api_base_response(self._list_serializer.serialize(created), code=201)
        except RequestException as ex:
            logger_api.error("create_list failed for user %s book %s: %s", self.user.uid, addressbook_key, ex)
            return create_api_base_response(None, ex.error)
        except (ValueError, KeyError) as exc:
            logger_api.error("Failed to parse list body for user %s book %s: %s", self.user.uid, addressbook_key, exc)
            return create_api_base_response(None, ERROR_CONTACT_JSON_PARSE_FAILED)

    def patch_list(self, addressbook_key: str, key: str, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Apply partial updates to a distribution list within an address book."""
        try:
            existing: CardList = self.module.get_list(self.user, addressbook_key, key,
                                                      user_sources=self._user_sources)
            list_update: CardList = self._list_deserializer.deserialize_with_update(existing, body)
            updated: CardList = self.module.update_list(self.user, addressbook_key, key, list_update,
                                                        user_sources=self._user_sources)
            return create_api_base_response(self._list_serializer.serialize(updated))
        except RequestException as ex:
            logger_api.error("patch_list failed for user %s list %s: %s", self.user.uid, key, ex)
            return create_api_base_response(None, ex.error)
        except (ValueError, KeyError) as exc:
            logger_api.error("Failed to parse patch body for user %s list %s: %s", self.user.uid, key, exc)
            return create_api_base_response(None, ERROR_CONTACT_JSON_PARSE_FAILED)

    def delete_list(self, addressbook_key: str, key: str) -> tuple[dict[str, Any], int]:
        """Delete a distribution list within an address book."""
        try:
            self.module.delete_list(self.user, addressbook_key, key, user_sources=self._user_sources)
            return create_api_base_response(None)
        except RequestException as ex:
            logger_api.error("delete_list failed for user %s list %s: %s", self.user.uid, key, ex)
            return create_api_base_response(None, ex.error)

    #
    # LDAP distribution groups (get/add/remove members on groupOfNames lists)
    #
    def _ldap_list_service(self) -> LDAPGroupService:
        """Build (and cache) the LDAPGroupService bound to this request's process settings.

        The service connects lazily to LDAP on the first member operation; connection
        failures surface as ``RequestException`` which the callers below translate into
        an API error envelope.
        """
        if not hasattr(self, "_ldap_list_service_cache"):
            self._ldap_list_service_cache = LDAPGroupService(
                self._process_setting, user_domain_settings=self._user_sources)
        return self._ldap_list_service_cache

    def get_list_members(self, addressbook_key: str) -> tuple[dict[str, Any], int]:
        """Get all members of an LDAP group list.

        LDAP groups are address books backed by the directory (groupOfNames
        entries). The addressbook_key may be an ``ldap:``-prefixed id, a DN, or
        a plain CN; numeric ids refer to SQL address books and are rejected.

        :param addressbook_key: The list id (ldap: prefix, DN, or CN).
        :return: API envelope with the member DNs, plus HTTP status code.
        """
        try:
            service = self._ldap_list_service()
            members: list[str] = service.get_members(addressbook_key)
            return create_api_base_response({"members": members, "total_count": len(members)}, error_code="")
        except RequestException as ex:
            logger_api.error(
                "get_list_members failed for user %s key %s: %s", self.user.uid, addressbook_key, ex)
            return create_api_base_response(None, ex.error)

    def add_list_member(self, addressbook_key: str, contact_id: str) -> tuple[dict[str, Any], int]:
        """Add a contact (by uid) to an LDAP group list.

        :param addressbook_key: The group id (ldap: prefix, DN, or CN).
        :param contact_id: The contact identifier (uid or email local part).
        :return: API envelope with the added member DN, plus HTTP status code (201).
        """
        try:
            service = self._ldap_list_service()
            member_dn: str = service.add_member(addressbook_key, contact_id)
            return create_api_base_response({"member_dn": member_dn}, code=201, error_code="")
        except RequestException as ex:
            logger_api.error(
                "add_list_member failed for user %s key %s contact %s: %s",
                self.user.uid, addressbook_key, contact_id, ex)
            return create_api_base_response(None, ex.error)

    def remove_list_member(self, addressbook_key: str, contact_id: str) -> tuple[dict[str, Any], int]:
        """Remove a contact (by uid) from an LDAP group list.

        :param addressbook_key: The group id (ldap: prefix, DN, or CN).
        :param contact_id: The contact identifier (uid or email local part).
        :return: API envelope with the removed member DN, plus HTTP status code.
        """
        try:
            service = self._ldap_list_service()
            member_dn: str = service.remove_member(addressbook_key, contact_id)
            return create_api_base_response({"member_dn": member_dn}, error_code="")
        except RequestException as ex:
            logger_api.error(
                "remove_list_member failed for user %s key %s contact %s: %s",
                self.user.uid, addressbook_key, contact_id, ex)
            return create_api_base_response(None, ex.error)

    #
    # Import / export (async: enqueue an Agent job, return 202 {job_id})
    #
    def import_addressbook(self, document: str, fmt: str) -> tuple[dict[str, Any], int]:
        """Enqueue an import of a document as a NEW address book and return its ``job_id`` (202).

        The caller polls ``GET /jobs/<job_id>`` until SUCCESS; the import counters plus the created
        book key/name are then in the job result.

        :param document: The decoded upload content.
        :param fmt: Source format ('json' / 'vcard3' / 'vcard4' / 'ldif'), validated by the route schema.
        """
        return self._enqueue_import(ContactJobKind.ADDRESSBOOK, None, document, fmt)

    def import_contact(self, key: str, document: str, fmt: str) -> tuple[dict[str, Any], int]:
        """Enqueue an import of contacts into an existing book and return its ``job_id`` (202)."""
        return self._enqueue_import(ContactJobKind.CONTACT, key, document, fmt)

    def import_list(self, key: str, document: str, fmt: str) -> tuple[dict[str, Any], int]:
        """Enqueue an import of distribution lists into an existing book and return its ``job_id`` (202)."""
        return self._enqueue_import(ContactJobKind.LIST, key, document, fmt)

    def _enqueue_import(
        self, kind: ContactJobKind, addressbook_key: str | None, document: str, fmt: str,
    ) -> tuple[dict[str, Any], int]:
        """Offload the document and enqueue an import job; shared by the three import endpoints."""
        try:
            job_id: str = self.module.enqueue_import(
                self.user, kind, addressbook_key, document, fmt,
            )
            return create_api_base_response({"job_id": job_id}, code=202)
        except RequestException as ex:
            logger_api.error("enqueue_import (%s) failed for user %s: %s", kind, self.user.uid, ex)
            return create_api_base_response(None, ex.error)

    #
    # Export (async)
    #
    def export_addressbook(self, key: str, accept: str) -> tuple[dict[str, Any], int]:
        """Enqueue an export of a whole address book and return its ``job_id`` (202).

        The serialization is negotiated from the Accept header at enqueue time (the worker has no
        HTTP context); the caller fetches the document from ``GET /jobs/<job_id>/result``.
        """
        return self._enqueue_export(ContactJobKind.ADDRESSBOOK, key, None, accept)

    def export_contact(self, addressbook_key: str, key: str, accept: str) -> tuple[dict[str, Any], int]:
        """Enqueue an export of a single contact and return its ``job_id`` (202)."""
        return self._enqueue_export(ContactJobKind.CONTACT, addressbook_key, key, accept)

    def export_list(self, addressbook_key: str, key: str, accept: str) -> tuple[dict[str, Any], int]:
        """Enqueue an export of a single distribution list and return its ``job_id`` (202)."""
        return self._enqueue_export(ContactJobKind.LIST, addressbook_key, key, accept)

    def _enqueue_export(
        self, kind: ContactJobKind, addressbook_key: str, item_key: str | None, accept: str,
    ) -> tuple[dict[str, Any], int]:
        """Resolve the export format from Accept and enqueue an export job; shared by the three endpoints."""
        try:
            export_format: ContactExportFormat | None = self._negotiate_export_format(accept)
            if export_format is None:
                return create_api_base_response(None, ERROR_CONTACT_EXPORT_FORMAT_UNSUPPORTED)
            job_id: str = self.module.enqueue_export(
                self.user, kind, addressbook_key, item_key, export_format.name,
            )
            return create_api_base_response({"job_id": job_id}, code=202)
        except RequestException as ex:
            logger_api.error("enqueue_export (%s) failed for user %s key %s: %s",
                             kind, self.user.uid, addressbook_key, ex)
            return create_api_base_response(None, ex.error)

    @staticmethod
    def _negotiate_export_format(accept: str) -> ContactExportFormat | None:
        """Resolve the export format from an Accept header value.

        Empty or wildcard accepts default to vCard 3.0 - the only dialect Apple / Google / Outlook all
        import reliably (vCard 4.0 imports blank in Apple Contacts). application/json selects JSON,
        text/ldif selects LDIF; a text/vcard accept yields 4.0 only when it carries version=4, else 3.0.
        Any other explicit type yields None so the caller answers 406.
        """
        value: str = accept.lower()
        if not value or "*/*" in value:
            return ContactExportFormat.VCARD3
        if "application/json" in value:
            return ContactExportFormat.JSON
        if "text/ldif" in value:
            return ContactExportFormat.LDIF
        if "text/vcard" in value or "text/x-vcard" in value:
            return ContactExportFormat.VCARD4 if "version=4" in value else ContactExportFormat.VCARD3
        return None

    #
    # External address books (CardDAV)
    #

    def create_external_addressbook(self, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Create a new external CardDAV address book subscription.

        :param body: Validated request body with ``name``, ``url``, optional ``sync_interval_minutes``.
        :return: API envelope with the created address book, plus HTTP status code.
        """
        try:
            created: CardAddressBook = self.module.create_external_addressbook(
                self.user,
                name=body["name"],
                url=body["url"],
                sync_interval_minutes=body.get("sync_interval_minutes", 60),
            )
            return create_api_base_response(self._addressbook_serializer.serialize(created), code=201)
        except RequestException as ex:
            logger_api.error("create_external_addressbook failed for user %s: %s", self.user.uid, ex)
            return create_api_base_response(None, ex.error)

    def enqueue_external_sync(self, key: str) -> tuple[dict[str, Any], int]:
        """Enqueue a manual CardDAV sync for an external address book and return its job_id (202).

        Currently runs synchronously; returns a placeholder job_id. Will dispatch through
        the agent infrastructure once the async worker is wired for CardDAV.
        """
        try:
            job_id: str = self.module.enqueue_external_sync(self.user, key)
            return create_api_base_response({"job_id": job_id, "status": "completed"}, code=200)
        except RequestException as ex:
            logger_api.error("enqueue_external_sync failed for user %s key %s: %s", self.user.uid, key, ex)
            return create_api_base_response(None, ex.error)


    #
    # LDAP group member operations
    #

