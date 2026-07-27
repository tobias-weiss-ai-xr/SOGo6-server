from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_mail_server as logger
from app.utils.db.Condition import EqualCondition, AndCondition, LessThanOrEqualCondition

if TYPE_CHECKING:
    from app.manager.db.ClientSQL import ClientSQL


class ModuleSnooze:
    """Manages email snooze — temporarily removes emails from inbox and
    restores them at a specified time.

    Implementation:
    1. When user snoozes a mail, we record it in ``sogo6_snoozed`` and
       rely on the IMAP flag ``\\Snoozed`` (or a dedicated folder) to
       hide it from the main view.
    2. A periodic agent job (SnoozeJob) queries for mails whose
       ``snooze_until <= now`` and restores them.

    Since IMAP move operations vary by server, this module stores the
    metadata and the *caller* (ApiSnooze / SnoozeJob) is responsible for
    the actual IMAP COPY + EXPUNGE / restore operations.
    """

    TABLE_NAME = "sogo6_snoozed"

    COL_ID = "id"
    COL_USER_UID = "user_uid"
    COL_MAIL_UID = "mail_uid"
    COL_FOLDER = "folder"
    COL_ORIGINAL_FOLDER = "original_folder"
    COL_SNOOZE_UNTIL = "snooze_until"
    COL_CREATED = "created_at"
    COL_ACCOUNT_ID = "account_id"

    ALL_COLS = (
        COL_ID, COL_USER_UID, COL_MAIL_UID, COL_FOLDER,
        COL_ORIGINAL_FOLDER, COL_SNOOZE_UNTIL, COL_CREATED, COL_ACCOUNT_ID,
    )

    # Preset snooze durations (ISO 8601-like labels)
    PRESETS = {
        "later_today": {"hours": 3},
        "tomorrow": {"hours": 24},
        "this_weekend": {"days": 5},   # approx next Saturday
        "next_week": {"days": 7},
    }

    def __init__(self, db: ClientSQL) -> None:
        self._db = db

    def _row_to_dict(self, row: list[Any]) -> dict[str, Any]:
        return {
            "id": row[0],
            "user_uid": row[1],
            "mail_uid": row[2],
            "folder": row[3],
            "original_folder": row[4],
            "snooze_until": row[5].isoformat() if row[5] else None,
            "created_at": row[6].isoformat() if row[6] else None,
            "account_id": row[7],
        }

    def snooze(
        self,
        user_uid: str,
        account_id: str,
        mail_uid: str,
        folder: str,
        snooze_until: datetime,
        original_folder: str | None = None,
    ) -> dict[str, Any]:
        """Record a snooze for an email.

        :param user_uid: The user's UID.
        :param account_id: The account ID for IMAP operations.
        :param mail_uid: The IMAP UID of the mail to snooze.
        :param folder: The IMAP folder where the mail currently lives.
        :param snooze_until: When to restore the mail.
        :param original_folder: The original folder to restore to (defaults to folder).
        :return: The created snooze record as a dict.
        """
        if snooze_until <= datetime.now(timezone.utc):
            raise RequestException(
                error=err.ERROR_VALIDATION_FAILED,
                message="snooze_until must be in the future.",
            )

        # Prevent duplicate snooze for the same mail
        existing = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=AndCondition([
                EqualCondition(self.COL_USER_UID, user_uid),
                EqualCondition(self.COL_MAIL_UID, mail_uid),
            ]),
        ))
        if existing:
            raise RequestException(
                error=err.ERROR_SNOOZE_DUPLICATE,
                message=f"Mail '{mail_uid}' is already snoozed for user '{user_uid}'.",
            )

        now = datetime.now(timezone.utc)
        target_folder = original_folder or folder

        values = [[
            None,  # auto-increment
            user_uid,
            mail_uid,
            folder,
            target_folder,
            snooze_until,
            now,
            account_id,
        ]]

        self._db.insert_in_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            values_tuple=values,
        )

        logger.info(
            "Snoozed mail %s (folder=%s) until %s for user %s",
            mail_uid, folder, snooze_until.isoformat(), user_uid,
        )

        # Return a representation with the auto-incremented id
        rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=AndCondition([
                EqualCondition(self.COL_USER_UID, user_uid),
                EqualCondition(self.COL_MAIL_UID, mail_uid),
            ]),
        ))
        if rows:
            return self._row_to_dict(rows[-1])
        return {
            "user_uid": user_uid,
            "mail_uid": mail_uid,
            "folder": folder,
            "original_folder": target_folder,
            "snooze_until": snooze_until.isoformat(),
            "created_at": now.isoformat(),
            "account_id": account_id,
        }

    def unsnooze(self, user_uid: str, snooze_id: int) -> dict[str, Any]:
        """Remove a snooze record (restore a snoozed email).

        Returns the snooze record so the caller can perform the IMAP restore.
        """
        rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=AndCondition([
                EqualCondition(self.COL_ID, snooze_id),
                EqualCondition(self.COL_USER_UID, user_uid),
            ]),
        ))
        if not rows:
            raise RequestException(
                error=err.ERROR_SNOOZE_NOT_FOUND,
                message=f"Snooze record {snooze_id} not found for user '{user_uid}'.",
            )

        record = self._row_to_dict(rows[0])

        self._db.delete_from_table(
            table_name=self.TABLE_NAME,
            condition=EqualCondition(self.COL_ID, snooze_id),
        )

        logger.info(
            "Unsnoozed mail %s (folder=%s -> %s) for user %s",
            record["mail_uid"], record["folder"], record["original_folder"], user_uid,
        )
        return record

    def list_snoozed(self, user_uid: str, include_expired: bool = False) -> list[dict[str, Any]]:
        """List all snooze records for a user."""
        condition = EqualCondition(self.COL_USER_UID, user_uid)
        rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=condition,
        ))
        results = [self._row_to_dict(row) for row in rows]

        if not include_expired:
            now = datetime.now(timezone.utc)
            results = [r for r in results if r["snooze_until"] and datetime.fromisoformat(r["snooze_until"]) > now]

        return results

    def list_due(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """List snooze records whose snooze_until has passed (for the agent job)."""
        check_time = now or datetime.now(timezone.utc)
        rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=LessThanOrEqualCondition(self.COL_SNOOZE_UNTIL, check_time),
        ))
        return [self._row_to_dict(row) for row in rows]

    def remove_record(self, snooze_id: int) -> None:
        """Remove a snooze record (called after successful IMAP restore)."""
        self._db.delete_from_table(
            table_name=self.TABLE_NAME,
            condition=EqualCondition(self.COL_ID, snooze_id),
        )

    @staticmethod
    def parse_preset(preset: str) -> dict[str, int] | None:
        """Return hours/days delta for a preset key, or None."""
        return ModuleSnooze.PRESETS.get(preset)
