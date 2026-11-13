"""Agent facade — contacts actions.

Search-first contact access (agents usually know a name/mail, not a key),
CRUD with default-addressbook resolution, addressbook list.
"""
from flask import g, request
from flask.views import MethodView
from flask.typing import ResponseReturnValue
import marshmallow
from marshmallow import Schema, fields, validate

from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

from . import agent_blueprint, contact_interface, register_action, require_scope

blp = agent_blueprint("Agent Contacts", "/agent/contacts", "Agent contacts actions")

CONTACTS_MAX_RESULTS = 50


# ── Schemas (OpenAPI contract) ─────────────────────────────────────────────

class AgentContactCreateSchema(Schema):
    """Minimal agent payload: {first_name, last_name, email} (+ optional extras).

    Absent optional fields are omitted (load_default=missing) so the delegated
    payload contains exactly what the agent supplied; unknown fields pass
    through so pre-existing UI payloads keep working.
    """

    class Meta:
        unknown = "include"

    first_name = fields.String(load_default=marshmallow.missing, allow_none=True)
    last_name = fields.String(load_default=marshmallow.missing, allow_none=True)
    email = fields.Email(load_default=marshmallow.missing, allow_none=True,
                         metadata={"description": "Primary email; stored as first address"})
    company = fields.String(load_default=marshmallow.missing, allow_none=True)
    note = fields.String(load_default=marshmallow.missing, allow_none=True)
    addressbook_key = fields.String(load_default=marshmallow.missing, allow_none=True,
                                     metadata={"description": "Target book; default = first personal book"})


class AgentContactPatchSchema(Schema):
    """Partial update — any subset of the create fields plus raw passthrough."""

    class Meta:
        unknown = "include"


class AgentContactsSearchQuerySchema(Schema):
    q = fields.String(required=True, metadata={"description": "Partial name or email"})
    limit = fields.Integer(load_default=20, validate=validate.Range(min=1, max=CONTACTS_MAX_RESULTS))


class AgentSuggestionSchema(Schema):
    key = fields.String(allow_none=True)
    name = fields.String(allow_none=True)
    email = fields.String(allow_none=True)
    primary_phone = fields.String(allow_none=True)


class AgentSuggestionsResponseSchema(Schema):
    suggestions = fields.List(fields.Nested(AgentSuggestionSchema()))


def _default_addressbook_key(interface) -> str | None:
    """First addressbook key of the user."""
    response, status = interface.get_all_addressbooks()
    if status >= 400:
        return None
    books = (response.get("data") or {}).get("addressbooks") or []
    if isinstance(books, dict):
        books = list(books.values())
    for book in books:
        if isinstance(book, dict) and book.get("key"):
            return book["key"]
    return None


def _compact_suggestion(entry: dict) -> dict:
    """Spec shape: {key, name, email, primary_phone} — phones may be null."""
    return {
        "key": entry.get("contact_key") or entry.get("key"),
        "name": entry.get("name"),
        "email": entry.get("email"),
        "primary_phone": entry.get("primary_phone") or entry.get("phone"),
    }


# ── Search ───────────────────────────────────────────────────────────────────

@blp.route("/search")
class AgentContactsSearch(MethodView):
    """Search contacts across all addressbooks (compact suggestions)."""

    @blp.arguments(AgentContactsSearchQuerySchema, location="query")
    def get(self, args: dict) -> ResponseReturnValue:
        """?q= partial name or email, ?limit= (default 20) — {key,name,email,phone}."""
        guard = require_scope("contacts:read")
        if guard is not None:
            return guard

        query = (args.get("q") or "").strip()
        if not query:
            return create_api_base_response({"suggestions": []})
        response, status = contact_interface().autocomplete(query)
        if status >= 400:
            return response, status
        suggestions = (response.get("data") or {}).get("suggestions") or []
        return create_api_base_response(
            {"suggestions": [_compact_suggestion(s) for s in suggestions[: args["limit"]]]})


# ── Contact CRUD ─────────────────────────────────────────────────────────────

@blp.route("")
class AgentContactsCreate(MethodView):
    """Create a contact."""

    @blp.arguments(AgentContactCreateSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """Create a contact — {first_name, last_name, email} is enough; key returned."""
        guard = require_scope("contacts:write")
        if guard is not None:
            return guard

        interface = contact_interface()
        addressbook_key = body.pop("addressbook_key", None)
        if not addressbook_key:
            addressbook_key = _default_addressbook_key(interface)
            if not addressbook_key:
                return create_api_base_response(None, err.ERROR_NOT_FOUND)
        logger_api.info("Agent contact create: user=%s book=%s", g.user.uid, addressbook_key)
        return interface.create_contact(addressbook_key, body)


@blp.route("/<string:key>")
class AgentContactDetail(MethodView):
    """Fetch, patch or delete a single contact (?addressbook_key=)."""

    def get(self, key: str) -> ResponseReturnValue:
        guard = require_scope("contacts:read")
        if guard is not None:
            return guard
        return contact_interface().get_contact(request.args.get("addressbook_key", ""), key)

    @blp.arguments(AgentContactPatchSchema)
    def patch(self, body: dict, key: str) -> ResponseReturnValue:
        guard = require_scope("contacts:write")
        if guard is not None:
            return guard
        return contact_interface().patch_contact(request.args.get("addressbook_key", ""), key, body)

    def delete(self, key: str) -> ResponseReturnValue:
        guard = require_scope("contacts:write")
        if guard is not None:
            return guard
        return contact_interface().delete_contact(request.args.get("addressbook_key", ""), key)


# ── Addressbooks ─────────────────────────────────────────────────────────────

@blp.route("/addressbooks")
class AgentAddressbooks(MethodView):
    """List addressbooks."""

    def get(self) -> ResponseReturnValue:
        guard = require_scope("contacts:read")
        if guard is not None:
            return guard
        return contact_interface().get_all_addressbooks()


# ── Registry ─────────────────────────────────────────────────────────────────

register_action("contacts.search", "GET", "/api/user/v1/agent/contacts/search",
                "Search contacts across addressbooks (?q=)", "contacts:read")
register_action("contacts.create", "POST", "/api/user/v1/agent/contacts",
                "Create a contact (addressbook_key optional)", "contacts:write")
register_action("contacts.get", "GET", "/api/user/v1/agent/contacts/{key}",
                "Get one contact (?addressbook_key=)", "contacts:read")
register_action("contacts.update", "PATCH", "/api/user/v1/agent/contacts/{key}",
                "Partial contact update (?addressbook_key=)", "contacts:write")
register_action("contacts.delete", "DELETE", "/api/user/v1/agent/contacts/{key}",
                "Delete a contact (?addressbook_key=)", "contacts:write")
register_action("contacts.addressbooks.list", "GET", "/api/user/v1/agent/contacts/addressbooks",
                "List addressbooks", "contacts:read")
