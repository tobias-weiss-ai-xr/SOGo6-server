from __future__ import annotations
from typing import TYPE_CHECKING

from flask import g, Response
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.interface.admin.InterfaceApiAdminConfig import InterfaceApiAdminConfig
from app.utils.logger.logger import logger_api
from app.utils.api.paginate_sort_filter import collection_paginate, CustomPaginateResponse

from .schema import adminConfig as sch

if TYPE_CHECKING:
    from app.config.settings.ProcessSetting import ProcessSetting
    from app.utils.api.paginate_sort_filter import CollectionPaginateArgs



blp = Blueprint("Config", __name__, url_prefix="/config")

@blp.before_request
def init_admin_config() -> None:
    """
    Init the interface and others if needed
    """
    logger_api.debug("Calling before_request for ApiAdminConfig")
    process : ProcessSetting = g.process_settings
    interface_api = InterfaceApiAdminConfig(process_setting=process)
    g.inter = interface_api

@blp.route("/dynamic-form")
class ApiAdminConfig(MethodView):
    """
    Action

    Endpoint that return the dynamic settings structure
    """
    @blp.response(200, sch.AdminConfigDynamicFormSchemaRet)
    def get(self) -> ResponseReturnValue:
        """
        Action, return the dynamic settings structure
        """
        interface_api : InterfaceApiAdminConfig = g.inter
        return interface_api.get_dynamic_setting_structure()


@blp.route("/system")
class ApiAdminConfigSystem(MethodView):
    """
    Singleton, can't be created, only modified

    Endpoint that return the list of the system settings
    """
    @blp.response(200, sch.AdminConfigSystemGetRetSchema, example=sch.AdminConfigSystemGetRetSchema.example())
    def get(self,) -> ResponseReturnValue:
        """
        Singleton, fetch the system settings
        """
        interface_api : InterfaceApiAdminConfig = g.inter
        return interface_api.get_all_setting_system()

    @blp.arguments(sch.AdminConfigSystemPatchSchema, example=sch.AdminConfigSystemPatchSchema.example(), error_status_code=400)
    @blp.response(200, sch.AdminConfigSystemGetRetSchema, example=sch.AdminConfigSystemGetRetSchema.example())
    def patch(self, new_data: dict) -> ResponseReturnValue:
        """
        Singleton, update the system settings
        """
        interface_api : InterfaceApiAdminConfig = g.inter
        return interface_api.update_all_setting_system(new_data["settings"])


@blp.route("/theme")
class ApiAdminConfigTheme(MethodView):
    """
    Singleton, can't be created, only modified

    Endpoint for theme customization settings
    """
    @blp.response(200, sch.AdminConfigThemeGetRetSchema, example=sch.AdminConfigThemeGetRetSchema.example())
    def get(self,) -> ResponseReturnValue:
        """
        Singleton, fetch the theme settings
        """
        interface_api : InterfaceApiAdminConfig = g.inter
        return interface_api.get_all_setting_theme()

    @blp.arguments(sch.AdminConfigThemePatchSchema, example=sch.AdminConfigThemePatchSchema.example(), error_status_code=400)
    @blp.response(200, sch.AdminConfigThemeGetRetSchema, example=sch.AdminConfigThemeGetRetSchema.example())
    def patch(self, new_data: dict) -> ResponseReturnValue:
        """
        Singleton, update the theme settings
        """
        interface_api : InterfaceApiAdminConfig = g.inter
        return interface_api.update_all_setting_theme(new_data["settings"])


@blp.route("/domain-default")
class ApiAdminConfigDefaultDomain(MethodView):
    """
    Singleton, can't be created, only modified

    Endpoint for the default domain setting
    """
    @blp.response(200, sch.AdminConfigDefaultDomainGetSchema, example=sch.AdminConfigDefaultDomainGetSchema.example())
    def get(self,) -> ResponseReturnValue:
        """
        Singleton, fetch the default domain setting
        """
        interface_api : InterfaceApiAdminConfig = g.inter
        return interface_api.get_all_setting_domain_default()

    @blp.arguments(sch.AdminConfigDefaultDomainPatchSchema, example=sch.AdminConfigDefaultDomainPatchSchema.example(), error_status_code=400)
    @blp.response(200, sch.AdminConfigDefaultDomainGetSchema, example=sch.AdminConfigDefaultDomainGetSchema.example())
    def patch(self, new_data: dict) -> ResponseReturnValue:
        """
        Singleton, update the default domain setting
        """
        interface_api : InterfaceApiAdminConfig = g.inter
        return interface_api.update_all_setting_domain_default(new_data["settings"])

