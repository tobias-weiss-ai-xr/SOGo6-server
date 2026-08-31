"""Interface for the unified Global Quick Search (Cmd+K).

Aggregates results from the contact, calendar and user-source modules into a
single response so the frontend command palette can show everything at once.
Mail search is intentionally NOT included here: it is per-account and IMAP
backed (the frontend calls the existing ``/mailboxes/<account>/search``
endpoint for the active account).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from app.module.calendar.model.CalendarUser import CalendarUser
from app.module.calendar.ModuleCalendar import ModuleCalendar
from app.module.contact.ModuleContact import ModuleContact
from app.module.admin.ModuleAdminUser import ModuleAdminUser
from app.service import sogo_cache
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.config.settings.ProcessSetting import ProcessSetting
    from app.auth.User import User

# Cap per-section results so the palette stays snappy.
_GLOBAL_SEARCH_LIMIT: int = 8
# Search calendar events within this rolling window from now.
_GLOBAL_SEARCH_LOOKAHEAD_DAYS: int = 365


class InterfaceApiGlobalSearch:
    """Unified search across contacts, calendar events and users."""

    def __init__(
        self, process_setting: ProcessSetting, user_domain_settings: dict, user: User,
    ) -> None:
        self.process_setting = process_setting
        self.user = user
        self.domain_settings = user_domain_settings
        self.contact_module = ModuleContact(process_setting, cache=sogo_cache())
        self.calendar_module = ModuleCalendar(process_setting, cache=sogo_cache())
        self.user_module = ModuleAdminUser(process_setting)

    def global_search(self, query: str, limit: int | None = None) -> tuple[dict[str, Any], int]:
        """Run a unified search and return grouped results.

        :param query: Free-text query (already validated by the API schema).
        :param limit: Max results per section (from the request, default 8).
        :return: (response, status_code) with ``data.contacts``,
            ``data.events`` and ``data.users`` arrays.
        """
        per_section = limit if limit and limit > 0 else _GLOBAL_SEARCH_LIMIT
        query = query.strip()
        if len(query) < 2:
            return create_api_base_response({
                "contacts": [], "events": [], "users": [],
            })

        contacts, events, users = [], [], []
        try:
            contacts = self._search_contacts(query, per_section)
        except (RequestException, Exception) as exc:  # noqa: BLE001
            logger_api.warning("Global search: contacts failed for %s: %s", self.user.uid, repr(exc))
        try:
            events = self._search_events(query, per_section)
        except (RequestException, Exception) as exc:  # noqa: BLE001
            logger_api.warning("Global search: events failed for %s: %s", self.user.uid, repr(exc))
        try:
            users = self._search_users(query, per_section)
        except (RequestException, Exception) as exc:  # noqa: BLE001
            logger_api.warning("Global search: users failed for %s: %s", self.user.uid, repr(exc))

        return create_api_base_response({
            "contacts": contacts,
            "events": events,
            "users": users,
        })

    # ── Section searches ───────────────────────────────────────────────

    def _search_contacts(self, query: str, limit: int) -> list[dict[str, Any]]:
        contacts, _ = self.contact_module.get_contacts(
            self.user, search=query, limit=limit, resolve_images=False,
        )
        return [
            {
                "key": c.key,
                "addressbook_key": c.addressbook_key,
                "fullname": getattr(c, "fullname", "") or "",
                "email": (getattr(c, "emails", None) or [None])[0] or "",
            }
            for c in contacts
        ]

    def _search_events(self, query: str, limit: int) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=_GLOBAL_SEARCH_LOOKAHEAD_DAYS)
        calendar_user = CalendarUser(user=self.user, owner=self.user)
        events = self.calendar_module.get_all_events(
            calendar_user, start=now, end=end, search=query,
        )
        events = events[:limit]
        return [
            {
                "key": getattr(e, "key", "") or "",
                "calendar_key": getattr(e, "calendar_key", "") or "",
                "title": getattr(e, "title", "") or "",
                "date_start": (
                    e.require_date_start.isoformat()
                    if getattr(e, "require_date_start", None) else None
                ),
                "date_end": (
                    e.require_date_end.isoformat()
                    if getattr(e, "require_date_end", None) else None
                ),
            }
            for e in events
        ]

    def _search_users(self, query: str, limit: int) -> list[dict[str, Any]]:
        _, users = self.user_module.list_users(query=query, page=1, per_page=limit)
        return [
            {
                "uid": u.get("uid", ""),
                "cn": u.get("cn", "") or "",
                "mail": u.get("mail", "") or "",
            }
            for u in users
        ]
