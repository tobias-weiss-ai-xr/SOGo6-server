from __future__ import annotations
from typing import TYPE_CHECKING

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.interface.admin.InterfaceApiAdminUser import InterfaceApiAdminUser
from app.utils.logger.logger import logger_api
from app.utils.api.paginate_sort_filter import collection_paginate, CustomPaginateResponse

from .schema import adminUser as sch

if TYPE_CHECKING:
    from app.config.settings.ProcessSetting import ProcessSetting
    from app.utils.api.paginate_sort_filter import CollectionPaginateArgs


blp = Blueprint("Admin Users", __name__, url_prefix="/users")


@blp.before_request
def init_admin_user() -> None:
    """
    Initialize the interface and anything else required for the request.
    """
    logger_api.debug("Calling before_request for ApiAdminUser")
    process: ProcessSetting = g.process_settings
    interface_api = InterfaceApiAdminUser(process_setting=process)
    g.inter = interface_api


# ── User CRUD ────────────────────────────────────────────────────────────────


@blp.route("/list")
class ApiAdminUserList(MethodView):
    """
    List/search users from the LDAP directory.
    """

    @blp.arguments(sch.UserSearchQuerySchema, location="query")
    @blp.response(200, sch.UserListResponseSchema, example=sch.UserListResponseSchema.example())
    def get(self, args: dict) -> ResponseReturnValue:
        """
        Search and paginate users from the LDAP user source.

        Supports searching by uid, cn, sn, givenName, mail, as well as
        pagination and sorting.

        :param args: Query parameters
        :type args: dict
        :return: API response dict
        :rtype: ResponseReturnValue
        """
        logger_api.debug("Calling ApiAdminUserList: args=%s", args)
        interface: InterfaceApiAdminUser = g.inter

        response, status_code = interface.list_users(
            query=args.get("query"),
            page=args.get("page", 1),
            per_page=args.get("per_page", 20),
            sort_by=args.get("sort_by", "uid"),
            sort_order=args.get("sort_order", "asc"),
        )

        return response, status_code


@blp.route("/<string:uid>")
class ApiAdminUserDetail(MethodView):
    """
    Get, update or delete a single user.
    """

    @blp.response(200, sch.UserDetailSchema, example=sch.UserDetailSchema.example())
    def get(self, uid: str) -> ResponseReturnValue:
        """
        Get a single user's details from LDAP.

        :param uid: The user ID to look up
        :type uid: str
        :return: API response dict with user data
        :rtype: ResponseReturnValue
        """
        logger_api.debug("Calling ApiAdminUserDetail.get: uid=%s", uid)
        interface: InterfaceApiAdminUser = g.inter

        response, status_code = interface.get_user(uid)
        return response, status_code

    @blp.arguments(sch.UserUpdateBodySchema, example=sch.UserUpdateBodySchema.example(), error_status_code=400)
    @blp.response(200, sch.UserDetailSchema, example=sch.UserDetailSchema.example())
    def put(self, args: dict, uid: str) -> ResponseReturnValue:
        """
        Update an existing user's attributes in LDAP.

        :param args: Request body with attributes to update
        :type args: dict
        :param uid: The user ID to update
        :type uid: str
        :return: API response dict
        :rtype: ResponseReturnValue
        """
        logger_api.debug("Calling ApiAdminUserDetail.put: uid=%s, args=%s", uid, args)
        interface: InterfaceApiAdminUser = g.inter

        response, status_code = interface.update_user(uid, args)
        return response, status_code

    @blp.response(200, sch.UserDeleteResponseSchema, example=sch.UserDeleteResponseSchema.example())
    def delete(self, uid: str) -> ResponseReturnValue:
        """
        Delete a user from LDAP.

        :param uid: The user ID to delete
        :type uid: str
        :return: API response dict
        :rtype: ResponseReturnValue
        """
        logger_api.debug("Calling ApiAdminUserDetail.delete: uid=%s", uid)
        interface: InterfaceApiAdminUser = g.inter

        response, status_code = interface.delete_user(uid)
        return response, status_code


