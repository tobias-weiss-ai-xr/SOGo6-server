from __future__ import annotations
from typing import TYPE_CHECKING

from flask import abort, g, request
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.config.settings.DomainSettings import MailSettings
from app.interface.mail.InterfaceApiMailFilter import InterfaceApiMailFilter
from app.utils.api.ApiBaseResponse import create_api_base_response
from app.utils.logger.logger import logger_api
from .schemas.filter import (
    FiltersPayloadSchema,
    VacationPayloadSchema,
    ForwardPayloadSchema,
    NotificationPayloadSchema,
    FiltersSetResponseSchema,
    FiltersGetResponseSchema,
    VacationGetResponseSchema,
    ForwardGetResponseSchema,
    NotificationGetResponseSchema,
    FilterItemPayloadSchema,
    FilterGetResponseSchema,
    FilterValidateResponseSchema,
    FilterPreviewPayloadSchema,
    FilterPreviewResponseSchema,
    FilterReorderPayloadSchema,
    FilterReorderResponseSchema,
    FilterPushResponseSchema,
    FilterTemplatesResponseSchema,
)

if TYPE_CHECKING:
    from app.config.settings.ProcessSetting import ProcessSetting
    from app.auth.User import User

blp = Blueprint("Mail Filters", __name__, url_prefix="/mailboxes/<string:account_id>")


@blp.before_request
def init_filter_config() -> None:
    """Initialize the filter interface for the request."""
    logger_api.debug("Calling before_request for ApiMailFilter")
    process: ProcessSetting = g.process_settings
    user_domain_settings: dict = g.user_domain_settings
    user: User = g.user

    mail_settings: dict = user_domain_settings.get(MailSettings.subparent, {})


    if not mail_settings.get("SOGO_D_MAIL_FILTERING_ENABLED", True):
        abort(403)

    _ROUTE_SETTING_MAP = {
        "/vacation": "SOGO_D_VACATION_ENABLED",
        "/forward":  "SOGO_D_FORWARD_ENABLED",
        "/notify":   "SOGO_D_NOTIFY_ENABLED",
    }

    for suffix, setting_key in _ROUTE_SETTING_MAP.items():
        if request.path.endswith(suffix):
            if not mail_settings.get(setting_key, False):
                logger_api.debug(
                    "Access denied for %s: %s is False", request.path, setting_key
                )
                abort(403)
            break

    g.inter = InterfaceApiMailFilter(
        process_setting=process,
        user_domain_settings=user_domain_settings,
        user=user,
    )


@blp.route("/filters")
class ApiMailFilterResource(MethodView):
    """API resource for mail filter rules."""

    @blp.response(200, FiltersGetResponseSchema, example=FiltersGetResponseSchema.example())
    def get(self, account_id: str) -> ResponseReturnValue:
        """Return the ``filters`` list for a given account.

        :param account_id: Account identifier.
        :type account_id: str
        :return: ApiBaseResponse with the current filters list.
        :rtype: ResponseReturnValue
        """
        logger_api.debug("ApiMailFilterResource.get for account_id: %s", account_id)
        interface: InterfaceApiMailFilter = g.inter
        return interface.get_filters()

    @blp.arguments(FiltersPayloadSchema, example=FiltersPayloadSchema.example(), error_status_code=400)
    @blp.response(200, FiltersSetResponseSchema, example=FiltersSetResponseSchema.example())
    def post(self, payload: dict, account_id: str) -> ResponseReturnValue:
        """Replace the ``filters`` list for a given account.

        :param payload: Validated body — must contain a ``filters`` key.
        :type payload: dict
        :param account_id: Account identifier.
        :type account_id: str
        :return: ApiBaseResponse with the full updated stored content.
        :rtype: ResponseReturnValue
        """
        logger_api.debug("ApiMailFilterResource.post for account_id: %s", account_id)
        interface: InterfaceApiMailFilter = g.inter
        return interface.set_filters(payload["filters"])


