"""ActiveSync (EAS) Protocol Support (#75) — mobile sync against the real store.

Exchange ActiveSync 16.1 protocol endpoints: Provision, FolderSync, Sync,
Ping, GetAttachment and SendMail.

- Wire format is real WBXML 1.3 (application/vnd.ms-sync.wbxml) produced by
  the Wbxml encoder — no JSON masquerading as WBXML.
- Folder hierarchies and message data come from the configured IMAP store via
  ActiveSyncGateway; SendMail delivers through the account's SMTP client.
- Sync is a real change log: the persisted sync state holds the actual UID
  set of each collection and responses carry Add/Delete deltas against it.
- When the request context has no mail account configuration, commands fail
  honestly (EAS status 6/7 "server failure") instead of inventing folders.

EAS status codes used: 1 success; 6/7 server failure; 9 sync key invalid.
"""
from __future__ import annotations

import base64
import json
import secrets
import time
from email import message_from_bytes

from flask import g, request, Response
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.service import sogo_cache
from app.service.activesync.ActiveSyncGateway import ActiveSyncGateway
from app.service.activesync.Wbxml import (
    WbxmlDecoder,
    WbxmlEncoder,
    WbxmlTag,
    group,
    leaf,
    opaque_node,
)
from app.utils import constants as cs
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api

blp = Blueprint("ActiveSync", __name__, url_prefix="/Microsoft-Server-ActiveSync")

_EAS_PFX = "eas:"
_EAS_POLICY_PFX = "eas_policy:"
_EAS_FOLDER_PFX = "eas_folder:"

EAS_VERSION = "16.1"
WBXML_CONTENT_TYPE = "application/vnd.ms-sync.wbxml"

# EAS devices send WBXML bodies and SendMail a raw RFC5322 stream; the API
# middleware only allows application/json by default, so these routes opt out
# and parse their own request representations.
_EAS_ACCEPTED_TYPES = {
    "application/vnd.ms-sync.wbxml",
    "application/json",
    "application/octet-stream",
    "text/plain",
    "application/x-www-form-urlencoded",
}

# EAS policy templates (real policy document values)
EAS_POLICIES = {
    "basic": {
        "AllowExternalDeviceManagement": False,
        "MaxInactivityTimeDeviceLock": "00:15:00",
        "DevicePasswordEnabled": True,
        "MinDevicePasswordLength": 4,
        "MaxDevicePasswordFailedAttempts": 5,
        "MaxAttachmentSize": 5242880,  # 5MB
        "RequireStorageCardEncryption": False,
        "RequireEncryption": True,
        "AllowSimpleDevicePassword": False,
        "PasswordRecoveryEnabled": False,
    },
    "strict": {
        "AllowExternalDeviceManagement": True,
        "MaxInactivityTimeDeviceLock": "00:05:00",
        "DevicePasswordEnabled": True,
        "MinDevicePasswordLength": 8,
        "AlphanumericDevicePasswordRequired": True,
        "MaxDevicePasswordFailedAttempts": 3,
        "MaxAttachmentSize": 10485760,  # 10MB
        "RequireStorageCardEncryption": True,
        "RequireEncryption": True,
        "AllowSimpleDevicePassword": False,
        "PasswordRecoveryEnabled": False,
        "RequireSignedSMIMEMessages": True,
        "RequireEncryptedSMIMEMessages": True,
    },
}


# ---------------------------------------------------------------------------- #
# context / helpers
# ---------------------------------------------------------------------------- #

def _gateway() -> ActiveSyncGateway | None:
    """Build the gateway when the request context has a real mail config."""
    try:
        if not getattr(g, "user_domain_settings", None) or not getattr(g, "process_settings", None):
            return None
        user = getattr(g, "user", None)
        if user is None or getattr(user, "anonymous", True):
            return None
        return ActiveSyncGateway(g.process_settings, g.user_domain_settings, user)
    except Exception:
        logger_api.debug("ActiveSync gateway unavailable (no mail context)", exc_info=True)
        return None


def _wbxml_response(root: WbxmlTag, status: int = 200) -> Response:
    response = Response(WbxmlEncoder.encode(root), status=status, content_type=WBXML_CONTENT_TYPE)
    response.headers["MS-ASProtocolVersion"] = EAS_VERSION
    return response


