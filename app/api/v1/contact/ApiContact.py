from __future__ import annotations  # pylint: disable=duplicate-code

from typing import TYPE_CHECKING

from flask import g, request
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.interface.contact.InterfaceApiContactContact import InterfaceApiContactContact
from app.module.contact.ContactConst import IMPORT_MAX_BYTES
from app.module.contact.source.ContactSourceDb import LIST_SORTABLE_COLUMNS, SORTABLE_COLUMNS
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.api.paginate_sort_filter import collection_paginate, CustomPaginateResponse
from app.utils.errors import ERROR_CONTACT_IMPORT_NO_FILE, ERROR_CONTACT_IMPORT_TOO_LARGE
from app.utils.logger.logger import logger_api
from .schemas.addressbook import (
    AddressBookCreateSchema,
    AddressBookUpdateSchema,
    AddressBookListResponseSchema,
    AddressBookResponseSchema,
    ContactImportQueryArgsSchema,
    ContactImportUploadSchema,
    ContactJobResponseSchema,
    ExternalAddressBookCreateSchema,
    ContactShareCreateSchema,
    ContactShareListResponseSchema,
    ContactShareResponseSchema,
)
from .schemas.contact import (
    ContactCreateSchema,
    ContactPatchSchema,
    ContactListResponseSchema,
    ContactResponseSchema,
    ContactSearchQueryArgsSchema,
    ContactAutocompleteQueryArgsSchema,
    ContactAutocompleteResponseSchema,
)
from .schemas.hybrid import (
    ListEntriesResponseSchema,
    ListMemberCreateSchema,
    ListMemberResponseSchema,
    ListMembersResponseSchema,
)
from .schemas.list import (
    ListCreateSchema,
    ListPatchSchema,
    ListCollectionResponseSchema,
    ListResponseSchema,
    ListSearchQueryArgsSchema,
)

if TYPE_CHECKING:
    from werkzeug.datastructures import FileStorage
    from app.utils.api.paginate_sort_filter import CollectionPaginateArgs

# collection_paginate types sort_value_set as a mutable set; SORTABLE_COLUMNS stays the immutable
# source of truth in the source layer and is exposed here as a plain set for the decorator.
_SORT_VALUES: set[str] = set(SORTABLE_COLUMNS)
_LIST_SORT_VALUES: set[str] = set(LIST_SORTABLE_COLUMNS)

# OpenAPI for the export routes: the export runs asynchronously (202 + job_id), but the serialization
# is still content-negotiated from the Accept header at enqueue time - declared here so Swagger shows it.
# The serialized document is fetched from GET /jobs/<job_id>/result once the job succeeds.
_EXPORT_OPENAPI: dict = {
    "parameters": [{
        "in": "header", "name": "Accept", "required": False,
        "description": "Export serialization: 'text/vcard; version=3.0' (default, widest client support), "
                       "'text/vcard; version=4.0', 'text/ldif' or 'application/json'. An unsupported type returns 406.",
        "schema": {"type": "string", "enum": [
            "text/vcard; version=4.0", "text/vcard; version=3.0", "text/ldif", "application/json"]},
    }],
    "responses": {"406": {"description": "The requested export format is not supported (ERROR_CONTACT_EXPORT_FORMAT_UNSUPPORTED)."}},
}

blp = Blueprint("Contact", __name__, url_prefix="")


@blp.before_request
def init_contact_config() -> None:  # pylint: disable=missing-function-docstring
    g.inter = InterfaceApiContactContact(
        process_setting=g.process_settings,
        user_domain_settings=g.user_domain_settings,
        user=g.user,
    )


