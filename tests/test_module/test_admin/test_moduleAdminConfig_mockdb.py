# pylint: disable=invalid-sequence-index
"""Unit tests for ModuleAdminConfig (settings/rules/domains) with a mocked DB manager."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest

from app.module.admin.ModuleAdminConfig import ModuleAdminConfig
from app.utils.exceptions import AggravatedException, BugException, RequestException
from app.utils import errors as err


@pytest.fixture
def mod():
    proc = mock.MagicMock()
    proc.SOGO_P_DB_TYPE = "SQLite"
    proc.get_db_settings.return_value = {"path": ":memory:"}
    inst = mock.MagicMock()
    with mock.patch(
        "app.module.admin.ModuleAdminConfig.import_and_instantiate_manager",
        return_value=inst,
    ) as imm, mock.patch(
        "app.module.admin.ModuleAdminConfig.check_data_for_sogo_schemas",
        side_effect=lambda data, schema: data,
    ) as check:
        m = ModuleAdminConfig(proc)
        yield SimpleNamespace(mod=m, db=inst, imm=imm, check=check, proc=proc)


class TestInit:
    def test_builds_db_manager(self, mod):
        assert mod.mod.sogo_db_manager is mod.db
        mod.imm.assert_called_once_with(
            module_path="app.manager.db",
            module_and_class_name="ClientSQLite",
            module_args={"path": ":memory:"},
        )


class TestDynamicForm:
    def test_has_system_and_domain(self, mod):
        out = mod.mod.get_dynamic_form_settings()
        assert "system" in out
        assert "domain" in out
        assert isinstance(out["system"], list)
        assert isinstance(out["domain"], list)


class TestGetSettingFromTable:
    def test_returns_row(self, mod):
        mod.db.select_from_table.return_value = [("{}",)]
        ret = mod.mod._get_setting_from_table_settings(("settings_system",))
        assert ret == ({},)
        mod.db.connect.assert_called_once()

    def test_normalizes_json_string(self, mod):
        mod.db.select_from_table.return_value = [('{"a": 1}',)]
        ret = mod.mod._get_setting_from_table_settings(("settings_system",))
        assert ret == ({"a": 1},)

    def test_invalid_json_passthrough(self, mod):
        mod.db.select_from_table.return_value = [("not json",)]
        ret = mod.mod._get_setting_from_table_settings(("settings_system",))
        assert ret == ("not json",)

    def test_empty_table_returns_tuple_of_empty_dicts(self, mod):
        mod.db.select_from_table.return_value = []
        ret = mod.mod._get_setting_from_table_settings(("a", "b"))
        assert ret == ({}, {})

    def test_more_than_one_row_raises(self, mod):
        mod.db.select_from_table.return_value = [("{}", "{}"), ("{}", "{}")]
        with pytest.raises(AggravatedException):
            mod.mod._get_setting_from_table_settings(("a",))


class TestGetters:
    def test_get_system_settings(self, mod):
        mod.db.select_from_table.return_value = [('{"x": 1}',)]
        assert mod.mod.get_system_settings() == {"x": 1}

    def test_get_default_domain_settings_warns(self, mod):
        mod.db.select_from_table.return_value = [('{"SOGO_D_AUTH_TYPE": "plain"}',)]
        with mock.patch("app.module.admin.ModuleAdminConfig.logger") as lg:
            out = mod.mod.get_default_domain_settings()
        assert out["SOGO_D_AUTH_TYPE"] == "plain"
        assert lg.warning.call_count >= 1

    def test_get_theme_settings(self, mod):
        mod.db.select_from_table.return_value = [('{"primary": "#fff"}',)]
        assert mod.mod.get_theme_settings() == {"primary": "#fff"}

    def test_get_both(self, mod):
        mod.db.select_from_table.return_value = [('{"s": 1}', '{"d": 2}')]
        sys_s, dom_s = mod.mod.get_both_system_and_default_domain_settings()
        assert sys_s == {"s": 1}
        assert dom_s == {"d": 2}


class TestRulesList:
    def test_get_rules_list(self, mod):
        mod.db.select_from_table.return_value = [(1, "R1"), (2, "R2")]
        assert mod.mod.get_rules_list() == [{"id": 1, "name": "R1"}, {"id": 2, "name": "R2"}]

    def test_get_one_rule(self, mod):
        row = (7, "h", "R1", "desc", '["a"]', '{"mfa": true}')
        mod.db.select_from_table.return_value = [row]
        out = mod.mod.get_one_rule(7)
        assert out["rule_name"] == "R1"
        assert out["rule_domains"] == ["a"]
        assert out["rule_setting"] == {"mfa": True}

    def test_get_one_rule_not_found(self, mod):
        mod.db.select_from_table.return_value = []
        with pytest.raises(RequestException) as ex:
            mod.mod.get_one_rule(99)
        assert ex.value.error.c == "S000381"


class TestCreateRule:
    def test_create_rule(self, mod):
        mod.db.select_from_table.return_value = []
        mod.db.insert_in_table.return_value = 1
        mod.db.select_from_table.side_effect = [[], [(12,)]]
        code, out = mod.mod.create_rule({
            "rule_name": "R", "rule_description": "d",
            "rule_domains": ["a.org"], "rule_setting": {"x": 1},
        })
        assert code == err.ERROR_NO_ERROR.c
        assert out["id"] == 12
        assert out["rule_name"] == "R"
        mod.db.insert_in_table.assert_called_once()

    def test_create_rule_row_tuple(self, mod):
        # select returns raw tuple (not list-wrapped) for fetch-id
        mod.db.select_from_table.side_effect = [[], [(3,)]]
        mod.db.insert_in_table.return_value = 1
        code, out = mod.mod.create_rule({"rule_name": "R"})
        assert code == err.ERROR_NO_ERROR.c
        assert out["id"] == 3

    def test_create_rule_duplicate_name(self, mod):
        mod.db.select_from_table.return_value = [(1,)]
        with pytest.raises(RequestException) as ex:
            mod.mod.create_rule({"rule_name": "R"})
        assert ex.value.error.c == "S000380"

    def test_create_rule_retries_on_bug(self, mod):
        mod.db.select_from_table.side_effect = [[], [(5,)]]
        mod.db.insert_in_table.side_effect = [BugException("dup", err.ERROR_UNKOWN), 1]
        code, out = mod.mod.create_rule({"rule_name": "R"})
        assert code == err.ERROR_NO_ERROR.c
        assert mod.db.insert_in_table.call_count == 2

    def test_create_rule_rows_not_1(self, mod):
        mod.db.select_from_table.side_effect = [[], [(5,)]]
        mod.db.insert_in_table.return_value = 2
        with pytest.raises(BugException):
            mod.mod.create_rule({"rule_name": "R"})


class TestUpdateRule:
    def test_update_one_rule(self, mod):
        row = (7, "h", "Old", "d", '["a"]', '{"x": 1}')
        mod.db.select_from_table.return_value = [row]
        mod.db.update_in_table.return_value = 1
        code, out = mod.mod.update_one_rule(7, {"rule_name": "New"})
        assert code == err.ERROR_NO_ERROR.c
        assert out["rule_name"] == "New"
        cond = mod.db.update_in_table.call_args.kwargs["condition"]
        assert cond.param_value == 7

    def test_update_rule_rows_not_1(self, mod):
        mod.db.select_from_table.return_value = [(7, "h", "R", "d", [], {})]
        mod.db.update_in_table.return_value = 0
        with pytest.raises(BugException):
            mod.mod.update_one_rule(7, {"rule_name": "X"})


class TestDeleteRule:
    def test_delete_one_rule(self, mod):
        mod.db.select_from_table.return_value = [(7, "h", "R", "d", [], {})]
        mod.db.delete_row_in_table.return_value = 1
        assert mod.mod.delete_one_rule(7) == 1

    def test_delete_one_rule_not_found(self, mod):
        mod.db.select_from_table.return_value = []
        with pytest.raises(RequestException):
            mod.mod.delete_one_rule(7)


class TestAllDomainsSettings:
    def test_default_columns(self, mod):
        cp = SimpleNamespace(first_item=0, last_item=9, fields="", fields_action="include",
                             sort_order="asc", sort_by="")
        mod.db.count_row_in_table.return_value = 2
        mod.db.select_from_table.return_value = [
            (1, "h1", "a.org", "d", "info", '{"x": 1}', "{}"),
            (2, "h2", "b.org", "d", "info", {"x": 2}, "{}"),
        ]
        count, rows = mod.mod.get_all_domains_settings(cp)
        assert count == 2
        assert rows[0]["settings"] == {"x": 1}
        assert rows[1]["settings"] == {"x": 2}
        assert "domain_settings" not in rows[0]
        assert mod.db.select_from_table.call_args.kwargs["offset"] == 0
        assert mod.db.select_from_table.call_args.kwargs["limit"] == 10

    def test_invalid_json_settings_becomes_empty(self, mod):
        cp = SimpleNamespace(first_item=0, last_item=0, fields="", fields_action="include",
                             sort_order="desc", sort_by="domain_name")
        mod.db.count_row_in_table.return_value = 1
        mod.db.select_from_table.return_value = [(1, "h", "a.org", "d", "info", "@@@", "{}")]
        _, rows = mod.mod.get_all_domains_settings(cp)
        assert rows[0]["settings"] == {}

    def test_fields_include(self, mod):
        cp = SimpleNamespace(first_item=0, last_item=4, fields="domain_name,domain_settings",
                             fields_action="include", sort_order="asc", sort_by="")
        mod.db.count_row_in_table.return_value = 1
        mod.db.select_from_table.return_value = [("a.org", '{"x": 1}')]
        _, rows = mod.mod.get_all_domains_settings(cp)
        assert set(rows[0].keys()) == {"domain_name", "settings"}
        assert rows[0]["settings"] == {"x": 1}

    def test_fields_exclude(self, mod):
        cp = SimpleNamespace(first_item=0, last_item=4, fields="domain_description",
                             fields_action="exclude", sort_order="asc", sort_by="")
        mod.db.count_row_in_table.return_value = 1
        mod.db.select_from_table.return_value = [(1, "h", "a.org", "info", '{"x": 1}', "{}")]
        _, rows = mod.mod.get_all_domains_settings(cp)
        assert "domain_description" not in rows[0]
        assert rows[0]["settings"] == {"x": 1}


class TestGetOneDomainSetting:
    def test_found(self, mod):
        mod.db.select_from_table.return_value = [
            (1, "h", "a.org", "d", "info", '{"x": 1}', "{}"),
        ]
        out = mod.mod.get_one_domain_setting("a.org", columns=None)
        assert out["domain_name"] == "a.org"
        assert out["settings"] == '{"x": 1}'
        assert out["hash"] == "h"

    def test_more_than_one_raises(self, mod):
        mod.db.select_from_table.return_value = [(1, "a"), (2, "a")]
        with pytest.raises(AggravatedException):
            mod.mod.get_one_domain_setting("a.org")

    def test_not_found_returns_default(self, mod):
        mod.db.select_from_table.side_effect = [[], [('{"d": 1}',)]]
        out = mod.mod.get_one_domain_setting("absent.org")
        assert out["domain_name"] == "default"
        assert out["settings"] == {"d": 1}
        assert "origin" in out

    def test_unknown_column_raises(self, mod):
        col = mock.MagicMock()
        col.name = "nope"
        with pytest.raises(BugException):
            mod.mod.get_one_domain_setting("a.org", columns=(col,))


class TestUpdateSettingInTableSettings:
    def test_insert_system_first_time(self, mod):
        mod.db.select_from_table.return_value = []
        mod.db.insert_in_table.return_value = 1
        code, values = mod.mod._update_setting_in_table_settings(
            {"a": 1}, "settings_system", mod.check)
        assert code == err.ERROR_NO_ERROR.c
        values_tuple = mod.db.insert_in_table.call_args.kwargs["values_tuple"][0]
        assert values_tuple == [1, {"a": 1}, {}, {}]

    def test_insert_domain_default_first_time(self, mod):
        mod.db.select_from_table.return_value = []
        mod.db.insert_in_table.return_value = 1
        code, _ = mod.mod._update_setting_in_table_settings(
            {"a": 1}, "settings_domain_default", mod.check)
        assert code == err.ERROR_NO_ERROR.c
        values_tuple = mod.db.insert_in_table.call_args.kwargs["values_tuple"][0]
        assert values_tuple == [1, {}, {"a": 1}, {}]

    def test_insert_unknown_column_raises(self, mod):
        mod.db.select_from_table.return_value = []
        with pytest.raises(BugException):
            mod.mod._update_setting_in_table_settings({"a": 1}, "bogus", mod.check)

    def test_update_existing(self, mod):
        mod.db.select_from_table.return_value = [('{"a": 1}',)]
        mod.db.update_in_table.return_value = 0
        code, values = mod.mod._update_setting_in_table_settings(
            {"b": 2}, "settings_system", mod.check)
        assert code == err.ERROR_NO_ERROR.c
        assert values == {"a": 1, "b": 2}

    def test_update_negative_rows_raises(self, mod):
        mod.db.select_from_table.return_value = [({"a": 1},)]
        mod.db.update_in_table.return_value = -1
        with pytest.raises(BugException):
            mod.mod._update_setting_in_table_settings({"b": 2}, "settings_system", mod.check)

    def test_more_than_one_row_raises(self, mod):
        mod.db.select_from_table.return_value = [({},), ({},)]
        with pytest.raises(AggravatedException):
            mod.mod._update_setting_in_table_settings({"a": 1}, "settings_system", mod.check)


class TestUpdateWrappers:
    def test_update_system_settings(self, mod):
        mod.db.select_from_table.return_value = []
        mod.db.insert_in_table.return_value = 1
        code, _ = mod.mod.update_system_settings({"a": 1})
        assert code == err.ERROR_NO_ERROR.c

    def test_update_domain_default_settings(self, mod):
        mod.db.select_from_table.return_value = []
        mod.db.insert_in_table.return_value = 1
        code, _ = mod.mod.update_domain_default_settings({"a": 1})
        assert code == err.ERROR_NO_ERROR.c


class TestUpdateThemeSettings:
    def test_insert_first_time(self, mod):
        mod.db.select_from_table.return_value = []
        mod.db.insert_in_table.return_value = 1
        code, values = mod.mod.update_theme_settings({"primary": "#123456"})
        assert code == err.ERROR_NO_ERROR.c
        assert values == {"primary": "#123456"}
        vt = mod.db.insert_in_table.call_args.kwargs["values_tuple"][0]
        assert vt[3] == {"primary": "#123456"}

    def test_update_existing_str(self, mod):
        mod.db.select_from_table.return_value = [('{"primary": "#000"}',)]
        mod.db.update_in_table.return_value = 1
        code, values = mod.mod.update_theme_settings({"accent": "#abc"})
        assert code == err.ERROR_NO_ERROR.c
        assert values == {"primary": "#000", "accent": "#abc"}

    def test_update_existing_dict(self, mod):
        mod.db.select_from_table.return_value = [({"primary": "#000"},)]
        mod.db.update_in_table.return_value = 1
        code, values = mod.mod.update_theme_settings({"accent": "#abc"})
        assert values == {"primary": "#000", "accent": "#abc"}

    def test_more_than_one_row_raises(self, mod):
        mod.db.select_from_table.return_value = [({},), ({},)]
        with pytest.raises(AggravatedException):
            mod.mod.update_theme_settings({"a": 1})

    def test_rows_not_1_raises_insert(self, mod):
        mod.db.select_from_table.return_value = []
        mod.db.insert_in_table.return_value = 0
        with pytest.raises(BugException):
            mod.mod.update_theme_settings({"a": 1})


class TestCreateDomainSettings:
    def test_create_domain(self, mod):
        mod.db.select_from_table.side_effect = [[], [('{"def": 1}',)]]
        mod.db.insert_in_table.return_value = 1
        code, out = mod.mod.create_domain_settings({
            "domain_name": "a.org",
            "domain_description": "d",
            "domain_info": {"k": "v"},
            "settings": {"SOGO_D_AUTH_TYPE": "saml2"},
        })
        assert code == err.ERROR_NO_ERROR.c
        assert out["domain_name"] == "a.org"
        assert out["hash"]
        assert out["settings"]["SOGO_D_AUTH_TYPE"] == "saml2"

    def test_create_domain_name_taken(self, mod):
        mod.db.select_from_table.return_value = [("a.org",)]
        with pytest.raises(RequestException) as ex:
            mod.mod.create_domain_settings({"domain_name": "a.org"})
        assert ex.value.error.c == "S000301"

    def test_create_domain_retry_on_bug(self, mod):
        mod.db.select_from_table.side_effect = [[], [('{"def": 1}',)]]
        mod.db.insert_in_table.side_effect = [BugException("dup", err.ERROR_UNKOWN), 1]
        code, out = mod.mod.create_domain_settings({"domain_name": "a.org"})
        assert code == err.ERROR_NO_ERROR.c
        assert mod.db.insert_in_table.call_count == 2

    def test_create_domain_rows_not_1(self, mod):
        mod.db.select_from_table.side_effect = [[], [('{"def": 1}',)]]
        mod.db.insert_in_table.return_value = 0
        with pytest.raises(BugException):
            mod.mod.create_domain_settings({"domain_name": "a.org"})


class TestUpdateOneDomainSettings:
    def test_update_domain(self, mod):
        mod.db.select_from_table.side_effect = [
            [(1, "h", "a.org", "desc", "info", '{"SOGO_D_AUTH_TYPE": "plain"}', "{}")],
            [('{"def": 1}',)],
        ]
        mod.db.update_in_table.return_value = 1
        code, out = mod.mod.update_one_domain_settings("a.org", {"settings": {"x": 1}})
        assert code == err.ERROR_NO_ERROR.c
        assert out["domain_name"] == "a.org"
        assert mod.db.update_in_table.call_args.kwargs["condition"].param_value == "a.org"

    def test_update_domain_not_found(self, mod):
        mod.db.select_from_table.return_value = []
        with pytest.raises(RequestException) as ex:
            mod.mod.update_one_domain_settings("ghost.org", {"settings": {}})
        assert ex.value.error.c == "S000302"

    def test_update_domain_rows_not_1(self, mod):
        mod.db.select_from_table.side_effect = [
            [(1, "h", "a.org", "desc", "info", '{"x": 1}', "{}")],
            [('{"def": 1}',)],
        ]
        mod.db.update_in_table.return_value = 2
        with pytest.raises(BugException):
            mod.mod.update_one_domain_settings("a.org", {"settings": {}})


class TestDeleteDomainSetting:
    def test_delete_domain(self, mod):
        mod.db.select_from_table.return_value = [
            (1, "h", "a.org", "desc", "info", '{"x": 1}', "{}"),
        ]
        mod.db.delete_row_in_table.return_value = 1
        assert mod.mod.delete_one_domain_setting("a.org") == 1

    def test_delete_domain_not_found(self, mod):
        mod.db.select_from_table.return_value = []
        with pytest.raises(RequestException) as ex:
            mod.mod.delete_one_domain_setting("ghost.org")
        assert ex.value.error.c == "S000302"


class TestCoverageClosure:
    def test_raw_dict_value_passthrough(self, mod):
        mod.db.select_from_table.return_value = [({"a": 1},)]
        ret = mod.mod._get_setting_from_table_settings(("settings_system",))
        assert ret == ({"a": 1},)

    def test_get_one_domain_setting_with_columns(self, mod):
        col = mod.db  # placeholder
        from app.config.db.tables import COL_DOMAIN_NAME, COL_DOMAIN_SETTINGS
        mod.db.select_from_table.return_value = [("a.org", '{"x": 1}')]
        out = mod.mod.get_one_domain_setting(
            "a.org", columns=(COL_DOMAIN_NAME, COL_DOMAIN_SETTINGS))
        assert out == {"domain_name": "a.org", "settings": '{"x": 1}'}

    def test_get_one_domain_setting_dict_settings_warns(self, mod):
        mod.db.select_from_table.return_value = [
            (1, "h", "a.org", "d", "info", {"SOGO_D_AUTH_TYPE": "plain"}, "{}"),
        ]
        with mock.patch("app.module.admin.ModuleAdminConfig.logger") as lg:
            out = mod.mod.get_one_domain_setting("a.org")
        assert out["settings"] == {"SOGO_D_AUTH_TYPE": "plain"}
        assert lg.warning.call_count >= 1

    def test_insert_rows_not_1_raises(self, mod):
        mod.db.select_from_table.return_value = []
        mod.db.insert_in_table.return_value = 0
        with pytest.raises(BugException):
            mod.mod._update_setting_in_table_settings({"a": 1}, "settings_system", mod.check)

    def test_update_existing_bad_json_string(self, mod):
        mod.db.select_from_table.return_value = [("@#@",)]
        mod.db.update_in_table.return_value = 1
        code, values = mod.mod._update_setting_in_table_settings(
            {"b": 2}, "settings_system", mod.check)
        assert code == err.ERROR_NO_ERROR.c
        assert values == {"b": 2}
