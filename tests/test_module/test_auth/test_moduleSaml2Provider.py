"""
Unit tests for ModuleSaml2Provider.list_providers.

Regression: GET /api/admin/v1/auth/saml2/providers returned 500 with
"Unknown Condition type" — ``list_providers(active_only=False)`` passed
``condition=None`` into select_from_table, and ClientMySQL.condition_to_query
raises on anything that is not a Condition (convention elsewhere is
``TrueCondition()`` for "select all").
"""
from types import SimpleNamespace
from unittest import mock

import pytest

from app.module.auth.ModuleSaml2Provider import ModuleSaml2Provider
from app.utils.db.Condition import EqualCondition, TrueCondition


class FakeSql:
    def __init__(self):
        self.last_condition = None
        self.last_sort = None

    def connect(self):
        return None

    def select_from_table(self, table_name, column_tuple, condition=None, **kwargs):
        self.last_condition = condition
        self.last_sort = kwargs.get("sort_by")
        return []


def _make_module(fake_db) -> ModuleSaml2Provider:
    process = SimpleNamespace(SOGO_P_DB_TYPE="MySQL")
    module = ModuleSaml2Provider(process)
    module._db = fake_db  # bypass lazy _get_db (constructor DB build)
    return module


def test_list_providers_default_passes_true_condition():
    fake = FakeSql()
    module = _make_module(fake)
    module.list_providers()  # active_only defaults to False
    assert isinstance(fake.last_condition, TrueCondition)


def test_list_providers_active_only_passes_equal_condition():
    fake = FakeSql()
    module = _make_module(fake)
    module.list_providers(active_only=True)
    assert isinstance(fake.last_condition, EqualCondition)


def test_list_providers_never_passes_none_condition():
    fake = FakeSql()
    module = _make_module(fake)
    module.list_providers()
    assert fake.last_condition is not None


def test_list_providers_sorts_by_name():
    fake = FakeSql()
    module = _make_module(fake)
    module.list_providers()
    assert fake.last_sort == "name"
