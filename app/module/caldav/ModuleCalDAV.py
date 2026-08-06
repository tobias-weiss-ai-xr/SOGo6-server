"""ModuleCalDAV — CalDAV server protocol engine.

Implements the CalDAV (RFC 4791), WebDAV (RFC 4918) and CalDAV sync (RFC 6578)
protocol surfaces over an in-memory resource store, mirroring the pattern of
``ModuleEmailAuth`` (pure, self-contained, fixture-free unit testing).

Resource hierarchy (RFC 4791 §4):

    /caldav/
    ├── principals/
    │   └── user/{email}/            principal collection + user principal
    └── calendars/
        └── {email}/
            ├── {calendar_name}/    calendar collection (MKCALENDAR / PROPPATCH)
            │   └── {uid}.ics       event resource (PUT / GET / HEAD / DELETE)

The engine exposes the following protocol capabilities:

* OPTIONS — DAV header (``1, 2, 3, calendar-access, calendar-schedule, extended-mkcol``)
* PROPFIND — property discovery with multistatus responses (Depth 0/1)
* PROPPATCH — calendar property updates (displayname, description, timezone, color)
* MKCALENDAR — calendar collection creation
* MKCOL — collection creation (extended MKCOL)
* PUT / GET / HEAD / DELETE — event resources (iCalendar, RFC 5545)
* REPORT — ``sync-collection`` (RFC 6578 delta sync), ``calendar-query``
  (time-range filter), ``calendar-multiget``, ``free-busy-query``
* Conditional requests — ``If-Match`` / ``If-None-Match`` with ETags
* ``.well-known/caldav`` discovery support (URI helpers)

All mutable operations bump a per-calendar change counter which seeds
sync-tokens (RFC 6578 ``<sync-token>``) — token ``0`` means "full sync".
"""

from __future__ import annotations

import base64
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import xml.etree.ElementTree as ET

from app.utils import errors as err
from app.utils.exceptions import RequestException

# ── XML namespaces (RFC 4791 / RFC 4918) ─────────────────────────────────────

DAV_NS = "DAV:"
CALDAV_NS = "urn:ietf:params:xml:ns:caldav"
CALENDAR_SERVER_NS = "http://calendarserver.org/ns/"

_COMPONENT_SET = ["VEVENT", "VTODO"]
_UID_SUFFIX_RE = re.compile(r"\.ics$", re.IGNORECASE)

# Max resources returned in one sync-collection response (spec: c:limit)
MAX_SYNC_LIMIT = 1000

# Error aliases for readability
ERROR_CALDAV_PATH_NOT_FOUND = "ERROR_CALDAV_PATH_NOT_FOUND"
ERROR_CALDAV_CALENDAR_EXISTS = "ERROR_CALDAV_CALENDAR_EXISTS"
ERROR_CALDAV_PRECONDITION = "ERROR_CALDAV_PRECONDITION_FAILED"
ERROR_CALDAV_SYNC_TOKEN_INVALID = "ERROR_CALDAV_SYNC_TOKEN_INVALID"
ERROR_CALDAV_INVALID_ICAL = "ERROR_CALDAV_INVALID_ICAL"
ERROR_CALDAV_NO_COMPONENT = "ERROR_CALDAV_NO_COMPONENT"
ERROR_CALDAV_REPORT_UNSUPPORTED = "ERROR_CALDAV_REPORT_UNSUPPORTED"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

class CalDavResource:
    """A parsed CalDAV resource path (RFC 4791 §9 - resource hierarchy)."""

    __slots__ = ("kind", "email", "calendar_name", "uid", "path")

    # kinds: root | principals | principal | calendar_home | calendar | event
    def __init__(
        self,
        kind: str,
        email: str | None = None,
        calendar_name: str | None = None,
        uid: str | None = None,
        path: str = "",
    ) -> None:
        self.kind = kind
        self.email = email
        self.calendar_name = calendar_name
        self.uid = uid
        self.path = path

    @property
    def is_collection(self) -> bool:
        return self.kind in {"root", "principals", "principal", "calendar_home", "calendar"}

    @property
    def href(self) -> str:
        """Canonical DAV:href for this resource (absolute within the server)."""
        if self.kind == "root":
            return "/caldav/"
        if self.kind == "principals":
            return "/caldav/principals/"
        if self.kind == "principal":
            return f"/caldav/principals/user/{self.email}/"
        if self.kind == "calendar_home":
            return f"/caldav/calendars/{self.email}/"
        if self.kind == "calendar":
            return f"/caldav/calendars/{self.email}/{self.calendar_name}/"
        return f"/caldav/calendars/{self.email}/{self.calendar_name}/{self.uid}.ics"

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<CalDavResource kind={self.kind} href={self.href}>"


