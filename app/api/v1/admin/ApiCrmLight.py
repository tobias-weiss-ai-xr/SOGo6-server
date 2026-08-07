"""CRM-light (#53) — contact interaction history, email-to-account association.

Lightweight CRM: associate contacts with accounts, track interactions,
categorize contacts, and record notes.
"""
from __future__ import annotations

import json
import secrets
import time
from typing import TYPE_CHECKING

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate

from app.service import sogo_cache
from app.utils.api.ApiBaseResponse import create_api_base_response

if TYPE_CHECKING:
    from app.auth.User import User

blp = Blueprint("CRM-light", __name__, url_prefix="/crm")

_PREFIX: str = "crm_contact:"
_ACCOUNT_PREFIX: str = "crm_account:"


class AccountCreateSchema(Schema):
    name = fields.String(required=True)
    domain = fields.String(load_default="")
    industry = fields.String(load_default="")
    notes = fields.String(load_default="")


class ContactUpdateSchema(Schema):
    account_id = fields.String(load_default="")
    tags = fields.List(fields.String(), load_default=[])
    notes = fields.String(load_default="")


class InteractionSchema(Schema):
    contact_uid = fields.String(required=True)
    type = fields.String(required=True, validate=validate.OneOf(["email_sent", "email_received", "meeting", "call", "note"]))
    subject = fields.String(required=True)
    notes = fields.String(load_default="")


@blp.route("/accounts")
class ApiCrmAccounts(MethodView):
    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        index = list(cache.get(f"{_ACCOUNT_PREFIX}index", list) or [])
        accounts = []
        for aid in index:
            raw = cache.get(f"{_ACCOUNT_PREFIX}{aid}", str)
            if raw:
                try:
                    accounts.append(json.loads(raw))
                except Exception:
                    continue
        return create_api_base_response({"accounts": accounts})

    @blp.arguments(AccountCreateSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        cache = sogo_cache()
        account_id = f"ACC-{int(time.time())}"
        account = {
            "id": account_id,
            "name": body["name"],
            "domain": body.get("domain", ""),
            "industry": body.get("industry", ""),
            "notes": body.get("notes", ""),
            "contacts": [],
            "created_at": int(time.time()),
        }
        cache.set(f"{_ACCOUNT_PREFIX}{account_id}", json.dumps(account), ttl=86400 * 365)
        idx = list(cache.get(f"{_ACCOUNT_PREFIX}index", list) or [])
        idx.append(account_id)
        cache.set(f"{_ACCOUNT_PREFIX}index", idx, ttl=86400 * 365)
        return create_api_base_response(account, code=201)


@blp.route("/contacts")
class ApiCrmContacts(MethodView):
    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        index = list(cache.get(f"{_PREFIX}index", list) or [])
        contacts = []
        for cid in index:
            raw = cache.get(f"{_PREFIX}{cid}", str)
            if raw:
                try:
                    contacts.append(json.loads(raw))
                except Exception:
                    continue
        return create_api_base_response({"contacts": contacts})

    @blp.arguments(ContactUpdateSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        user: User = g.user
        cache = sogo_cache()
        contact_id = user.uid
        raw = cache.get(f"{_PREFIX}{contact_id}", str)
        contact = json.loads(raw) if raw else {
            "id": contact_id,
            "account_id": "",
            "tags": [],
            "notes": "",
            "interactions": [],
            "created_at": int(time.time()),
        }
        if body.get("account_id"):
            contact["account_id"] = body["account_id"]
        if body.get("tags"):
            contact["tags"] = list(set(contact.get("tags", []) + body["tags"]))
        if body.get("notes"):
            contact["notes"] = body["notes"]
        cache.set(f"{_PREFIX}{contact_id}", json.dumps(contact), ttl=86400 * 365)
        idx = list(cache.get(f"{_PREFIX}index", list) or [])
        if contact_id not in idx:
            idx.append(contact_id)
            cache.set(f"{_PREFIX}index", idx, ttl=86400 * 365)
        return create_api_base_response(contact)


@blp.route("/interactions")
class ApiCrmInteractions(MethodView):
    @blp.arguments(InteractionSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        user: User = g.user
        cache = sogo_cache()
        contact_id = body["contact_uid"]
        raw = cache.get(f"{_PREFIX}{contact_id}", str)
        contact = json.loads(raw) if raw else {
            "id": contact_id, "account_id": "", "tags": [], "notes": "", "interactions": [],
        }
        interaction = {
            "id": f"INT-{secrets.token_hex(4)}",
            "type": body["type"],
            "subject": body["subject"],
            "notes": body.get("notes", ""),
            "created_by": user.uid,
            "created_at": int(time.time()),
        }
        contact["interactions"].append(interaction)
        cache.set(f"{_PREFIX}{contact_id}", json.dumps(contact), ttl=86400 * 365)
        return create_api_base_response(interaction, code=201)
