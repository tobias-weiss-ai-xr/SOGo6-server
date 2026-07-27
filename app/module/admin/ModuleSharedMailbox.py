from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api as logger_admin
from app.utils.maths.sogo_hash import generate_uuid
from app.utils.db.Condition import EqualCondition, TrueCondition

if TYPE_CHECKING:
    from app.manager.db.ClientSQL import ClientSQL


class ModuleSharedMailbox:
    """Manages shared/team mailboxes (e.g., support@, info@).

    Shared mailboxes allow multiple team members to send and receive email
    from a common address. Each shared mailbox has:
    - An email address (e.g., support@example.org)
    - A display name
    - A list of member UIDs who can access it
    - Optional description and settings
    """

    TABLE_NAME = "sogo6_shared_mailboxes"

    # Column names
    COL_ID = "id"
    COL_EMAIL = "email"
    COL_NAME = "name"
    COL_DESC = "description"
    COL_MEMBERS = "member_uids"
    COL_ACTIVE = "is_active"
    COL_CREATED = "created_at"
    COL_UPDATED = "updated_at"

    ALL_COLS = (COL_ID, COL_EMAIL, COL_NAME, COL_DESC, COL_MEMBERS, COL_ACTIVE, COL_CREATED, COL_UPDATED)

    def __init__(self, db: ClientSQL) -> None:
        self._db = db

    def create(self, email: str, name: str, description: str = "",
               member_uids: list[str] | None = None) -> dict[str, Any]:
        """Create a new shared mailbox."""
        # Check for duplicate
        existing = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=EqualCondition(self.COL_EMAIL, email),
        ))
        if existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_DUPLICATE)

        now = datetime.now(timezone.utc).isoformat()
        mailbox_id = generate_uuid()
        members_json = member_uids or []

        values = [[
            mailbox_id, email, name, description,
            members_json, True, now, now,
        ]]

        self._db.insert_in_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            values_tuple=values,
        )

        logger_admin.info("Created shared mailbox %s <%s>", name, email)
        return self._row_to_dict([
            mailbox_id, email, name, description,
            members_json, True, now, now,
        ])

    def get_all(self) -> list[dict[str, Any]]:
        """Return all shared mailboxes."""
        rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=TrueCondition(),
        ))
        return [self._row_to_dict(row) for row in rows]

    def get_by_id(self, mailbox_id: str) -> dict[str, Any] | None:
        """Return a shared mailbox by ID."""
        rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            condition=EqualCondition(self.COL_ID, mailbox_id),
        ))
        return self._row_to_dict(rows[0]) if rows else None

    def get_for_user(self, user_uid: str) -> list[dict[str, Any]]:
        """Return shared mailboxes accessible by a user."""
        all_mailboxes = self.get_all()
        return [m for m in all_mailboxes if user_uid in m.get("member_uids", [])]

    def update(self, mailbox_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a shared mailbox."""
        existing = self.get_by_id(mailbox_id)
        if not existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_NOT_FOUND)

        allowed_fields = {self.COL_NAME, self.COL_DESC, self.COL_MEMBERS, self.COL_ACTIVE}
        update_cols: list[str] = []
        update_vals: list[Any] = []

        for key in self.ALL_COLS:
            if key in updates and key in allowed_fields:
                update_cols.append(key)
                update_vals.append(updates[key])

        if not update_cols:
            return existing

        update_cols.append(self.COL_UPDATED)
        update_vals.append(datetime.now(timezone.utc).isoformat())

        self._db.update_in_table(
            table_name=self.TABLE_NAME,
            column_tuple=tuple(update_cols),
            values_list=update_vals,
            condition=EqualCondition(self.COL_ID, mailbox_id),
        )

        logger_admin.info("Updated shared mailbox %s", mailbox_id)
        return {**existing, **{k: v for k, v in zip(update_cols, update_vals)}}

    def delete(self, mailbox_id: str) -> None:
        """Delete a shared mailbox."""
        existing = self.get_by_id(mailbox_id)
        if not existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_NOT_FOUND)

        self._db.delete_row_in_table(
            table_name=self.TABLE_NAME,
            condition=EqualCondition(self.COL_ID, mailbox_id),
        )

        logger_admin.info("Deleted shared mailbox %s <%s>", existing.get("name"), existing.get("email"))

    def add_member(self, mailbox_id: str, user_uid: str) -> dict[str, Any]:
        """Add a user as a member of a shared mailbox."""
        existing = self.get_by_id(mailbox_id)
        if not existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_NOT_FOUND)

        members: list[str] = existing.get("member_uids") or []
        if user_uid not in members:
            members.append(user_uid)
            return self.update(mailbox_id, {self.COL_MEMBERS: members})

        return existing

    def remove_member(self, mailbox_id: str, user_uid: str) -> dict[str, Any]:
        """Remove a user from a shared mailbox's member list."""
        existing = self.get_by_id(mailbox_id)
        if not existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_NOT_FOUND)

        members: list[str] = existing.get("member_uids") or []
        if user_uid in members:
            members.remove(user_uid)
            return self.update(mailbox_id, {self.COL_MEMBERS: members})

        return existing

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        """Convert a DB row (tuple) to a dict."""
        if isinstance(row, dict):
            return row
        return {
            "id": row[0],
            "email": row[1],
            "name": row[2],
            "description": row[3],
            "member_uids": row[4] if isinstance(row[4], list) else [],
            "is_active": bool(row[5]) if row[5] else True,
            "created_at": str(row[6]) if row[6] else None,
            "updated_at": str(row[7]) if row[7] else None,
        }

    @staticmethod
    def ensure_table(db: ClientSQL) -> None:
        """Create the shared mailboxes table if it doesn't exist."""
        try:
            from app.utils.db.Table import Column, Table

            cols = [
                Column(name="id", data_type="text", extra_args={"max_len": 64}),
                Column(name="email", data_type="text", is_unique=True, extra_args={"max_len": 256}),
                Column(name="name", data_type="text", extra_args={"max_len": 256}),
                Column(name="description", data_type="text", is_nullable=True, extra_args={"max_len": 1024}),
                Column(name="member_uids", data_type="json", is_nullable=True),
                Column(name="is_active", data_type="bool", is_nullable=False),
                Column(name="created_at", data_type="datetime", is_nullable=True),
                Column(name="updated_at", data_type="datetime", is_nullable=True),
            ]
            table = Table(
                name=ModuleSharedMailbox.TABLE_NAME,
                columns=cols,
                primary_keys=("id",),
            )
            existing = db.get_table_info(table.name)
            if not existing:
                db.create_table(table)
        except Exception as exc:
            from app.utils.logger.logger import logger
            logger.warning("Could not ensure shared mailboxes table: %s", exc)
