"""Real per-user quota usage — no hardcoded zeros.

Previously the quota API reported ``mailbox_used_mb=0.0``, ``calendar_used=0``
and ``contact_used=0`` with a comment reading *"In production this would query
actual storage"* — i.e. fabricated usage. This service reports what actually
happened:

* **calendar** — real count of the user's calendars via ``ModuleCalendar``
  (the app's real calendar storage).
* **contact** — real total of the user's contacts via ``ModuleContact``.
* **mailbox** — real IMAP ``STATUS (MESSAGES SIZE)`` probe over the app's own
  ``ClientImap``, summing bytes across every selectable folder. Requires
  probe credentials in the environment (``SOGO_QUOTA_IMAP_*``); without them
  the status is honestly ``not_configured`` — never a fabricated 0.

Each probe returns ``{"status", "used", "error?"}`` where ``used=None`` means
"unknown", not "zero". Over-quota is computed from real usage vs the recorded
limits only — an unknown usage never claims compliance. The limits themselves
are the admin's record; enforcement inside the mail server is that server's
own configuration and outside this app's scope.
"""
from __future__ import annotations

import os
import re
from typing import Any, Callable

from app.utils import constants as cs

_STATUS_OK = "completed"
_STATUS_NOT_CONFIGURED = "not_configured"
_STATUS_UNREACHABLE = "unreachable"
_STATUS_ERROR = "error"

_SIZE_RE = re.compile(r"SIZE\s+(\d+)", re.IGNORECASE)


class QuotaUsageService:
    """Probe real usage for one user and compare it against their limits."""

    def __init__(
        self,
        user_uid: str,
        limits: dict[str, int] | None = None,
        process_settings: Any | None = None,
        calendar_probe: Callable[[], dict] | None = None,
        contact_probe: Callable[[], dict] | None = None,
        mailbox_probe: Callable[[], dict] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.uid = user_uid
        self.limits = limits or {}
        self.process_settings = process_settings
        self.env = env if env is not None else dict(os.environ)
        self.calendar_probe: Callable[[], dict] = calendar_probe or self._calendar_usage
        self.contact_probe: Callable[[], dict] = contact_probe or self._contact_usage
        self.mailbox_probe: Callable[[], dict] = mailbox_probe or self._mailbox_usage

    # ------------------------------------------------------------------ #
    def usage(self) -> dict:
        """Real usage + computed over-quota flags (None usage never claims)."""
        calendar = self.calendar_probe()
        contact = self.contact_probe()
        mailbox = self.mailbox_probe()

        used = {
            "calendar_count": calendar.get("used"),
            "contact_count": contact.get("used"),
            "mailbox_used_mb": mailbox.get("used"),
        }
        over_limits: list[str] = []
        for name, limit, current in (
            ("calendar_count", self.limits.get("calendar_count"), used["calendar_count"]),
            ("contact_count", self.limits.get("contact_count"), used["contact_count"]),
            ("mailbox_size_mb", self.limits.get("mailbox_size_mb"), used["mailbox_used_mb"]),
        ):
            if limit and current is not None and current > limit:
                over_limits.append(name)

        return {
            "used": used,
            "sources": {"calendar": calendar, "contact": contact, "mailbox": mailbox},
            "over_quota": bool(over_limits),
            "over_limits": over_limits,
        }

    # ------------------------------------------------------------------ #
    # Real probes
    # ------------------------------------------------------------------ #
    def _calendar_usage(self) -> dict:
        """Count the user's calendars through the real calendar module."""
        if self.process_settings is None:
            return {
                "status": _STATUS_UNREACHABLE, "used": None,
                "error": "process settings unavailable (no calendar storage reachable)",
            }
        try:
            from app.module.calendar.ModuleCalendar import ModuleCalendar
            from app.auth.User import User

            module = ModuleCalendar(self.process_settings)
            calendars = module.get_all_calendars(User(uid=self.uid))
            return {"status": _STATUS_OK, "used": len(calendars)}
        except Exception as exc:  # pylint: disable=broad-except
            return {"status": _STATUS_ERROR, "used": None, "error": str(exc)[:200]}

    def _contact_usage(self) -> dict:
        """Count the user's contacts across all their address books (real)."""
        if self.process_settings is None:
            return {
                "status": _STATUS_UNREACHABLE, "used": None,
                "error": "process settings unavailable (no contact storage reachable)",
            }
        try:
            from app.module.contact.ModuleContact import ModuleContact
            from app.auth.User import User

            module = ModuleContact(self.process_settings)
            _, total = module.get_contacts(
                User(uid=self.uid),
                addressbook_key=None, search=None, offset=0, limit=0,
                resolve_ab=False, resolve_images=False,
            )
            return {"status": _STATUS_OK, "used": total}
        except Exception as exc:  # pylint: disable=broad-except
            return {"status": _STATUS_ERROR, "used": None, "error": str(exc)[:200]}

    def _mailbox_usage(self) -> dict:
        """Real IMAP mailbox size via the app's own ClientImap + STATUS SIZE.

        Requires SOGO_QUOTA_IMAP_HOST / SOGO_QUOTA_IMAP_USER / SOGO_QUOTA_IMAP_PASS
        (optionally SOGO_QUOTA_IMAP_PORT, _ENCRYPTION, _AUTH_MECH). Without
        credentials the status is honestly ``not_configured``.
        """
        host = self.env.get("SOGO_QUOTA_IMAP_HOST")
        user = self.env.get("SOGO_QUOTA_IMAP_USER")
        password = self.env.get("SOGO_QUOTA_IMAP_PASS")
        if not (host and user and password):
            return {
                "status": _STATUS_NOT_CONFIGURED, "used": None,
                "error": "mailbox probe not configured — set SOGO_QUOTA_IMAP_HOST/USER/PASS",
            }
        try:
            port = int(self.env.get("SOGO_QUOTA_IMAP_PORT", "143"))
            encryption = self.env.get("SOGO_QUOTA_IMAP_ENCRYPTION", cs.SOCKET_ENC_PLAIN)
            if encryption not in cs.SOCK_ENC_LIST:
                encryption = cs.SOCKET_ENC_PLAIN
            auth_mech = self.env.get("SOGO_QUOTA_IMAP_AUTH_MECH", "LOGIN")

            from app.manager.mail.ClientImap import ClientImap

            client = ClientImap(
                server=host, port=port, encryption=encryption,
                auth_mech=auth_mech, folders_map={"inbox": "INBOX"},
            )
            try:
                client.connect()
                client.login(user, password)
                total_bytes = 0
                counted_folders = 0
                for folder in client.list_folders():
                    if not folder.get("can_be_select", True):
                        continue
                    typ, data = client.connection.status(folder.get("path", ""), "(MESSAGES SIZE)")  # type: ignore[union-attr]
                    match = _SIZE_RE.search(str(data))
                    if not match:
                        return {
                            "status": _STATUS_ERROR, "used": None,
                            "error": f"IMAP server lacks STATUS SIZE support on {folder.get('path')}",
                        }
                    total_bytes += int(match.group(1))
                    counted_folders += 1
                return {
                    "status": _STATUS_OK,
                    "used": round(total_bytes / 1048576.0, 3),
                    "bytes": total_bytes,
                    "folders": counted_folders,
                }
            finally:
                if client.connection is not None:
                    try:
                        client.connection.logout()
                    except Exception:  # pylint: disable=broad-except
                        pass
        except Exception as exc:  # pylint: disable=broad-except
            return {"status": _STATUS_ERROR, "used": None, "error": str(exc)[:200]}