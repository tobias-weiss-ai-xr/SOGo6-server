"""Native Mobile App Management (#76) — cross-platform mobile support.

APNS/FCM push registration, device management, 
mobile app config provisioning, and OTA update checking.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time

from flask import request
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.service import sogo_cache
from app.utils import errors as err
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api

blp = Blueprint("Mobile App", __name__, url_prefix="/admin/mobile")

_DEVICE_PFX = "mob_device:"
_PUSH_PFX = "mob_push:"
_CONFIG_PFX = "mob_config:"


def _validate_apns_token(token: str) -> bool:
    """Validate APNS device token format (64 hex chars)."""
    return bool(re.match(r'^[0-9a-fA-F]{64}$', token))


def _validate_fcm_token(token: str) -> bool:
    """Validate FCM registration token format."""
    return len(token) >= 100 and ":" in token  # FCM tokens are long


def _normalize_platform(user_agent: str) -> str:
    """Detect mobile platform from User-Agent."""
    ua = user_agent.lower()
    if "iphone" in ua or "ipad" in ua or "ios" in ua:
        return "ios"
    elif "android" in ua:
        return "android"
    elif "windows phone" in ua:
        return "windows"
    elif "harmonyos" in ua:
        return "harmonyos"
    return "unknown"


def _compute_mobile_config(server_url: str, email: str) -> dict:
    """Generate mobile app provisioning config.
    
    Returns config for IMAP, CalDAV, CardDAV, and SMTP auto-configuration.
    """
    domain = server_url.replace("https://", "").replace("http://", "").split("/")[0]
    return {
        "server_url": server_url,
        "domain": domain,
        "email": email,
        "imap": {
            "host": domain,
            "port": 993,
            "encryption": "SSL/TLS",
            "auth": "password",
        },
        "smtp": {
            "host": domain,
            "port": 587,
            "encryption": "STARTTLS",
            "auth": "password",
        },
        "caldav": {
            "url": f"{server_url}/SOGo/dav/{email}/calendar",
            "principal": f"{email}",
        },
        "carddav": {
            "url": f"{server_url}/SOGo/dav/{email}/contacts",
            "principal": f"{email}",
        },
        "active_sync": {
            "url": f"{server_url}/Microsoft-Server-ActiveSync",
        },
        "jmap": {
            "url": f"{server_url}/jmap",
        },
    }


def _check_app_version(current: str, latest: str) -> dict:
    """Compare app versions (semver-like) and return update info."""
    def parse_ver(v: str) -> tuple[int, ...]:
        parts = re.findall(r'\d+', v)
        return tuple(int(p) for p in parts) if parts else (0, 0, 0)
    current_parts = parse_ver(current)
    latest_parts = parse_ver(latest)
    has_update = latest_parts > current_parts
    return {
        "current_version": current,
        "latest_version": latest,
        "has_update": has_update,
        "update_required": (latest_parts[0] > current_parts[0]) or (latest_parts[1] > current_parts[1] and latest_parts[0] == current_parts[0]),
        "download_url": f"https://apps.sogo.local/download/{latest}" if has_update else None,
    }


@blp.route("/devices")
class MobileDevices(MethodView):
    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        idx = list(cache.get(f"{_DEVICE_PFX}index", list) or [])
        devices = []
        for did in idx:
            raw = cache.get(f"{_DEVICE_PFX}{did}", str)
            if raw:
                devices.append(json.loads(raw))
        devices.sort(key=lambda d: d.get("last_seen", 0), reverse=True)
        return create_api_base_response(data=devices)


@blp.route("/devices/register")
class MobileDeviceRegister(MethodView):
    def post(self) -> ResponseReturnValue:
        body = request.get_json(force=True)
        user_email = body.get("email", "")
        platform = body.get("platform", "")
        app_version = body.get("app_version", "")
        push_token = body.get("push_token", "")
        device_model = body.get("device_model", "")
        os_version = body.get("os_version", "")
        
        if not user_email:
            return create_api_base_response(error_code="E000003", error_msg="email required", success=False)
        
        # Validate push token
        if push_token:
            if platform == "ios" and not _validate_apns_token(push_token):
                return create_api_base_response(error_code="E000020", error_msg="Invalid APNS token", success=False)
            elif platform == "android" and not _validate_fcm_token(push_token):
                return create_api_base_response(error_code="E000021", error_msg="Invalid FCM token", success=False)
        
        cache = sogo_cache()
        device_id = secrets.token_hex(12)
        device = {
            "id": device_id,
            "user_email": user_email,
            "platform": platform,
            "app_version": app_version,
            "device_model": device_model,
            "os_version": os_version,
            "push_token": push_token,
            "push_type": "apns" if platform == "ios" else "fcm" if platform == "android" else "none",
            "last_seen": time.time(),
            "registered_at": time.time(),
            "status": "active",
        }
        cache.set(f"{_DEVICE_PFX}{device_id}", json.dumps(device), ttl=86400 * 365)
        idx = list(cache.get(f"{_DEVICE_PFX}index", list) or [])
        idx.append(device_id)
        cache.set(f"{_DEVICE_PFX}index", idx, ttl=86400 * 365)
        
        # Register push token for notifications
        if push_token:
            push_reg = {
                "device_id": device_id,
                "user_email": user_email,
                "token": push_token,
                "platform": platform,
                "registered_at": time.time(),
            }
            cache.set(f"{_PUSH_PFX}{push_token}", json.dumps(push_reg), ttl=86400 * 365)
        
        # Return provisioning config
        server_url = body.get("server_url", "")
        if server_url:
            device["config"] = _compute_mobile_config(server_url, user_email)
        
        # Check for updates
        if app_version:
            device["update_info"] = _check_app_version(app_version, "2.0.0")
        
        logger_api.info("Mobile device registered: %s (%s, %s)", device_id, platform, device_model)
        return create_api_base_response(data=device)


@blp.route("/devices/<device_id>")
class MobileDeviceDetail(MethodView):
    def get(self, device_id: str) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_DEVICE_PFX}{device_id}", str)
        if not raw:
            return create_api_base_response(error_code="E000002", error_msg="Device not found", success=False)
        return create_api_base_response(data=json.loads(raw))

    def delete(self, device_id: str) -> ResponseReturnValue:
        """Unregister device and remove push token."""
        cache = sogo_cache()
        raw = cache.get(f"{_DEVICE_PFX}{device_id}", str)
        if raw:
            device = json.loads(raw)
            if device.get("push_token"):
                cache.delete(f"{_PUSH_PFX}{device['push_token']}")
        cache.delete(f"{_DEVICE_PFX}{device_id}")
        idx = list(cache.get(f"{_DEVICE_PFX}index", list) or [])
        idx = [d for d in idx if d != device_id]
        cache.set(f"{_DEVICE_PFX}index", idx, ttl=86400 * 365)
        return create_api_base_response(data={"unregistered": device_id})


@blp.route("/devices/<device_id>/ping")
class MobileDevicePing(MethodView):
    def post(self, device_id: str) -> ResponseReturnValue:
        """Keep-alive ping from mobile app."""
        cache = sogo_cache()
        raw = cache.get(f"{_DEVICE_PFX}{device_id}", str)
        if not raw:
            return create_api_base_response(error_code="E000002", error_msg="Device not found", success=False)
        device = json.loads(raw)
        device["last_seen"] = time.time()
        device["status"] = "active"
        cache.set(f"{_DEVICE_PFX}{device_id}", json.dumps(device), ttl=86400 * 365)
        # Check for updates
        update = _check_app_version(device.get("app_version", "1.0.0"), "2.0.0")
        return create_api_base_response(data={"pong": True, "update": update})


@blp.route("/config")
class MobileConfig(MethodView):
    def get(self) -> ResponseReturnValue:
        cache = sogo_cache()
        raw = cache.get(f"{_CONFIG_PFX}app", str)
        config = json.loads(raw) if raw else {
            "app_name": "SOGo Mail",
            "latest_version": "2.0.0",
            "min_version": "1.5.0",
            "server_url": "",
            "theme": "system",
            "biometric_enabled": True,
            "push_enabled": True,
            "features": {
                "calendar": True,
                "contacts": True,
                "mail": True,
                "tasks": True,
                "notes": True,
            },
        }
        return create_api_base_response(data=config)

    def post(self) -> ResponseReturnValue:
        """Update mobile app configuration."""
        body = request.get_json(force=True)
        config = {
            "app_name": body.get("app_name", "SOGo Mail"),
            "latest_version": body.get("latest_version", "2.0.0"),
            "min_version": body.get("min_version", "1.5.0"),
            "server_url": body.get("server_url", ""),
            "theme": body.get("theme", "system"),
            "biometric_enabled": body.get("biometric_enabled", True),
            "push_enabled": body.get("push_enabled", True),
            "features": body.get("features", {"calendar": True, "contacts": True, "mail": True, "tasks": True, "notes": True}),
            "updated_at": time.time(),
        }
        cache = sogo_cache()
        cache.set(f"{_CONFIG_PFX}app", json.dumps(config), ttl=86400 * 365)
        return create_api_base_response(data=config)


@blp.route("/push/broadcast")
class MobilePushBroadcast(MethodView):
    def post(self) -> ResponseReturnValue:
        """Send push notification to all registered devices (or subset).

        Requires a push provider: set ``SOGO_PUSH_PROVIDER`` to ``apns`` or
        ``fcm`` (with the matching credentials — APNS auth key / FCM
        service-account). When unset, the endpoint refuses to claim success
        and reports ``sent: 0`` with a clear reason.
        """
        body = request.get_json(force=True)
        message = body.get("message", "")
        title = body.get("title", "SOGo Notification")
        target_email = body.get("email", "")  # empty = broadcast to all
        platform_filter = body.get("platform", "")  # empty = all platforms
        dry_run = bool(body.get("dry_run", False))

        if not message:
            return create_api_base_response(error_code="E000003", error_msg="message required", success=False)

        cache = sogo_cache()
        idx = list(cache.get(f"{_DEVICE_PFX}index", list) or [])
        devices = []
        for did in idx:
            raw = cache.get(f"{_DEVICE_PFX}{did}", str)
            if not raw:
                continue
            device = json.loads(raw)
            if target_email and device.get("user_email") != target_email:
                continue
            if platform_filter and device.get("platform") != platform_filter:
                continue
            if device.get("push_token"):
                devices.append(device)

        provider = os.environ.get("SOGO_PUSH_PROVIDER", "").lower()
        if provider not in ("apns", "fcm") and not dry_run:
            logger_api.warning(
                "Push broadcast skipped: no provider configured (SOGO_PUSH_PROVIDER=apns|fcm); %d devices matched",
                len(devices),
            )
            return create_api_base_response(
                data={
                    "sent": 0,
                    "matched_devices": len(devices),
                    "title": title,
                    "message": message,
                    "provider": "none",
                    "reason": "push provider not configured (set SOGO_PUSH_PROVIDER=apns or fcm)",
                },
                error_code="S0003B1",
                error_msg="push provider not configured",
                success=False,
                code=503,
            )

        if dry_run:
            return create_api_base_response(data={
                "sent": 0,
                "matched_devices": len(devices),
                "title": title,
                "message": message,
                "dry_run": True,
            })

        # Real provider dispatch (apns2 / firebase-admin) belongs here, wired
        # behind SOGO_PUSH_PROVIDER. Until a client dependency is installed,
        # attempting an actual delivery would silently drop notifications:
        # refuse to do so.
        return create_api_base_response(
            error=err.ERROR_PUSH_PROVIDER_UNSUPPORTED,
            data={"sent": 0, "matched_devices": len(devices)},
        )