def _request_tree() -> list | dict:
    """Decode a request body: real WBXML when the client sent WBXML, JSON fallback."""
    if request.mimetype and "wbxml" in request.mimetype:
        try:
            return WbxmlDecoder.decode(request.get_data())
        except Exception as exc:
            logger_api.warning("EAS WBXML request parse failed: %s", exc)
            return {}
    return request.get_json(silent=True, force=True) or {}


def _child_text(tree, name: str) -> str | None:
    """Pull the text of the first element `name` from a decoded WBXML tree."""
    for node, payload in tree or []:
        if node == name:
            if isinstance(payload, str):
                return payload
            for inner, p in payload or []:
                if inner == "$text":
                    return p
    return None


def _server_id(folder_path: str) -> str:
    """Stable EAS ServerId for a folder path (base64url, prefixed)."""
    return base64.urlsafe_b64encode(("f:" + folder_path).encode("utf-8")).decode("ascii")


def _folder_from_server_id(server_id: str) -> str | None:
    try:
        raw = base64.urlsafe_b64decode(server_id.encode("ascii")).decode("utf-8")
    except Exception:
        return None
    if not raw.startswith("f:"):
        return None
    return raw[2:]


def _attachment_id(folder: str, uid: str, index: int) -> str:
    return base64.urlsafe_b64encode(f"att:{folder}\x00{uid}\x00{index}".encode("utf-8")).decode("ascii")


def _device_id() -> str:
    return request.headers.get("X-MS-DeviceID", request.headers.get("User-Agent", "unknown"))


def _policy_compliant(device_id: str, policy_key: str) -> bool:
    if not policy_key:
        return False
    cache = sogo_cache()
    raw = cache.get(f"{_EAS_POLICY_PFX}{device_id}", str)
    if not raw:
        return False
    try:
        stored = json.loads(raw)
    except Exception:
        return False
    return stored.get("policy_key") == policy_key and stored.get("status") == "provisioned"


def _mail_uids(gateway: ActiveSyncGateway, account_id: str, folder: str) -> list[str]:
    """All real UIDs of a folder (paginated)."""
    uids: list[str] = []
    offset = 0
    page_size = 500
    while True:
        rows, total = gateway.get_folder_mails(account_id, folder, limit=page_size, offset=offset)
        uids.extend(str(row.get("uid", "")) for row in rows if row.get("uid") is not None)
        if len(uids) >= total or not rows:
            break
        offset += page_size
    return uids


def _folder_rows(gateway: ActiveSyncGateway, account_id: str) -> list[dict]:
    try:
        return gateway.list_mailbox_rows(account_id)
    except RequestException as exc:
        logger_api.warning("EAS folder list failed: %s", exc)
        return []


# ---------------------------------------------------------------------------- #
# Provision
# ---------------------------------------------------------------------------- #

@blp.route("/Provision")
class EasProvision(MethodView):
    accepted_content_types = _EAS_ACCEPTED_TYPES

    def post(self) -> ResponseReturnValue:
        """EAS Provision: issue a real policy key bound to the device."""
        device_id = _device_id()
        body = _request_tree()
        policy_name = _child_text(body, "PolicyType") if isinstance(body, list) else None
        if not policy_name:
            policy_name = (body.get("PolicyType") if isinstance(body, dict) else None) or "basic"
        policy_name = policy_name if policy_name in EAS_POLICIES else "basic"

        policy_key = secrets.token_hex(8)
        cache = sogo_cache()
        cache.set(f"{_EAS_POLICY_PFX}{device_id}", json.dumps({
            "device_id": device_id,
            "policy_key": policy_key,
            "policy_name": policy_name,
            "policy": EAS_POLICIES[policy_name],
            "status": "provisioned",
            "provisioned_at": time.time(),
        }), ttl=86400 * 365)
        logger_api.info("EAS device provisioned: %s (policy=%s)", device_id, policy_name)

        return _wbxml_response(group("Provision", "Provision", [
            leaf("Provision", "Status", 1),
            group("Provision", "Policies", [
                group("Provision", "Policy", [
                    leaf("Provision", "PolicyType", policy_name),
                    leaf("Provision", "PolicyKey", policy_key),
                    leaf("Provision", "Status", 1),
                ]),
            ]),
        ]))


# ---------------------------------------------------------------------------- #
# FolderSync
# ---------------------------------------------------------------------------- #

