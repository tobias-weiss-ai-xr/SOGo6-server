"""Schemas for the Agent Action Layer facade (compact, token-efficient)."""
from marshmallow import Schema, fields, validate

from app.utils.api.ApiBaseResponse import ApiBaseResponse


SNIPPET_MAX_CHARS = 200


class AgentMailSummarySchema(Schema):
    """Compact mail summary — one line of context per message."""

    uid = fields.Raw(metadata={"description": "IMAP UID of the mail (use with /agent/mail/messages/{uid})"})
    from_ = fields.Raw(data_key="from", metadata={"description": "Sender {name, email}"})
    subject = fields.String(allow_none=True)
    date = fields.Raw(allow_none=True)
    snippet = fields.String(metadata={"description": f"First {SNIPPET_MAX_CHARS} chars of the text body"})
    seen = fields.Boolean()
    flagged = fields.Boolean()
    has_attachment = fields.Boolean(data_key="has_attachments")


class AgentMailListResponseSchema(ApiBaseResponse):
    data = fields.Dict(required=False, allow_none=True, metadata={
        "description": "{total, folder, messages: [AgentMailSummary]}"
    })


class AgentMailDetailQuerySchema(Schema):
    strip_quotes = fields.Boolean(load_default=False, metadata={
        "description": "Drop quoted reply lines (lines starting with '>') from text bodies"})
    max_chars = fields.Integer(load_default=4000, validate=validate.Range(min=100, max=50000), metadata={
        "description": "Truncate each text body to this many characters"})


class AgentMailSendSchema(Schema):
    """One-call mail send: recipients + body + inline base64 attachments."""

    from_addr = fields.Email(load_default=None, allow_none=True, data_key="from",
                             metadata={"description": "Sender address; defaults to the token user's address"})
    to = fields.List(fields.Email(), required=True, validate=validate.Length(min=1))
    cc = fields.List(fields.Email(), load_default=list)
    bcc = fields.List(fields.Email(), load_default=list)
    subject = fields.String(load_default="")
    body = fields.String(load_default="")
    is_html = fields.Boolean(load_default=False)
    reply_to = fields.String(load_default=None, allow_none=True)
    attachments = fields.List(fields.Dict(), load_default=list, metadata={
        "description": "Inline attachments: [{filename, content_b64, content_type?}]"})
    send_at = fields.String(load_default=None, allow_none=True, metadata={
        "description": "ISO 8601 datetime for scheduled delivery (optional)"})


class AgentMailBatchActionSchema(Schema):
    action = fields.String(required=True, validate=validate.OneOf([
        'delete', 'move', 'spam', 'ham', 'tag', 'untag', 'copy',
        'mark_read', 'mark_unread', 'mark_flagged', 'mark_unflagged']))
    mail_uids = fields.List(fields.Integer(), required=True)
    data = fields.Raw(required=False, allow_none=True, metadata={
        "description": "Action payload, e.g. target folder for move/copy"})


class AgentNlSearchSchema(Schema):
    query = fields.String(required=True, metadata={"description": "Natural language search, e.g. 'unread mails from Alice last week'"})


class AgentManifestResponseSchema(ApiBaseResponse):
    data = fields.Dict(required=False, allow_none=True, metadata={
        "description": "{version, actions: [{id, method, path, description, scope}]}"})
