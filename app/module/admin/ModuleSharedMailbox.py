from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_admin
from app.utils.maths.sogo_hash import generate_uuid

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

    def __init__(self, db: ClientSQL) -> None:
        self._db = db

    def create(self, email: str, name: str, description: str = "",
               member_uids: list[str] | None = None) -> dict[str, Any]:
        """Create a new shared mailbox.

        :param email: The shared email address (e.g., support@example.org).
        :param name: Display name for the shared mailbox.
        :param description: Optional description.
        :param member_uids: Optional list of user UIDs to add as members.
        :return: The created shared mailbox dict.
        :raises RequestException: If the email already exists.
        """
        # Check for duplicate
        existing = self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=("*",),
            condition=f"email = '{email}'",
        )
        if existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_DUPLICATE)

        now = datetime.now(timezone.utc).isoformat()
        mailbox_id = generate_uuid()
        data = {
            "id": mailbox_id,
            "email": email,
            "name": name,
            "description": description,
            "member_uids": member_uids or [],
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }

        self._db.insert_into_table(
            table_name=self.TABLE_NAME,
            data=data,
        )

        logger_admin.info("Created shared mailbox %s <%s>", name, email)
        return data

    def get_all(self) -> list[dict[str, Any]]:
        """Return all shared mailboxes."""
        rows = self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=("*",),
            sort_by="name",
        )
        return [self._row_to_dict(row) for row in rows]

    def get_by_id(self, mailbox_id: str) -> dict[str, Any] | None:
        """Return a shared mailbox by ID."""
        rows = self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=("*",),
            condition=f"id = '{mailbox_id}'",
        )
        return self._row_to_dict(rows[0]) if rows else None

    def get_for_user(self, user_uid: str) -> list[dict[str, Any]]:
        """Return shared mailboxes accessible by a user."""
        all_mailboxes = self.get_all()
        return [m for m in all_mailboxes if user_uid in m.get("member_uids", [])]

    def update(self, mailbox_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a shared mailbox.

        :param mailbox_id: The shared mailbox ID.
        :param updates: Dict with fields to update (name, description, member_uids, is_active).
        :return: The updated shared mailbox dict.
        :raises RequestException: If not found.
        """
        existing = self.get_by_id(mailbox_id)
        if not existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_NOT_FOUND)

        allowed_fields = {"name", "description", "member_uids", "is_active"}
        update_data = {k: v for k, v in updates.items() if k in allowed_fields}
        if not update_data:
            return existing

        update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

        self._db.update_table(
            table_name=self.TABLE_NAME,
            data=update_data,
            condition=f"id = '{mailbox_id}'",
        )

        logger_admin.info("Updated shared mailbox %s", mailbox_id)
        return {**existing, **update_data}

    def delete(self, mailbox_id: str) -> None:
        """Delete a shared mailbox.

        :raises RequestException: If not found.
        """
        existing = self.get_by_id(mailbox_id)
        if not existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_NOT_FOUND)

        self._db.delete_from_table(
            table_name=self.TABLE_NAME,
            condition=f"id = '{mailbox_id}'",
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
            return self.update(mailbox_id, {"member_uids": members})

        return existing

    def remove_member(self, mailbox_id: str, user_uid: str) -> dict[str, Any]:
        """Remove a user from a shared mailbox's member list."""
        existing = self.get_by_id(mailbox_id)
        if not existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_NOT_FOUND)

        members: list[str] = existing.get("member_uids") or []
        if user_uid in members:
            members.remove(user_uid)
            return self.update(mailbox_id, {"member_uids": members})

        return existing

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        """Convert a DB row to a dict, handling tuple or dict formats."""
        if isinstance(row, dict):
            return row
        # Tuple format
        return {
            "id": row[0],
            "email": row[1],
            "name": row[2],
            "description": row[3],
            "member_uids": row[4] if isinstance(row[4], list) else [],
            "is_active": row[5] if isinstance(row[5], bool) else True,
            "created_at": str(row[6]) if row[6] else None,
            "updated_at": str(row[7]) if row[7] else None,
        }

    @staticmethod
    def ensure_table(db: ClientSQL) -> None:
        """Create the shared mailboxes table if it doesn't exist."""
        db.create_table(
            table_name=ModuleSharedMailbox.TABLE_NAME,
            columns=[
                ("id", "TEXT PRIMARY KEY"),
                ("email", "TEXT UNIQUE NOT NULL"),
                ("name", "TEXT NOT NULL"),
                ("description", "TEXT DEFAULT ''"),
                ("member_uids", "JSONB DEFAULT '[]'"),
                ("is_active", "BOOLEAN DEFAULT TRUE"),
                ("created_at", "TIMESTAMP DEFAULT NOW()"),
                ("updated_at", "TIMESTAMP DEFAULT NOW()"),
            ],
        )