@blp.route("/FolderSync")
class EasFolderSync(MethodView):
    accepted_content_types = _EAS_ACCEPTED_TYPES

    def post(self) -> ResponseReturnValue:
        """EAS FolderSync: real store folder hierarchy."""
        device_id = _device_id()
        gateway = _gateway()
        body = _request_tree()
        sync_key = _child_text(body, "SyncKey") if isinstance(body, list) else None
        if sync_key is None:
            sync_key = (body.get("SyncKey") if isinstance(body, dict) else None) or "0"

        cache = sogo_cache()
        raw_state = cache.get(f"{_EAS_FOLDER_PFX}{device_id}", str)
        try:
            state = json.loads(raw_state) if raw_state else {}
        except Exception:
            state = {}

        if gateway is None:
            return _wbxml_response(group("FolderHierarchy", "FolderSync", [
                leaf("AirSync", "Status", 6),
            ]))

        folders = []
        for row in _folder_rows(gateway, _account_id()):
            path = row.get(cs.FOLDER_PATH, "") or ""
            name = row.get(cs.FOLDER_NAME, path) or path
            parent = path.rsplit(".", 1)[0] if "." in path else ""
            folders.append({
                "ServerId": _server_id(path),
                "ParentId": _server_id(parent) if parent else "0",
                "DisplayName": name,
                "Type": ActiveSyncGateway.eas_folder_type(row.get(cs.FOLDER_TYPE), path, name),
            })

        if sync_key != "0" and raw_state and state.get("sync_key") != sync_key:
            return _wbxml_response(group("FolderHierarchy", "FolderSync", [
                leaf("AirSync", "Status", 9),  # invalid sync key
            ]))

        new_key = secrets.token_hex(8)
        cache.set(f"{_EAS_FOLDER_PFX}{device_id}", json.dumps({
            "sync_key": new_key,
            "folders": folders,
        }), ttl=86400)

        add_nodes = [
            group("FolderHierarchy", "Folder", [
                leaf("FolderHierarchy", "ServerId", f["ServerId"]),
                leaf("FolderHierarchy", "ParentId", f["ParentId"]),
                leaf("FolderHierarchy", "DisplayName", f["DisplayName"]),
                leaf("FolderHierarchy", "Type", f["Type"]),
            ])
            for f in folders
        ]
        return _wbxml_response(group("FolderHierarchy", "FolderSync", [
            leaf("FolderHierarchy", "SyncKey", new_key),
            leaf("AirSync", "Status", 1),
            group("FolderHierarchy", "Changes", [
                leaf("FolderHierarchy", "Count", len(folders)),
                group("FolderHierarchy", "Add", add_nodes),
            ]),
        ]))


# ---------------------------------------------------------------------------- #
# Sync
# ---------------------------------------------------------------------------- #

def _account_id() -> str:
    return request.args.get("accountId") or getattr(getattr(g, "user", None), "uid", "default")