class CalDavEvent:
    """An event resource stored in a calendar collection."""

    __slots__ = ("uid", "ical", "etag", "last_modified", "change_seq")

    def __init__(
        self,
        uid: str,
        ical: str,
        etag: str,
        last_modified: datetime,
        change_seq: int,
    ) -> None:
        self.uid = uid
        self.ical = ical
        self.etag = etag
        self.last_modified = last_modified
        self.change_seq = change_seq


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------

class ModuleCalDAV:
    """CalDAV server protocol engine backed by an in-memory resource store.

    Store layout::

        principals:  {email: {"display_name": str, "email": str}}
        calendars:   {(email, name): {"displayname": str, "description": str,
                                      "timezone": str, "color": str, "etag": str,
                                      "last_modified": datetime, "change_counter": int}}
        events:      {(email, name, uid): CalDavEvent}
        tombstones:  {(email, name): {uid: seq}}

    Every mutating operation bumps the owning calendar's ``change_counter``,
    which combined with tombstones forms opaque RFC 6578 sync tokens.
    """

    # -- lifecycle -----------------------------------------------------------

    def __init__(self, base_path: str = "/caldav") -> None:
        self.base_path = base_path
        self.principals: dict[str, dict[str, Any]] = {}
        self._calendars: dict[tuple[str, str], dict[str, Any]] = {}
        self._events: dict[tuple[str, str, str], CalDavEvent] = {}
        self._tombstones: dict[tuple[str, str], dict[str, int]] = {}
        self._token_counter = 0

    # ------------------------------------------------------------------
    # Path resolution (URI -> CalDavResource)
    # ------------------------------------------------------------------

    def resolve(self, path: str) -> CalDavResource:
        """Split a request URL under ``base_path`` into a CalDavResource.

        :raises RequestException: ERROR_CALDAV_PATH_NOT_FOUND for unknown
            path shapes (404 semantics).
        """
        clean = path
        if clean.startswith(self.base_path):
            clean = clean[len(self.base_path):]
        clean = "/" + clean.lstrip("/")
        while "//" in clean:
            clean = clean.replace("//", "/")
        segments = [s for s in clean.split("/") if s]

        if not segments:
            return CalDavResource("root", path=clean)

        if segments[0] == "principals":
            if len(segments) == 1:
                return CalDavResource("principals", path=clean)
            if len(segments) >= 2 and segments[1] == "user":
                if len(segments) > 3:
                    raise RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND)
                email = segments[2] if len(segments) > 2 else ""
                return CalDavResource("principal", email=email, path=clean)
            email = segments[1]
            if len(segments) > 2:
                raise RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND)
            return CalDavResource("principal", email=email, path=clean)

        if segments[0] == "calendars":
            if len(segments) < 2:
                return CalDavResource("calendar_home", path=clean)
            email = segments[1]
            if len(segments) == 2:
                return CalDavResource("calendar_home", email=email, path=clean)
            name = segments[2]
            if len(segments) == 3:
                return CalDavResource("calendar", email=email, calendar_name=name, path=clean)
            if len(segments) == 4:
                uid = _UID_SUFFIX_RE.sub("", segments[3])
                return CalDavResource(
                    "event", email=email, calendar_name=name, uid=uid, path=clean
                )
            raise RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND)

        raise RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND)

    # ------------------------------------------------------------------
    # Principal / user registry
    # ------------------------------------------------------------------

    def register_user(self, email: str, display_name: str | None = None) -> dict[str, Any]:
        """Register a CalDAV principal (the authenticated user)."""
        key = email.lower()
        principal = self.principals.setdefault(
            key, {"email": key, "display_name": display_name or key}
        )
        if display_name:
            principal["display_name"] = display_name
        return principal

    def principal_exists(self, email: str) -> bool:
        return email.lower() in self.principals

    def list_principal_emails(self) -> list[str]:
        """Sorted emails — used by principals collection PROPFIND (depth 1)."""
        return sorted(self.principals)

    # ------------------------------------------------------------------
    # Calendar collections
    # ------------------------------------------------------------------

    def create_calendar(
        self,
        email: str,
        name: str,
        display_name: str | None = None,
        description: str | None = None,
        timezone: str | None = None,
        color: str | None = None,
    ) -> str:
        """Create a calendar collection. Returns its ETag."""
        email, name = email.lower(), name.lower()
        key = (email, name)
        if key in self._calendars:
            raise RequestException(error=err.ERROR_CALDAV_CALENDAR_EXISTS)
        self.register_user(email)
        now = self._now_utc()
        etag = self._etag(name, now)
        self._calendars[key] = {
            "user": email,
            "name": name,
            "displayname": display_name or name,
            "description": description or "",
            "timezone": timezone or "UTC",
            "color": color,
            "etag": etag,
            "last_modified": now,
            "change_counter": 0,
        }
        self._tombstones.setdefault(key, {})
        return etag

    def calendar_exists(self, email: str, name: str) -> bool:
        return (email.lower(), name.lower()) in self._calendars

    def list_calendars(self, email: str) -> list[dict[str, Any]]:
        """Return calendar dicts owned by ``email`` (sorted by name)."""
        email = email.lower()
        return [
            c for (owner, _name), c in sorted(self._calendars.items()) if owner == email
        ]

    def get_calendar(self, email: str, name: str) -> dict[str, Any]:
        try:
            return self._calendars[(email.lower(), name.lower())]
        except KeyError:
            raise RequestException(error=err.ERROR_CALENDAR_NOT_FOUND) from None

    def delete_calendar(self, email: str, name: str) -> None:
        email, name = email.lower(), name.lower()
        key = (email, name)
        if key not in self._calendars:
            raise RequestException(error=err.ERROR_CALENDAR_NOT_FOUND)
        del self._calendars[key]
        for event_key in [k for k in self._events if k[:2] == key]:
            del self._events[event_key]
        self._tombstones.pop(key, None)

    def update_calendar_props(
        self, email: str, name: str, changes: dict[str, str]
    ) -> list[tuple[str, str]]:
        """Apply a PROPPATCH. Returns list of (propname, status-text)."""
        calendar = self.get_calendar(email, name)
        results: list[tuple[str, str]] = []
        for prop, value in changes.items():
            if prop in ("displayname", "description", "timezone", "color"):
                calendar[prop] = value
                results.append((prop, "200 OK"))
            else:
                # RFC 4918 §13.4 – read-only property → 403 Forbidden
                results.append((prop, "403 Forbidden"))
        if results:
            calendar["last_modified"] = self._now_utc()
            calendar["etag"] = self._etag(calendar["name"], calendar["last_modified"])
            self._bump_change_counter(email, name)
        return results

    # ------------------------------------------------------------------
    # Event resources
    # ------------------------------------------------------------------

    def put_event(
        self,
        email: str,
        calendar_name: str,
        uid: str,
        ical_text: str,
        if_match: str | None = None,
        if_none_match: str | None = None,
    ) -> tuple[str, bool]:
        """Create (True) or update (False) an event, honoring ETag preconditions.

        :raises RequestException: 412 on precondition failure, 422 on invalid
            iCalendar, 404 when the calendar doesn't exist.
        :returns: (etag, created)
        """
        self.get_calendar(email, calendar_name)
        key = (email.lower(), calendar_name.lower(), uid.lower())
        existing = self._events.get(key)

        if existing is not None:
            if if_match is not None and if_match not in (existing.etag, "*"):
                raise RequestException(error=err.ERROR_CALDAV_PRECONDITION_FAILED)
            if if_none_match == "*":
                raise RequestException(error=err.ERROR_CALDAV_PRECONDITION_FAILED)
        else:
            if if_match is not None and if_match != "*":
                raise RequestException(error=err.ERROR_CALDAV_PRECONDITION_FAILED)

        validated = self._validate_ical(ical_text, expected_uid=uid)
        now = self._now_utc()
        seq = self._bump_change_counter(email, calendar_name)
        etag = self._etag(f"{uid}:{seq}", now)
        self._events[key] = CalDavEvent(
            uid=uid, ical=validated, etag=etag, last_modified=now, change_seq=seq
        )
        created = existing is None
        if created:
            # resurrected resource: drop the delete tombstone from the ledger
            self._tombstones.get(key[:2], {}).pop(uid.lower(), None)
        return etag, created

    def get_event(self, email: str, calendar_name: str, uid: str) -> CalDavEvent:
        self.get_calendar(email, calendar_name)
        key = (email.lower(), calendar_name.lower(), uid.lower())
        event = self._events.get(key)
        if event is None:
            raise RequestException(error=err.ERROR_CALENDAR_EVENT_NOT_FOUND)
        return event

    def delete_event(
        self, email: str, calendar_name: str, uid: str, if_match: str | None = None
    ) -> None:
        self.get_calendar(email, calendar_name)
        key = (email.lower(), calendar_name.lower(), uid.lower())
        event = self._events.get(key)
        if event is None:
            raise RequestException(error=err.ERROR_CALENDAR_EVENT_NOT_FOUND)
        if if_match is not None and if_match not in (event.etag, "*"):
            raise RequestException(error=err.ERROR_CALDAV_PRECONDITION_FAILED)
        seq = self._bump_change_counter(email, calendar_name)
        self._events.pop(key)
        self._tombstones.setdefault(key[:2], {})[uid.lower()] = seq

    def list_events(self, email: str, calendar_name: str) -> list[CalDavEvent]:
        """All live events of a calendar (sorted by uid)."""
        prefix = (email.lower(), calendar_name.lower())
        events = [self._events[k] for k in self._events if k[:2] == prefix]
        return sorted(events, key=lambda e: e.uid)

    def event_count(self, email: str, calendar_name: str) -> int:
        prefix = (email.lower(), calendar_name.lower())
        return sum(1 for k in self._events if k[:2] == prefix)

    # ------------------------------------------------------------------
    # Sync (RFC 6578)
    # ------------------------------------------------------------------

    def sync_changes(
        self, email: str, calendar_name: str, token: str | None
    ) -> tuple[list[CalDavEvent], list[str], str]:
        """Compute the RFC 6578 delta for a sync-collection REPORT.

        :param token: opaque sync-token from a previous response; None or "0" = full sync
        :returns: (changed_events, deleted_uids, next_token)
        """
        calendar = self.get_calendar(email, calendar_name)
        start_seq = self._decode_token(token) if token and token not in ("0", "") else 0

        prefix = (email.lower(), calendar_name.lower())
        changed = [
            self._events[k]
            for k in self._events
            if k[:2] == prefix and self._events[k].change_seq > start_seq
        ]
        deleted = [
            uid for uid, seq in self._tombstones.get(prefix, {}).items() if seq > start_seq
        ]

        next_seq = max(calendar["change_counter"], start_seq)
        return sorted(changed, key=lambda e: e.uid), sorted(deleted), self._format_token(next_seq)

    def sync_token(self, email: str, calendar_name: str) -> str:
        calendar = self.get_calendar(email, calendar_name)
        return self._format_token(calendar["change_counter"])

    # ------------------------------------------------------------------
    # Free/busy (RFC 4791 §7.10)
    # ------------------------------------------------------------------

    def free_busy_report(
        self, email: str, calendar_name: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        """Return free-busy periods computed from events overlapping [start, end)."""
        self.get_calendar(email, calendar_name)
        periods: list[dict[str, Any]] = []
        for event in self.list_events(email, calendar_name):
            for s, e in self._event_periods_in_range(event, start, end):
                periods.append({"start": s.isoformat(), "end": e.isoformat(), "type": "busy"})
        return sorted(periods, key=lambda p: p["start"])

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _bump_change_counter(self, email: str, calendar_name: str) -> int:
        email, calendar_name = email.lower(), calendar_name.lower()
        calendar = self.get_calendar(email, calendar_name)
        calendar["change_counter"] += 1
        return calendar["change_counter"]

    def _format_token(self, seq: int) -> str:
        """Opaque RFC 6578 sync token encoding the change counter."""
        self._token_counter += 1
        payload = base64.urlsafe_b64encode(
            f"{seq}:{self._token_counter}".encode()
        ).decode().rstrip("=")
        return f"urn:x-sogo6:sync:{payload}"

    def _decode_token(self, token: str) -> int:
        """Extract the seq part of a previous sync-token."""
        try:
            payload = token.rsplit(":", 1)[1]
            padded = payload + "=" * (-len(payload) % 4)
            seq = int(base64.urlsafe_b64decode(padded).decode().split(":")[0])
            return seq
        except Exception:
            raise RequestException(error=err.ERROR_CALDAV_SYNC_TOKEN_INVALID) from None

    def _validate_ical(self, ical_text: str, expected_uid: str) -> str:
        """Parse + normalize an iCalendar body; raise 422 on invalid content."""
        from icalendar import Calendar
        if len(ical_text) > 10 * 1024 * 1024:
            raise RequestException(error=err.ERROR_CALENDAR_IMPORT_TOO_LARGE)
        try:
            parsed = Calendar.from_ical(ical_text)
        except Exception as exc:
            raise RequestException(error=err.ERROR_CALDAV_INVALID_ICAL) from exc

        found = False
        for comp in parsed.walk():
            if comp.name not in ("VEVENT", "VTODO", "VJOURNAL"):
                continue
            uid = str(comp.get("UID") or "")
            if uid and uid.lower() == expected_uid.lower():
                found = True
                break
            if not uid:
                comp["UID"] = expected_uid
                found = True
                break
        if not found:
            raise RequestException(error=err.ERROR_CALDAV_NO_COMPONENT)
        return parsed.to_ical().decode("utf-8", errors="replace")

    def _event_periods_in_range(
        self, event: CalDavEvent, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime]]:
        """Overlapping [start, end) periods of a stored event (single occurrence)."""
        from icalendar import Calendar as ICal
        try:
            parsed = ICal.from_ical(event.ical)
        except Exception:
            return []
        periods: list[tuple[datetime, datetime]] = []
        for comp in parsed.subcomponents:
            if comp.name not in ("VEVENT", "VTODO"):
                continue
            dtstart = comp.get("DTSTART")
            dtend = comp.get("DTEND") or comp.get("DUE")
            if dtstart is None:
                continue
            dtstart_dt = getattr(dtstart, "dt", dtstart)
            if not isinstance(dtstart_dt, datetime):
                try:
                    dtstart_dt = datetime(
                        dtstart_dt.year, dtstart_dt.month, dtstart_dt.day, tzinfo=timezone.utc
                    )
                except AttributeError:
                    continue
            dtend_dt = getattr(dtend, "dt", None) if dtend is not None else None
            if dtend_dt is None:
                dtend_dt = dtstart_dt + timedelta(hours=1)
            elif not isinstance(dtend_dt, datetime):
                try:
                    dtend_dt = datetime(
                        dtend_dt.year, dtend_dt.month, dtend_dt.day, tzinfo=timezone.utc
                    )
                except AttributeError:
                    continue
            s = self._ensure_aware(dtstart_dt)
            e = self._ensure_aware(dtend_dt)
            overlap_s = max(s, start)
            overlap_e = min(e, end)
            if overlap_s < overlap_e:
                periods.append((overlap_s, overlap_e))
        return periods

    @staticmethod
    def _ensure_aware(dt: datetime) -> datetime:
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

    @staticmethod
    def _etag(seed: Any, when: datetime) -> str:
        digest = hashlib.sha1(f"{seed}:{when.isoformat()}".encode()).hexdigest()[:10]
        return f'"{digest}"'

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc).replace(microsecond=0)

    # ------------------------------------------------------------------
    # XML response builders
    # ------------------------------------------------------------------

    @staticmethod
    def _xml(tag: str, ns: str = DAV_NS, attrib: dict | None = None, text: str | None = None) -> ET.Element:
        elem = ET.Element(f"{{{ns}}}{tag}" if ns else tag, attrib or {})
        if text is not None:
            elem.text = text
        return elem