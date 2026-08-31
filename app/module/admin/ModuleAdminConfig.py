from __future__ import annotations
from typing import TYPE_CHECKING, Callable

import json as json_module
from app.config.db import tables as tbl
from app.config.settings.SystemSettings import get_all_system_schemas
from app.config.settings.DomainSettings import get_all_domain_schemas
from app.config.settings.DynamicFormSettings import create_dynamic_dict_for_settings
from app.config.settings.SogoSchema import check_data_for_sogo_schemas
from app.utils.dict import merge_patch, set_origin_from_settings
from app.utils.db.Condition import EqualCondition, NotEqualCondition, TrueCondition, Order
from app.utils.db.Table import Column
from app.utils.exceptions import AggravatedException, BugException, RequestException
from app.utils.logger.logger import logger
from app.utils.module.importManager import import_and_instantiate_manager
from app.utils.maths.sogo_hash import get_unique_token, HASH_SIZE_DOMAIN
from app.utils import errors as err


def _warn_insecure_domain_settings(settings: dict) -> None:
    """Log warnings for potentially insecure domain settings.
    
    This function checks domain settings for common security misconfigurations
    and logs warnings to help administrators identify and fix them.
    
    :param settings: Dictionary containing domain settings
    :type settings: dict
    """
    # Check for plain authentication with no rate limiting
    if settings.get('SOGO_D_AUTH_TYPE') == 'plain':
        login_max_attempt = settings.get('SOGO_D_LOGIN_CHECK_MAX_ATTEMPT', 0)
        if login_max_attempt == 0:
            logger.warning(
                "SECURITY WARNING: Domain uses 'plain' authentication without user-based rate limiting. "
                "Consider setting SOGO_D_LOGIN_CHECK_MAX_ATTEMPT > 0 to protect against brute force attacks."
            )
    
    # Check if password change is disabled
    if settings.get('SOGO_D_PWD_CHANGE_ENABLED') is False:
        logger.warning(
            "SECURITY WARNING: Password change is disabled for this domain. "
            "Users will not be able to change their passwords. "
            "Consider enabling SOGO_D_PWD_CHANGE_ENABLED."
        )
    
    # Check if MFA is not enforced
    login_mfa_force = settings.get('SOGO_D_LOGIN_MFA_FORCE')
    if login_mfa_force is False or login_mfa_force is None:
        logger.warning(
            "SECURITY WARNING: Multi-factor authentication (MFA) is not enforced for this domain. "
            "Consider enabling SOGO_D_LOGIN_MFA_FORCE to require MFA for all logins."
        )
    
    # Check for weak rate limiting settings
    ip_max_attempt = settings.get('SOGO_D_LOGIN_IP_MAX_ATTEMPT', 20)
    ip_time_span = settings.get('SOGO_D_LOGIN_IP_TIME_SPAN', 60)
    if ip_max_attempt < 10 and ip_time_span < 300:
        logger.warning(
            "SECURITY WARNING: IP-based rate limiting may be too lenient. "
            "Current settings: %d attempts per %d seconds. "
            "Consider more restrictive settings for better protection against brute force attacks.",
            ip_max_attempt, ip_time_span
        )
    
    # Check for missing OpenID client secret (if OpenID is enabled)
    if settings.get('SOGO_D_AUTH_TYPE') == 'openid':
        client_secret = settings.get('SOGO_D_OPENID_CLIENT_SECRET', '')
        if not client_secret:
            logger.error(
                "SECURITY ERROR: OpenID authentication is enabled but SOGO_D_OPENID_CLIENT_SECRET is not configured. "
                "This will prevent authentication from working."
            )


if TYPE_CHECKING:
    from app.config.settings.ProcessSetting import ProcessSetting
    from app.manager.db.ClientSQL import ClientSQL
    from app.utils.api.paginate_sort_filter import CollectionPaginateArgs

