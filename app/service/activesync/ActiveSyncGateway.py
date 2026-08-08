"""ActiveSync gateway — thin adapter between EAS commands and the mail stack.

Wraps the real store (ModuleMail) and outgoing (ModuleMailOutgoing) so the
EAS endpoint layer stays pure protocol: WBXML in/out, folders + mails +
attachments + send mapped here.  Every call reaches the configured mail/SMTP
store; there is no simulated data anywhere in this path.
"""
from __future__ import annotations

from typing import Any

from app.auth.User import User
from app.config.settings.DomainSettings import MailSettings, MailSettingsObj
from app.module.mail.ModuleMail import ModuleMail
from app.module.mail.ModuleMailOutgoing import ModuleMailOutgoing


class ActiveSyncGateway:
    """Per-request adapter over ModuleMail + ModuleMailOutgoing."""

    def __init__(self, process_setting, user_domain_settings: dict, user: User) -> None:
        domain: dict = user_domain_settings or {}
        self.mail_settings = MailSettingsObj(domain.get(MailSettings.subparent, {}))
        self.user = user
        self.module = ModuleMail(user, self.mail_settings)

    # ---- folder store --------------------------------------------------- #

    def list_mailbox_rows(self, account_id: str) -> list[dict[str, Any]]:
        """Real IMAP folder list (with counts) for the account."""
        return self.module.get_folder_list(account_id)

    def get_folder_mails(self, account_id: str, folder: str, limit: int, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        """Page of mails (metadata only, no full contents) + total count."""
        from app.utils.api.paginate_sort_filter import CollectionPaginateArgs

        page = offset // max(limit, 1) + 1
        collection = CollectionPaginateArgs(
            page=page,
            page_size=max(limit, 1),
            fields="uid",
            fields_action="include",
        )
        return self.module.get_folder_mails(account_id, folder, collection)

    def get_mail_detail(self, account_id: str, folder: str, mail_uid: str) -> dict[str, Any]:
        """Full parsed mail detail for one UID."""
        return self.module.get_mail_detail(account_id, folder, mail_uid)

    def get_mail_raw(self, account_id: str, folder: str, mail_uid: str) -> str:
        """Raw RFC 5322 source of one message (used for Sync bodies + attachments)."""
        return self.module.get_mail_raw(account_id, folder, mail_uid)["raw"]

    def destroy_mail(self, account_id: str, folder: str, mail_uid: str) -> None:
        self.module.delete_mails(account_id, folder, mail_uid)

    # ---- send ------------------------------------------------------------ #

    def send_message(self, account_id: str, message) -> None:
        """Send an already-built RFC5322 message through the account's SMTP client."""
        outgoing = ModuleMailOutgoing(self.user, self.mail_settings)
        outgoing.send_raw_message(account_id, message)

    # --------------------------------------------------------------------- #
    # EAS folder-type mapping helper
    # --------------------------------------------------------------------- #

    # EAS FolderHierarchy Type values (MS-ASCMD §2.2.2.7.4)
    _EAS_TYPES = {
        "other": 1, "inbox": 2, "drafts": 3, "draft": 3, "trash": 4, "deleted": 4,
        "sent": 5, "outbox": 6, "tasks": 7, "task": 7, "calendar": 8, "contacts": 9,
        "notes": 10, "journal": 11, "junk": 12, "spam": 12, "archive": 1,
    }

    @staticmethod
    def eas_folder_type(folder_type: str | None, path: str, name: str) -> int:
        """Map a store folder to its EAS folder Type value (default 12/other)."""
        low = " ".join([(folder_type or ""), path, name]).lower()
        for key, value in ActiveSyncGateway._EAS_TYPES.items():
            if key in low:
                return value
        return 1  # "default"/other