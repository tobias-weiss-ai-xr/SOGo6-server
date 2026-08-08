"""JMAP mail gateway — the thin adapter between JMAP methods and the IMAP store.

Wraps the real mail stack (ModuleMail -> ClientMailServer -> IMAP) so the
JMAP endpoint layer stays pure protocol: JSON in/out, RFC 8620/8621 types
mapped here.  Every call goes to the configured mail store; there is no
simulated data anywhere in this path.
"""
from __future__ import annotations

from typing import Any

from app.auth.User import User
from app.config.settings.DomainSettings import MailSettings, MailSettingsObj
from app.module.mail.ModuleMail import ModuleMail
from app.utils import constants as cs
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api


class JmapMailGateway:
    """Per-request adapter over ModuleMail. Raises RequestException on store errors."""

    def __init__(self, process_setting, user_domain_settings: dict, user: User) -> None:
        domain: dict = user_domain_settings or {}
        self.mail_settings = MailSettingsObj(domain.get(MailSettings.subparent, {}))
        self.user = user
        self.module = ModuleMail(user, self.mail_settings)

    # ---- mailbox listing ------------------------------------------------- #

    def list_mailbox_rows(self, account_id: str) -> list[dict[str, Any]]:
        """Real IMAP folder list (with counts) for the account."""
        return self.module.get_folder_list(account_id)

    def create_mailbox(self, account_id: str, name: str, parent_path: str = "") -> dict[str, Any]:
        """Create a real IMAP folder; returns its details."""
        return self.module.create_folder(account_id, name, parent_path)

    def delete_mailbox(self, account_id: str, folder_path: str) -> None:
        self.module.delete_folder(account_id, folder_path)

    # ------------------------------------------------------------------ #
    # email access
    # ------------------------------------------------------------------ #

    def get_mail(self, account_id: str, folder_path: str, mail_uid: str) -> dict[str, Any]:
        """Full mail detail (uid, flags, headers, contents, attachments)."""
        return self.module.get_mail_detail(account_id, folder_path, mail_uid)

    def get_mails(self, account_id: str, folder_path: str, limit: int, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        """Page of mails (metadata only, no contents) + total count."""
        from app.utils.api.paginate_sort_filter import CollectionPaginateArgs

        page = offset // max(limit, 1) + 1
        collection = CollectionPaginateArgs(
            page=page,
            page_size=max(limit, 1),
            fields="uid",
            fields_action="include",
        )
        return self.module.get_folder_mails(account_id, folder_path, collection)

    def destroy_mail(self, account_id: str, folder_path: str, mail_uid: str) -> None:
        self.module.delete_mails(account_id, folder_path, mail_uid)

    def move_mail(self, account_id: str, from_folder: str, mail_uid: int, to_folder: str) -> None:
        self.module.move_mails(account_id, from_folder, [mail_uid], to_folder)

    # ------------------------------------------------------------------ #
    # RFC-role mapping helper (kept here so the endpoint stays protocol-only)
    # ------------------------------------------------------------------ #

    @staticmethod
    def role_for_folder(folder_type: str | None, path: str, name: str) -> str | None:
        """Map a store folder to its JMAP mailbox role (RFC 8621 §2.1)."""
        if not folder_type:
            folder_type = ""
        low = folder_type.lower()
        path_low = path.lower()
        name_low = name.lower()
        if low == "inbox" or path_low == "inbox" or name_low == "inbox":
            return "inbox"
        if low == "sent" or "sent" in path_low:
            return "sent"
        if low == "drafts" or "draft" in path_low:
            return "drafts"
        if low == "trash" or "trash" in path_low:
            return "trash"
        if low == "junk" or "junk" in path_low or "spam" in path_low:
            return "junk"
        if low == "archive" or "archive" in path_low:
            return "archive"
        return None