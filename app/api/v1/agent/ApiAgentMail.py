"""Agent facade — mail actions.

Compact, one-call semantics over the existing mail interfaces:
summary lists (snippets, no full bodies), body-truncated detail view,
single-call send with inline base64 attachments, search, batch actions,
folders and drafts.
"""
import base64
import binascii

from flask import g, request
from flask.views import MethodView
from flask.typing import ResponseReturnValue

from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.api.paginate_sort_filter import CollectionPaginateArgs
from app.utils.logger.logger import logger_api

from . import agent_blueprint, mail_folder_interface, mail_interface, mail_send_interface, register_action, require_scope
from .schemas import SNIPPET_MAX_CHARS, AgentMailBatchActionSchema, AgentMailDetailQuerySchema, AgentMailSendSchema

blp = agent_blueprint("Agent Mail", "/agent/mail", "Agent mail actions (compact, one-call)")

AGENT_MAX_PAGE_SIZE = 50


def _page_args(fallback_size: int = 20) -> tuple[int, int] | None:
    """Parse `page` + (`page_size` | `limit`) args with the agent page cap."""
    try:
        page = max(1, int(request.args.get("page", 1)))
        raw_size = request.args.get("page_size") or request.args.get("limit") or fallback_size
        page_size = min(AGENT_MAX_PAGE_SIZE, max(1, int(raw_size)))
    except ValueError:
        return None
    return page, page_size


def _summary(mail: dict) -> dict:
    """Compact spec-shaped summary: snippet capped, flags bucketed, no bodies."""
    seen = bool(mail.get("seen"))
    flagged = bool(mail.get("flagged"))
    return {
        "uid": mail.get("uid"),
        "from": mail.get("from"),
        "subject": mail.get("subject"),
        "date": mail.get("date"),
        "snippet": _text_snippet(mail, SNIPPET_MAX_CHARS),
        "flags": {"seen": seen, "flagged": flagged},
        "seen": seen,
        "flagged": flagged,
        "has_attachments": mail.get("has_attachment"),
    }


def _text_snippet(mail: dict, max_chars: int) -> str:
    """First ``max_chars`` chars of the first text/plain (fallback: any) body."""
    contents = mail.get("contents") or []
    text = ""
    for content in contents:
        ctype = str(content.get("contentType", ""))
        if ctype.startswith("text/plain"):
            text = str(content.get("content", "") or "")
            break
        if not text:
            text = str(content.get("content", "") or "")
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def _strip_quotes(text: str) -> str:
    """Drop quoted reply lines and collapse the result."""
    kept = [line for line in text.splitlines() if not line.lstrip().startswith(">")]
    return "\n".join(kept).strip()


def _compact_detail(mail: dict, strip_quotes: bool, max_chars: int) -> dict:
    """Compact a full mail dict for agent consumption."""
    compact = {
        "uid": mail.get("uid"),
        "from": mail.get("from"),
        "to": mail.get("to"),
        "cc": mail.get("cc"),
        "subject": mail.get("subject"),
        "date": mail.get("date"),
        "seen": mail.get("seen"),
        "flagged": mail.get("flagged"),
        "has_attachments": mail.get("has_attachment"),
        "is_signed": mail.get("is_signed"),
        "body": {},
        "attachments": [
            {"filename": a.get("filename"), "contentType": a.get("contentType"), "size": a.get("size")}
            for a in (mail.get("attachments") or [])
        ],
    }
    for content in mail.get("contents") or []:
        ctype = str(content.get("contentType", ""))
        if not ctype.startswith("text/"):
            continue
        body_text = str(content.get("content", "") or "")
        if strip_quotes:
            body_text = _strip_quotes(body_text)
        if len(body_text) > max_chars:
            body_text = body_text[:max_chars] + "…"
        compact["body"][ctype] = body_text
    return compact


# ── Message list ─────────────────────────────────────────────────────────────

@blp.route("/messages")
class AgentMailMessages(MethodView):
    """List mails of a folder as compact summaries."""

    def get(self) -> ResponseReturnValue:
        """Summaries (uid, from, subject, snippet<=200, flags) — no full bodies."""
        guard = require_scope("mail:read")
        if guard is not None:
            return guard

        folder = request.args.get("folder", "INBOX")
        account_id = request.args.get("account_id", "0")
        page_args = _page_args()
        if page_args is None:
            return create_api_base_response(None, err.ERROR_VALIDATION_FAILED)
        page, page_size = page_args

        collection = CollectionPaginateArgs(page=page, page_size=page_size, sort_by="date", sort_order="desc")
        total, response, status = mail_interface().get_mail_list(account_id, folder, collection)
        if status >= 400:
            return response, status

        mails = response.get("data") or []
        messages = [_summary(mail) for mail in mails]
        return create_api_base_response({"total": total, "folder": folder, "messages": messages})


