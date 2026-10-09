# Share / ACL engine (unified across all resource types)
from app.factory.share.RepositoryAcl import (
    AclEntry,
    RepositoryAcl,
)
from app.factory.share.share import Share
from app.factory.share.shareCalendar import (
    CALENDAR_RESOURCE_TYPE,
    FULL_MODIFY_RIGHTS as CALENDAR_FULL_MODIFY_RIGHTS,
    LEVEL_TO_STR as CALENDAR_LEVEL_TO_STR,
    ShareCalendar,
    STR_TO_LEVEL as CALENDAR_STR_TO_LEVEL,
)
from app.factory.share.shareContact import (
    CONTACT_RESOURCE_TYPE,
    FULL_MODIFY_RIGHTS as CONTACT_FULL_MODIFY_RIGHTS,
    RIGHT_CREATE,
    RIGHT_EDIT,
    RIGHT_ERASE,
    RIGHT_VIEW,
    ShareContact,
)
from app.factory.share.shareMailFolder import (
    FOLDER_PERMISSION_CODE_TO_RIGHT,
    FOLDER_PERMISSIONS,
    FOLDER_RESOURCE_TYPE,
    FOLDER_SHARE_PERMISSION_CODES,
    imap_permissions_to_rights,
    right_to_camel,
    rights_to_imap_permissions,
)

__all__ = [
    # Base classes
    "Share",
    "AclEntry",
    "RepositoryAcl",
    # Calendar
    "CALENDAR_RESOURCE_TYPE",
    "ShareCalendar",
    "CALENDAR_LEVEL_TO_STR",
    "CALENDAR_STR_TO_LEVEL",
    "CALENDAR_FULL_MODIFY_RIGHTS",
    # Contact / Address Book
    "CONTACT_RESOURCE_TYPE",
    "ShareContact",
    "RIGHT_VIEW",
    "RIGHT_CREATE",
    "RIGHT_EDIT",
    "RIGHT_ERASE",
    "CONTACT_FULL_MODIFY_RIGHTS",
    # Mail Folder
    "FOLDER_RESOURCE_TYPE",
    "FOLDER_SHARE_PERMISSION_CODES",
    "FOLDER_PERMISSION_CODE_TO_RIGHT",
    "FOLDER_PERMISSIONS",
    "rights_to_imap_permissions",
    "imap_permissions_to_rights",
    "right_to_camel",
]
