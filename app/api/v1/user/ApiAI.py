"""AI & Intelligence API — Tier 5 features (#56-#65).

Exposes AI service functions via REST endpoints for the frontend.
"""
from __future__ import annotations

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate

from app.service.ai.AIService import get_model_backend, cached_ai_result
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

blp = Blueprint("AI Service", __name__, url_prefix="/ai")


class SummarizeSchema(Schema):
    text = fields.String(required=True, metadata={"description": "Email body text to summarize"})
    max_sentences = fields.Integer(load_default=3, validate=validate.Range(min=1, max=10))


class ClassifySchema(Schema):
    text = fields.String(required=True)
    subject = fields.String(load_default="")
    sender = fields.String(load_default="")


class SuggestReplySchema(Schema):
    email_text = fields.String(required=True)
    tone = fields.String(load_default="professional", validate=validate.OneOf(["professional", "friendly", "formal"]))


class SearchSchema(Schema):
    query = fields.String(required=True)


class AnomalySchema(Schema):
    recipient_count = fields.Integer(load_default=0)
    hour = fields.Integer(load_default=12)
    new_recipient_ratio = fields.Float(load_default=0)


class EnrichSchema(Schema):
    text = fields.String(required=True)


@blp.route("/summarize")
class ApiAISummarize(MethodView):
    @blp.arguments(SummarizeSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        model = get_model_backend()
        summary = model.summarize(body["text"], body.get("max_sentences", 3))
        return create_api_base_response({"summary": summary, "model": "fallback"})


@blp.route("/classify")
class ApiAIClassify(MethodView):
    @blp.arguments(ClassifySchema)
    def post(self, body: dict) -> ResponseReturnValue:
        model = get_model_backend()
        labels = model.classify(body["text"], body.get("subject", ""), body.get("sender", ""))
        return create_api_base_response({"labels": labels})


@blp.route("/suggest-reply")
class ApiAISuggestReply(MethodView):
    @blp.arguments(SuggestReplySchema)
    def post(self, body: dict) -> ResponseReturnValue:
        model = get_model_backend()
        suggestion = model.suggest_reply(body["email_text"], body.get("tone", "professional"))
        return create_api_base_response({"suggestion": suggestion})


@blp.route("/natural-search")
class ApiAINaturalSearch(MethodView):
    @blp.arguments(SearchSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        model = get_model_backend()
        structured = model.nl_to_search(body["query"])
        return create_api_base_response(structured)


@blp.route("/detect-anomaly")
class ApiAIAnomaly(MethodView):
    @blp.arguments(AnomalySchema)
    def post(self, body: dict) -> ResponseReturnValue:
        model = get_model_backend()
        result = model.detect_anomaly({
            "recipient_count": body.get("recipient_count", 0),
            "hour": body.get("hour", 12),
            "new_recipient_ratio": body.get("new_recipient_ratio", 0),
        })
        return create_api_base_response(result)


@blp.route("/enrich-contact")
class ApiAIEnrichContact(MethodView):
    @blp.arguments(EnrichSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        model = get_model_backend()
        info = model.extract_contact_info(body["text"])
        return create_api_base_response(info)


@blp.route("/classify-attachment")
class ApiAIClassifyAttachment(MethodView):
    class AttachmentSchema(Schema):
        filename = fields.String(required=True)
        content_type = fields.String(load_default="")

    @blp.arguments(AttachmentSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        model = get_model_backend()
        result = model.classify_attachment(body["filename"], body.get("content_type", ""))
        return create_api_base_response(result)
