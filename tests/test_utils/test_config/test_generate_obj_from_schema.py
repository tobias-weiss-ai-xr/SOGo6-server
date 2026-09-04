# pylint: disable=invalid-sequence-index
"""Unit tests for generateObjFromSchema helpers (46% -> high)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

from marshmallow import Schema, fields

from app.config.settings.SogoSchema import SogoSchema
from app.utils.config.generateObjFromSchema import (
    FIELD_DEFAULT,
    FIELD_TYPING,
    SettingsObj,
    fetch_inner_data_type,
    print_settings_obj_from_schema,
    typing_and_default_value_from_field,
)


class TestSettingsObj:
    def test_empty(self):
        obj = SettingsObj()
        assert not hasattr(obj, "anything")

    def test_scalar(self):
        obj = SettingsObj({"a": 1, "b": "x"})
        assert obj.a == 1
        assert obj.b == "x"

    def test_list_cloned(self):
        lst = [1, 2]
        obj = SettingsObj({"lst": lst})
        lst.append(3)
        assert obj.lst == [1, 2]

    def test_dict_deepcopied(self):
        d = {"k": {"n": 1}}
        obj = SettingsObj({"d": d})
        d["k"]["n"] = 99
        assert obj.d == {"k": {"n": 1}}

    def test_none_becomes_empty(self):
        obj = SettingsObj(None)
        assert not hasattr(obj, "x")


class TestFetchInnerDataType:
    def test_plain_inner(self):
        assert fetch_inner_data_type(fields.List(fields.String())) == "list[str]"

    def test_list_in_list(self):
        assert fetch_inner_data_type(fields.List(fields.List(fields.Integer()))) == "list[list[int]]"

    def test_unknown_inner_falls_back(self):
        from marshmallow import validate
        assert fetch_inner_data_type(fields.List(fields.Raw())) == "list"


class TestTypingAndDefault:
    def test_each_field_type_maps(self):
        cases = [
            (fields.Boolean(), "bool", False),
            (fields.Integer(), "int", 0),
            (fields.List(fields.String()), "list[str]", []),
            (fields.Email(), "str", '""'),
            (fields.String(), "str", '""'),
            (fields.Url(), "str", '""'),
            (fields.Dict(), "dict", {}),
            (fields.Float(), "float", 0.0),
        ]
        for field, ftype, fdefault in cases:
            got_type, got_default = typing_and_default_value_from_field(field)
            assert got_type == ftype, field.__class__.__name__
            assert got_default == fdefault, field.__class__.__name__

    def test_field_default_table_consistent(self):
        assert FIELD_TYPING[fields.Boolean] == "bool"
        assert FIELD_DEFAULT[fields.Integer] == 0
        assert FIELD_DEFAULT[fields.List] == []
        assert FIELD_DEFAULT[fields.Dict] == {}


class TestPrintSettingsObj:
    def test_prints_class(self, capsys):
        class TestSchema(SogoSchema):
            name = fields.String()
            count = fields.Integer()
            flags = fields.List(fields.Boolean())
            enabled = fields.Boolean(dump_default=True)

        print_settings_obj_from_schema(TestSchema())
        out = capsys.readouterr().out
        assert "class TestSchemaObj(SettingsObj):" in out
        assert "name: str = \"\"" in out
        assert "count: int = 0" in out
        assert "flags: list[bool] = []" in out
        assert "enabled: bool = True" in out

    def test_prints_string_default(self, capsys):
        class StrSchema(SogoSchema):
            label = fields.String(dump_default="Hello")

        print_settings_obj_from_schema(StrSchema())
        out = capsys.readouterr().out
        assert 'label: str = "Hello"' in out

    def test_missing_dump_default_uses_field_default(self, capsys):
        class PlainSchema(Schema):
            num = fields.Integer()

        print_settings_obj_from_schema(PlainSchema())
        out = capsys.readouterr().out
        assert "num: int = 0" in out