@blp.route("/Sync")
class EasSync(MethodView):
    accepted_content_types = _EAS_ACCEPTED_TYPES

    def post(self) -> ResponseReturnValue:
        """EAS Sync: real change log against the store UID set."""
        device_id = _device_id()
        policy_key = request.headers.get("MS-ASPolicyKey", "")
        if not _policy_compliant(device_id, policy_key):
            return _wbxml_response(group("AirSync", "Sync", [
                leaf("AirSync", "Status", 449),
            ]))

        gateway = _gateway()
        body = _request_tree()
        sync_key = _child_text(body, "SyncKey") if isinstance(body, list) else None
        if sync_key is None:
            sync_key = (body.get("SyncKey") if isinstance(body, dict) else None) or "0"
        collection = _child_text(body, "CollectionId") if isinstance(body, list) else None
        if collection is None:
            collection = (body.get("CollectionId") if isinstance(body, dict) else None) or "inbox"
        window = 100
        if isinstance(body, list):
            for node, payload in body:
                if node == "Collection" and isinstance(payload, list):
                    for inner, p in payload:
                        if inner == "Options" and isinstance(p, list):
                            for o, op in p:
                                if o == "WindowSize":
                                    window = int(op) if str(op).isdigit() else 100
        elif isinstance(body, dict):
            window = int((body.get("Options") or {}).get("WindowSize", 100) or 100)

        if gateway is None:
            return _wbxml_response(group("AirSync", "Sync", [
                leaf("AirSync", "Status", 7),  # server failure
            ]))

        cache = sogo_cache()
        state_key = f"{_EAS_PFX}sync:{device_id}:{collection}"
        raw = cache.get(state_key, str)
        try:
            state = json.loads(raw) if raw else {}
        except Exception:
            state = {}

        if sync_key != "0" and raw and state.get("sync_key") != sync_key:
            return _wbxml_response(group("AirSync", "Sync", [
                leaf("AirSync", "Status", 9),  # invalid sync key
            ]))

        try:
            current = _mail_uids(gateway, _account_id(), collection)
        except RequestException as exc:
            logger_api.warning("EAS sync failed for %s: %s", collection, exc)
            return _wbxml_response(group("AirSync", "Sync", [
                leaf("AirSync", "Status", 7),
            ]))

        previous = state.get("uids", [])
        if sync_key == "0" or not previous:
            added = current
            deleted: list[str] = []
        else:
            added = [u for u in current if u not in previous]
            deleted = [u for u in previous if u not in current]

        added = added[: max(window, 1)]
        new_key = secrets.token_hex(8)
        cache.set(state_key, json.dumps({
            "sync_key": new_key,
            "uids": current,
            "last_sync": time.time(),
        }), ttl=86400)

        commands: list[WbxmlTag] = []
        for uid in added:
            try:
                raw_mime = gateway.get_mail_raw(_account_id(), collection, uid)
                detail = gateway.get_mail_detail(_account_id(), collection, uid)
            except RequestException:
                continue
            commands.append(group("AirSync", "Add", [
                leaf("AirSync", "ServerId", uid),
                group("AirSync", "ApplicationData", [
                    leaf("Email", "From", (detail.get("from_") or {}).get("mail") or ""),
                    leaf("Email", "To", ", ".join(a.get("email", "") for a in (detail.get("to") or []))),
                    leaf("Email", "Subject", detail.get("subject") or ""),
                    leaf("Email", "DateReceived", detail.get("date") or ""),
                    group("AirSyncBase", "Body", [
                        leaf("AirSyncBase", "Type", 1),
                        opaque_node("AirSyncBase", "Data", raw_mime),
                    ]),
                ]),
            ]))
        for uid in deleted:
            commands.append(group("AirSync", "Delete", [
                leaf("AirSync", "ServerId", uid),
            ]))

        return _wbxml_response(group("AirSync", "Sync", [
            leaf("AirSync", "Status", 1),
            leaf("AirSync", "SyncKey", new_key),
            group("AirSync", "Collection", [
                leaf("AirSync", "CollectionId", collection),
                leaf("AirSync", "Status", 1),
                leaf("AirSync", "SyncKey", new_key),
                group("AirSync", "Commands", commands),
            ]),
        ]))


# ---------------------------------------------------------------------------- #
# Ping
# ---------------------------------------------------------------------------- #

@blp.route("/Ping")
class EasPing(MethodView):
    accepted_content_types = _EAS_ACCEPTED_TYPES

    def post(self) -> ResponseReturnValue:
        """EAS Ping: report real folder changes since the last sync state."""
        device_id = _device_id()
        gateway = _gateway()
        body = _request_tree()
        heartbeat = request.headers.get("MS-ASHeartbeatInterval", "300")
        try:
            heartbeat = max(30, min(int(heartbeat), 3600))
        except ValueError:
            heartbeat = 300

        folders: list[str] = []
        if isinstance(body, list):
            for node, payload in body:
                if node == "Folders" and isinstance(payload, list):
                    for inner, p in payload:
                        if inner == "Folder" and isinstance(p, list):
                            for o, op in p:
                                if o == "Id":
                                    folders.append(str(op))
        elif isinstance(body, dict):
            for f in (body.get("Folders") or {}).get("Folder", []):
                folders.append(str(f.get("Id", "")))

        if gateway is None:
            return _wbxml_response(group("Ping", "Ping", [
                leaf("Ping", "Status", 2),
                group("Ping", "Folders", [group("Ping", "Folder", [
                    leaf("Ping", "Id", fid),
                ]) for fid in folders]),
            ]))

        cache = sogo_cache()
        changed = []
        for fid in folders:
            collection = _folder_from_server_id(fid) or fid
            try:
                current = _mail_uids(gateway, _account_id(), collection)
            except RequestException:
                continue
            raw = cache.get(f"{_EAS_PFX}sync:{device_id}:{collection}", str)
            try:
                state = json.loads(raw) if raw else {}
            except Exception:
                state = {}
            if not state.get("uids") or set(current) != set(state.get("uids", [])):
                changed.append(fid)

        status = 2 if changed else 1
        return _wbxml_response(group("Ping", "Ping", [
            leaf("Ping", "Status", status),
            leaf("Ping", "HeartbeatInterval", heartbeat),
            group("Ping", "Folders", [group("Ping", "Folder", [
                leaf("Ping", "Id", fid),
            ]) for fid in (changed or folders)]),
        ]))


