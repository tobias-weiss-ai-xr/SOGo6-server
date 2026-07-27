from __future__ import annotations

from app.module.calendar.source.CalendarSourceDb import CalendarSourceDb


class CalendarSourceCalDav(CalendarSourceDb):
    """DB-backed source for external CalDAV calendars.

    Events are populated by the CalendarSyncEngine. Write restrictions are
    enforced by CalendarAclEngine at the module level. This subclass exists
    for future CalDAV-specific behavior (e.g. bi-directional sync with PUT
    to push local changes back to the CalDAV server).
    """
