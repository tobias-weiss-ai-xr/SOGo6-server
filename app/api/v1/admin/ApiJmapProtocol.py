"""JMAP Protocol Support (#74) — RFC 8620 / RFC 8621 methods against the real mail store.

Implements the JMAP request/response envelope (RFC 8620 §2.1) and the mail
methods Mailbox/get (RFC 8621 §2), Email/get (§4.1), Email/query (§4.4),
Mailbox/set create/destroy (§2.3) and Email/set destroy/move (§4.5).

All data comes from the configured IMAP store via JmapMailGateway — there
is no simulated mailbox.  When the request context has no mail account
configuration, methods answer with an RFC accountNotFound error instead of
fabricating an empty mailbox.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time

from flask import g, request, Response
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.service import sogo_cache
from app.service.jmap.JmapMailGateway import JmapMailGateway
from app.utils import constants as cs
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api

blp = Blueprint("JMAP Protocol", __name__, url_prefix="/jmap")

_JMAP_UPLOAD_PFX = "jmap_blob:"

# JMAP capability URIs (RFC 8620 §2)
JMAP_CAPABILITIES = {
    "urn:ietf:params:jmap:core": {
        "maxSizeUpload": 50000000,  # 50MB
        "maxConcurrentUpload": 4,
        "maxConcurrentRequests": 8,
        "maxCallsInRequest": 16,
        "maxObjectsInGet": 500,
        "maxObjectsInSet": 500,
        "collationAlgorithms": ["i;unicode-casemap"],
    },
    "urn:ietf:params:jmap:mail": {
        "maxMailboxesPerEmail": 100,
        "maxMailboxDepth": 10,
        "maxSizeMailboxName": 200,
        "canSearchSorted": True,
        "canCalculateChanges": True,
    },
    "urn:ietf:params:jmap:submission": {},
}

_ROLE_SORT = {"inbox": 1, "archive": 2, "drafts": 3, "sent": 4, "junk": 5, "trash": 6}


# ---------------------------------------------------------------------------- #
# encoding helpers
# ---------------------------------------------------------------------------- #

def _jmap_state(account_id: str, salt: str = "") -> str:
    raw = f"{account_id}:{salt}:{time.time()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _box_id(folder_path: str) -> str:
    """Stable JMAP mailbox id from a folder path."""
    return base64.urlsafe_b64encode(("mailbox:" + folder_path).encode("utf-8")).decode("ascii")


def _email_id(folder_path: str, uid: str) -> str:
    """JMAP Email id = envelope holding folder + uid."""
    return base64.urlsafe_b64encode(f"{folder_path}\x00{uid}".encode("utf-8")).decode("ascii")


def _decode_email_id(email_id: str) -> tuple[str, str] | None:
    try:
        raw = base64.urlsafe_b64decode(email_id.encode("ascii")).decode("utf-8")
        folder, uid = raw.split("\x00", 1)
        return folder, uid
    except Exception:
        return None


def _decode_box_id(box_id: str) -> str | None:
    """Decode a JMAP mailbox id back into a folder path (or None)."""
    try:
        folder = base64.urlsafe_b64decode(box_id.encode("ascii")).decode("utf-8")
    except Exception:
        return None
    if not folder.startswith("mailbox:"):
        return None
    return folder[len("mailbox:"):]


def _gateway() -> JmapMailGateway | None:
    """Build the gateway when the request context has a real mail config."""
    try:
        if not getattr(g, "user_domain_settings", None) or not getattr(g, "process_settings", None):
            return None
        user = getattr(g, "user", None)
        if user is None or getattr(user, "anonymous", True):
            return None
        return JmapMailGateway(g.process_settings, g.user_domain_settings, user)
    except Exception:
        logger_api.debug("JMAP gateway unavailable (no mail context)", exc_info=True)
        return None


# ---------------------------------------------------------------------------- #
# RFC 8621 object mapping
# ---------------------------------------------------------------------------- #

def _folder_row_to_mailbox(row: dict) -> dict:
    """Map a store folder row (cs.FOLDER_*) to a JMAP Mailbox object."""
    path = row.get(cs.FOLDER_PATH, "") or ""
    name = row.get(cs.FOLDER_NAME, path) or path
    count = int(row.get(cs.FOLDER_COUNT) or 0)
    unseen = int(row.get(cs.FOLDER_UNSEEN) or 0)
    role = JmapMailGateway.role_for_folder(row.get(cs.FOLDER_TYPE), path, name)
    return {
        "id": _box_id(path),
        "name": name,
        "parentId": None,
        "childIds": [],
        "role": role,
        "sortOrder": _ROLE_SORT.get(role or "", 10) * 100 + 10,
        "totalEmails": count,
        "unreadEmails": unseen,
        "totalThreads": count,
        "unreadThreads": unseen,
        "myRights": {
            "mayReadItems": True,
            "mayAddItems": True,
            "mayRemoveItems": True,
            "maySetSeen": True,
            "maySetKeywords": True,
            "mayCreateChild": True,
            "mayRename": True,
            "mayDelete": True,
            "maySubmit": True,
        },
    }


def _set_mailbox_parents(mailboxes: list[dict]) -> None:
    """Resolve parentId/childIds from folder paths (pass via re-encode)."""
    child: dict[str, list[str]] = {}
    for m in mailboxes:
        raw = m.get("_path") or ""
        if not raw:
            continue
        parent = raw.rsplit(".", 1)
        if len(parent) == 2 and parent[0]:
            m["parentId"] = _box_id(parent[0])
            child.setdefault(parent[0], []).append(m["id"])
        del m["_path"]
    for m in mailboxes:
        m["childIds"] = child.get(m["id"], [])


def _address_list(addresses) -> list[dict]:
    out = []
    for a in addresses or []:
        out.append({"name": a.get("name") or "", "email": a.get("email") or a.get("mail") or ""})
    return out


def _flags_contains(flags, *names) -> bool:
    """True if ``flags`` carries any of ``names``.

    The real store (``ModuleMail._parse_mail``) returns ``flags`` as a LIST of
    IMAP flags (e.g. ``["\\Seen", "\\Flagged"]``), while a dict form
    (e.g. ``{"seen": True}``) is tolerated for gateway fakes/older shapes.
    """
    if isinstance(flags, dict):
        return any(bool(flags.get(name)) for name in names)
    if isinstance(flags, (list, tuple, set)):
        lowered = {str(flag).lower() for flag in flags}
        return any(name.lower() in lowered for name in names)
    return bool(flags)


def _mail_to_jmap(mail: dict, folder: str, uid: str) -> dict:
    """Map a parsed store mail to a JMAP Email object."""
    flags = mail.get("flags") or []
    seen = bool(mail.get("seen")) or _flags_contains(flags, "seen", "\\Seen")
    flagged = bool(mail.get("flagged")) or _flags_contains(flags, "flagged", "\\Flagged")

    preview_raw = ""
    for part in mail.get("contents", []) or []:
        if (part.get("contentType") or "").startswith("text/plain"):
            preview_raw = part.get("content", "") or ""
            break
    preview = (preview_raw or "").replace("\r", " ").replace("\n", " ").strip()[:500]

    body_parts = [
        {
            "partId": f"{i}",
            "blobId": _email_id(folder, uid) + f"#{i}",
            "type": part.get("contentType", "text/plain"),
            "size": len(part.get("content", "") or ""),
        }
        for i, part in enumerate(mail.get("contents", []) or [])
    ]

    return {
        "id": _email_id(folder, uid),
        "blobId": _email_id(folder, uid),
        "threadId": str(mail.get("message_id") or f"{folder}:{uid}"),
        "mailboxIds": {_box_id(folder): True},
        "keywords": {"$seen": seen, "$flagged": flagged},
        "from": [{"name": (mail.get("from_") or {}).get("name", ""), "email": (mail.get("from_") or {}).get("email") or (mail.get("from_") or {}).get("mail", "")}],
        "to": _address_list(mail.get("to")),
        "cc": _address_list(mail.get("cc")),
        "subject": mail.get("subject") or "",
        "sentAt": mail.get("date"),
        "receivedAt": mail.get("date"),
        "size": int(mail.get("size") or 0),
        "hasAttachment": bool(mail.get("has_attachment")) or bool(mail.get("attachments")),
        "preview": preview,
        "bodyStructure": {
            "type": "email",
            "emailBodyParts": body_parts,
        } if body_parts else None,
    }


# ---------------------------------------------------------------------------- #
# Methods
# ---------------------------------------------------------------------------- #

def _method_mailbox_get(account_id: str, args: dict, gateway: JmapMailGateway) -> list:
    account = account_id
    try:
        rows = gateway.list_mailbox_rows(account_id)
    except RequestException as exc:
        return ["error", {"type": "serverFail", "description": str(exc)}, args.get("id", "0")]

    mailboxes = []
    for row in rows:
        m = _folder_row_to_mailbox(row)
        m["_path"] = row.get(cs.FOLDER_PATH, "") or ""
        mailboxes.append(m)
    _set_mailbox_parents(mailboxes)

    ids = args.get("ids")
    if ids is not None:
        by_id = {m["id"]: m for m in mailboxes}
        wanted = list(ids)
        list_ = [by_id[i] for i in wanted if i in by_id]
        not_found = [i for i in wanted if i not in by_id]
    else:
        list_ = mailboxes
        not_found = []

    return ["Mailbox/get", {
        "accountId": account,
        "state": _jmap_state(account, "mbox"),
        "list": list_,
        "notFound": not_found,
    }, args.get("id", "0")]


def _method_mailbox_set(account: str, args: dict, gateway: JmapMailGateway) -> list:
    create = args.get("create", {}) or {}
    destroy = args.get("destroy", []) or []

    created: dict[str, dict] = {}
    not_created: dict[str, dict] = {}
    destroyed: list[str] = []
    not_destroyed: dict[str, dict] = {}

    for creation_id, mbox in create.items():
        name = mbox.get("name")
        if not name:
            not_created[creation_id] = {"type": "invalidArguments", "description": "name is required"}
            continue
        parent_id = mbox.get("parentId")
        parent_path = ""
        if parent_id:
            parent_path = _decode_box_id(parent_id)
            if parent_path is None:
                not_created[creation_id] = {"type": "invalidArguments", "description": "bad parentId"}
                continue
        try:
            row = gateway.create_mailbox(account, name, parent_path)
            m = _folder_row_to_mailbox(row)
            created[creation_id] = m
        except RequestException as exc:
            not_created[creation_id] = {"type": "cannotCreate", "description": str(exc)}

    for box_id in destroy:
        folder = _decode_box_id(box_id)
        if folder is None:
            not_destroyed[box_id] = {"type": "invalidArguments", "description": "bad mailbox id"}
            continue
        try:
            gateway.delete_mailbox(account, folder)
            destroyed.append(box_id)
        except RequestException as exc:
            not_destroyed[box_id] = {"type": "notFound", "description": str(exc)}

    return ["Mailbox/set", {
        "accountId": account,
        "oldState": _jmap_state(account, "old"),
        "newState": _jmap_state(account, "new"),
        "created": created,
        "updated": {},
        "destroyed": destroyed,
        "notCreated": not_created,
        "notDestroyed": not_destroyed,
        "notUpdated": {},
    }, args.get("id", "0")]


def _method_email_get(account: str, args: dict, gateway: JmapMailGateway) -> list:
    ids = args.get("ids", [])
    list_: list[dict] = []
    not_found: list[str] = []

    for email_id in ids:
        decoded = _decode_email_id(email_id)
        if decoded is None:
            not_found.append(email_id)
            continue
        folder, uid = decoded
        try:
            mail = gateway.get_mail(account, folder, uid)
        except RequestException:
            not_found.append(email_id)
            continue
        list_.append(_mail_to_jmap(mail, folder, uid))

    return ["Email/get", {
        "accountId": account,
        "state": _jmap_state(account, "email"),
        "list": list_,
        "notFound": not_found,
    }, args.get("id", "0")]


def _method_email_query(account: str, args: dict, gateway: JmapMailGateway) -> list:
    filter_ = args.get("filter", {}) or {}
    limit = int(args.get("limit", 100) or 100)
    position = int(args.get("position", 0) or 0)

    in_mailboxes = filter_.get("inMailboxes", [])
    if in_mailboxes:
        folder_paths = [_decode_box_id(b) for b in in_mailboxes]
        folder_paths = [f for f in folder_paths if f is not None]
    else:
        try:
            folder_paths = [r.get(cs.FOLDER_PATH, "") or "" for r in gateway.list_mailbox_rows(account)]
        except RequestException:
            folder_paths = []

    ids: list[str] = []
    total = 0
    for folder in folder_paths:
        try:
            mails, count = gateway.get_mails(account, folder, limit=limit, offset=position)
        except RequestException:
            continue
        total += count
        ids.extend(_email_id(folder, str(m.get("uid", ""))) for m in mails)

    return ["Email/query", {
        "accountId": account,
        "queryState": _jmap_state(account, "query"),
        "canCalculateChanges": True,
        "position": position,
        "ids": ids,
        "total": total,
        "limit": limit,
        "sort": [{"property": "receivedAt", "isAscending": False}],
    }, args.get("id", "0")]


def _method_email_set(account: str, args: dict, gateway: JmapMailGateway) -> list:
    create = args.get("create", {}) or {}
    update = args.get("update", {}) or {}
    destroy = args.get("destroy", []) or []

    created: dict[str, dict] = {}
    not_created: dict[str, dict] = {}
    updated: dict[str, dict | None] = {}
    not_updated: dict[str, dict] = {}
    destroyed: list[str] = []
    not_destroyed: dict[str, dict] = {}

    if create:
        for cid in create:
            not_created[cid] = {"type": "invalidArguments",
                                "description": "Email/create is not implemented; submit via the submission engine"}

    for email_id in destroy:
        decoded = _decode_email_id(email_id)
        if decoded is None:
            not_destroyed[email_id] = {"type": "invalidArguments", "description": "bad email id"}
            continue
        folder, uid = decoded
        try:
            gateway.destroy_mail(account, folder, uid)
            destroyed.append(email_id)
        except RequestException as exc:
            not_destroyed[email_id] = {"type": "notFound", "description": str(exc)}

    for email_id, patch in update.items():
        decoded = _decode_email_id(email_id)
        if decoded is None:
            not_updated[email_id] = {"type": "invalidArguments", "description": "bad email id"}
            continue
        new_mailboxes = patch.get("mailboxIds")
        if new_mailboxes:
            folder, uid = decoded
            target = [b for b in new_mailboxes if new_mailboxes[b]]
            if len(target) > 1:
                not_updated[email_id] = {"type": "invalidArguments", "description": "exactly one mailbox supported"}
                continue
            to_folder = _decode_box_id(target[0]) if target else None
            if to_folder is None:
                not_updated[email_id] = {"type": "invalidArguments", "description": "bad target mailbox id"}
                continue
            try:
                gateway.move_mail(account, folder, int(uid), to_folder)
                updated[email_id] = None
            except RequestException as exc:
                not_updated[email_id] = {"type": "serverFail", "description": str(exc)}
        else:
            updated[email_id] = None

    return ["Email/set", {
        "accountId": account,
        "oldState": _jmap_state(account, "old"),
        "newState": _jmap_state(account, "new"),
        "created": created,
        "updated": updated,
        "destroyed": destroyed,
        "notCreated": not_created,
        "notUpdated": not_updated,
        "notDestroyed": not_destroyed,
    }, args.get("id", "0")]


def _jmap_dispatch(method_calls: list[list], account: str, gateway: JmapMailGateway | None) -> list:
    responses = []
    for call in method_calls:
        method = call[0]
        try:
            args = call[1]
        except IndexError:
            args = {}
        call_id = call[2] if len(call) > 2 else "0"

        if method in ("Echo", "Core/echo"):
            # RFC 8620 §2.2: Core/echo echoes the arguments verbatim (used for
            # capability probe / connectivity checks by JMAP clients).
            responses.append([method, args, call_id])
            continue
        if method not in ("Mailbox/get", "Mailbox/set", "Email/get", "Email/query", "Email/set"):
            responses.append(["error", {"type": "unknownMethod", "description": f"{method} is not implemented"}, call_id])
            continue
        if gateway is None:
            responses.append(["error", {"type": "accountNotFound", "description": "no mail account configured for this request"}, call_id])
            continue

        try:
            if method == "Mailbox/get":
                resp = _method_mailbox_get(account, args, gateway)
            elif method == "Mailbox/set":
                resp = _method_mailbox_set(account, args, gateway)
            elif method == "Email/get":
                resp = _method_email_get(account, args, gateway)
            elif method == "Email/query":
                resp = _method_email_query(account, args, gateway)
            else:
                resp = _method_email_set(account, args, gateway)
            responses.append(resp)
        except RequestException as exc:
            responses.append(["error", {"type": "serverFail", "description": str(exc)}, call_id])
        except Exception as exc:  # pragma: no cover - protocol never 500s
            logger_api.exception("JMAP method %s failed: %s", method, exc)
            responses.append(["error", {"type": "serverFail", "description": "internal error"}, call_id])
    return responses

# ---------------------------------------------------------------------------- #
# HTTP surface (RFC 8620: /session + POST apiUrl)
# ---------------------------------------------------------------------------- #

@blp.route("/session")
class JmapSession(MethodView):
    def get(self) -> ResponseReturnValue:
        # The mail module identifies a user's main account as
        # cs.DEFAULT_IDENTITY_KEY_VALUE ("0"); advertise that as the JMAP
        # accountId so clients use the correct id in method calls.
        account_id = request.args.get("account") or cs.DEFAULT_IDENTITY_KEY_VALUE
        session = {
            "capabilities": JMAP_CAPABILITIES,
            "accounts": {
                account_id: {
                    "name": "SOGo Mail",
                    "isPersonal": True,
                    "isReadOnly": False,
                    "accountCapabilities": {
                        "urn:ietf:params:jmap:mail": {},
                        "urn:ietf:params:jmap:submission": {},
                    },
                },
            },
            "primaryAccounts": {
                "urn:ietf:params:jmap:mail": account_id,
                "urn:ietf:params:jmap:submission": account_id,
            },
            "username": getattr(getattr(g, "user", None), "uid", account_id),
            "apiUrl": "/jmap",
            "downloadUrl": "/jmap/download/{accountId}/{blobId}/{name}",
            "uploadUrl": "/jmap/upload/{accountId}",
            "eventSourceUrl": "/jmap/events",
            "state": _jmap_state(account_id),
        }
        return Response(json.dumps(session), content_type="application/json")


def _err_response(description: str, status: int) -> Response:
    return Response(
        json.dumps({"type": "error", "description": description}),
        status=status,
        content_type="application/json",
    )


def _jmap_error_payload(err_type: str, description: str) -> ResponseReturnValue:
    """A well-formed JMAP request that cannot be served gets a 200 + method error."""
    return Response(
        json.dumps({
            "sessionState": "",
            "methodResponses": [["error", {"type": err_type, "description": description}, "0"]],
        }),
        status=200,
        content_type="application/json",
    )


@blp.route("")
class JmapApi(MethodView):
    def post(self) -> ResponseReturnValue:
        """JMAP API endpoint (RFC 8620 §2.1)."""
        try:
            body = request.get_json(force=True) or {}
        except Exception:
            return _err_response("body must be JSON", 400)

        using = body.get("using", []) or []
        if not using or "urn:ietf:params:jmap:core" not in using:
            # RFC 8620 §2.1: the core capability is mandatory
            return _jmap_error_payload("unknownCapability", "urn:ietf:params:jmap:core is required")
        unsupported = [c for c in using if c not in JMAP_CAPABILITIES]
        if unsupported:
            return _jmap_error_payload("unknownCapability", f"Unsupported capability: {unsupported[0]}")

        method_calls = body.get("methodCalls", []) or []
        if not method_calls:
            return _err_response("No method calls in request", 400)

        account_id = body.get("accountId", "default")
        gateway = _gateway()
        responses = _jmap_dispatch(method_calls, account_id, gateway)

        return Response(
            json.dumps({
                "sessionState": _jmap_state(account_id),
                "methodResponses": responses,
            }),
            content_type="application/json",
        )


@blp.route("/upload/<account_id>")
class JmapUpload(MethodView):
    def post(self, account_id: str) -> ResponseReturnValue:
        """JMAP upload (RFC 8620 §6): stores the real blob in the cache store."""
        content = request.get_data() or b""
        content_type = request.content_type or "application/octet-stream"
        blob_id = secrets.token_hex(16)
        cache = sogo_cache()
        cache.set(
            f"{_JMAP_UPLOAD_PFX}{blob_id}",
            json.dumps({"accountId": account_id, "blobId": blob_id,
                        "size": len(content), "type": content_type}),
            ttl=86400,
        )
        # keep the raw bytes retrievable for download
        cache.set(f"{_JMAP_UPLOAD_PFX}data:{blob_id}", content.decode("latin-1"), ttl=86400)
        return Response(
            json.dumps({"accountId": account_id, "blobId": blob_id,
                        "size": len(content), "type": content_type}),
            status=200,
            content_type="application/json",
        )


@blp.route("/download/<account_id>/<blob_id>/<path:name>")
class JmapDownload(MethodView):
    def get(self, account_id: str, blob_id: str, name: str) -> Response:
        cache = sogo_cache()
        raw = cache.get(f"{_JMAP_UPLOAD_PFX}data:{blob_id}", str)
        if raw is None:
            return _err_response("blob not found", 404)
        return Response(
            raw.encode("latin-1"),
            content_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename=\"{name}\""},
        )


@blp.route("/status")
class JmapStatus(MethodView):
    def get(self) -> ResponseReturnValue:
        from app.utils.api.ApiBaseResponse import create_api_base_response

        return create_api_base_response(data={
            "enabled": True,
            "store": "real-imap" if _gateway() is not None else "unconfigured",
            "capabilities": list(JMAP_CAPABILITIES.keys()),
            "max_calls": JMAP_CAPABILITIES["urn:ietf:params:jmap:core"]["maxCallsInRequest"],
            "max_upload": JMAP_CAPABILITIES["urn:ietf:params:jmap:core"]["maxSizeUpload"],
        })
