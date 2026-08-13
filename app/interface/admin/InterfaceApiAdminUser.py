from __future__ import annotations
from typing import TYPE_CHECKING, Any

from app.module.admin.ModuleAdminUser import ModuleAdminUser
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.config.settings.ProcessSetting import ProcessSetting
    from app.utils.api.paginate_sort_filter import CollectionPaginateArgs


class InterfaceApiAdminUser:
    """
    Interface for the admin user API (ApiAdminUser).
    """

    def __init__(self, process_setting: ProcessSetting) -> None:
        """
        :param process_setting: the process settings
        :type process_setting: ProcessSetting
        """
        self.module = ModuleAdminUser(process_settings=process_setting)

    # ── User CRUD ─────────────────────────────────────────────────────────────

    def list_users(self, query: str | None = None, page: int = 1, per_page: int = 20,
                   sort_by: str = "uid", sort_order: str = "asc") -> tuple[dict[str, Any], int]:
        """
        List/search users from the LDAP directory.

        :param query: Optional search string
        :param page: Page number (1-based)
        :param per_page: Items per page
        :param sort_by: Field to sort by
        :param sort_order: 'asc' or 'desc'
        :return: Tuple of (API response dict, HTTP status code)
        """
        try:
            total_count, users = self.module.list_users(
                query=query, page=page, per_page=per_page,
                sort_by=sort_by, sort_order=sort_order,
            )
        except RequestException as ex:
            logger_api.error("Request exception in list_users: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response(users)

    def get_user(self, uid: str) -> tuple[dict[str, Any], int]:
        """
        Get a single user from LDAP.

        :param uid: The user ID
        :return: Tuple of (API response dict, HTTP status code)
        """
        try:
            user = self.module.get_user(uid)
        except RequestException as ex:
            logger_api.error("Request exception in get_user: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response(user)

    def create_user(self, data: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """
        Create a new user in LDAP.

        :param data: User data (uid, cn, sn, givenName, mail, password, …)
        :return: Tuple of (API response dict, HTTP status code)
        """
        try:
            result = self.module.create_user(data)
        except RequestException as ex:
            logger_api.error("Request exception in create_user: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response(result)

    def update_user(self, uid: str, data: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """
        Update an existing user in LDAP.

        :param uid: The user ID to update
        :param data: Attributes to modify (cn, sn, givenName, mail, password)
        :return: Tuple of (API response dict, HTTP status code)
        """
        try:
            result = self.module.update_user(uid, data)

            # If the password changed, revoke the user's sessions so the old
            # credential can no longer be used with previously issued tokens.
            if "password" in data:
                try:
                    from app.service import sogo_cache
                    cache = sogo_cache()
                    cache.revoke_user_sessions_by_uid([uid])
                    cache.close()
                    logger_api.info(
                        "Revoked all sessions for uid=%s after admin password update",
                        uid,
                    )
                except Exception as cache_ex:
                    logger_api.error(
                        "Failed to revoke sessions after admin password update for uid=%s: %s",
                        uid,
                        cache_ex,
                    )
        except RequestException as ex:
            logger_api.error("Request exception in update_user: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response(result)

    def delete_user(self, uid: str) -> tuple[dict[str, Any], int]:
        """
        Delete a user from LDAP.

        :param uid: The user ID to delete
        :return: Tuple of (API response dict, HTTP status code)
        """
        try:
            result = self.module.delete_user(uid)
        except RequestException as ex:
            logger_api.error("Request exception in delete_user: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response(result)

    # ── Session Management ────────────────────────────────────────────────────

    def get_active_users(self, collection_param: CollectionPaginateArgs) -> tuple[int, dict[str, Any], int]:
        """
        Return the list of currently active users.

        When *sort_by* is None the sorted-set score (last activity)
        is used and pagination is server-side.  Any other value triggers
        an in-memory sort over all sessions.

        :param first: 0-based index of the first item (pagination)
        :type first: int
        :param last: 0-based index of the last item (pagination, exclusive)
        :type last: int
        :param sort_by: field name to sort on (None = last activity)
        :type sort_by: str | None
        :param sort_order: "asc" or "desc" (default "desc" = most recent first)
        :type sort_order: str
        :param include_fields: comma-separated list of fields to keep
        :type include_fields: str | None
        :return: Tuple of (item_count, API response dict, HTTP status code)
        :rtype: Tuple[int, Dict[str, Any], int]
        """
        try:
            total_count, active_users = self.module.get_active_users(collection_param)
        except RequestException as ex:
            logger_api.error("Request exception in get_active_users: %s", str(ex))
            return 0, *create_api_base_response(None, ex.error)
        return total_count, *create_api_base_response(active_users)

    def revoke_users(self, uids: list[str] | None = None, redis_keys: list[str] | None = None) -> tuple[dict[str, Any], int]:
        """
        Revoke cache sessions either by UID or by direct Redis key.

        Exactly one of *uids* or *redis_keys* must be provided.

        :param uids: list of user UIDs to revoke (mutually exclusive with *redis_keys*)
        :type uids: list[str] | None
        :param redis_keys: list of Redis hash keys to revoke (mutually exclusive with *uids*)
        :type redis_keys: list[str] | None
        :return: Tuple of (API response dict, HTTP status code)
        :rtype: Tuple[Dict[str, Any], int]
        """
        try:
            revoked_count = self.module.revoke_users(uids=uids, redis_keys=redis_keys)
        except RequestException as ex:
            logger_api.error("Request exception in revoke_users: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response({"revoked": revoked_count})

    def revoke_inactive_users(self, timestamp: int) -> tuple[dict[str, Any], int]:
        """
        Revoke cache sessions whose last activity is older than the given
        Unix timestamp.

        :param timestamp: Unix timestamp.  Sessions with a
            last-activity score ≤ this value are considered inactive.
        :type timestamp: int
        :return: Tuple of (API response dict, HTTP status code)
        :rtype: Tuple[Dict[str, Any], int]
        """
        try:
            revoked_count = self.module.revoke_inactive_users(timestamp)
        except RequestException as ex:
            logger_api.error("Request exception in revoke_inactive_users: %s", str(ex))
            return create_api_base_response(None, ex.error)
        return create_api_base_response({"revoked": revoked_count})
