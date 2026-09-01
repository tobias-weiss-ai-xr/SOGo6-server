"""Schemas for the hybrid SQL+LDAP address book API (BACKEND-GAPS F3, subsection 2).

The hybrid backend presents every addressable contact list - PostgreSQL address
books *and* LDAP ``groupOfNames`` distribution lists - as a single namespace.
Each normalized list entry carries a ``source`` marker ('sql' | 'ldap') so
clients can tell the two backends apart; member ids are routed by type
(numeric address book keys vs ``ldap:<cn>`` group ids / DNs) through
:mod:`app.utils.id_resolver`.
"""
from __future__ import annotations

from marshmallow import Schema, fields

from app.utils.api.ApiBaseResponse import ApiBaseResponse


class ListEntrySchema(Schema):
    """A normalized contact-list entry in the hybrid SQL+LDAP namespace."""

    source = fields.String(
        metadata={"description": "Backend source: 'sql' (PostgreSQL address book) or 'ldap' (groupOfNames group)."}
    )
    id = fields.String(
        metadata={"description": "List identifier: address book key, or 'ldap:<cn>' group id."}
    )
    name = fields.String()
    description = fields.String(allow_none=True)
    member_count = fields.Integer(metadata={"description": "Number of members (contacts on a SQL book, DNs on an LDAP group)."})
    members = fields.List(
        fields.String(),
        metadata={"description": "Member identifiers (LDAP member DNs for groups; empty for SQL books)."},
    )


class ListEntriesDataSchema(Schema):
    """Data payload for the hybrid address-book/list listing response."""

    lists = fields.List(fields.Nested(ListEntrySchema))
    total_count = fields.Integer()


class ListEntriesResponseSchema(ApiBaseResponse):
    """Response schema for the hybrid list of every addressable contact list."""

    data = fields.Nested(ListEntriesDataSchema, allow_none=True)


class ListMemberCreateSchema(Schema):
    """Request body for adding a member (contact) to a contact list."""

    contact_id = fields.String(
        required=True,
        metadata={"description": "Contact to add: a uid, an email address (local part used as uid), or a full LDAP DN."},
    )


class ListMembersDataSchema(Schema):
    """Data payload for the member collection response."""

    members = fields.List(fields.String(), metadata={"description": "Member identifiers (DNs for LDAP groups, contact uids for SQL books)."})
    total_count = fields.Integer()


class ListMembersResponseSchema(ApiBaseResponse):
    """Response schema for the member list of a contact list."""

    data = fields.Nested(ListMembersDataSchema, allow_none=True)


class ListMemberDataSchema(Schema):
    """Data payload for a single member add/remove response."""

    member_dn = fields.String(
        allow_none=True,
        metadata={"description": "The member identifier (DN) that was added to or removed from the list."},
    )


class ListMemberResponseSchema(ApiBaseResponse):
    """Response schema for add/remove member on a contact list."""

    data = fields.Nested(ListMemberDataSchema, allow_none=True)