class ModuleAdminConfig:
    """
    Module to handle systems, domains and rules settings
    """
    def __init__(self, process_settings: ProcessSetting):
        """
        Initialize the admin config module

        :param process_settings: Process settings containing database configuration
        :type process_settings: ProcessSetting
        """
        self.process_settings  = process_settings
        sogo_db_type = f"Client{process_settings.SOGO_P_DB_TYPE}"

        self.sogo_db_manager: ClientSQL = import_and_instantiate_manager(module_path="app.manager.db",
                                                         module_and_class_name=sogo_db_type,
                                                         module_args=self.process_settings.get_db_settings())

    def get_dynamic_form_settings(self) -> dict:
        """
        Return the full dictionnary with the dynamic form format

        :return: The full dynamic form
        :rtype: dict
        """
        full_form: dict = {}
        #System settings
        full_form["system"] = []
        for schema in get_all_system_schemas():
            full_form["system"].append(create_dynamic_dict_for_settings(schema()))

        #Domain settings
        full_form["domain"] = []
        for schema in get_all_domain_schemas():
            full_form["domain"].append(create_dynamic_dict_for_settings(schema()))


        return full_form

    def _get_setting_from_table_settings(self, column_tuple: tuple) -> tuple:
        """
        Generic function that fetch, test and return the configuration/dict
        found in the `column_table` of table `TABLE_SETTINGS`

        This table should only be one row

        :param column_name: name of the colum from `TABLE_SETTINGS` to fetch the data
        :type column_name: str
        :raises AggravatedException: if `TABLE_SETTINGS` has more than one row
        :return: the data found in the column. Can be empty if this is the first time setting up SOGo
        :rtype: dict
        """
        self.sogo_db_manager.connect()

        #Get the current system settings, purposely put a "true" condition to check if there is only 1 row.
        cond_select = NotEqualCondition(param_name=tbl.COL_SETTINGS_UNIQUE.name, param_value=0)
        result  = list(self.sogo_db_manager.select_from_table(table_name=tbl.TABLE_SETTINGS.name,
                                               column_tuple=column_tuple,
                                               condition=cond_select))
        size = len(result)
        if size > 1:
            #There is more than one row in table tbl.TABLE_SETTINGS which is not normal
            logger.error("Table %s has more than one row (%s}) which is not normal. Please check manually this table", tbl.TABLE_SETTINGS.name ,size)
            raise AggravatedException(f"Table {tbl.TABLE_SETTINGS.name} has more than one row ({size}) which is not normal. Please check manually this table")

        if size == 0:
            #Empty, this is the first time SOGo is configured.
            logger.warning("Table %s is empty, which is normal if this is the first time you use SOGo", tbl.TABLE_SETTINGS.name)
            ret: tuple = ({},)
            for _ in range(len(column_tuple)-1):
                ret += ret
            return ret

        ret = result[0]

        # MySQL/MariaDB returns JSON columns as strings, PostgreSQL returns parsed dicts.
        # Normalize to dict for consistent behavior across database backends.
        parsed = []
        for value in ret:
            if isinstance(value, str):
                try:
                    parsed.append(json_module.loads(value))
                except (json_module.JSONDecodeError, TypeError):
                    parsed.append(value)
            else:
                parsed.append(value)
        ret = tuple(parsed)

        return ret


    def get_system_settings(self) -> dict:
        """
        Return the system settings or an empty dict if there is not

        :return: dict with current system settings
        :rtype: dict
        """

        return self._get_setting_from_table_settings((tbl.COL_SETTINGS_SYSTEM.name,))[0]

    def get_default_domain_settings(self) -> dict:
        """
        Return the default domain settings or an empty dict if there is not

        :return: dict with current default domain settings
        :rtype: dict
        """
        settings = self._get_setting_from_table_settings((tbl.COL_SETTINGS_DOMAIN_DEFAULT.name,))[0]
        
        # Check for insecure settings and log warnings
        if isinstance(settings, dict):
            _warn_insecure_domain_settings(settings)
        
        return settings

    def get_theme_settings(self) -> dict:
        """
        Return the theme settings or an empty dict if there is not

        :return: dict with current theme settings
        :rtype: dict
        """
        return self._get_setting_from_table_settings((tbl.COL_SETTINGS_THEME.name,))[0]

    def get_rules_list(self) -> list[dict]:
        """
        Return the list of all rules.

        :return: List of dicts with id and name for each rule
        :rtype: list[dict]
        """
        self.sogo_db_manager.connect()
        result = list(self.sogo_db_manager.select_from_table(
            table_name=tbl.TABLE_RULES.name,
            column_tuple=(tbl.COL_ID.name, tbl.COL_RULE_NAME.name),
            condition=TrueCondition(),
        ))
        return [{"id": row[0], "name": row[1]} for row in result]

    def get_one_rule(self, rule_id: int) -> dict:
        """
        Get a single rule by its id.

        :param rule_id: Rule id
        :type rule_id: int
        :raises RequestException: if rule not found
        :return: dict with rule data
        :rtype: dict
        """
        self.sogo_db_manager.connect()
        cond = EqualCondition(param_name=tbl.COL_ID.name, param_value=rule_id)
        result = list(self.sogo_db_manager.select_from_table(
            table_name=tbl.TABLE_RULES.name,
            column_tuple=tuple(col.name for col in tbl.TABLE_RULES.columns),
            condition=cond,
        ))
        if len(result) == 0:
            raise RequestException(f"Rule with id {rule_id} not found", err.ERROR_RULE_NOT_FOUND)
        row = result[0]
        col_names = [col.name for col in tbl.TABLE_RULES.columns]
        ret = dict(zip(col_names, row))
        if tbl.COL_RULE_SETTINGS.name in ret and isinstance(ret[tbl.COL_RULE_SETTINGS.name], str):
            ret[tbl.COL_RULE_SETTINGS.name] = json_module.loads(ret[tbl.COL_RULE_SETTINGS.name])
        if tbl.COL_RULE_DOMAINS.name in ret and isinstance(ret[tbl.COL_RULE_DOMAINS.name], str):
            ret[tbl.COL_RULE_DOMAINS.name] = json_module.loads(ret[tbl.COL_RULE_DOMAINS.name])
        return ret

    def create_rule(self, data: dict) -> tuple[str, dict]:
        """
        Create a new rule.

        :param data: dict with rule_name, rule_description, rule_domains, rule_setting
        :type data: dict
        :return: (error_code, result_dict)
        :rtype: tuple[str, dict]
        """
        self.sogo_db_manager.connect()

        rule_name = data["rule_name"]
        rule_description = data.get("rule_description", "")
        rule_domains = data.get("rule_domains", [])
        rule_setting = data.get("rule_setting", {})

        # Check unique name
        cond = EqualCondition(param_name=tbl.COL_RULE_NAME.name, param_value=rule_name)
        existing = list(self.sogo_db_manager.select_from_table(
            table_name=tbl.TABLE_RULES.name,
            column_tuple=(tbl.COL_ID.name,),
            condition=cond,
        ))
        if existing:
            raise RequestException(f"Rule name '{rule_name}' already exists", err.ERROR_RULE_NAME_TAKEN)

        value_hash = get_unique_token(HASH_SIZE_DOMAIN)

        insert_values = [[
            value_hash,
            rule_name,
            rule_description,
            rule_domains,
            rule_setting,
        ]]
        columns = (
            tbl.COL_HASH.name,
            tbl.COL_RULE_NAME.name,
            tbl.COL_RULE_DESCRIPTION.name,
            tbl.COL_RULE_DOMAINS.name,
            tbl.COL_RULE_SETTINGS.name,
        )

        try:
            row_updated = self.sogo_db_manager.insert_in_table(
                table_name=tbl.TABLE_RULES.name,
                column_tuple=columns,
                values_tuple=insert_values,
            )
        except BugException:
            value_hash = get_unique_token(HASH_SIZE_DOMAIN + 1)
            insert_values[0][0] = value_hash
            row_updated = self.sogo_db_manager.insert_in_table(
                table_name=tbl.TABLE_RULES.name,
                column_tuple=columns,
                values_tuple=insert_values,
            )

        if row_updated != 1:
            logger.error("Failed to create rule, rows affected: %s", row_updated)
            raise BugException(f"Failed to create rule, rows affected: {row_updated}", err.ERROR_UNKOWN)

        # Fetch the inserted rule to get its auto-generated id
        cond = EqualCondition(param_name=tbl.COL_HASH.name, param_value=value_hash)
        result = list(self.sogo_db_manager.select_from_table(
            table_name=tbl.TABLE_RULES.name,
            column_tuple=(tbl.COL_ID.name,),
            condition=cond,
        ))
        rule_id = result[0][0] if result else None

        return err.ERROR_NO_ERROR.c, {
            "id": rule_id,
            "hash": value_hash,
            "rule_name": rule_name,
            "rule_description": rule_description,
            "rule_domains": rule_domains,
            "rule_setting": rule_setting,
        }

    def update_one_rule(self, rule_id: int, new_param: dict) -> tuple[str, dict]:
        """
        Update a rule.

        :param rule_id: Rule id
        :type rule_id: int
        :param new_param: dict with fields to update
        :type new_param: dict
        :return: (error_code, result_dict)
        :rtype: tuple[str, dict]
        """
        self.sogo_db_manager.connect()

        stored = self.get_one_rule(rule_id)

        # Merge patch
        for key in ("rule_name", "rule_description", "rule_domains", "rule_setting"):
            if key in new_param:
                stored[key] = new_param[key]

        col_names = []
        values = []
        for key in ("rule_name", "rule_description", "rule_domains", "rule_setting"):
            col_names.append(key)
            values.append(stored[key])

        cond = EqualCondition(param_name=tbl.COL_ID.name, param_value=rule_id)
        row_updated = self.sogo_db_manager.update_in_table(
            table_name=tbl.TABLE_RULES.name,
            column_tuple=tuple(col_names),
            values_list=values,
            condition=cond,
        )

        if row_updated != 1:
            logger.error("Failed to update rule %s, rows affected: %s", rule_id, row_updated)
            raise BugException(f"Failed to update rule {rule_id}, rows affected: {row_updated}", err.ERROR_UNKOWN)

        return err.ERROR_NO_ERROR.c, stored

    def delete_one_rule(self, rule_id: int) -> int:
        """
        Delete a rule.

        :param rule_id: Rule id
        :type rule_id: int
        :raises RequestException: if rule not found
        :return: number of deleted rows
        :rtype: int
        """
        self.sogo_db_manager.connect()

        # Verify existence
        self.get_one_rule(rule_id)

        cond = EqualCondition(param_name=tbl.COL_ID.name, param_value=rule_id)
        deleted = self.sogo_db_manager.delete_row_in_table(tbl.TABLE_RULES.name, cond, expected_row=1)
        return deleted

    def get_both_system_and_default_domain_settings(self) -> tuple[dict, dict]:
        """
        Return a tuple of both system settings and default domain settings

        :return: Tuple containing system settings and default domain settings
        :rtype: tuple[dict, dict]
        """

        return self._get_setting_from_table_settings((tbl.COL_SETTINGS_SYSTEM.name,tbl.COL_SETTINGS_DOMAIN_DEFAULT.name))

    def get_all_domains_settings(self, collection_param: CollectionPaginateArgs) -> tuple[int, list]:
        """Return a list of all domains settings with pagination, sorting and filtering options
        """

        offset = collection_param.first_item
        limit = collection_param.last_item - offset + 1

        # Validation of the requested columns.
        column_names = [col.name for col in tbl.TABLE_DOMAIN.columns]
        if collection_param.fields:
            requested = collection_param.fields.split(",")
            if collection_param.fields_action == "include":
                columns = [tbl.TABLE_DOMAIN.get_column_from_name(f) for f in requested]
                column_names = [col.name for col in columns]
            if collection_param.fields_action == "exclude":
                for field in requested:
                    column_names.remove(field)

        # Validation of sorting parameters
        order = Order.ASC if collection_param.sort_order == "asc" else Order.DESC
        sort_column = tbl.TABLE_DOMAIN.get_column_from_name(collection_param.sort_by).name if collection_param.sort_by else None

        # Fetch data from the database
        self.sogo_db_manager.connect()
        cond_select = TrueCondition()
        count = self.sogo_db_manager.count_row_in_table(table_name=tbl.TABLE_DOMAIN.name, condition=cond_select)
        result = list(self.sogo_db_manager.select_from_table(
            table_name=tbl.TABLE_DOMAIN.name,
            column_tuple=tuple(column_names),
            condition=cond_select,
            offset=offset,
            limit=limit,
            sort_by=sort_column,
            order=order,
        ))

        # Process results into a list of dictionaries
        ret = []
        for record in result:
            record_dict = dict(zip(column_names, record))
            if "settings" in record_dict:
                # MySQL/MariaDB returns JSON columns as strings, PostgreSQL returns parsed dicts.
                # Normalize to dict for consistent behavior across database backends.
                if isinstance(record_dict["settings"], str):
                    try:
                        record_dict["settings"] = json_module.loads(record_dict["settings"])
                    except (json_module.JSONDecodeError, TypeError):
                        record_dict["settings"] = {}
            ret.append(record_dict)

        return count, ret

    def get_one_domain_setting(self, domain_id:str, columns: tuple[Column, ...]|None = None) -> dict:
        """
        Get one domain setting for the specified domain ID

        :param domain_id: The domain name/ID
        :type domain_id: str
        :param columns: Database columns to query, defaults to None (all columns)
        :type columns: tuple[Column, ...]|None
        :return: Dictionary containing domain settings
        :rtype: dict
        """
        self.sogo_db_manager.connect()

        if columns is not None:
            for column in columns:
                if column.name not in tbl.TABLE_DOMAIN.columns_name:
                    raise BugException(f"Trying to query a column {column.name} that does not exist in {tbl.TABLE_DOMAIN.name}")
            column_tuple = tuple(col.name for col in columns)
        else:
            column_tuple = tuple(col.name for col in tbl.TABLE_DOMAIN.columns)

        #Get the domain setting
        cond_select = EqualCondition(param_name=tbl.COL_DOMAIN_NAME.name, param_value=domain_id)
        result = list(self.sogo_db_manager.select_from_table(table_name=tbl.TABLE_DOMAIN.name,
                                               column_tuple=column_tuple,
                                               condition=cond_select))
        size = len(result)
        if size > 1:
            #There is more than one row which is impossible as the domain_name is not duplicable
            logger.error("Table %s has more than one row (%s}) with the same domain_name: %s. Please check manually this table", tbl.TABLE_DOMAIN.name, size, domain_id)
            raise AggravatedException(f"Table {tbl.TABLE_SETTINGS.name} has more than one row ({size}) with the same domain_name {domain_id}. Please check manually this table")

        if size == 0:
            #Empty, the resource does not exist
            logger.debug("No domain found for name %s, return the default one", domain_id)
            default_settings = self.get_default_domain_settings()
            origins = set_origin_from_settings("default", default_settings, default_settings)
            return {
                "domain_name": "default",
                "settings": default_settings,
                "origin": origins
            }

        ret: dict = {}
        for idx, col in enumerate(column_tuple):
            if col == tbl.COL_DOMAIN_SETTINGS.name:
                ret["settings"] = result[0][idx]
            else:
                ret[col] = result[0][idx]

        # Check for insecure settings and log warnings
        if "settings" in ret and isinstance(ret["settings"], dict):
            _warn_insecure_domain_settings(ret["settings"])

        return ret

    def _update_setting_in_table_settings(self, new_param: dict, column_name: str, get_schema: Callable) -> tuple[str, dict]:
        """
        new_param is expected to be of JSON merge patch.
        If the subparent allows multiple entrees, it should be a dict key=uid, value=dict of param
        {
            subparent1: {
                            setting1.1: value1.1,
                            setting1.2: value1.2,
                        },
            subparent2: {
                            setting2.1: value2.1,
                            setting2.2: value2.2,
                        },
            subparent3: {
                    "uid1": {
                            setting3.0.1: value3.0.1,
                            setting3.0.2: value3.0.2,
                        },
                    "uid2": {
                            setting3.1.1: value3.1.1,
                            setting3.1.2: value3.1.2,
                        }
        }

        :param new_param: values for the settings
        :type new_param: dict
        :param new_param: column name of the settings (either system or domain_default)
        :type new_param: str
        :return: True if everything was ok, False with a string that explains the problem
        :rtype: tuple[bool, str]

        :raises: ValidationError()
        :raises: AggravatedException()
        """

        self.sogo_db_manager.connect()

        #Get the current system settings, purposely put a "true" condition to check if there is only 1 row.
        cond_select = NotEqualCondition(param_name=tbl.COL_SETTINGS_UNIQUE.name, param_value=0)
        result  = list(self.sogo_db_manager.select_from_table(table_name=tbl.TABLE_SETTINGS.name,
                                               column_tuple=(column_name,),
                                               condition=cond_select))
        size = len(result)
        if size > 1:
            #There is more than one row in table TABLE_SETTINGS which is not normal
            logger.error("Table %s has more than one row (%s}) which is not normal. Please check manually this table", tbl.TABLE_SETTINGS.name ,size)
            raise AggravatedException(f"Table {tbl.TABLE_SETTINGS.name} has more than one row ({size}) which is not normal", err.ERROR_TABLE_SYSTEM_NOT_UNIQUE)

        ret = -1
        values: dict = {}
        if size == 0:
            #Empty, this is the first time SOGo is configured.
            logger.warning("Table %s is empty, which is normal if this is the first time you use SOGo", tbl.TABLE_SETTINGS.name)
            clean_param: dict = {}
            merge_patch(new_param, clean_param)
            values = check_data_for_sogo_schemas(clean_param, get_schema)
            if column_name == tbl.COL_SETTINGS_SYSTEM.name:
                values_tuple = [1, values, {}, {}]
            elif column_name == tbl.COL_SETTINGS_DOMAIN_DEFAULT.name:
                values_tuple = [1, {}, values, {}]
            else:
                raise BugException(f"Trying to insert an unknown column in {tbl.TABLE_SETTINGS.name}: {column_name}", err.ERROR_BUG_UNKNWON_COLUMN)
            ret = self.sogo_db_manager.insert_in_table(table_name=tbl.TABLE_SETTINGS.name,
                                               column_tuple=(tbl.COL_SETTINGS_UNIQUE.name, tbl.COL_SETTINGS_SYSTEM.name,tbl.COL_SETTINGS_DOMAIN_DEFAULT.name,tbl.COL_SETTINGS_THEME.name),
                                               values_tuple=[values_tuple])
            if ret != 1:
                logger.error("Something went wrong when inserting the system settings, rows inserted: %s, should be 1", ret)
                raise BugException(f"Something went wrong when inserting the system settings, rows inserted: {ret}, should be 1", err.ERROR_TABLE_SYSTEM_NOT_UNIQUE)
        if size == 1:
            #Merge the new data and check it
            current_settings: dict = result[0][0]
            # MySQL/MariaDB returns JSON columns as strings, normalize to dict
            if isinstance(current_settings, str):
                try:
                    current_settings = json_module.loads(current_settings)
                except (json_module.JSONDecodeError, TypeError):
                    current_settings = {}
            merge_patch(new_param, current_settings)

            values = check_data_for_sogo_schemas(current_settings, get_schema)

            #Update the column
            cond_update = EqualCondition(param_name=tbl.COL_SETTINGS_UNIQUE.name, param_value=1)
            ret = self.sogo_db_manager.update_in_table(table_name=tbl.TABLE_SETTINGS.name,
                                               column_tuple=(column_name,),
                                               values_list=[values],
                                               condition=cond_update)
            # For UPDATE, ret can be 0 if no rows were actually changed (data already matches)
            # This is valid behavior, not an error (MySQL returns 0 when no data changes)
            if ret < 0:
                logger.error("Something went wrong when updating the system settings, rows updated: %s", ret)
                raise BugException(f"Something went wrong when updating the system settings, rows updated: {ret}", err.ERROR_TABLE_SYSTEM_NOT_UNIQUE)

        return err.ERROR_NO_ERROR.c, values


    def update_system_settings(self, new_param: dict) -> tuple[str, dict]:
        """
        Method to update/insert the system settings

        :param new_param: values for the settings
        :type new_param: dict
        :return: Return the code error and the new settings values
        :rtype: tuple[int, dict]
        """

        return self._update_setting_in_table_settings(new_param, tbl.COL_SETTINGS_SYSTEM.name, get_all_system_schemas)

    def update_domain_default_settings(self, new_param: dict) -> tuple[str, dict]:
        """
        Method to update/insert the default domain settings

        :param new_param: values for the settings
        :type new_param: dict
        :return: Return the code error and the new settings values
        :rtype: tuple[int, dict]
        """

        return self._update_setting_in_table_settings(new_param, tbl.COL_SETTINGS_DOMAIN_DEFAULT.name, get_all_domain_schemas)

    def update_theme_settings(self, new_param: dict) -> tuple[str, dict]:
        """
        Update the theme settings.
        Accepts a dict of theme variables (e.g. {"primary": "#123456", ...}).

        :param new_param: values for the theme settings
        :type new_param: dict
        :return: (error_code, new_values)
        :rtype: tuple[str, dict]
        """
        self.sogo_db_manager.connect()

        cond_select = NotEqualCondition(param_name=tbl.COL_SETTINGS_UNIQUE.name, param_value=0)
        result = list(self.sogo_db_manager.select_from_table(
            table_name=tbl.TABLE_SETTINGS.name,
            column_tuple=(tbl.COL_SETTINGS_THEME.name,),
            condition=cond_select
        ))
        size = len(result)

        values: dict = {}
        if size == 0:
            # First-time setup — insert row with theme column
            values = new_param
            values_tuple = [1, {}, {}, values]
            ret = self.sogo_db_manager.insert_in_table(
                table_name=tbl.TABLE_SETTINGS.name,
                column_tuple=(
                    tbl.COL_SETTINGS_UNIQUE.name,
                    tbl.COL_SETTINGS_SYSTEM.name,
                    tbl.COL_SETTINGS_DOMAIN_DEFAULT.name,
                    tbl.COL_SETTINGS_THEME.name,
                ),
                values_tuple=[values_tuple],
            )
        elif size == 1:
            current_raw = result[0][0] or {}
            if isinstance(current_raw, str):
                current = json_module.loads(current_raw)
            else:
                current = dict(current_raw) if current_raw else {}
            # JSON Merge Patch
            current.update(new_param)
            values = current

            cond_update = EqualCondition(param_name=tbl.COL_SETTINGS_UNIQUE.name, param_value=1)
            ret = self.sogo_db_manager.update_in_table(
                table_name=tbl.TABLE_SETTINGS.name,
                column_tuple=(tbl.COL_SETTINGS_THEME.name,),
                values_list=[values],
                condition=cond_update,
            )
        else:
            logger.error("Table %s has more than one row (%s)", tbl.TABLE_SETTINGS.name, size)
            raise AggravatedException(
                f"Table {tbl.TABLE_SETTINGS.name} has more than one row ({size})",
                err.ERROR_TABLE_SYSTEM_NOT_UNIQUE,
            )

        if ret != 1:
            logger.error("Failed to update theme settings, rows affected: %s", ret)
            raise BugException(
                f"Failed to update theme settings, rows affected: {ret}",
                err.ERROR_TABLE_SYSTEM_NOT_UNIQUE,
            )

        return err.ERROR_NO_ERROR.c, values

    def create_domain_settings(self, new_param: dict) -> tuple[str, dict]:
        """
        Create new domain settings
        """

        self.sogo_db_manager.connect()
        domain_name = new_param["domain_name"]

        domain_cond = EqualCondition(tbl.COL_DOMAIN_NAME.name, domain_name)
        domain_result = list(self.sogo_db_manager.select_from_table(table_name=tbl.TABLE_DOMAIN.name,
                                               column_tuple=(tbl.COL_DOMAIN_NAME.name,),
                                               condition=domain_cond))
        if len(domain_result) > 0:
            raise RequestException(f"Domain's name '{domain_name}' already taken", err.ERROR_DOMAIN_NAME_TAKEN)

        domain_description = new_param.get("domain_description", "")
        domain_info = new_param.get("domain_info", {})

        values_default = self.get_default_domain_settings()
        values_new = new_param.get("settings", {})

        origins = set_origin_from_settings(domain_name, values_new, values_default)

        values_default.update(values_new)
        values = check_data_for_sogo_schemas(values_default, get_all_domain_schemas)

        value_hash = get_unique_token(HASH_SIZE_DOMAIN)

        insert_values = [[value_hash, domain_name, domain_description, domain_info, values, origins]]
        colums = (tbl.COL_HASH.name, tbl.COL_DOMAIN_NAME.name, tbl.COL_DOMAIN_DESCRIPTION.name, tbl.COL_DOMAIN_INFO.name, tbl.COL_DOMAIN_SETTINGS.name, tbl.COL_DOMAIN_ORIGIN.name)

        #Insert in column
        try:
            row_updated = self.sogo_db_manager.insert_in_table(table_name=tbl.TABLE_DOMAIN.name,
                                            column_tuple=colums,
                                            values_tuple=insert_values)
        except BugException:
            #Means there is a unique violation either for column domain_name
            #(could happen if another request in anoter worker did it at the same time)
            #Or the hash is already taken. Check the log to see which column has a problem.
            #If hash, try to do it again with another token
            value_hash = get_unique_token(HASH_SIZE_DOMAIN+1)
            insert_values[0][0] = value_hash
            row_updated = self.sogo_db_manager.insert_in_table(table_name=tbl.TABLE_DOMAIN.name,
                                            column_tuple=colums,
                                            values_tuple=insert_values)

        if row_updated != 1:
            #Only one row is supposed to be updated
            logger.error("Something went wrong when updating the system settings, rows updated: %s, should be 1", row_updated)
            raise BugException(f"Something went wrong when updating the system settings, rows updated: {row_updated}, should be 1", err.ERROR_TABLE_SYSTEM_NOT_UNIQUE)

        result = {
            "hash": value_hash,
            "domain_name": domain_name,
            "domain_description": domain_description,
            "domain_info": domain_info,
            "settings": values,
            "origin": origins,
        }

        return err.ERROR_NO_ERROR.c, result

    def update_one_domain_settings(self, domain_id:str, new_param: dict) -> tuple[str, dict]:
        """
        Method to update the default domain settings

        :param new_param: values for the settings
        :type new_param: dict
        :return: Return the code error and the new settings values
        :rtype: tuple[int, dict]
        """

        self.sogo_db_manager.connect()

        # raise RequestException if domain not found
        stored_data = self.get_one_domain_setting(domain_id)
        if stored_data.get("domain_name") != domain_id:
            # get_one_domain_setting silently falls back to the default-shaped
            # dict (domain_name="default") when no row exists; patching a
            # nonexistent domain must 404 instead of crashing on missing keys.
            raise RequestException(f"Domain '{domain_id}' not found", err.ERROR_DOMAIN_NAME_NOT_FOUND)

        merge_patch(new_param, stored_data)

        values = check_data_for_sogo_schemas(stored_data["settings"], get_all_domain_schemas)
        values_default = self.get_default_domain_settings()
        origins = set_origin_from_settings(domain_id, values, values_default)

        update_values = [stored_data.get("domain_description", ""), stored_data.get("domain_info", {}), values, origins]
        colums = (tbl.COL_DOMAIN_DESCRIPTION.name, tbl.COL_DOMAIN_INFO.name, tbl.COL_DOMAIN_SETTINGS.name, tbl.COL_DOMAIN_ORIGIN.name)

        #Update in column
        cond = EqualCondition(tbl.COL_DOMAIN_NAME.name, domain_id)
        row_updated = self.sogo_db_manager.update_in_table(table_name=tbl.TABLE_DOMAIN.name,
                                            column_tuple=colums,
                                            values_list=update_values,
                                            condition=cond)
        if row_updated != 1:
            #Only one row is supposed to be updated
            logger.error("Something went wrong when updating the domain setting for %s, rows updated: %s, should be 1", domain_id, row_updated)
            raise BugException(f"Something went wrong when updating the system settings, rows updated: {row_updated}, should be 1", err.ERROR_TABLE_SYSTEM_NOT_UNIQUE)

        result = {
            "domain_name": domain_id,
            "domain_description": stored_data["domain_description"],
            "domain_info": stored_data["domain_info"],
            "settings": values,
            "origin": origins,
        }

        return err.ERROR_NO_ERROR.c, result

    def delete_one_domain_setting(self, domain_id:str) -> int:
        """
        Delete onr 

        :param domain_id: _description_
        :raises RequestException: raise if 0 or more than 1 row would have been deleted
        :type domain_id: str
        """
        self.sogo_db_manager.connect()

        #Just use this method to check if the domain exist
        stored_data = self.get_one_domain_setting(domain_id)
        if stored_data.get("domain_name") != domain_id:
            # get_one_domain_setting silently falls back to the default-shaped
            # dict (domain_name="default") when no row exists; deleting a
            # nonexistent domain must 404 instead of surfacing the raw
            # row-count mismatch from delete_row_in_table (500 S000403).
            raise RequestException(f"Domain '{domain_id}' not found", err.ERROR_DOMAIN_NAME_NOT_FOUND)

        cond = EqualCondition(tbl.COL_DOMAIN_NAME.name, domain_id)

        deleted_rows = self.sogo_db_manager.delete_row_in_table(tbl.TABLE_DOMAIN.name, cond, expected_row=1)

        return deleted_rows
