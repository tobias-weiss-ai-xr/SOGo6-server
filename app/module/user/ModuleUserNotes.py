from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_user_profile as logger
from app.utils.db.Condition import EqualCondition
from app.utils.maths.sogo_hash import generate_uuid

if TYPE_CHECKING:
    from app.manager.db.ClientSQL import ClientSQL


class ModuleUserNotes:
    """
    Module to handle user notes in sogo6_user_notes table
    """

    TABLE_NAME = "sogo6_user_notes"

    # Column names
    COL_ID = "id"
    COL_USER_UID = "user_uid"
    COL_TITLE = "title"
    COL_CONTENT = "content"
    COL_CREATED = "created_at"
    COL_UPDATED = "updated_at"

    ALL_COLS = (
        COL_ID,
        COL_USER_UID,
        COL_TITLE,
        COL_CONTENT,
        COL_CREATED,
        COL_UPDATED,
    )

    def __init__(self, db: ClientSQL) -> None:
        """
        Initialize the module with database connection

        :param db: Database connection manager
        :type db: ClientSQL
        """
        self._db = db

    def _row_to_dict(self, row: list[Any]) -> dict[str, Any]:
        """
        Convert a database row to a dictionary

        :param row: Database row as list
        :type row: list[Any]
        :return: Dictionary representation of the row
        :rtype: dict[str, Any]
        """
        def _fmt(value):
            if value is None:
                return None
            if hasattr(value, "isoformat"):
                return value.isoformat()
            return str(value)

        return {
            "id": _fmt(row[0]),
            "user_uid": _fmt(row[1]),
            "title": _fmt(row[2]),
            "content": _fmt(row[3]),
            "created_at": _fmt(row[4]),
            "updated_at": _fmt(row[5]),
        }

    def create_note(self, user_uid: str, title: str, content: str) -> dict[str, Any]:
        """
        Create a new user note

        :param user_uid: User unique identifier
        :type user_uid: str
        :param title: Note title (max 255 characters)
        :type title: str
        :param content: Note content
        :type content: str
        :return: Created note as dictionary
        :rtype: dict[str, Any]
        """
        self._db.connect()

        note_id = generate_uuid()
        now = datetime.now(timezone.utc)

        values = [[
            note_id,
            user_uid,
            title,
            content,
            now,
            now,
        ]]

        self._db.insert_in_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            values_tuple=values,
        )

        logger.info("Created note %s for user %s with title: %s", note_id, user_uid, title)

        return {
            "id": note_id,
            "user_uid": user_uid,
            "title": title,
            "content": content,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

    def get_note(self, note_id: str) -> dict[str, Any]:
        """
        Get a note by its ID

        :param note_id: Note unique identifier
        :type note_id: str
        :return: Note as dictionary
        :rtype: dict[str, Any]
        :raises RequestException: If note not found
        """
        self._db.connect()

        rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=EqualCondition(self.COL_ID, note_id),
        ))

        if not rows:
            logger.error("Note not found: %s", note_id)
            raise RequestException(
                error=err.ERROR_NOT_FOUND,
                message=f"Note {note_id} not found",
            )

        return self._row_to_dict(rows[0])

    def list_notes(self, user_uid: str) -> list[dict[str, Any]]:
        """
        List all notes for a user

        :param user_uid: User unique identifier
        :type user_uid: str
        :return: List of notes as dictionaries
        :rtype: list[dict[str, Any]]
        """
        self._db.connect()

        rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=EqualCondition(self.COL_USER_UID, user_uid),
        ))

        logger.debug("Found %d notes for user %s", len(rows), user_uid)
        return [self._row_to_dict(row) for row in rows]

    def update_note(self, note_id: str, title: str, content: str) -> dict[str, Any]:
        """
        Update an existing note

        :param note_id: Note unique identifier
        :type note_id: str
        :param title: Updated note title
        :type title: str
        :param content: Updated note content
        :type content: str
        :return: Updated note as dictionary
        :rtype: dict[str, Any]
        :raises RequestException: If note not found
        """
        self._db.connect()

        # First verify the note exists
        rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=EqualCondition(self.COL_ID, note_id),
        ))

        if not rows:
            logger.error("Note not found for update: %s", note_id)
            raise RequestException(
                error=err.ERROR_NOT_FOUND,
                message=f"Note {note_id} not found",
            )

        now = datetime.now(timezone.utc)

        # Update the note
        updated_rows = self._db.update_in_table(
            table_name=self.TABLE_NAME,
            column_tuple=(self.COL_TITLE, self.COL_CONTENT, self.COL_UPDATED),
            values_list=[title, content, now],
            condition=EqualCondition(self.COL_ID, note_id),
        )

        if updated_rows == 0:
            logger.error("Failed to update note: %s", note_id)
            raise RequestException(
                error=err.ERROR_NOT_FOUND,
                message=f"Note {note_id} not found or not updated",
            )

        logger.info("Updated note %s with title: %s", note_id, title)

        # Return the updated note
        updated_row = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=EqualCondition(self.COL_ID, note_id),
        ))

        return self._row_to_dict(updated_row[0])

    def delete_note(self, note_id: str) -> bool:
        """
        Delete a note by its ID

        :param note_id: Note unique identifier
        :type note_id: str
        :return: True if deletion was successful
        :rtype: bool
        :raises RequestException: If note not found
        """
        self._db.connect()

        # First verify the note exists
        rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=(self.COL_ID,),
            condition=EqualCondition(self.COL_ID, note_id),
        ))

        if not rows:
            logger.error("Note not found for deletion: %s", note_id)
            raise RequestException(
                error=err.ERROR_NOT_FOUND,
                message=f"Note {note_id} not found",
            )

        # Delete the note
        deleted_rows = self._db.delete_row_in_table(
            table_name=self.TABLE_NAME,
            condition=EqualCondition(self.COL_ID, note_id),
        )

        if deleted_rows == 0:
            logger.error("Failed to delete note: %s", note_id)
            raise RequestException(
                error=err.ERROR_NOT_FOUND,
                message=f"Note {note_id} not found or not deleted",
            )

        logger.info("Deleted note: %s", note_id)
        return True