@blp.route("/vacation")
class ApiMailVacationResource(MethodView):
    """API resource for vacation / auto-reply settings."""


    @blp.response(200, VacationGetResponseSchema, example=VacationGetResponseSchema.example())
    def get(self, account_id: str) -> ResponseReturnValue:
        """Return the ``Vacation`` section for a given account.

        :param account_id: Account identifier.
        :type account_id: str
        :return: ApiBaseResponse with the current vacation settings.
        :rtype: ResponseReturnValue
        """
        logger_api.debug("ApiMailVacationResource.get for account_id: %s", account_id)
        interface: InterfaceApiMailFilter = g.inter
        return interface.get_vacation()

    @blp.arguments(VacationPayloadSchema, example=VacationPayloadSchema.example(), error_status_code=400)
    @blp.response(200, FiltersSetResponseSchema, example=FiltersSetResponseSchema.example())
    def post(self, payload: dict, account_id: str) -> ResponseReturnValue:
        """Replace the ``Vacation`` section for a given account.

        :param payload: Validated body — must contain a ``Vacation`` key.
        :type payload: dict
        :param account_id: Account identifier.
        :type account_id: str
        :return: ApiBaseResponse with the full updated stored content.
        :rtype: ResponseReturnValue
        """
        logger_api.debug("ApiMailVacationResource.post for account_id: %s", account_id)
        interface: InterfaceApiMailFilter = g.inter
        return interface.set_vacation(payload["Vacation"])


@blp.route("/forward")
class ApiMailForwardResource(MethodView):
    """API resource for mail forwarding settings."""

    @blp.response(200, ForwardGetResponseSchema, example=ForwardGetResponseSchema.example())
    def get(self, account_id: str) -> ResponseReturnValue:
        """Return the ``Forward`` section for a given account.

        :param account_id: Account identifier.
        :type account_id: str
        :return: ApiBaseResponse with the current forward settings.
        :rtype: ResponseReturnValue
        """
        logger_api.debug("ApiMailForwardResource.get for account_id: %s", account_id)
        interface: InterfaceApiMailFilter = g.inter
        return interface.get_forward()

    @blp.arguments(ForwardPayloadSchema, example=ForwardPayloadSchema.example(), error_status_code=400)
    @blp.response(200, FiltersSetResponseSchema, example=FiltersSetResponseSchema.example())
    def post(self, payload: dict, account_id: str) -> ResponseReturnValue:
        """Replace the ``Forward`` section for a given account.

        :param payload: Validated body — must contain a ``Forward`` key.
        :type payload: dict
        :param account_id: Account identifier.
        :type account_id: str
        :return: ApiBaseResponse with the full updated stored content.
        :rtype: ResponseReturnValue
        """
        logger_api.debug("ApiMailForwardResource.post for account_id: %s", account_id)
        interface: InterfaceApiMailFilter = g.inter
        return interface.set_forward(payload["Forward"])


@blp.route("/notify")
class ApiMailNotifyResource(MethodView):
    """API resource for mail notification settings."""

    @blp.response(200, NotificationGetResponseSchema, example=NotificationGetResponseSchema.example())
    def get(self, account_id: str) -> ResponseReturnValue:
        """Return the ``Notification`` section for a given account.

        :param account_id: Account identifier.
        :type account_id: str
        :return: ApiBaseResponse with the current notification settings.
        :rtype: ResponseReturnValue
        """
        logger_api.debug("ApiMailNotifyResource.get for account_id: %s", account_id)
        interface: InterfaceApiMailFilter = g.inter
        return interface.get_notification()

    @blp.arguments(NotificationPayloadSchema, example=NotificationPayloadSchema.example(), error_status_code=400)
    @blp.response(200, FiltersSetResponseSchema, example=FiltersSetResponseSchema.example())
    def post(self, payload: dict, account_id: str) -> ResponseReturnValue:
        """Replace the ``Notification`` section for a given account.

        :param payload: Validated body — must contain a ``Notification`` key.
        :type payload: dict
        :param account_id: Account identifier.
        :type account_id: str
        :return: ApiBaseResponse with the full updated stored content.
        :rtype: ResponseReturnValue
        """
        logger_api.debug("ApiMailNotifyResource.post for account_id: %s", account_id)
        interface: InterfaceApiMailFilter = g.inter
        return interface.set_notification(payload["Notification"])


