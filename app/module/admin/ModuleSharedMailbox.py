"""Shared mailbox management module.

Extended implementation supporting:
- Quota settings (max size, max emails)
- Auto-responder (subject, message)
- Email forwarding (forward_to, keep_copy)
- Signatures (HTML, plain text)
- Member roles (admin, moderator, member)
- Member activity tracking

Tables:
- sogo6_shared_mailboxes — mailbox configuration with extended fields
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api as logger_admin
from app.utils.maths.sogo_hash import generate_uuid
from app.utils.db.Condition import EqualCondition, TrueCondition

if TYPE_CHECKING:
    from app.manager.db.ClientSQL import ClientSQL

VALID_ROLES = ("admin", "moderator", "member")


class ModuleSharedMailbox:
    """Manages shared/team mailboxes (e.g., support@, info@).

    Shared mailboxes allow multiple team members to send and receive email
    from a common address. Each shared mailbox has:
    - An email address (e.g., support@example.org)
    - A display name
    - A list of members with roles (admin, moderator, member)
    - Optional description and settings
    - Quota settings (max size, max emails)
    - Auto-responder configuration
    - Email forwarding rules
    - Custom signatures (HTML and plain text)
    """

    TABLE_NAME = "sogo6_shared_mailboxes"

    # Core column names
    COL_ID = "id"
    COL_EMAIL = "email"
    COL_NAME = "name"
    COL_DESC = "description"
    COL_MEMBERS = "member_uids"
    COL_MEMBER_ROLES = "member_roles"
    COL_ACTIVE = "is_active"
    COL_CREATED = "created_at"
    COL_UPDATED = "updated_at"

    # Extended: Quota
    COL_QUOTA_ENABLED = "quota_enabled"
    COL_QUOTA_MAX_SIZE = "quota_max_size"
    COL_QUOTA_MAX_EMAILS = "quota_max_emails"

    # Extended: Auto-responder
    COL_AUTO_RESPOND_ENABLED = "auto_respond_enabled"
    COL_AUTO_RESPOND_SUBJECT = "auto_respond_subject"
    COL_AUTO_RESPOND_MESSAGE = "auto_respond_message"

    # Extended: Forwarding
    COL_FORWARD_TO = "forward_to"
    COL_FORWARD_KEEP_COPY = "forward_keep_copy"

    # Extended: Signatures
    COL_SIGNATURE_ENABLED = "signature_enabled"
    COL_SIGNATURE_HTML = "signature_html"
    COL_SIGNATURE_PLAIN = "signature_plain"

    ALL_COLS = (
        COL_ID, COL_EMAIL, COL_NAME, COL_DESC, COL_MEMBERS, COL_MEMBER_ROLES,
        COL_ACTIVE, COL_CREATED, COL_UPDATED,
        COL_QUOTA_ENABLED, COL_QUOTA_MAX_SIZE, COL_QUOTA_MAX_EMAILS,
        COL_AUTO_RESPOND_ENABLED, COL_AUTO_RESPOND_SUBJECT, COL_AUTO_RESPOND_MESSAGE,
        COL_FORWARD_TO, COL_FORWARD_KEEP_COPY,
        COL_SIGNATURE_ENABLED, COL_SIGNATURE_HTML, COL_SIGNATURE_PLAIN,
    )

    # Fields that can be updated
    UPDATABLE_FIELDS = {
        COL_NAME, COL_DESC, COL_MEMBERS, COL_MEMBER_ROLES, COL_ACTIVE,
        COL_QUOTA_ENABLED, COL_QUOTA_MAX_SIZE, COL_QUOTA_MAX_EMAILS,
        COL_AUTO_RESPOND_ENABLED, COL_AUTO_RESPOND_SUBJECT, COL_AUTO_RESPOND_MESSAGE,
        COL_FORWARD_TO, COL_FORWARD_KEEP_COPY,
        COL_SIGNATURE_ENABLED, COL_SIGNATURE_HTML, COL_SIGNATURE_PLAIN,
    }

    def __init__(self, db: ClientSQL) -> None:
        self._db = db

    # ── CRUD ───────────────────────────────────────────────────────────────

    def create(
        self,
        email: str,
        name: str,
        description: str = "",
        member_uids: list[str] | None = None,
        *,
        is_active: bool = True,
        quota_enabled: bool = False,
        quota_max_size: int | None = None,
        quota_max_emails: int | None = None,
        auto_respond_enabled: bool = False,
        auto_respond_subject: str | None = None,
        auto_respond_message: str | None = None,
        forward_to: list[str] | None = None,
        forward_keep_copy: bool = True,
        signature_enabled: bool = False,
        signature_html: str | None = None,
        signature_plain: str | None = None,
    ) -> dict[str, Any]:
        """Create a new shared mailbox with extended fields."""
        existing = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=(self.COL_ID,),
            condition=EqualCondition(self.COL_EMAIL, email),
        ))
        if existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_DUPLICATE)

        now = datetime.now(timezone.utc).isoformat()
        mailbox_id = generate_uuid()
        members_json = member_uids or []
        member_roles_json = self._build_member_roles(members_json)

        values = [[
            mailbox_id, email, name, description,
            members_json, member_roles_json, is_active, now, now,
            quota_enabled, quota_max_size, quota_max_emails,
            auto_respond_enabled, auto_respond_subject, auto_respond_message,
            forward_to or [], forward_keep_copy,
            signature_enabled, signature_html, signature_plain,
        ]]

        self._db.insert_in_table(
            table_name=self.TABLE_NAME,
            column_tuple=self.ALL_COLS,
            values_tuple=values,
        )

        logger_admin.info("Created shared mailbox %s <%s>", name, email)
        return self.get_by_id(mailbox_id)  # type: ignore[return-value]

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
        """Return shared mailboxes accessible by a user (with role)."""
        all_mailboxes = self.get_all()
        result = []
        for mb in all_mailboxes:
            role = self._get_member_role(mb, user_uid)
            if role:
                mb_copy = dict(mb)
                mb_copy["role"] = role
                result.append(mb_copy)
        return result

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search shared mailboxes by name, email or description.

        Returns mailboxes whose name, email or description contains the query
        (case-insensitive). When query is empty, all mailboxes are returned.
        """
        q = (query or "").strip().lower()
        mailboxes = self.get_all()
        if not q:
            return mailboxes
        return [
            mb for mb in mailboxes
            if q in (mb.get("name") or "").lower()
            or q in (mb.get("email") or "").lower()
            or q in (mb.get("description") or "").lower()
        ]

    # ── Import / Export ────────────────────────────────────────────────────

    @staticmethod
    def _config_from_mailbox(mailbox: dict[str, Any]) -> dict[str, Any]:
        """Build a portable configuration dict for a mailbox (no internal ids)."""
        return {
            "email": mailbox.get("email"),
            "name": mailbox.get("name"),
            "description": mailbox.get("description") or "",
            "is_active": mailbox.get("is_active", True),
            "member_uids": mailbox.get("member_uids") or [],
            "quota_enabled": mailbox.get("quota_enabled", False),
            "quota_max_size": mailbox.get("quota_max_size"),
            "quota_max_emails": mailbox.get("quota_max_emails"),
            "auto_respond_enabled": mailbox.get("auto_respond_enabled", False),
            "auto_respond_subject": mailbox.get("auto_respond_subject"),
            "auto_respond_message": mailbox.get("auto_respond_message"),
            "forward_to": mailbox.get("forward_to") or [],
            "forward_keep_copy": mailbox.get("forward_keep_copy", True),
            "signature_enabled": mailbox.get("signature_enabled", False),
            "signature_html": mailbox.get("signature_html"),
            "signature_plain": mailbox.get("signature_plain"),
        }

    def export_config(self, mailbox_id: str) -> dict[str, Any]:
        """Export a single mailbox as a portable configuration dict."""
        mailbox = self.get_by_id(mailbox_id)
        if not mailbox:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_NOT_FOUND)
        return self._config_from_mailbox(mailbox)

    def export_all_configs(self) -> list[dict[str, Any]]:
        """Export all mailboxes as portable configuration dicts."""
        return [self._config_from_mailbox(mb) for mb in self.get_all()]

    def import_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Create (or update) a shared mailbox from a configuration dict.

        If a mailbox with the same email already exists, its settings are
        updated with the imported values (idempotent import).
        """
        email = config.get("email")
        if not email:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_DUPLICATE)

        existing_rows = list(self._db.select_from_table(
            table_name=self.TABLE_NAME,
            column_tuple=(self.COL_ID,),
            condition=EqualCondition(self.COL_EMAIL, email),
        ))
        if existing_rows:
            # Idempotent update for existing mailbox
            updates = {
                "name": config.get("name"),
                "description": config.get("description"),
                "is_active": config.get("is_active", True),
                "member_uids": config.get("member_uids") or [],
                "quota_enabled": config.get("quota_enabled", False),
                "quota_max_size": config.get("quota_max_size"),
                "quota_max_emails": config.get("quota_max_emails"),
                "auto_respond_enabled": config.get("auto_respond_enabled", False),
                "auto_respond_subject": config.get("auto_respond_subject"),
                "auto_respond_message": config.get("auto_respond_message"),
                "forward_to": config.get("forward_to") or [],
                "forward_keep_copy": config.get("forward_keep_copy", True),
                "signature_enabled": config.get("signature_enabled", False),
                "signature_html": config.get("signature_html"),
                "signature_plain": config.get("signature_plain"),
            }
            return self.update(existing_rows[0][0], updates)

        return self.create(
            email=email,
            name=config.get("name") or email,
            description=config.get("description") or "",
            member_uids=config.get("member_uids") or None,
            is_active=config.get("is_active", True),
            quota_enabled=config.get("quota_enabled", False),
            quota_max_size=config.get("quota_max_size"),
            quota_max_emails=config.get("quota_max_emails"),
            auto_respond_enabled=config.get("auto_respond_enabled", False),
            auto_respond_subject=config.get("auto_respond_subject"),
            auto_respond_message=config.get("auto_respond_message"),
            forward_to=config.get("forward_to") or None,
            forward_keep_copy=config.get("forward_keep_copy", True),
            signature_enabled=config.get("signature_enabled", False),
            signature_html=config.get("signature_html"),
            signature_plain=config.get("signature_plain"),
        )

    def update(self, mailbox_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a shared mailbox. Only allowed fields are applied."""
        existing = self.get_by_id(mailbox_id)
        if not existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_NOT_FOUND)

        update_cols: list[str] = []
        update_vals: list[Any] = []

        for key in self.ALL_COLS:
            if key in updates and key in self.UPDATABLE_FIELDS:
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
        return self.get_by_id(mailbox_id)  # type: ignore[return-value]

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

    # ── Member Management with Roles ──────────────────────────────────────

    def add_member(self, mailbox_id: str, user_uid: str, role: str = "member") -> dict[str, Any]:
        """Add a user as a member of a shared mailbox with a role."""
        if role not in VALID_ROLES:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_ROLE_INVALID)

        existing = self.get_by_id(mailbox_id)
        if not existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_NOT_FOUND)

        members: list[str] = existing.get("member_uids") or []
        if user_uid in members:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_MEMBER_ALREADY_EXISTS)

        members.append(user_uid)
        member_roles: list[dict] = existing.get("member_roles") or []
        now = datetime.now(timezone.utc).isoformat()
        member_roles.append({
            "uid": user_uid,
            "role": role,
            "added_at": now,
            "last_activity_at": None,
        })

        return self.update(mailbox_id, {
            self.COL_MEMBERS: members,
            self.COL_MEMBER_ROLES: member_roles,
        })

    def remove_member(self, mailbox_id: str, user_uid: str) -> dict[str, Any]:
        """Remove a user from a shared mailbox."""
        existing = self.get_by_id(mailbox_id)
        if not existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_NOT_FOUND)

        members: list[str] = existing.get("member_uids") or []
        if user_uid not in members:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_MEMBER_NOT_FOUND)

        members.remove(user_uid)
        member_roles: list[dict] = existing.get("member_roles") or []
        member_roles = [mr for mr in member_roles if mr.get("uid") != user_uid]

        return self.update(mailbox_id, {
            self.COL_MEMBERS: members,
            self.COL_MEMBER_ROLES: member_roles,
        })

    def update_member_role(self, mailbox_id: str, user_uid: str, role: str) -> dict[str, Any]:
        """Update a member's role."""
        if role not in VALID_ROLES:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_ROLE_INVALID)

        existing = self.get_by_id(mailbox_id)
        if not existing:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_NOT_FOUND)

        member_roles: list[dict] = existing.get("member_roles") or []
        found = False
        for mr in member_roles:
            if mr.get("uid") == user_uid:
                mr["role"] = role
                found = True
                break

        if not found:
            raise RequestException(error=err.ERROR_SHARED_MAILBOX_MEMBER_NOT_FOUND)

        return self.update(mailbox_id, {self.COL_MEMBER_ROLES: member_roles})

    def get_member_role(self, mailbox_id: str, user_uid: str) -> str | None:
        """Get a user's role for a shared mailbox (or None if not a member)."""
        mb = self.get_by_id(mailbox_id)
        if not mb:
            return None
        return self._get_member_role(mb, user_uid)

    def update_member_activity(self, mailbox_id: str, user_uid: str) -> None:
        """Update last_activity_at for a member."""
        existing = self.get_by_id(mailbox_id)
        if not existing:
            return
        member_roles: list[dict] = existing.get("member_roles") or []
        now = datetime.now(timezone.utc).isoformat()
        for mr in member_roles:
            if mr.get("uid") == user_uid:
                mr["last_activity_at"] = now
                break
        self.update(mailbox_id, {self.COL_MEMBER_ROLES: member_roles})

    # ── Permission helpers ─────────────────────────────────────────────────

    def check_permission(self, mailbox_id: str, user_uid: str, required_role: str = "member") -> bool:
        """Check if a user has the required role (or higher) for a mailbox.

        Role hierarchy: admin > moderator > member
        """
        role = self.get_member_role(mailbox_id, user_uid)
        if not role:
            return False
        role_order = {"member": 1, "moderator": 2, "admin": 3}
        return role_order.get(role, 0) >= role_order.get(required_role, 0)

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _build_member_roles(member_uids: list[str]) -> list[dict]:
        """Build default member_roles JSON from a list of UIDs (all 'member')."""
        now = datetime.now(timezone.utc).isoformat()
        return [
            {"uid": uid, "role": "member", "added_at": now, "last_activity_at": None}
            for uid in member_uids
        ]

    @staticmethod
    def _get_member_role(mailbox: dict[str, Any], user_uid: str) -> str | None:
        """Extract a user's role from a mailbox dict."""
        member_roles: list[dict] = mailbox.get("member_roles") or []
        for mr in member_roles:
            if mr.get("uid") == user_uid:
                return mr.get("role")
        # Fallback: if member_uids contains the user but member_roles doesn't,
        # they're a legacy "member"
        if user_uid in (mailbox.get("member_uids") or []):
            return "member"
        return None

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        """Convert a DB row (tuple) to a dict with JSON normalization."""
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

        member_uids = _parse_json(row[4], [])
        if not isinstance(member_uids, list):
            member_uids = []
        member_roles = _parse_json(row[5], [])
        if not isinstance(member_roles, list):
            member_roles = []
        forward_to = _parse_json(row[15], [])
        if not isinstance(forward_to, list):
            forward_to = []

        return {
            "id": row[0],
            "email": row[1],
            "name": row[2],
            "description": row[3],
            "member_uids": member_uids,
            "member_roles": member_roles,
            "is_active": bool(row[6]) if row[6] is not None else True,
            "created_at": str(row[7]) if row[7] else None,
            "updated_at": str(row[8]) if row[8] else None,
            "quota_enabled": bool(row[9]) if row[9] is not None else False,
            "quota_max_size": row[10],
            "quota_max_emails": row[11],
            "auto_respond_enabled": bool(row[12]) if row[12] is not None else False,
            "auto_respond_subject": row[13],
            "auto_respond_message": row[14],
            "forward_to": forward_to,
            "forward_keep_copy": bool(row[16]) if row[16] is not None else True,
            "signature_enabled": bool(row[17]) if row[17] is not None else False,
            "signature_html": row[18],
            "signature_plain": row[19],
        }

    # ── Table creation ─────────────────────────────────────────────────────

    @staticmethod
    def ensure_table(db: ClientSQL) -> None:
        """Create the shared mailboxes table with extended columns."""
        try:
            from app.utils.db.Table import Column, Table

            cols = [
                Column(name="id", data_type="str", extra_args={"max_len": 64}),
                Column(name="email", data_type="str", is_unique=True, extra_args={"max_len": 256}),
                Column(name="name", data_type="str", extra_args={"max_len": 256}),
                Column(name="description", data_type="text", is_nullable=True, extra_args={"max_len": 1024}),
                Column(name="member_uids", data_type="json", is_nullable=True),
                Column(name="member_roles", data_type="json", is_nullable=True),
                Column(name="is_active", data_type="bool", is_nullable=False),
                Column(name="created_at", data_type="datetime", is_nullable=True),
                Column(name="updated_at", data_type="datetime", is_nullable=True),
                # Quota
                Column(name="quota_enabled", data_type="bool", is_nullable=True),
                Column(name="quota_max_size", data_type="int", is_nullable=True),
                Column(name="quota_max_emails", data_type="int", is_nullable=True),
                # Auto-responder
                Column(name="auto_respond_enabled", data_type="bool", is_nullable=True),
                Column(name="auto_respond_subject", data_type="str", is_nullable=True, extra_args={"max_len": 256}),
                Column(name="auto_respond_message", data_type="text", is_nullable=True),
                # Forwarding
                Column(name="forward_to", data_type="json", is_nullable=True),
                Column(name="forward_keep_copy", data_type="bool", is_nullable=True),
                # Signatures
                Column(name="signature_enabled", data_type="bool", is_nullable=True),
                Column(name="signature_html", data_type="text", is_nullable=True),
                Column(name="signature_plain", data_type="text", is_nullable=True),
            ]
            table = Table(
                name=ModuleSharedMailbox.TABLE_NAME,
                columns=cols,
                primary_keys=("id",),
            )
            existing = db.get_table_info(table.name)
            if not existing:
                db.create_table(table)
            else:
                # Migration: add new columns if they don't exist
                ModuleSharedMailbox._migrate_add_columns(db, existing)
        except Exception as exc:
            from app.utils.logger.logger import logger
            logger.warning("Could not ensure shared mailboxes table: %s", exc)

    @staticmethod
    def _migrate_add_columns(db: ClientSQL, existing_info: Any) -> None:
        """Add new columns to existing table if they don't exist."""
        try:
            existing_cols = set()
            if isinstance(existing_info, list):
                for col_info in existing_info:
                    if isinstance(col_info, dict):
                        existing_cols.add(col_info.get("name", ""))
                    elif isinstance(col_info, (list, tuple)) and len(col_info) > 0:
                        existing_cols.add(col_info[0])
            elif isinstance(existing_info, dict):
                existing_cols = {k for k in existing_info.keys()}

            new_cols = [
                ("member_roles", "json"),
                ("quota_enabled", "bool"),
                ("quota_max_size", "int"),
                ("quota_max_emails", "int"),
                ("auto_respond_enabled", "bool"),
                ("auto_respond_subject", "str"),
                ("auto_respond_message", "text"),
                ("forward_to", "json"),
                ("forward_keep_copy", "bool"),
                ("signature_enabled", "bool"),
                ("signature_html", "text"),
                ("signature_plain", "text"),
            ]
            for col_name, col_type in new_cols:
                if col_name not in existing_cols:
                    try:
                        db.add_column_to_table(
                            table_name=ModuleSharedMailbox.TABLE_NAME,
                            column_name=col_name,
                            data_type=col_type,
                            is_nullable=True,
                        )
                    except Exception:
                        continue
        except Exception:
            pass  # Best-effort migration  # best-effort: keep fallback/default value on failure