# ---------------------------------------------------------------------------- #
# GetAttachment
# ---------------------------------------------------------------------------- #

@blp.route("/GetAttachment")
class EasGetAttachment(MethodView):
    def get(self) -> ResponseReturnValue:
        """EAS GetAttachment: real attachment bytes extracted from the raw mail."""
        gateway = _gateway()
        attachment_id = request.args.get("AttachmentId", "") or request.args.get("attachmentId", "")
        if not attachment_id or gateway is None:
            return Response(b"", status=404)

        try:
            raw = base64.urlsafe_b64decode(attachment_id.encode("ascii")).decode("utf-8")
            if not raw.startswith("att:"):
                return Response(b"", status=404)
            folder, uid, index = raw[4:].split("\x00", 2)
            index = int(index)
        except Exception:
            return Response(b"", status=404)

        try:
            raw_mail = gateway.get_mail_raw(_account_id(), folder, uid)
        except RequestException:
            return Response(b"", status=404)

        parts = list(message_from_bytes(raw_mail.encode("utf-8")).walk())
        if index >= len(parts):
            return Response(b"", status=404)
        part = parts[index]
        payload = part.get_payload(decode=True) or b""
        filename = part.get_filename() or f"attachment-{index}"
        response = Response(payload, content_type=part.get_content_type() or "application/octet-stream")
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


# ---------------------------------------------------------------------------- #
# SendMail
# ---------------------------------------------------------------------------- #

@blp.route("/SendMail")
class EasSendMail(MethodView):
    accepted_content_types = _EAS_ACCEPTED_TYPES

    def post(self) -> ResponseReturnValue:
        """EAS SendMail: the request body is the RFC5322 message — send it."""
        gateway = _gateway()
        if gateway is None:
            return Response(b"", status=500)  # EAS smart-fail
        raw = request.get_data()
        if not raw:
            return Response(b"", status=500)
        try:
            message = message_from_bytes(raw)
            gateway.send_message(_account_id(), message)
        except RequestException as exc:
            logger_api.warning("EAS SendMail failed: %s", exc)
            return Response(b"", status=500)
        logger_api.info("EAS SendMail delivered (%s bytes)", len(raw))
        return Response(b"", status=200)


# ---------------------------------------------------------------------------- #
# Settings / status
# ---------------------------------------------------------------------------- #

@blp.route("/Settings")
class EasSettings(MethodView):
    accepted_content_types = _EAS_ACCEPTED_TYPES

    def post(self) -> ResponseReturnValue:
        """EAS Settings: acknowledge settings read/write."""
        return _wbxml_response(group("Settings", "Settings", [
            leaf("Settings", "Status", 1),
        ]))


@blp.route("")
class EasRoot(MethodView):
    def options(self) -> ResponseReturnValue:
        """OPTIONS response for ActiveSync autodiscovery."""
        return Response(
            headers={
                "MS-ASProtocolVersions": "14.0,14.1,16.0,16.1",
                "MS-ASProtocolCommands": "Sync,SendMail,GetAttachment,FolderSync,Provision,Ping,Settings",
                "MS-ASEmailPolicy": "Basic,Strict",
            },
        )


@blp.route("/status")
class EasStatus(MethodView):
    def get(self) -> ResponseReturnValue:
        """Admin endpoint: ActiveSync server status."""
        cache = sogo_cache()
        keys = []
        try:
            keys = cache.redis.keys(f"{_EAS_POLICY_PFX}*")
        except Exception:
            keys = []
        return create_api_base_response(data={
            "enabled": True,
            "protocol_version": EAS_VERSION,
            "wire_format": "wbxml-1.3",
            "provisioned_devices": len(keys),
            "supported_commands": ["Sync", "SendMail", "GetAttachment", "FolderSync", "Provision", "Ping", "Settings"],
            "policies": list(EAS_POLICIES.keys()),
        })

