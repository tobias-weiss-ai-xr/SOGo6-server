from __future__ import annotations

"""Mail folder sharing utilities for the sogo6_acl table.

.. warning::

   Mail folder ACLs are *not* stored in sogo6_acl.  They live in the IMAP server's own
   ACL mechanism (RFC 4314).  This module only provides code / right name translations
   so our API endpoints can speak IMAP's ACL alphabet when delegating to the IMAP
   server.
"""

# Discriminant reserved for IMAP folder shares if we ever wish to migrate here.
FOLDER_RESOURCE_TYPE: str = "folder"

# RFC 4314 permission codes.  The lowercase letters are canonical.
FOLDER_SHARE_PERMISSION_CODES: tuple[str, ...] = (
    "l",  # lookup: list the folder name, see its hierarchy delimiters
    "r",  # read: SELECT the mailbox, perform STATUS, SEARCH, FETCH, etc.
    "s",  # seen: set or clear \\Seen and (non-standard) \\Deleted flags
    "w",  # write: set or clear flags other than \\Seen and \\Deleted
    "i",  # insert: store messages, append to mailbox
    "p",  # post: send mail to submission address, for mailbox used as delivery destination
    "k",  # create: CREATE new sub-mailboxes in any implementation-defined hierarchy
    "x",  # delete: expunge the mailbox (turns it into a \\Noselect mailbox)
    "t",  # delete-mailbox: remove the mailbox name
    "e",  # expunge: fsck Maildir or dirsync Cy form of EXPUNGE
    "a",  # admin: perform SETACL / DELETEACL / GETACL / LISTRIGHTS
)

# FOLDER_PERMISSION_CODE_TO_RIGHT maps each lowercase ACL code to its human-readable name.
# The order is irrelevant - the presence / absence of each code determines access.
FOLDER_PERMISSION_CODE_TO_RIGHT: dict[str, str] = {
    "l": "lookup",
    "r": "read",
    "s": "markAsSeen",
    "w": "markAsFlagged",
    "i": "insert",
    "p": "post",
    "k": "createMailSubfolder",
    "x": "expunge",
    "t": "deleteMailfolder",
    "e": "expungePermanently",
    "a": "admin",
}

# Valid right names (values of FOLDER_PERMISSION_CODE_TO_RIGHT) - used for API request validation.
FOLDER_PERMISSIONS: tuple[str, ...] = tuple(FOLDER_PERMISSION_CODE_TO_RIGHT.values())


def rights_to_imap_permissions(rights: dict[str, int]) -> str:
    """Encode our dict[str -> int] rights blob as an IMAP ACL string (e.g. ``'lrswt'``)."""
    parts = []
    for code in FOLDER_SHARE_PERMISSION_CODES:
        right = FOLDER_PERMISSION_CODE_TO_RIGHT[code]
        if right in rights and rights[right] > 0:
            parts.append(code)
    return "".join(parts)


def imap_permissions_to_rights(imap_rights: str) -> dict[str, int]:
    """Decode an IMAP ACL string (e.g. ``'lrswt'``) into our dict[str -> int] rights blob."""
    result = {right: 0 for right in FOLDER_PERMISSION_CODE_TO_RIGHT.values()}
    # Accept uppercase or lower, in any order.
    normalized = imap_rights.lower()
    for code in FOLDER_SHARE_PERMISSION_CODES:
        right = FOLDER_PERMISSION_CODE_TO_RIGHT[code]
        if code in normalized:
            result[right] = 1
    return result


def right_to_camel(right: str) -> str:
    """Convert a snake_case right name to camelCase for API responses.  No-op for uppercase."""
    return right
