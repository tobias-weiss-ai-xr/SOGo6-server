from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.config.db import tables as tbl
from app.module.contact.model.ContactShare import ContactShare
from app.module.contact.model.enums.ContactShareLevel import ContactShareLevel
from app.utils import errors as err
from app.utils.db.Condition import AndCondition, EqualCondition
from app.utils.exceptions import BugException, RequestException
from app.utils.logger.logger import logger_contact

if TYPE_CHECKING:
    from app.manager.db.ClientSQL import ClientSQL


# All column names in ALL_CONTACT_SHARE_COL order
_ALL_COLS: tuple[str, ...] = tuple(col.name for col in tbl.ALL_CONTACT_SHARE_COL)

# Columns for INSERT - id is serial, omitted
_INSERT_COLS: tuple[str, ...] = tuple(
    col.name for col in tbl.ALL_CONTACT_SHARE_COL if col.name != tbl.COL_ID.name
)


class RepositoryContactShare:
    """Handles all DB reads and writes for sogo6_contacts_shares."""

    def __init__(self, db: ClientSQL) -> None:
        self._db = db

    @staticmethod
    def _row_to_share(row: tuple) -> ContactShare:
        """Map a DB row to a ContactShare model."""
        d = dict(zip(_ALL_COLS, row))
        return ContactShare(
            user_uid=d["user_uid"],
            addressbook_key=d["addressbook_key"],
            share_level=ContactShareLevel[d["share_level"].upper()],
        )

    def insert(self, share: ContactShare) -> ContactShare:
        """Persist a new share entry and return it."""
        now = datetime.now(timezone.utc)
        values = [[
            share.addressbook_key,
            share.user_uid,
            share.share_level.name.lower(),
            now,
        ]]

        try:
            inserted = self._db.insert_in_table(
                table_name=tbl.TABLE_CONTACT_SHARE.name,
                column_tuple=_INSERT_COLS,
                values_tuple=values,
            )
        except BugException as exc:
            logger_contact.error(
                "Unique violation inserting share addressbook_key=%s user=%s: %s",
                share.addressbook_key, share.user_uid, exc,
            )
            raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_DUPLICATE) from exc

        if inserted != 1:
            logger_contact.error(
                "Contact share insert affected %s rows instead of 1 (addressbook_key=%s, user=%s)",
                inserted, share.addressbook_key, share.user_uid,
            )
            raise BugException("Contact share insert did not affect exactly 1 row")

        return share

    def find_by_addressbook_key(self, addressbook_key: str) -> list[ContactShare]:
        """Return all shares for the given address book, ordered by id."""
        condition = EqualCondition(tbl.COL_CONTACT_SHARE_ADDRESSBOOK_KEY.name, addressbook_key)
        rows = self._db.select_from_table(
            table_name=tbl.TABLE_CONTACT_SHARE.name,
            column_tuple=_ALL_COLS,
            condition=condition,
            sort_by=tbl.COL_ID.name,
        )
        return [self._row_to_share(row) for row in rows]

    def find_by_addressbook_and_user(self, addressbook_key: str, user_uid: str) -> ContactShare | None:
        """Return the share for a specific user on an address book, or None."""
        condition = AndCondition(
            EqualCondition(tbl.COL_CONTACT_SHARE_ADDRESSBOOK_KEY.name, addressbook_key),
            EqualCondition(tbl.COL_CONTACT_SHARE_USER_UID.name, user_uid),
        )
        rows = list(self._db.select_from_table(
            table_name=tbl.TABLE_CONTACT_SHARE.name,
            column_tuple=_ALL_COLS,
            condition=condition,
            limit=1,
        ))
        if not rows:
            return None
        return self._row_to_share(rows[0])

    def find_addressbook_keys_for_user(self, user_uid: str) -> list[str]:
        """Return all address book keys that are shared with the given user."""
        condition = EqualCondition(tbl.COL_CONTACT_SHARE_USER_UID.name, user_uid)
        rows = self._db.select_from_table(
            table_name=tbl.TABLE_CONTACT_SHARE.name,
            column_tuple=(tbl.COL_CONTACT_SHARE_ADDRESSBOOK_KEY.name,),
            condition=condition,
        )
        return [row[0] for row in rows]

    def delete(self, addressbook_key: str, user_uid: str) -> None:
        """Remove a share entry for the given user on the given address book."""
        condition = AndCondition(
            EqualCondition(tbl.COL_CONTACT_SHARE_ADDRESSBOOK_KEY.name, addressbook_key),
            EqualCondition(tbl.COL_CONTACT_SHARE_USER_UID.name, user_uid),
        )
        deleted = self._db.delete_row_in_table(
            table_name=tbl.TABLE_CONTACT_SHARE.name,
            condition=condition,
            expected_row=1,
        )
        if deleted == 0:
            logger_contact.error(
                "Contact share not found for addressbook_key=%s user=%s on delete",
                addressbook_key, user_uid,
            )
            raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND)