@blp.route("/addressbooks")
class ApiAddressBookList(MethodView):
    """API to list and create address books."""

    @blp.response(200, AddressBookListResponseSchema)
    def get(self) -> ResponseReturnValue:
        """List all address books for the current user."""
        logger_api.debug("GET /addressbooks user=%s", g.user.uid)
        interface: InterfaceApiContactContact = g.inter
        return interface.get_all_addressbooks()

    @blp.arguments(AddressBookCreateSchema)
    @blp.response(201, AddressBookResponseSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """Create a new address book."""
        logger_api.debug("POST /addressbooks user=%s body=%s", g.user.uid, body)
        interface: InterfaceApiContactContact = g.inter
        return interface.create_addressbook(body)


@blp.route("/addressbooks/<string:key>")
class ApiAddressBookDetail(MethodView):
    """API to retrieve, update and delete a single address book."""

    @blp.response(200, AddressBookResponseSchema)
    def get(self, key: str) -> ResponseReturnValue:
        """Get an address book by its key."""
        logger_api.debug("GET /addressbooks/%s user=%s", key, g.user.uid)
        interface: InterfaceApiContactContact = g.inter
        return interface.get_addressbook(key)

    @blp.arguments(AddressBookUpdateSchema)
    @blp.response(200, AddressBookResponseSchema)
    def patch(self, body: dict, key: str) -> ResponseReturnValue:
        """Update an address book."""
        logger_api.debug("PATCH /addressbooks/%s user=%s body=%s", key, g.user.uid, body)
        interface: InterfaceApiContactContact = g.inter
        return interface.update_addressbook(key, body)

    @blp.response(200, AddressBookResponseSchema)
    def delete(self, key: str) -> ResponseReturnValue:
        """Delete an address book and all its contacts."""
        logger_api.debug("DELETE /addressbooks/%s user=%s", key, g.user.uid)
        interface: InterfaceApiContactContact = g.inter
        return interface.delete_addressbook(key)


@blp.route("/addressbooks/<string:key>/shares")
class ApiAddressBookShareList(MethodView):
    """API to list and add shares on an address book."""

    @blp.response(200, ContactShareListResponseSchema)
    def get(self, key: str) -> ResponseReturnValue:
        """List all shares for an address book."""
        logger_api.debug("GET /addressbooks/%s/shares user=%s", key, g.user.uid)
        interface: InterfaceApiContactContact = g.inter
        return interface.list_shares(key)

    @blp.arguments(ContactShareCreateSchema)
    @blp.response(201, ContactShareResponseSchema)
    def post(self, body: dict, key: str) -> ResponseReturnValue:
        """Share an address book with a user."""
        logger_api.debug("POST /addressbooks/%s/shares user=%s body=%s", key, g.user.uid, body)
        interface: InterfaceApiContactContact = g.inter
        return interface.add_share(key, body)


@blp.route("/addressbooks/<string:key>/shares/<string:user_uid>")
class ApiAddressBookShareDetail(MethodView):
    """API to remove a share from an address book."""

    @blp.response(200, ContactShareResponseSchema)
    def delete(self, key: str, user_uid: str) -> ResponseReturnValue:
        """Remove a share from an address book."""
        logger_api.debug("DELETE /addressbooks/%s/shares/%s user=%s", key, user_uid, g.user.uid)
        interface: InterfaceApiContactContact = g.inter
        return interface.remove_share(key, user_uid)


@blp.route("/addressbooks/<string:key>/contacts")
class ApiAddressBookContactList(MethodView):
    """API to list (paginated) and create contacts within one address book."""

    @blp.response(200, ContactListResponseSchema)
    @blp.arguments(ContactSearchQueryArgsSchema, location="query", arg_name="query_args")
    @collection_paginate(blp, sort_value_set=_SORT_VALUES, can_filter=False)
    def get(self, query_args: dict, collection_param: CollectionPaginateArgs, key: str) -> CustomPaginateResponse:
        """List the contacts of an address book, with search, sort and pagination."""
        logger_api.debug("GET /addressbooks/%s/contacts user=%s params=%s", key, g.user.uid, collection_param)
        interface: InterfaceApiContactContact = g.inter
        return interface.get_contacts(key, collection_param, search=query_args.get("search"))

    @blp.arguments(ContactCreateSchema)
    @blp.response(201, ContactResponseSchema)
    def post(self, body: dict, key: str) -> ResponseReturnValue:
        """Create a new contact in the address book."""
        logger_api.debug("POST /addressbooks/%s/contacts user=%s", key, g.user.uid)
        interface: InterfaceApiContactContact = g.inter
        return interface.create_contact(key, body)


@blp.route("/contacts")
class ApiContactList(MethodView):
    """API to list (paginated) contacts across all the user's address books."""

    @blp.response(200, ContactListResponseSchema)
    @blp.arguments(ContactSearchQueryArgsSchema, location="query", arg_name="query_args")
    @collection_paginate(blp, sort_value_set=_SORT_VALUES, can_filter=False)
    def get(self, query_args: dict, collection_param: CollectionPaginateArgs) -> CustomPaginateResponse:
        """List contacts across every address book, with search, sort and pagination."""
        logger_api.debug("GET /contacts user=%s params=%s", g.user.uid, collection_param)
        interface: InterfaceApiContactContact = g.inter
        return interface.get_contacts(None, collection_param, search=query_args.get("search"))


@blp.route("/contacts/autocomplete")
class ApiContactAutocomplete(MethodView):
    """Recipient autocompletion: lightweight {name, email} suggestions across the user's contacts."""

    @blp.response(200, ContactAutocompleteResponseSchema)
    @blp.arguments(ContactAutocompleteQueryArgsSchema, location="query", arg_name="query_args")
    def get(self, query_args: dict) -> ResponseReturnValue:
        """Return recipient suggestions for the ``q`` query string."""
        logger_api.debug("GET /contacts/autocomplete user=%s q=%s", g.user.uid, query_args.get("q"))
        interface: InterfaceApiContactContact = g.inter
        return interface.autocomplete(query_args["q"])


@blp.route("/addressbooks/<string:key>/contacts/<string:contact_key>")
class ApiContactDetail(MethodView):
    """API to retrieve, update and delete a single contact within an address book."""

    @blp.response(200, ContactResponseSchema)
    def get(self, key: str, contact_key: str) -> ResponseReturnValue:
        """Get a contact by its key within the address book."""
        logger_api.debug("GET /addressbooks/%s/contacts/%s user=%s", key, contact_key, g.user.uid)
        interface: InterfaceApiContactContact = g.inter
        return interface.get_contact(key, contact_key)

    @blp.arguments(ContactPatchSchema)
    @blp.response(200, ContactResponseSchema)
    def patch(self, body: dict, key: str, contact_key: str) -> ResponseReturnValue:
        """Apply partial updates to a contact."""
        logger_api.debug("PATCH /addressbooks/%s/contacts/%s user=%s", key, contact_key, g.user.uid)
        interface: InterfaceApiContactContact = g.inter
        return interface.patch_contact(key, contact_key, body)

    @blp.response(200, ContactResponseSchema)
    def delete(self, key: str, contact_key: str) -> ResponseReturnValue:
        """Delete a contact."""
        logger_api.debug("DELETE /addressbooks/%s/contacts/%s user=%s", key, contact_key, g.user.uid)
        interface: InterfaceApiContactContact = g.inter
        return interface.delete_contact(key, contact_key)


@blp.route("/addressbooks/<string:key>/lists")
class ApiListCollection(MethodView):
    """API to list (paginated) and create distribution lists within one address book."""

    @blp.response(200, ListCollectionResponseSchema)
    @blp.arguments(ListSearchQueryArgsSchema, location="query", arg_name="query_args")
    @collection_paginate(blp, sort_value_set=_LIST_SORT_VALUES, can_filter=False)
    def get(self, query_args: dict, collection_param: CollectionPaginateArgs, key: str) -> CustomPaginateResponse:
        """List the distribution lists of an address book, with search, sort and pagination."""
        logger_api.debug("GET /addressbooks/%s/lists user=%s params=%s", key, g.user.uid, collection_param)
        interface: InterfaceApiContactContact = g.inter
        return interface.get_lists(key, collection_param, search=query_args.get("search"))

    @blp.arguments(ListCreateSchema)
    @blp.response(201, ListResponseSchema)
    def post(self, body: dict, key: str) -> ResponseReturnValue:
        """Create a new distribution list in the address book."""
        logger_api.debug("POST /addressbooks/%s/lists user=%s", key, g.user.uid)
        interface: InterfaceApiContactContact = g.inter
        return interface.create_list(key, body)


@blp.route("/addressbooks/lists")
class ApiContactLists(MethodView):
    """Hybrid backend: list every addressable contact list (SQL address books + LDAP groups)."""

    @blp.response(200, ListEntriesResponseSchema)
    @blp.arguments(ListSearchQueryArgsSchema, location="query", arg_name="query_args")
    @collection_paginate(blp, sort_value_set=_LIST_SORT_VALUES, can_filter=False)
    def get(self, query_args: dict, collection_param: CollectionPaginateArgs) -> CustomPaginateResponse:
        """List all contact lists across both backends (PostgreSQL address books and LDAP groupOfNames).

        Each entry is normalized with ``source`` ('sql'|'ldap'), ``id`` (book key or ``ldap:<cn>``),
        name, description, member_count and (for LDAP) members. The address books endpoint
        (``GET /addressbooks``) keeps returning the SQL books only; this route is the merged view.

        ``InterfaceApiContactContact.list_lists`` returns the 2-tuple ``(response, status)`` while
        ``@collection_paginate`` expects ``(item_count, response, status)``; the merged total is
        already inside the payload (``total_count``) so we adapt it here.
        """
        logger_api.debug("GET /addressbooks/lists user=%s params=%s", g.user.uid, collection_param)
        interface: InterfaceApiContactContact = g.inter
        data, status = interface.list_lists(collection_param)
        total: int = 0
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            total = int(data["data"].get("total_count") or 0)
        return total, data, status

@blp.route("/addressbooks/<string:key>/members")
class ApiAddressBookMemberList(MethodView):
    """Hybrid backend: list and add members of a contact list (routed by id type)."""

    @blp.response(200, ListMembersResponseSchema)
    def get(self, key: str) -> ResponseReturnValue:
        """List the members of a contact list, routed by id type.

        LDAP groups (``ldap:<cn>`` / DN) return their member DNs; SQL address books (numeric keys)
        return their contact uids. A missing group/address book yields 404.
        """
        logger_api.debug("GET /addressbooks/%s/members user=%s", key, g.user.uid)
        interface: InterfaceApiContactContact = g.inter
        return interface.get_list_members(key)

    @blp.arguments(ListMemberCreateSchema)
    @blp.response(201, ListMemberResponseSchema)
    def post(self, body: dict, key: str) -> ResponseReturnValue:
        """Add a contact (by id) to a contact list, routed by id type.

        LDAP groups receive a ``member`` MOD_ADD (idempotent); SQL address books reject direct
        member additions with ``S000707`` (use the distribution-list API instead).
        """
        logger_api.debug("POST /addressbooks/%s/members user=%s contact=%s",
                         key, g.user.uid, body.get("contact_id"))
        interface: InterfaceApiContactContact = g.inter
        return interface.add_list_member(key, body["contact_id"])


@blp.route("/addressbooks/<string:key>/members/<string:contact_id>")
class ApiAddressBookMemberDetail(MethodView):
    """Hybrid backend: remove a member from a contact list (routed by id type)."""

    @blp.response(200, ListMemberResponseSchema)
    def delete(self, key: str, contact_id: str) -> ResponseReturnValue:
        """Remove a contact from a contact list, routed by id type (idempotent)."""
        logger_api.debug("DELETE /addressbooks/%s/members/%s user=%s", key, contact_id, g.user.uid)
        interface: InterfaceApiContactContact = g.inter
        return interface.remove_list_member(key, contact_id)


@blp.route("/addressbooks/<string:key>/lists/<string:list_key>")
class ApiListDetail(MethodView):
    """API to retrieve, update and delete a single distribution list within an address book."""

    @blp.response(200, ListResponseSchema)
    def get(self, key: str, list_key: str) -> ResponseReturnValue:
        """Get a distribution list by its key within the address book."""
        logger_api.debug("GET /addressbooks/%s/lists/%s user=%s", key, list_key, g.user.uid)
        interface: InterfaceApiContactContact = g.inter
        return interface.get_list(key, list_key)

    @blp.arguments(ListPatchSchema)
    @blp.response(200, ListResponseSchema)
    def patch(self, body: dict, key: str, list_key: str) -> ResponseReturnValue:
        """Apply partial updates to a distribution list."""
        logger_api.debug("PATCH /addressbooks/%s/lists/%s user=%s", key, list_key, g.user.uid)
        interface: InterfaceApiContactContact = g.inter
        return interface.patch_list(key, list_key, body)

    @blp.response(200, ListResponseSchema)
    def delete(self, key: str, list_key: str) -> ResponseReturnValue:
        """Delete a distribution list."""
        logger_api.debug("DELETE /addressbooks/%s/lists/%s user=%s", key, list_key, g.user.uid)
        interface: InterfaceApiContactContact = g.inter
        return interface.delete_list(key, list_key)


#
# Import (grouped together in Swagger, followed by the symmetric export block)
#
def _read_import_upload(files: dict) -> str | tuple[dict, int]:
    """Read and decode the uploaded import ``file`` part.

    Shared by the three import routes: returns the decoded document on success, or an error envelope
    tuple when no file is present or the payload exceeds IMPORT_MAX_BYTES (the caller forwards it).
    """
    upload: FileStorage | None = files.get("file")
    if upload is None:
        return create_api_base_response(None, ERROR_CONTACT_IMPORT_NO_FILE)
    raw: bytes = upload.stream.read()
    if len(raw) > IMPORT_MAX_BYTES:
        return create_api_base_response(None, ERROR_CONTACT_IMPORT_TOO_LARGE)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


@blp.route("/addressbooks/import")
class ApiAddressBookImport(MethodView):
    """API to import a document as a NEW address book (created server-side) holding its contacts and lists."""

    accepted_content_types: set[str] = {"multipart/form-data"}

    @blp.arguments(ContactImportUploadSchema, location="files")
    @blp.arguments(ContactImportQueryArgsSchema, location="query", arg_name="query_args")
    @blp.response(202, ContactJobResponseSchema)
    def post(self, files: dict, query_args: dict) -> ResponseReturnValue:
        """Enqueue an import of the uploaded document as a new address book (returns a job_id)."""
        logger_api.debug("POST /addressbooks/import user=%s format=%s", g.user.uid, query_args.get("format"))
        document = _read_import_upload(files)
        if not isinstance(document, str):
            return document
        interface: InterfaceApiContactContact = g.inter
        return interface.import_addressbook(document, query_args["format"])


@blp.route("/addressbooks/<string:key>/contacts/import")
class ApiContactImport(MethodView):
    """API to import contacts from a document into an existing address book (upsert by uid)."""

    accepted_content_types: set[str] = {"multipart/form-data"}

    @blp.arguments(ContactImportUploadSchema, location="files")
    @blp.arguments(ContactImportQueryArgsSchema, location="query", arg_name="query_args")
    @blp.response(202, ContactJobResponseSchema)
    def post(self, files: dict, query_args: dict, key: str) -> ResponseReturnValue:
        """Enqueue an import of the uploaded contacts into the address book (returns a job_id)."""
        logger_api.debug("POST /addressbooks/%s/contacts/import user=%s format=%s",
                         key, g.user.uid, query_args.get("format"))
        document = _read_import_upload(files)
        if not isinstance(document, str):
            return document
        interface: InterfaceApiContactContact = g.inter
        return interface.import_contact(key, document, query_args["format"])


@blp.route("/addressbooks/<string:key>/lists/import")
class ApiListImport(MethodView):
    """API to import distribution lists from a document into an existing address book (upsert by uid)."""

    accepted_content_types: set[str] = {"multipart/form-data"}

    @blp.arguments(ContactImportUploadSchema, location="files")
    @blp.arguments(ContactImportQueryArgsSchema, location="query", arg_name="query_args")
    @blp.response(202, ContactJobResponseSchema)
    def post(self, files: dict, query_args: dict, key: str) -> ResponseReturnValue:
        """Enqueue an import of the uploaded distribution lists into the address book (returns a job_id)."""
        logger_api.debug("POST /addressbooks/%s/lists/import user=%s format=%s",
                         key, g.user.uid, query_args.get("format"))
        document = _read_import_upload(files)
        if not isinstance(document, str):
            return document
        interface: InterfaceApiContactContact = g.inter
        return interface.import_list(key, document, query_args["format"])


#
# Export (mirrors the import block above)
#
@blp.route("/addressbooks/<string:key>/export")
class ApiAddressBookExport(MethodView):
    """API to export a whole address book (contacts and lists) as vCard, LDIF or JSON."""

    @blp.doc(**_EXPORT_OPENAPI)
    @blp.response(202, ContactJobResponseSchema)
    def get(self, key: str) -> ResponseReturnValue:
        """Enqueue a whole-book export; the serialization is negotiated from the Accept header (returns a job_id)."""
        logger_api.debug("GET /addressbooks/%s/export user=%s accept=%s",
                         key, g.user.uid, request.headers.get("Accept"))
        interface: InterfaceApiContactContact = g.inter
        return interface.export_addressbook(key, request.headers.get("Accept", ""))


@blp.route("/addressbooks/<string:key>/contacts/<string:contact_key>/export")
class ApiContactExport(MethodView):
    """API to export a single contact as vCard, LDIF or JSON."""

    @blp.doc(**_EXPORT_OPENAPI)
    @blp.response(202, ContactJobResponseSchema)
    def get(self, key: str, contact_key: str) -> ResponseReturnValue:
        """Enqueue a single-contact export; the serialization is negotiated from the Accept header (returns a job_id)."""
        logger_api.debug("GET /addressbooks/%s/contacts/%s/export user=%s",
                         key, contact_key, g.user.uid)
        interface: InterfaceApiContactContact = g.inter
        return interface.export_contact(key, contact_key, request.headers.get("Accept", ""))


@blp.route("/addressbooks/<string:key>/lists/<string:list_key>/export")
class ApiListExport(MethodView):
    """API to export a single distribution list as a vCard group card, LDIF groupOfNames or JSON."""

    @blp.doc(**_EXPORT_OPENAPI)
    @blp.response(202, ContactJobResponseSchema)
    def get(self, key: str, list_key: str) -> ResponseReturnValue:
        """Enqueue a single-list export; the serialization is negotiated from the Accept header (returns a job_id)."""
        logger_api.debug("GET /addressbooks/%s/lists/%s/export user=%s", key, list_key, g.user.uid)
        interface: InterfaceApiContactContact = g.inter
        return interface.export_list(key, list_key, request.headers.get("Accept", ""))


#
# External address books (CardDAV subscriptions)
#


@blp.route("/addressbooks/external")
class ApiExternalAddressBookCreate(MethodView):
    """API to create an external CardDAV address book subscription."""

    @blp.arguments(ExternalAddressBookCreateSchema)
    @blp.response(201, AddressBookResponseSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """Create a new external CardDAV address book subscription."""
        logger_api.debug("POST /addressbooks/external user=%s url=%s", g.user.uid, body.get("url"))
        interface: InterfaceApiContactContact = g.inter
        return interface.create_external_addressbook(body)


@blp.route("/addressbooks/<string:key>/sync")
class ApiExternalAddressBookSync(MethodView):
    """API to trigger a manual sync of an external CardDAV address book."""

    @blp.response(202, ContactJobResponseSchema)
    def post(self, key: str) -> ResponseReturnValue:
        """Trigger a manual sync of the external CardDAV address book.

        Returns a job_id; poll GET /jobs/<job_id> until SUCCESS.
        """
        logger_api.debug("POST /addressbooks/%s/sync user=%s", key, g.user.uid)
        interface: InterfaceApiContactContact = g.inter
        return interface.enqueue_external_sync(key)
