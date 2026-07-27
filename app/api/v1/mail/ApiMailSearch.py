"""API endpoints for cross-folder mail search."""

from __future__ import annotations
from typing import TYPE_CHECKING, Any

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint, abort
from marshmallow import ValidationError

from app.interface.mail.InterfaceApiMailMail import InterfaceApiMailMail
from app.utils.logger.logger import logger_api
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils import errors as err
from app.utils.api.paginate_sort_filter import make_pagination_metadata
from .schemas.mail import MailSearchQuerySchema, MailSearchResponseSchema

if TYPE_CHECKING:
    from app.auth.User import User
    from app.config.settings.ProcessSetting import ProcessSetting

blp = Blueprint(
    "Mail Search",
    __name__,
    url_prefix="/mailboxes/<string:account_id>/search",
)


@blp.before_request
def init_mail_config() -> None:
    """Initialize the mail interface for search requests."""
    logger_api.debug("Calling before_request for ApiMailSearch")
    process: ProcessSetting = g.process_settings
    user_domain_settings: dict = g.user_domain_settings
    user: User = g.user

    interface_api = InterfaceApiMailMail(
        process_setting=process,
        user_domain_settings=user_domain_settings,
        user=user,
    )
    g.inter = interface_api


@blp.route("")
class ApiMailSearch(MethodView):
    """API to search mails across folders."""

    @blp.arguments(
        MailSearchQuerySchema,
        location="query",
        error_status_code=400,
    )
    @blp.response(200, MailSearchResponseSchema)
    def get(
        self,
        search_params: dict[str, Any],
        account_id: str,
    ) -> ResponseReturnValue:
        """Search mails across one or more folders.

        Searches for mails matching the given criteria across the specified
        folders (defaults to INBOX if none provided). Returns paginated results
        sorted by date (descending).

        :param search_params: Search query parameters
        :type search_params: dict[str, Any]
        :param account_id: The account identifier
        :type account_id: str
        :return: Paginated search results
        :rtype: ResponseReturnValue
        """
        logger_api.debug(
            "Calling ApiMailSearch.get for account_id: %s, params: %s",
            account_id,
            search_params,
        )
        interface: InterfaceApiMailMail = g.inter

        try:
            item_count, response_data, status_code = interface.search_mails(
                account_id, search_params
            )

            # Build response with pagination metadata header
            from flask import make_response, jsonify

            flask_response = make_response(jsonify(response_data), status_code)
            if item_count:
                page = search_params.get("page", 1)
                per_page = search_params.get("per_page", 20)
                flask_response.headers["X-Pagination"] = __import__(
                    "json"
                ).dumps(
                    make_pagination_metadata(page, per_page, item_count)
                )
            return flask_response
        except ValidationError as ex:
            logger_api.error("Validation error in search_mails: %s", ex.messages)
            abort(400, message=str(ex.messages))
