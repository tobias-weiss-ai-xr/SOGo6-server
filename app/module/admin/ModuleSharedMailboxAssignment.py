"""Shared mailbox email assignment module.

Manages email assignments within shared mailboxes — assigning emails to
team members for handling, tracking assignment status (pending, accepted,
completed, cancelled), and recording completion timestamps.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api as logger
from app.utils.maths.sogo_hash import generate_uuid
from app.utils.db.Condition import EqualCondition, TrueCondition

if TYPE_CHECKING:
    from app.manager.db.ClientSQL import ClientSQL

VALID_STATUSES = ("pending", "accepted", "completed", "cancelled")


class ModuleSharedMailboxAssignment:
    """Email assignment tracking for shared mailboxes."""

    TABLE_NAME = "sogo6_shared_mailbox_assignments"

    COL_ID = "id"
    COL_MAILBOX_ID = "mailbox_id"
    COL_EMAIL_ID = "email_id"
    COL_ASSIGNED_TO = "assigned_to"
    COL_ASSIGNED_BY = "assigned_by"
    COL_REASON = "reason"
    COL_STATUS = "status"
    COL_NOTIFIED = "notified"
    COL_CREATED = "created_at"
    COL_COMPLETED = "completed_at"

    ALL_COLS = (
        COL_ID, COL_MAILBOX_ID, COL_EMAIL_ID, COL_ASSIGNED_TO,
        COL_ASSIGNED_BY, COL_REASON, COL_STATUS, COL_NOTIFIED,
        COL_CREATED, COL_COMPLETED,
    )

    def __init__(self, db: ClientSQL) -> None:
        self._db = db

    def create_assignment(
        self,
        mailbox_id: str,
        email_id: str,
        assigned_to: str,
        assigned_by: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Create a new email assignment."""
        # Check for existing active assignment for this email
        existing = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=EqualCondition(self.COL_EMAIL_ID, email_id),
        ))
        for row in existing:
            assignment = self._row_to_dict(row)
            if assignment.get("status") in ("pending", "accepted"):
                raise RequestException(error=err.ERROR_SHARED_MAILBOX_ASSIGNMENT_ALREADY_EXISTS)

        now = datetime.now(timezone.utc).isoformat()
        assignment_id = generate_uuid()
        values = [[
            assignment_id, mailbox_id, email_id, assigned_to,
            assigned_by, reason, "pending", False, now, None,
        ]]
        self._db.insert_in_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            values_tuple=values,
        )
        logger.info("Created assignment %s for email %s to %s", assignment_id, email_id, assigned_to)
        return self.get_assignment(assignment_id)  # type: ignore[return-value]

    def get_assignment(self, assignment_id: str) -> dict[str, Any] | None:
        """Get a single assignment by ID."""
        rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=EqualCondition(self.COL_ID, assignment_id),
        ))
        return self._row_to_dict(rows[0]) if rows else None

    def list_assignments(
        self,
        mailbox_id: str | None = None,
        assigned_to: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List assignments, optionally filtered by mailbox, assignee, or status."""
        if mailbox_id:
            condition = EqualCondition(self.COL_MAILBOX_ID, mailbox_id)
        elif assigned_to:
            condition = EqualCondition(self.COL_ASSIGNED_TO, assigned_to)
        else:
            condition = TrueCondition()

        rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=condition,
        ))
        assignments = [self._row_to_dict(row) for row in rows]

        if assigned_to:
            assignments = [a for a in assignments if a.get("assigned_to") == assigned_to]
        if status:
            assignments = [a for a in assignments if a.get("status") == status]

        # Sort by created_at descending
        assignments.sort(key=lambda a: a.get("created_at", ""), reverse=True)
        return assignments

    def update_assignment(
        self,
        assignment_id: str,
        status: str | None = None,
        reason: str | None = None,
        notified: bool | None = None,
    ) -> dict[str, Any] | None:
        """Update an assignment (status, reason, notified)."""
        existing = self.get_assignment(assignment_id)
        if not existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_ASSIGNMENT_NOT_FOUND)

        if status is not None and status not in VALID_STATUSES:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_ROLE_INVALID)

        update_cols: list[str] = []
        update_vals: list[Any] = []

        if status is not None:
            update_cols.append(self.COL_STATUS)
            update_vals.append(status)
            if status in ("completed", "cancelled"):
                update_cols.append(self.COL_COMPLETED)
                update_vals.append(datetime.now(timezone.utc).isoformat())

        if reason is not None:
            update_cols.append(self.COL_REASON)
            update_vals.append(reason)

        if notified is not None:
            update_cols.append(self.COL_NOTIFIED)
            update_vals.append(notified)

        if not update_cols:
            return existing

        self._db.update_in_table(
            table_name=self.TABLE_NAME,
            column_tuple=tuple(update_cols),
            values_list=update_vals,
            condition=EqualCondition(self.COL_ID, assignment_id),
        )

        logger.info("Updated assignment %s: status=%s", assignment_id, status)
        return self.get_assignment(assignment_id)

    def accept_assignment(self, assignment_id: str, user_uid: str) -> dict[str, Any] | None:
        """Accept an assignment (set status to 'accepted')."""
        existing = self.get_assignment(assignment_id)
        if not existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_ASSIGNMENT_NOT_FOUND)
        if existing["assigned_to"] != user_uid:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_ASSIGNMENT_ACCESS_DENIED)
        return self.update_assignment(assignment_id, status="accepted")

    def complete_assignment(self, assignment_id: str, user_uid: str) -> dict[str, Any] | None:
        """Complete an assignment (set status to 'completed')."""
        existing = self.get_assignment(assignment_id)
        if not existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_ASSIGNMENT_NOT_FOUND)
        if existing["assigned_to"] != user_uid:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_ASSIGNMENT_ACCESS_DENIED)
        return self.update_assignment(assignment_id, status="completed")

    def cancel_assignment(self, assignment_id: str) -> dict[str, Any] | None:
        """Cancel an assignment."""
        return self.update_assignment(assignment_id, status="cancelled")

    def delete_assignment(self, assignment_id: str) -> bool:
        """Delete an assignment."""
        existing = self.get_assignment(assignment_id)
        if not existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_ASSIGNMENT_NOT_FOUND)

        self._db.delete_row_in_table(
            table_name=self.TABLE_NAME,
            condition=EqualCondition(self.COL_ID, assignment_id),
        )
        logger.info("Deleted assignment %s", assignment_id)
        return True

    def delete_assignments_for_mailbox(self, mailbox_id: str) -> int:
        """Delete all assignments for a mailbox. Returns count deleted."""
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
        """Convert a DB row to dict."""
        if isinstance(row, dict):
            return row
        return {
            "id": row[0],
            "mailbox_id": row[1],
            "email_id": row[2],
            "assigned_to": row[3],
            "assigned_by": row[4],
            "reason": row[5],
            "status": row[6],
            "notified": bool(row[7]) if row[7] is not None else False,
            "created_at": str(row[8]) if row[8] else None,
            "completed_at": str(row[9]) if row[9] else None,
        }

    @staticmethod
    def ensure_table(db: ClientSQL) -> None:
        """Create the shared mailbox assignments table if it doesn't exist."""
        try:
            from app.utils.db.Table import Column, Table

            cols = [
                Column(name="id", data_type="str", extra_args={"max_len": 64}),
                Column(name="mailbox_id", data_type="str", extra_args={"max_len": 64}),
                Column(name="email_id", data_type="str", extra_args={"max_len": 128}),
                Column(name="assigned_to", data_type="str", extra_args={"max_len": 256}),
                Column(name="assigned_by", data_type="str", extra_args={"max_len": 256}),
                Column(name="reason", data_type="text", is_nullable=True),
                Column(name="status", data_type="str", extra_args={"max_len": 32}),
                Column(name="notified", data_type="bool", is_nullable=True),
                Column(name="created_at", data_type="datetime", is_nullable=True),
                Column(name="completed_at", data_type="datetime", is_nullable=True),
            ]
            table = Table(
                name=ModuleSharedMailboxAssignment.TABLE_NAME,
                columns=cols,
                primary_keys=("id",),
            )
            existing = db.get_table_info(table.name)
            if not existing:
                db.create_table(table)
        except Exception as exc:
            from app.utils.logger.logger import logger as _l
            _l.warning("Could not ensure shared mailbox assignments table: %s", exc)
