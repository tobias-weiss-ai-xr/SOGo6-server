"""Global Quick Search (Cmd+K) API.

``GET /search/global?q=...`` returns grouped results across contacts, calendar
events and directory users so the frontend command palette can present one
unified result set.
"""
from typing import TYPE_CHECKING

from flask import g
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate

from app.interface.user.InterfaceApiGlobalSearch import InterfaceApiGlobalSearch
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.config.settings.ProcessSetting import ProcessSetting
    from app.auth.User import User

blp = Blueprint("Global Search", __name__, url_prefix="/search")


class GlobalSearchQueryArgs(Schema):
    """Query arguments for the unified global search."""

    q = fields.String(required=True, metadata={"description": "Free-text search query (min 2 chars)."})
    limit = fields.Integer(load_default=8, validate=validate.Range(min=1, max=50), metadata={"description": "Max results per section."})


@blp.before_request
def init_search_config() -> None:
    """Initialize the global search interface for this request."""
    logger_api.debug("Calling before_request for ApiGlobalSearch")
    process: ProcessSetting = g.process_settings
    user_domain_settings: dict = g.user_domain_settings
    user: User = g.user
    g.inter = InterfaceApiGlobalSearch(process, user_domain_settings, user)


@blp.route("/global")
class ApiGlobalSearch(MethodView):
    """Unified search across contacts, calendar events and users."""

    @blp.arguments(GlobalSearchQueryArgs, location="query", error_status_code=400)
    @blp.response(200)
    def get(self, args: dict) -> ResponseReturnValue:
        """Search contacts, events and users for the given query."""
        logger_api.debug("GET /search/global user=%s q=%s", g.user.uid, args.get("q"))
        interface: InterfaceApiGlobalSearch = g.inter
        return interface.global_search(args.get("q", ""), args.get("limit"))
