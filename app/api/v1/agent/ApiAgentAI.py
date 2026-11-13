"""Agent facade — AI-assist actions over the user's own data.

summarize / suggest-reply fetch the mail server-side (no need for the agent
to pull bodies first), nl-search converts natural language to structured mail
search parameters.
"""
from flask import request
from flask.views import MethodView
from flask.typing import ResponseReturnValue

from app.service.ai.AIService import get_model_backend
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

from . import agent_blueprint, mail_interface, register_action, require_scope
from .schemas import AgentNlSearchSchema

blp = agent_blueprint("Agent AI", "/agent/ai", "AI-assist actions (Ollama-backed)")

_SNIPPET_CHARS = 4000


def _mail_text(mail_uid: str, folder: str, account_id: str) -> str | None:
    """Fetch a mail and return its concatenated text bodies (truncated)."""
    response, status = mail_interface().get_mail_detail(account_id, folder, str(mail_uid))
    if status >= 400:
        return None
    mail = response.get("data") or {}
    parts = []
    for content in mail.get("contents") or []:
        ctype = str(content.get("contentType", ""))
        if ctype.startswith("text/"):
            parts.append(str(content.get("content", "") or ""))
    text = "\n".join(parts).strip()
    return text[:_SNIPPET_CHARS] if text else None


@blp.route("/summarize/<int:mail_uid>")
class AgentAISummarize(MethodView):
    """Summarize a mail server-side."""

    def post(self, mail_uid: int) -> ResponseReturnValue:
        """Fetches the mail (?folder=INBOX), summarizes, returns {summary}."""
        guard = require_scope("mail:read")
        if guard is not None:
            return guard

        text = _mail_text(mail_uid, request.args.get("folder", "INBOX"), request.args.get("account_id", "0"))
        if text is None:
            return create_api_base_response(None, err.ERROR_NOT_FOUND)
        body = request.get_json(silent=True) or {}
        summary = get_model_backend().summarize(text, body.get("max_sentences", 3))
        return create_api_base_response({"summary": summary})


@blp.route("/suggest-reply/<int:mail_uid>")
class AgentAISuggestReply(MethodView):
    """Draft a reply suggestion for a mail."""

    def post(self, mail_uid: int) -> ResponseReturnValue:
        """Fetches the mail, suggests a reply ({tone} optional)."""
        guard = require_scope("mail:read")
        if guard is not None:
            return guard

        text = _mail_text(mail_uid, request.args.get("folder", "INBOX"), request.args.get("account_id", "0"))
        if text is None:
            return create_api_base_response(None, err.ERROR_NOT_FOUND)
        body = request.get_json(silent=True) or {}
        suggestion = get_model_backend().suggest_reply(text, body.get("tone", "professional"))
        return create_api_base_response({"suggestion": suggestion})


@blp.route("/nl-search")
class AgentAINlSearch(MethodView):
    """Natural language → structured mail search params."""

    @blp.arguments(AgentNlSearchSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        """Converts {query: 'unread from Alice last week'} to search params."""
        guard = require_scope("mail:read")
        if guard is not None:
            return guard

        structured = get_model_backend().nl_to_search(body["query"])
        return create_api_base_response({"search_params": structured})


# ── Registry ─────────────────────────────────────────────────────────────────

register_action("ai.summarize_mail", "POST", "/api/user/v1/agent/ai/summarize/{mail_uid}",
                "Summarize a mail (fetched server-side)", "mail:read")
register_action("ai.suggest_reply", "POST", "/api/user/v1/agent/ai/suggest-reply/{mail_uid}",
                "Suggest a reply for a mail (fetched server-side)", "mail:read")
register_action("ai.nl_search", "POST", "/api/user/v1/agent/ai/nl-search",
                "Natural language → structured mail search params", "mail:read")
