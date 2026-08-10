from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.config.db import tables as tbl
from app.module.calendar.model.CalendarShare import CalendarShare
from app.module.calendar.model.enums.CalendarShareLevel import CalendarShareLevel
from app.utils import errors as err
from app.utils.db.Condition import AndCondition, EqualCondition
from app.utils.exceptions import BugException, RequestException
from app.utils.logger.logger import logger_calendar

if TYPE_CHECKING:
    from app.manager.db.ClientSQL import ClientSQL


# All column names in ALL_CAL_SHARE_COL order
_ALL_COLS: tuple[str, ...] = tuple(col.name for col in tbl.ALL_CAL_SHARE_COL)

# Columns for INSERT - id is serial, omitted
_INSERT_COLS: tuple[str, ...] = tuple(
    col.name for col in tbl.ALL_CAL_SHARE_COL if col.name != tbl.COL_ID.name
)


class RepositoryCalendarShare:
    """Handles all DB reads and writes for sogo_calendar_shares."""

    def __init__(self, db: ClientSQL) -> None:
        self._db = db

    @staticmethod
    def _row_to_share(row: tuple) -> CalendarShare:
        """Map a DB row to a CalendarShare model."""
        d = dict(zip(_ALL_COLS, row))
        return CalendarShare(
            user_uid=d["user_uid"],
            calendar_key=d["calendar_key"],
            public_level=CalendarShareLevel[d["public_level"].upper()],
            confidential_level=CalendarShareLevel[d["confidential_level"].upper()],
            private_level=CalendarShareLevel[d["private_level"].upper()],
            can_create=bool(d["can_create"]),
            can_delete=bool(d["can_delete"]),
        )

    def insert(self, share: CalendarShare) -> CalendarShare:
        """Persist a new share entry and return it with the id populated."""
        now = datetime.now(timezone.utc)
        values = [[
            share.calendar_key,
            share.user_uid,
            share.public_level.name.lower(),
            share.confidential_level.name.lower(),
            share.private_level.name.lower(),
            share.can_create,
            share.can_delete,
            now,
        ]]

        try:
            inserted = self._db.insert_in_table(
                table_name=tbl.TABLE_CALENDAR_SHARE.name,
                column_tuple=_INSERT_COLS,
                values_tuple=values,
            )
        except BugException as exc:
            logger_calendar.error(
                "Unique violation inserting share calendar_key=%s user=%s: %s",
                share.calendar_key, share.user_uid, exc,
            )
            raise RequestException(error=err.ERROR_CALENDAR_DUPLICATE) from exc

        if inserted != 1:
            logger_calendar.error(
                "Calendar share insert affected %s rows instead of 1 (calendar_key=%s, user=%s)",
                inserted, share.calendar_key, share.user_uid,
            )
            raise BugException("Calendar share insert did not affect exactly 1 row")

        return share

    def find_by_calendar_key(self, calendar_key: str) -> list[CalendarShare]:
        """Return all shares for the given calendar, ordered by id."""
        condition = EqualCondition(tbl.COL_CAL_SHARE_CALENDAR_KEY.name, calendar_key)
        rows = self._db.select_from_table(
            table_name=tbl.TABLE_CALENDAR_SHARE.name,
            column_tuple=_ALL_COLS,
            condition=condition,
            sort_by=tbl.COL_ID.name,
        )
        return [self._row_to_share(row) for row in rows]

    def find_calendar_keys_for_user(self, user_uid: str) -> list[str]:
        """Return all calendar keys that are shared with the given user."""
        condition = EqualCondition(tbl.COL_CAL_SHARE_USER_UID.name, user_uid)
        rows = self._db.select_from_table(
            table_name=tbl.TABLE_CALENDAR_SHARE.name,
            column_tuple=(tbl.COL_CAL_SHARE_CALENDAR_KEY.name,),
            condition=condition,
        )
        return [row[0] for row in rows]

    def find_by_calendar_and_user(self, calendar_key: str, user_uid: str) -> CalendarShare | None:
        """Return the share for a specific user on a calendar, or None."""
        condition = AndCondition(
            EqualCondition(tbl.COL_CAL_SHARE_CALENDAR_KEY.name, calendar_key),
            EqualCondition(tbl.COL_CAL_SHARE_USER_UID.name, user_uid),
        )
        rows = list(self._db.select_from_table(
            table_name=tbl.TABLE_CALENDAR_SHARE.name,
            column_tuple=_ALL_COLS,
            condition=condition,
            limit=1,
        ))
        if not rows:
            return None
        return self._row_to_share(rows[0])

    def delete(self, calendar_key: str, user_uid: str) -> None:
        """Remove a share entry for the given user on the given calendar."""
        condition = AndCondition(
            EqualCondition(tbl.COL_CAL_SHARE_CALENDAR_KEY.name, calendar_key),
            EqualCondition(tbl.COL_CAL_SHARE_USER_UID.name, user_uid),
        )
        deleted = self._db.delete_row_in_table(
            table_name=tbl.TABLE_CALENDAR_SHARE.name,
            condition=condition,
            expected_row=1,
        )
        if deleted == 0:
            logger_calendar.error(
                "Calendar share not found for calendar_key=%s user=%s on delete",
                calendar_key, user_uid,
            )
            raise RequestException(error=err.ERROR_CALENDAR_NOT_FOUND)