# --------------------------------------------------------------------------- #
# Sieve Editor granular filter endpoints                                       #
# --------------------------------------------------------------------------- #


@blp.route("/filters/templates")
class ApiMailFilterTemplatesResource(MethodView):
    """List built-in sieve filter templates (spec: GET /filters/templates)."""

    @blp.response(200, FilterTemplatesResponseSchema, example=FilterTemplatesResponseSchema.example())
    def get(self, account_id: str) -> ResponseReturnValue:
        """Return a set of built-in filter templates to bootstrap the editor.

        :param account_id: Account identifier.
        :type account_id: str
        :return: ApiBaseResponse with the templates list.
        :rtype: ResponseReturnValue
        """
        logger_api.debug("ApiMailFilterTemplatesResource.get for account_id: %s", account_id)
        templates = [
            {
                "name": "Move newsletter to folder",
                "enabled": True,
                "actions": [{"method": "fileinto", "arguments": {"folders": ["INBOX.Newsletters"]}}],
                "rules": {
                    "op": "and",
                    "rules": [
                        {"field": "from", "operator": "contains", "value": "newsletter"},
                    ],
                },
            },
            {
                "name": "Archive after 30 days",
                "enabled": True,
                "actions": [{"method": "fileinto", "arguments": {"folders": ["Archive"]}}],
                "rules": {
                    "op": "and",
                    "rules": [],
                },
            },
            {
                "name": "Forward invoices to accountant",
                "enabled": True,
                "actions": [{"method": "redirect", "arguments": {"addresses": ["accountant@example.org"]}}],
                "rules": {
                    "op": "or",
                    "rules": [
                        {"field": "subject", "operator": "contains", "value": "invoice"},
                        {"field": "from", "operator": "contains", "value": "billing"},
                    ],
                },
            },
        ]
        interface: InterfaceApiMailFilter = g.inter
        return create_api_base_response(templates)


@blp.route("/filters/validate")
class ApiMailFilterValidateResource(MethodView):
    """Validate a single filter payload without persisting it (spec: POST /filters/validate)."""

    @blp.arguments(FilterItemPayloadSchema, example=FilterItemPayloadSchema.example(), error_status_code=400)
    @blp.response(200, FilterValidateResponseSchema, example=FilterValidateResponseSchema.example())
    def post(self, payload: dict, account_id: str) -> ResponseReturnValue:
        """Validate filter structure (name, actions, rules).

        :param payload: Validated filter payload.
        :type payload: dict
        :param account_id: Account identifier.
        :type account_id: str
        :return: ApiBaseResponse with ``valid`` and ``errors``.
        :rtype: ResponseReturnValue
        """
        logger_api.debug("ApiMailFilterValidateResource.post for account_id: %s", account_id)
        interface: InterfaceApiMailFilter = g.inter
        return interface.validate_filter(payload)


@blp.route("/filters/preview")
class ApiMailFilterPreviewResource(MethodView):
    """Preview whether a filter matches sample headers (spec: POST /filters/preview)."""

    @blp.arguments(FilterPreviewPayloadSchema, error_status_code=400)
    @blp.response(200, FilterPreviewResponseSchema, example=FilterPreviewResponseSchema.example())
    def post(self, payload: dict, account_id: str) -> ResponseReturnValue:
        """Evaluate a filter rule tree against sample message headers.

        :param payload: ``{filter: {...}, headers: {...}}``.
        :type payload: dict
        :param account_id: Account identifier.
        :type account_id: str
        :return: ApiBaseResponse with ``matched`` and ``action``.
        :rtype: ResponseReturnValue
        """
        logger_api.debug("ApiMailFilterPreviewResource.post for account_id: %s", account_id)
        interface: InterfaceApiMailFilter = g.inter
        return interface.preview_filter(payload["filter"], payload["headers"])