@blp.route("/domains")
class ApiAdminConfigDomain(MethodView):
    """
    Collection, each resource is the sogo's settings associated to a domain
    """
    @blp.response(200, sch.AdminConfigDomainGetSchema, example=sch.AdminConfigDomainGetSchema.example())
    @collection_paginate(blp, sort_value_set=sch.AdminConfigDomainGetSchema.sort_by_values(), filter_value_set=sch.AdminConfigDomainGetSchema.filter_by_values())
    def get(self, collection_param: CollectionPaginateArgs) -> CustomPaginateResponse:
        """
        Collection, get the list of domains settings
        """
        interface_api : InterfaceApiAdminConfig = g.inter
        return interface_api.get_all_domain_settings(collection_param)

    @blp.arguments(sch.AdminConfigDomainPostSchema, example=sch.AdminConfigDomainPostSchema.example(), error_status_code=400)
    @blp.response(200, sch.AdminConfigDomainGetSchema, example=sch.AdminConfigDomainGetSchema.example())
    @blp.response(400, sch.ApiBaseResponse)
    def post(self, new_data: dict) -> ResponseReturnValue:
        """
        Collection, create a new set of settings for a domain
        """
        interface_api : InterfaceApiAdminConfig = g.inter
        ret = interface_api.post_new_domain_settings(new_data)
        return ret


@blp.route("/domains/<string:domain_name>")
class ApiAdminConfigDomainSettings(MethodView):
    """
    Endpoint that return the list of settings for a domain (or the default)
    """
    @blp.response(200)
    def get(self, domain_name: str) -> ResponseReturnValue:
        """
        Resource, get the specified domain settings
        """
        interface_api : InterfaceApiAdminConfig = g.inter
        ret = interface_api.get_domain_settings(domain_name)
        return ret

    @blp.arguments(sch.AdminConfigDomainPatchSchema, example=sch.AdminConfigDomainPatchSchema.example(), error_status_code=400)
    @blp.response(200)
    def patch(self, new_data: dict, domain_name: str) -> ResponseReturnValue:
        """
        Resource, update the specified domain settings
        """
        interface_api : InterfaceApiAdminConfig = g.inter
        return interface_api.update_domain_settings(domain_name, new_data)

    @blp.response(200)
    def delete(self, domain_name: str) -> None|ResponseReturnValue:
        """
        Resource, delete specified domain settings
        """
        interface_api : InterfaceApiAdminConfig = g.inter
        ret, code = interface_api.delete_domain_settings(domain_name)
        if code == 200:
            return None
        return ret, code

@blp.route("/rules")
class ApiAdminConfigRuleList(MethodView):
    """
    Endpoint that returns a list of all rules
    """
    @blp.response(200)
    def get(self) -> ResponseReturnValue:
        """
        Return the list of rules defined
        """
        interface_api: InterfaceApiAdminConfig = g.inter
        return interface_api.get_list_of_rule()

    @blp.arguments(sch.AdminConfigRulePostSchema, example=sch.AdminConfigRulePostSchema.example(), error_status_code=400)
    @blp.response(201)
    def post(self, new_data: dict) -> ResponseReturnValue:
        """
        Create a new rule
        """
        interface_api: InterfaceApiAdminConfig = g.inter
        return interface_api.post_new_rule(new_data)


@blp.route("/rules/<int:rule_id>")
class ApiAdminConfigRuleSettings(MethodView):
    """
    Endpoint that returns the settings of a specific rule
    """
    @blp.response(200)
    def get(self, rule_id: int) -> ResponseReturnValue:
        """
        Return the rule settings
        """
        interface_api: InterfaceApiAdminConfig = g.inter
        return interface_api.get_rule_settings(rule_id)

    @blp.arguments(sch.AdminConfigRulePatchSchema, example=sch.AdminConfigRulePatchSchema.example(), error_status_code=400)
    @blp.response(200)
    def patch(self, new_data: dict, rule_id: int) -> ResponseReturnValue:
        """
        Update a rule
        """
        interface_api: InterfaceApiAdminConfig = g.inter
        return interface_api.update_rule_settings(rule_id, new_data)

    @blp.response(200)
    def delete(self, rule_id: int) -> ResponseReturnValue:
        """
        Delete a rule
        """
        interface_api: InterfaceApiAdminConfig = g.inter
        ret, code = interface_api.delete_rule_settings(rule_id)
        if code == 200:
            return None
        return ret, code
