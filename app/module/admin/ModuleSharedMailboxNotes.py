"""Shared mailbox internal notes module.

Manages internal notes associated with shared mailboxes and individual emails.
Notes can be public (visible to all members) or private (visible only to author).
Supports @mentions via a JSON list of UIDs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api as logger
from app.utils.maths.sogo_hash import generate_uuid
from app.utils.db.Condition import EqualCondition

if TYPE_CHECKING:
    from app.manager.db.ClientSQL import ClientSQL


class ModuleSharedMailboxNotes:
    """Internal notes for shared mailboxes and emails."""

    TABLE_NAME = "sogo6_shared_mailbox_notes"

    COL_ID = "id"
    COL_MAILBOX_ID = "mailbox_id"
    COL_EMAIL_ID = "email_id"
    COL_AUTHOR_UID = "author_uid"
    COL_CONTENT = "content"
    COL_IS_PRIVATE = "is_private"
    COL_MENTIONS = "mentions"
    COL_CREATED = "created_at"
    COL_UPDATED = "updated_at"

    ALL_COLS = (
        COL_ID, COL_MAILBOX_ID, COL_EMAIL_ID, COL_AUTHOR_UID,
        COL_CONTENT, COL_IS_PRIVATE, COL_MENTIONS, COL_CREATED, COL_UPDATED,
    )

    def __init__(self, db: ClientSQL) -> None:
        self._db = db

    def create_note(
        self,
        mailbox_id: str,
        author_uid: str,
        content: str,
        email_id: str | None = None,
        is_private: bool = False,
        mentions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new note."""
        now = datetime.now(timezone.utc).isoformat()
        note_id = generate_uuid()
        values = [[
            note_id, mailbox_id, email_id, author_uid,
            content, is_private, mentions or [], now, now,
        ]]
        self._db.insert_in_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            values_tuple=values,
        )
        logger.info("Created note %s for mailbox %s", note_id, mailbox_id)
        return self.get_note(note_id)  # type: ignore[return-value]

    def get_note(self, note_id: str) -> dict[str, Any] | None:
        """Get a single note by ID."""
        rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=EqualCondition(self.COL_ID, note_id),
        ))
        return self._row_to_dict(rows[0]) if rows else None

    def list_notes(
        self,
        mailbox_id: str,
        email_id: str | None = None,
        user_uid: str | None = None,
        include_private: bool = False,
    ) -> list[dict[str, Any]]:
        """List notes for a mailbox, optionally filtered by email.

        If user_uid is provided and include_private is True, returns:
        - All public notes
        - Private notes by user_uid
        """
        rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=EqualCondition(self.COL_MAILBOX_ID, mailbox_id),
        ))
        notes = [self._row_to_dict(row) for row in rows]

        # Filter by email_id if provided
        if email_id is not None:
            notes = [n for n in notes if n.get("email_id") == email_id]

        # Filter private notes
        if not include_private:
            notes = [n for n in notes if not n.get("is_private")]
        elif user_uid:
            notes = [
                n for n in notes
                if not n.get("is_private") or n.get("author_uid") == user_uid
            ]

        # Sort by created_at descending
        notes.sort(key=lambda n: n.get("created_at", ""), reverse=True)
        return notes

    def update_note(self, note_id: str, content: str) -> dict[str, Any] | None:
        """Update note content."""
        existing = self.get_note(note_id)
        if not existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_NOTE_NOT_FOUND)

        now = datetime.now(timezone.utc).isoformat()
        self._db.update_in_table(
            table_name=self.TABLE_NAME,
            column_tuple=(self.COL_CONTENT, self.COL_UPDATED),
            values_list=[content, now],
            condition=EqualCondition(self.COL_ID, note_id),
        )
        return self.get_note(note_id)

    def delete_note(self, note_id: str) -> bool:
        """Delete a note."""
        existing = self.get_note(note_id)
        if not existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_NOTE_NOT_FOUND)

        self._db.delete_row_in_table(
            table_name=self.TABLE_NAME,
            condition=EqualCondition(self.COL_ID, note_id),
        )
        logger.info("Deleted note %s", note_id)
        return True

    def delete_notes_for_mailbox(self, mailbox_id: str) -> int:
        """Delete all notes for a mailbox. Returns count deleted."""
        rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=(self.COL_ID,),
            condition=EqualCondition(self.COL_MAILBOX_ID, mailbox_id),
        ))
        count = 0
        for row in rows:
            self._db.delete_row_in_table(
                table_name=self.TABLE_NAME,
                condition=EqualCondition(self.COL_ID, row[0]),
            )
            count += 1
        return count

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        """Convert a DB row to dict with JSON normalization."""
        if isinstance(row, dict):
            return row

        def _parse_json(val: Any, default: Any) -> Any:
            if val is None:
                return default
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    return default
            return val

        mentions = _parse_json(row[6], [])
        if not isinstance(mentions, list):
            mentions = []

        return {
            "id": row[0],
            "mailbox_id": row[1],
            "email_id": row[2],
            "author_uid": row[3],
            "content": row[4],
            "is_private": bool(row[5]) if row[5] is not None else False,
            "mentions": mentions,
            "created_at": str(row[7]) if row[7] else None,
            "updated_at": str(row[8]) if row[8] else None,
        }

    @staticmethod
    def ensure_table(db: ClientSQL) -> None:
        """Create the shared mailbox notes table if it doesn't exist."""
        try:
            from app.utils.db.Table import Column, Table

            cols = [
                Column(name="id", data_type="str", extra_args={"max_len": 64}),
                Column(name="mailbox_id", data_type="str", extra_args={"max_len": 64}),
                Column(name="email_id", data_type="str", is_nullable=True, extra_args={"max_len": 128}),
                Column(name="author_uid", data_type="str", extra_args={"max_len": 256}),
                Column(name="content", data_type="text"),
                Column(name="is_private", data_type="bool", is_nullable=True),
                Column(name="mentions", data_type="json", is_nullable=True),
                Column(name="created_at", data_type="datetime", is_nullable=True),
                Column(name="updated_at", data_type="datetime", is_nullable=True),
            ]
            table = Table(
                name=ModuleSharedMailboxNotes.TABLE_NAME,
                columns=cols,
                primary_keys=("id",),
            )
            existing = db.get_table_info(table.name)
            if not existing:
                db.create_table(table)
        except Exception as exc:
            from app.utils.logger.logger import logger as _l
            _l.warning("Could not ensure shared mailbox notes table: %s", exc)
