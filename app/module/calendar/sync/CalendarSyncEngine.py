from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast

from app.module.calendar.sync.CalDavFetcher import CalDavFetcher
from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_calendar
from app.utils.maths.sogo_hash import generate_uuid

if TYPE_CHECKING:
    from app.manager.cache.ClientRedis import ClientRedis
    from app.module.calendar.model.CalCalendar import CalCalendar
    from app.module.calendar.model.CalEvent import CalEvent
    from app.module.calendar.model.enums.CalendarSourceType import CalendarSourceType
    from app.module.calendar.source.CalendarSources import CalendarSources

SYNC_LOCK_TTL_SECONDS: int = 300  # 5 minutes
MAX_ICS_EVENTS: int = 5000


class CalendarSyncEngine:
    """Synchronizes external calendar sources (CalDAV / ICS) into the local database.

    For ICS feeds: fetches the .ics file, parses VEVENT/VTODO components,
    compares with local events by UID, and inserts/updates/deletes as needed.
    For CalDAV: uses PROPFIND to discover the calendar, then fetches the
    iCalendar data via GET.
    """

    def __init__(self, sources: CalendarSources, cache: ClientRedis) -> None:
        self._sources = sources
        self._cache = cache

    def sync(self, calendar: CalCalendar) -> None:
        """Run a full sync for an external calendar.

        Acquires a Redis lock to prevent concurrent syncs on the same calendar.
        Fetches remote data, parses it, and applies the diff.
        """
        from app.module.calendar.model.enums.CalendarSourceType import CalendarSourceType

        if calendar.source_type not in (CalendarSourceType.ICS, CalendarSourceType.CALDAV):
            raise RequestException(error=err.ERROR_CALENDAR_NOT_SUPPORTED)

        url: str | None = (calendar.sync_config or {}).get("url")
        if not url:
            raise RequestException(error=err.ERROR_CALENDAR_SYNC_FAILED)

        lock_key: str = f"calendar_sync_lock:{calendar.key}"
        lock_token: str = generate_uuid()
        if not self._cache.set(lock_key, lock_token, ttl=SYNC_LOCK_TTL_SECONDS, nx=True):
            logger_calendar.warning("Calendar sync already in progress for %s, skipping", calendar.key)
            return

        self._update_sync_status(calendar, "running")
        try:
            username: str | None = (calendar.sync_config or {}).get("username")
            password: str | None = (calendar.sync_config or {}).get("password")
            ics_text: str = CalDavFetcher.fetch_ics(url, username=username, password=password)
            self._apply_diff(calendar, ics_text)
            self._update_sync_status(calendar, "completed")
            logger_calendar.info("Calendar sync completed for %s", calendar.key)
        except RequestException as exc:
            self._update_sync_status(calendar, "failed",
                                     error=exc.error.m if exc.error else "Sync failed")
            raise
        except Exception:
            logger_calendar.exception("Unexpected calendar sync error for %s", calendar.key)
            self._update_sync_status(calendar, "failed", error="Unexpected sync error")
            raise
        finally:
            stored: str | None = cast("str | None", self._cache.get(lock_key, str))
            if stored == lock_token:
                self._cache.delete(lock_key)

    def _apply_diff(self, calendar: CalCalendar, ics_text: str) -> None:
        """Parse ICS text and apply insert/update/delete to the local source.

        Splits raw iCalendar text into individual VEVENT/VTODO components,
        parses each one, and compares with local events by UID.
        """
        from app.module.calendar.serializer.CalEventsDeserializerIcal import (
            CalEventsDeserializerIcal,
        )
        from app.module.calendar.serializer.calendar.CalDeserializerDict import (
            CalDeserializerDict,
        )

        source = self._sources.get(calendar)
        local_by_uid: dict[str, dict] = {
            meta["uid"]: meta for meta in source.get_sync_metadata()
            if meta.get("uid")
        }

        # Parse ICS into events
        deserializer = CalEventsDeserializerIcal()
        try:
            remote_events: list[CalEvent] = deserializer.deserialize(ics_text)
        except Exception as exc:
            logger_calendar.error("Failed to parse ICS content for %s: %s", calendar.key, exc)
            raise RequestException(error=err.ERROR_CALENDAR_ICS_PARSE_FAILED) from exc

        if len(remote_events) > MAX_ICS_EVENTS:
            logger_calendar.error(
                "Calendar %s has %d events (max %d), truncating",
                calendar.key, len(remote_events), MAX_ICS_EVENTS,
            )
            remote_events = remote_events[:MAX_ICS_EVENTS]

        remote_uids: set[str] = set()
        modified_uids: set[str] = set()

        for remote in remote_events:
            if not remote.uid:
                remote.uid = generate_uuid()
            remote_uids.add(remote.uid)
            remote.calendar_key = calendar.require_key

            if remote.uid in local_by_uid:
                meta = local_by_uid[remote.uid]
                if self._is_modified(meta, remote):
                    remote.key = meta.get("key")
                    try:
                        source.update_event(remote)
                        modified_uids.add(remote.uid)
                        logger_calendar.debug("Updated event %s in calendar %s",
                                              remote.uid, calendar.key)
                    except Exception as exc:
                        logger_calendar.warning("Failed to update event %s: %s",
                                                remote.uid, exc)
            else:
                try:
                    source.insert_event(remote)
                    logger_calendar.debug("Inserted event %s in calendar %s",
                                          remote.uid, calendar.key)
                except Exception as exc:
                    logger_calendar.warning("Failed to insert event %s: %s",
                                            remote.uid, exc)

        # Soft-delete local events that no longer exist in the remote feed
        for uid, meta in local_by_uid.items():
            if uid not in remote_uids and meta.get("key"):
                try:
                    source.delete_by_key(meta["key"])
                    logger_calendar.debug("Deleted event %s from calendar %s",
                                          uid, calendar.key)
                except Exception as exc:
                    logger_calendar.warning("Failed to delete event %s: %s", uid, exc)

    def _update_sync_status(
        self, calendar: CalCalendar, status: str, error: str | None = None,
    ) -> None:
        """Update sync_config with current status and timestamp."""
        if calendar.sync_config is None:
            calendar.sync_config = {}
        calendar.sync_config["sync_status"] = status
        calendar.sync_config["last_sync"] = datetime.now(timezone.utc).isoformat()
        if error:
            calendar.sync_config["sync_error"] = error
        elif "sync_error" in calendar.sync_config:
            del calendar.sync_config["sync_error"]
        self._sources.update_sync_config(calendar)

    @staticmethod
    def _is_modified(meta: dict, remote: CalEvent) -> bool:
        """Determine if the remote event has been modified compared to local metadata.

        Compares SEQUENCE numbers and last-modified timestamps.
        """
        from datetime import datetime

        # Check SEQUENCE number
        remote_seq = remote.sequence or 0
        local_seq = meta.get("sequence", 0)
        if remote_seq > local_seq:
            return True

        # Check DTSTAMP / last-modified
        remote_dtstamp = remote.dtstamp
        local_dtstamp = meta.get("dtstamp")
        if remote_dtstamp and local_dtstamp:
            if isinstance(remote_dtstamp, datetime) and isinstance(local_dtstamp, datetime):
                return remote_dtstamp.timestamp() > local_dtstamp.timestamp()

        # Fall back to updated_at
        remote_updated = remote.updated_at
        local_updated = meta.get("updated_at")
        if remote_updated and local_updated:
            if isinstance(remote_updated, datetime) and isinstance(local_updated, datetime):
                return remote_updated.timestamp() > local_updated.timestamp()

        # If we can't determine, always sync (conservative)
        return True