@blp.route("/filters/push")
class ApiMailFilterPushResource(MethodView):
    """Re-push the current merged configuration to the Sieve server (spec: POST /filters/push)."""

    @blp.response(200, FilterPushResponseSchema, example=FilterPushResponseSchema.example())
    def post(self, account_id: str) -> ResponseReturnValue:
        """Push the stored filters column to Sieve, rebuilding the merged script.

        :param account_id: Account identifier.
        :type account_id: str
        :return: ApiBaseResponse with the pushed content.
        :rtype: ResponseReturnValue
        """
        logger_api.debug("ApiMailFilterPushResource.post for account_id: %s", account_id)
        interface: InterfaceApiMailFilter = g.inter
        return interface.push_to_sieve()


@blp.route("/filters/reorder")
class ApiMailFilterReorderResource(MethodView):
    """Reorder the filters list (spec: PATCH /filters/reorder)."""

    @blp.arguments(FilterReorderPayloadSchema, example=FilterReorderPayloadSchema.example(), error_status_code=400)
    @blp.response(200, FilterReorderResponseSchema, example=FilterReorderResponseSchema.example())
    def patch(self, payload: dict, account_id: str) -> ResponseReturnValue:
        """Reorder filters by the desired ``order`` of names, then push to Sieve.

        :param payload: ``{order: [name, ...]}``.
        :type payload: dict
        :param account_id: Account identifier.
        :type account_id: str
        :return: ApiBaseResponse with the full updated filters content.
        :rtype: ResponseReturnValue
        """
        logger_api.debug("ApiMailFilterReorderResource.patch for account_id: %s", account_id)
        interface: InterfaceApiMailFilter = g.inter
        return interface.reorder_filters(payload["order"])


@blp.route("/filters/<string:filter_id>")
class ApiMailFilterItemResource(MethodView):
    """Get / update / delete a single filter by name (spec: sieve-editor granular endpoints)."""

    @blp.response(200, FilterGetResponseSchema, example=FilterGetResponseSchema.example())
    def get(self, account_id: str, filter_id: str) -> ResponseReturnValue:
        """Return a single filter by its name/id.

        :param account_id: Account identifier.
        :type account_id: str
        :param filter_id: Filter name (acts as id).
        :type filter_id: str
        :return: ApiBaseResponse with the matching filter.
        :rtype: ResponseReturnValue
        """
        logger_api.debug("ApiMailFilterItemResource.get filter_id=%s account_id=%s", filter_id, account_id)
        interface: InterfaceApiMailFilter = g.inter
        return interface.get_filter(filter_id)

    @blp.arguments(FilterItemPayloadSchema, example=FilterItemPayloadSchema.example(), error_status_code=400)
    @blp.response(200, FiltersSetResponseSchema, example=FiltersSetResponseSchema.example())
    def put(self, payload: dict, account_id: str, filter_id: str) -> ResponseReturnValue:
        """Create or replace a single filter by name/id, then push to Sieve.

        :param payload: Validated filter payload (``name`` must match ``filter_id``).
        :type payload: dict
        :param account_id: Account identifier.
        :type account_id: str
        :param filter_id: Filter name.
        :type filter_id: str
        :return: ApiBaseResponse with the full updated filters content.
        :rtype: ResponseReturnValue
        """
        logger_api.debug("ApiMailFilterItemResource.put filter_id=%s account_id=%s", filter_id, account_id)
        interface: InterfaceApiMailFilter = g.inter
        payload["name"] = filter_id
        return interface.set_filter(filter_id, payload)

    @blp.response(200, FiltersSetResponseSchema, example=FiltersSetResponseSchema.example())
    def delete(self, account_id: str, filter_id: str) -> ResponseReturnValue:
        """Delete a single filter by name/id, then push to Sieve.

        :param account_id: Account identifier.
        :type account_id: str
        :param filter_id: Filter name.
        :type filter_id: str
        :return: ApiBaseResponse with the full updated filters content.
        :rtype: ResponseReturnValue
        """
        logger_api.debug("ApiMailFilterItemResource.delete filter_id=%s account_id=%s", filter_id, account_id)
        interface: InterfaceApiMailFilter = g.inter
        return interface.delete_filter(filter_id)