@blp.route("/create")
class ApiAdminUserCreate(MethodView):
    """
    Create a new user in the LDAP directory.
    """

    @blp.arguments(sch.UserCreateBodySchema, example=sch.UserCreateBodySchema.example(), error_status_code=400)
    @blp.response(201, sch.UserCreateResponseSchema, example=sch.UserCreateResponseSchema.example())
    def post(self, args: dict) -> ResponseReturnValue:
        """
        Create a new user entry in the LDAP user source.

        The minimal required fields are uid, cn, sn, givenName, mail, and
        password.  uidNumber, gidNumber, and homeDirectory are optional
        and will be auto-generated if omitted.

        :param args: Request body with user data
        :type args: dict
        :return: API response dict with created user DN
        :rtype: ResponseReturnValue
        """
        logger_api.debug("Calling ApiAdminUserCreate: args=%s", args)
        interface: InterfaceApiAdminUser = g.inter

        response, status_code = interface.create_user(args)
        return response, status_code


# ── Session Management ────────────────────────────────────────────────────


@blp.route("/active")
class ApiAdminUserActive(MethodView):
    """
    Collection of currently active users.

    An active user is a user who has a valid session stored in the cache.
    """

    @blp.response(200, sch.AdminUserActiveSchema, example=sch.AdminUserActiveSchema.example())
    @collection_paginate(blp, sort_value_set=sch.AdminUserActiveSchema.sort_by_values(), can_filter=False)
    def get(self, collection_param: CollectionPaginateArgs) -> CustomPaginateResponse:
        """
        Get the list of currently active users.

        Returns all users that have a live session in the cache, together
        with their last activity timestamp.

        :param collection_param: The object for pagination, sorting anf filtering
        :type collection_param: CollectionPaginateArgs
        :return: A tuple of (item count, API response dict, status code)
        :rtype: Tuple[int, dict, int]
        """
        logger_api.debug("Calling ApiAdminUserActive: Fetching active users: %s", collection_param)
        interface: InterfaceApiAdminUser = g.inter

        item_count, response, status_code = interface.get_active_users(collection_param)

        #return response, status_code
        return item_count, response, status_code


@blp.route("/revoke")
class ApiAdminUserRevoke(MethodView):
    """
    Revoke one or several user sessions from the cache.

    Sending a list of UIDs will immediately invalidate all active sessions
    belonging to those users.
    """

    @blp.arguments(sch.AdminUserRevokeBodySchema, example=sch.AdminUserRevokeBodySchema.example(), error_status_code=400)
    @blp.response(200, sch.AdminUserRevokeSchema, example=sch.AdminUserRevokeSchema.example())
    def post(self, body: dict) -> ResponseReturnValue:
        """
        Revoke all active sessions for the given UIDs.

        Accepts a list of UIDs and removes every matching session hash from the
        cache as well as all sorted-set indexes.  Returns the total number of
        sessions that were deleted.

        :param body: Request body containing the list of UIDs to revoke
        :type body: dict
        :return: API response dict with the revoke count
        :rtype: ResponseReturnValue
        """
        uids: list[str] | None = body.get("uid")
        redis_keys: list[str] | None = body.get("redis_key")
        logger_api.debug("Calling ApiAdminUserRevoke: revoking sessions for uids: %s, redis_keys: %s", uids, redis_keys)

        interface: InterfaceApiAdminUser = g.inter
        response, status_code = interface.revoke_users(uids=uids, redis_keys=redis_keys)

        return response, status_code


@blp.route("/inactive")
class ApiAdminUserInactive(MethodView):
    """
    Revoke inactive user sessions from the cache.

    Sending a Unix timestamp will remove all sessions whose last activity
    is older than (≤) that timestamp.
    """

    @blp.arguments(sch.AdminUserInactiveBodySchema, example=sch.AdminUserInactiveBodySchema.example(), error_status_code=400)
    @blp.response(200, sch.AdminUserInactiveSchema, example=sch.AdminUserInactiveSchema.example())
    def post(self, body: dict) -> ResponseReturnValue:
        """
        Revoke all sessions whose last activity is older than the given timestamp.

        Accepts a Unix timestamp and removes every session hash from the
        cache whose last-activity score is ≤ that value, along with all
        sorted-set index entries.  Returns the total number of sessions
        that were deleted.

        :param body: Request body containing the timestamp
        :type body: dict
        :return: API response dict with the revoke count
        :rtype: ResponseReturnValue
        """
        timestamp: int = body["timestamp"]
        logger_api.debug("Calling ApiAdminUserInactive: revoking sessions older than %d", timestamp)

        interface: InterfaceApiAdminUser = g.inter
        response, status_code = interface.revoke_inactive_users(timestamp=timestamp)

        return response, status_code
