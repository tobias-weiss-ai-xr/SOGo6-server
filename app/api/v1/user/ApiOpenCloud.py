"""OpenCloud Integration via nubusintercom (#37).

Provides SOGo-side endpoints for:
- Token exchange with nubusintercom
- File browsing via OpenCloud WebDAV
- File selection for compose attachments
- User provisioning in OpenCloud
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.request
from typing import TYPE_CHECKING

from flask import g, request, Response
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import AggravatedException
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User

blp = Blueprint("OpenCloud Integration", __name__, url_prefix="/opencloud")

_INTERCOM_URL = os.getenv("INTERCOM_URL", "http://sogo6-nubusintercom:8100")
_INTERCOM_SECRET = os.getenv("INTERCOM_SHARED_SECRET", "")


def _require_intercom_secret() -> str:
    """Return the intercom shared secret or raise if not configured."""
    if not _INTERCOM_SECRET:
        raise AggravatedException(
            "INTERCOM_SHARED_SECRET is not set. "
            "Set the environment variable to a shared secret known to nubusintercom."
        )
    return _INTERCOM_SECRET


def _sign_payload(payload: dict) -> str:
    """Sign a payload with the shared intercom secret."""
    secret = _require_intercom_secret()
    body = json.dumps(payload, sort_keys=True)
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def _call_intercom(path: str, method: str = "GET", body: dict | None = None, token: str | None = None) -> dict | None:
    """Make an authenticated call to nubusintercom."""
    url = f"{_INTERCOM_URL}{path}"
    headers = {"Content-Type": "application/json"}
    data = None

    if body is not None:
        data = json.dumps(body).encode()
        sig = _sign_payload(body)
        headers["X-Intercom-Signature"] = sig
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read().decode())
    except Exception as e:
        logger_api.warning("Intercom call failed: %s %s → %s", method, url, e)
        return None


class TokenExchangeSchema(Schema):
    scopes = fields.List(fields.String(), load_default=["files.read", "files.write"])


@blp.route("/token/exchange")
class ApiOpenCloudTokenExchange(MethodView):
    """Exchange the current user's session for an intercom token."""

    @blp.arguments(TokenExchangeSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        user: User = g.user
        scopes = body.get("scopes", ["files.read", "files.write"])

        payload = {
            "user_uid": user.uid,
            "scopes": scopes,
            "timestamp": int(time.time()),
        }

        result = _call_intercom("/api/v1/token/exchange", "POST", payload)
        if result:
            return create_api_base_response(result)

        return create_api_base_response(
            error=err.ERROR_INTERCOM_UNREACHABLE,
            error_msg="nubusintercom service unavailable",
        )


class FileBrowseSchema(Schema):
    path = fields.String(load_default="/")
    type = fields.String(load_default="all")


@blp.route("/files/browse")
class ApiOpenCloudFileBrowse(MethodView):
    """Browse OpenCloud files via nubusintercom."""

    def get(self) -> ResponseReturnValue:
        # First get a token, then browse
        user: User = g.user
        token_result = _call_intercom("/api/v1/token/exchange", "POST", {
            "user_uid": user.uid,
            "scopes": ["files.read"],
            "timestamp": int(time.time()),
        })

        if not token_result:
            return create_api_base_response(
                error=err.ERROR_INTERCOM_UNREACHABLE,
                error_msg="Could not obtain intercom token",
            )

        access_token = token_result.get("access_token", "")
        path = request.args.get("path", "/")
        file_type = request.args.get("type", "all")

        browse_url = f"/api/v1/files/browse?path={path}&type={file_type}"
        result = _call_intercom(browse_url, "GET", token=access_token)

        if result:
            return create_api_base_response(result)

        return create_api_base_response(
            error=err.ERROR_INTERCOM_UNREACHABLE,
            error_msg="File browse failed",
        )


class FileSelectSchema(Schema):
    file_path = fields.String(required=True)
    action = fields.String(load_default="attach")


@blp.route("/files/select")
class ApiOpenCloudFileSelect(MethodView):
    """Select a file from OpenCloud for attachment or linking."""

    @blp.arguments(FileSelectSchema)
    def post(self, body: dict) -> ResponseReturnValue:
        user: User = g.user
        token_result = _call_intercom("/api/v1/token/exchange", "POST", {
            "user_uid": user.uid,
            "scopes": ["files.read"],
            "timestamp": int(time.time()),
        })

        if not token_result:
            return create_api_base_response(
                error=err.ERROR_INTERCOM_UNREACHABLE,
                error_msg="Could not obtain intercom token",
            )

        access_token = token_result.get("access_token", "")
        result = _call_intercom("/api/v1/files/select", "POST", body, token=access_token)

        if result:
            return create_api_base_response(result)

        return create_api_base_response(
            error=err.ERROR_INTERCOM_UNREACHABLE,
            error_msg="File select failed",
        )