# ── Message detail ───────────────────────────────────────────────────────────

@blp.route("/messages/<int:mail_uid>")
class AgentMailMessageDetail(MethodView):
    """Fetch one mail with server-side body truncation."""

    @blp.arguments(AgentMailDetailQuerySchema, location="query", arg_name="args")
    def get(self, args: dict, mail_uid: int) -> ResponseReturnValue:
        """Full mail with `strip_quotes` and `max_chars` applied to text bodies."""
        guard = require_scope("mail:read")
        if guard is not None:
            return guard

        folder = request.args.get("folder", "INBOX")
        account_id = request.args.get("account_id", "0")

        response, status = mail_interface().get_mail_detail(account_id, folder, str(mail_uid))
        if status >= 400:
            return response, status
        mail = response.get("data") or {}
        return create_api_base_response(_compact_detail(mail, args["strip_quotes"], args["max_chars"]))


# ── Send (one call, inline attachments) ──────────────────────────────────────

@blp.route("/send")
class AgentMailSend(MethodView):
    """Send a mail in a single call, attachments inline as base64."""

    @blp.arguments(AgentMailSendSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """Server combines upload + send; returns the send result envelope."""
        guard = require_scope("mail:send")
        if guard is not None:
            return guard

        attachments = []
        for att in body.get("attachments") or []:
            try:
                data = base64.b64decode(att["content_b64"], validate=True)
            except (KeyError, binascii.Error, ValueError):
                return create_api_base_response(None, err.ERROR_VALIDATION_FAILED)
            attachments.append({
                "filename": att["filename"],
                "data": data,
                "content_type": att.get("content_type") or "application/octet-stream",
            })

        mail_data = {
            "from_addr": body.get("from_addr") or getattr(g.user, "mail", None) or g.user.uid,
            "to": body["to"],
            "cc": body.get("cc") or [],
            "bcc": body.get("bcc") or [],
            "subject": body.get("subject") or "",
            "body": body.get("body") or "",
            "is_html": body.get("is_html", False),
            "reply_to": body.get("reply_to"),
            "send_at": body.get("send_at"),
            "attachments": attachments,
        }

        logger_api.info("Agent mail send: user=%s to=%s attachments=%d",
                        g.user.uid, len(body["to"]), len(attachments))
        response, status = mail_send_interface().send_mail(
            request.args.get("account_id", "0"), mail_data, key=None)
        return response, status


# ── Search ───────────────────────────────────────────────────────────────────

@blp.route("/search")
class AgentMailSearch(MethodView):
    """Cross-folder mail search returning compact summaries."""

    def get(self) -> ResponseReturnValue:
        """Search by query/from/to/subject/date filters (see MailSearchQuerySchema)."""
        guard = require_scope("mail:read")
        if guard is not None:
            return guard

        allowed = {
            "query", "folders", "in_body", "from", "to", "subject", "body", "bcc",
            "with_attachments", "unseen_only", "flagged_only", "date_from", "date_to",
            "sort_by", "sort_order",
        }
        search_params = {k: v for k, v in request.args.items() if k in allowed}
        page_args = _page_args()
        if page_args is not None:
            search_params["page"], search_params["per_page"] = page_args
        else:
            search_params["page"], search_params["per_page"] = 1, 20

        total, response, status = mail_interface().search_mails(
            request.args.get("account_id", "0"), search_params)
        if status >= 400:
            return response, status

        mails = response.get("data") or []
        if isinstance(mails, dict):
            mails = mails.get("mails") or mails.get("results") or []
        messages = [{
            "uid": m.get("uid"),
            "folder": m.get("folder"),
            "from": m.get("from"),
            "subject": m.get("subject"),
            "date": m.get("date"),
            "snippet": _text_snippet(m, SNIPPET_MAX_CHARS),
            "flags": {"seen": bool(m.get("seen")), "flagged": bool(m.get("flagged"))},
            "has_attachments": m.get("has_attachment"),
        } for m in mails]
        return create_api_base_response({"total": total, "messages": messages})


# ── Batch action ─────────────────────────────────────────────────────────────

@blp.route("/messages/batch-action")
class AgentMailBatchAction(MethodView):
    """Apply one action to many mails (delete, move, mark_read, ...)."""

    @blp.arguments(AgentMailBatchActionSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """Body: {action, mail_uids, data?}; folder via ?folder= query."""
        guard = require_scope("mail:send")
        if guard is not None:
            return guard

        return mail_interface().batch_mail_action(
            request.args.get("account_id", "0"),
            request.args.get("folder", "INBOX"),
            body,
        )


# ── Folders ──────────────────────────────────────────────────────────────────────

@blp.route("/folders")
class AgentMailFolders(MethodView):
    """List mail folders (compact)."""

    def get(self) -> ResponseReturnValue:
        """Folder list: name, path, unread/total counts."""
        guard = require_scope("mail:read")
        if guard is not None:
            return guard

        response, status = mail_folder_interface().get_folder_list(request.args.get("account_id", "0"))
        if status >= 400:
            return response, status
        folders = response.get("data") or []
        if isinstance(folders, dict):
            folders = folders.get("folders") or []
        compact = []
        for folder in folders:
            if isinstance(folder, dict):
                compact.append({
                    "name": folder.get("name"),
                    "path": folder.get("path") or folder.get("id"),
                    "unread": folder.get("unread") or folder.get("unseen"),
                    "total": folder.get("total") or folder.get("exists"),
                })
            else:
                compact.append({"name": str(folder)})
        return create_api_base_response({"folders": compact})


# ── Drafts ───────────────────────────────────────────────────────────────────

@blp.route("/drafts")
class AgentMailDrafts(MethodView):
    """Save a draft."""

    @blp.arguments(AgentMailSendSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """Same body as send; stored in the Drafts folder, returns draft key."""
        guard = require_scope("mail:send")
        if guard is not None:
            return guard

        mail_data = {
            "from_addr": body.get("from_addr") or getattr(g.user, "mail", None) or g.user.uid,
            "to": body["to"],
            "cc": body.get("cc") or [],
            "bcc": body.get("bcc") or [],
            "subject": body.get("subject") or "",
            "body": body.get("body") or "",
            "is_html": body.get("is_html", False),
        }
        logger_api.info("Agent draft save: user=%s", g.user.uid)
        return mail_send_interface().save_draft(
            request.args.get("account_id", "0"), mail_data, key=None, close=False)


@blp.route("/drafts/<string:key>/send")
class AgentMailDraftSend(MethodView):
    """Send an existing draft by its tmp_draft key."""

    def post(self, key: str) -> ResponseReturnValue:
        """Sends the draft stored under `key` (headers/attachments included)."""
        guard = require_scope("mail:send")
        if guard is not None:
            return guard

        mail_data = {"from_addr": g.user.mail or g.user.uid, "to": []}
        return mail_send_interface().send_mail(
            request.args.get("account_id", "0"), mail_data, key=key)


# ── Registry ─────────────────────────────────────────────────────────────────

register_action("mail.messages.list", "GET", "/api/user/v1/agent/mail/messages",
                "List mails of a folder as compact summaries (snippets, no bodies)", "mail:read")
register_action("mail.messages.get", "GET", "/api/user/v1/agent/mail/messages/{uid}",
                "Get one mail with strip_quotes/max_chars body truncation", "mail:read")
register_action("mail.send", "POST", "/api/user/v1/agent/mail/send",
                "Send a mail in one call, attachments inline as base64", "mail:send")
register_action("mail.search", "GET", "/api/user/v1/agent/mail/search",
                "Cross-folder mail search returning compact summaries", "mail:read")
register_action("mail.messages.batch_action", "POST", "/api/user/v1/agent/mail/messages/batch-action",
                "Apply one action (delete/move/mark_read/…) to many mails", "mail:send")
register_action("mail.folders.list", "GET", "/api/user/v1/agent/mail/folders",
                "List mail folders with unread/total counts", "mail:read")
register_action("mail.drafts.create", "POST", "/api/user/v1/agent/mail/drafts",
                "Save a draft", "mail:send")
register_action("mail.drafts.send", "POST", "/api/user/v1/agent/mail/drafts/{key}/send",
                "Send an existing draft by key", "mail:send")
