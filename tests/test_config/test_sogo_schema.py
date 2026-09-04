# pylint: disable=invalid-sequence-index
"""Unit tests for SogoSchema (46% -> high)."""
from __future__ import annotations

import os

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest
from marshmallow import ValidationError, fields

from app.config.settings.SogoSchema import SogoSchema, check_data_for_sogo_schemas


def make_dep_schema():
    """Schema where 'secret_mode' is required only when 'mode' == 'advanced'."""

    class DepSchema(SogoSchema):
        subparent = "DEP"
        dependencies = {"secret_mode": ("mode", "advanced")}
        is_required = {"secret_mode"}
        mode = fields.String()
        secret_mode = fields.String()

    return DepSchema


def make_plain_schema():
    class PlainSchema(SogoSchema):
        subparent = "PLAIN"
        name = fields.String()
        count = fields.Integer()

    return PlainSchema


def make_duplicable_schema():
    class DupSchema(SogoSchema):
        subparent = "DUP"
        is_duplicable = True
        is_uid = "key"
        key = fields.String()
        label = fields.String()

    return DupSchema


class TestValidateRequiredWithDependency:
    def test_ok_when_dependency_not_satisfied(self):
        s = make_dep_schema()()
        out = s.load({"mode": "simple"})
        assert out == {"mode": "simple"}

    def test_ok_when_dependency_satisfied_and_field_present(self):
        s = make_dep_schema()()
        out = s.load({"mode": "advanced", "secret_mode": "x"})
        assert out["secret_mode"] == "x"

    def test_error_when_dependency_satisfied_but_field_missing(self):
        s = make_dep_schema()()
        with pytest.raises(ValidationError) as exc:
            s.load({"mode": "advanced"})
        assert "secret_mode" in exc.value.messages

    def test_defaults(self):
        assert make_plain_schema().subparent == "PLAIN"
        assert make_plain_schema().is_duplicable is False
        assert make_duplicable_schema().is_duplicable is True
        assert make_duplicable_schema().is_uid == "key"


class TestCheckDataForSogoSchemas:
    def test_single_non_duplicable(self):
        out = check_data_for_sogo_schemas(
            {"PLAIN": {"name": "x", "count": 3, "extra": "ignored"}},
            lambda: [make_plain_schema()],
        )
        assert out == {"PLAIN": {"name": "x", "count": 3}}
        assert "extra" not in out["PLAIN"]

    def test_missing_subparent_becomes_empty(self):
        out = check_data_for_sogo_schemas(
            {},
            lambda: [make_plain_schema()],
        )
        assert out == {"PLAIN": {}}

    def test_duplicable_blocks(self):
        out = check_data_for_sogo_schemas(
            {"DUP": {"b1": {"key": "k1", "label": "l1", "extra": 1},
                     "b2": {"key": "k2"}}},
            lambda: [make_duplicable_schema()],
        )
        assert out["DUP"]["b1"] == {"key": "k1", "label": "l1"}
        assert out["DUP"]["b2"] == {"key": "k2"}
        assert "extra" not in out["DUP"]["b1"]

    def test_duplicable_empty(self):
        out = check_data_for_sogo_schemas(
            {"DUP": {}}, lambda: [make_duplicable_schema()])
        assert out["DUP"] == {}

    def test_multiple_schemas(self):
        out = check_data_for_sogo_schemas(
            {"PLAIN": {"count": 1}, "DUP": {}},
            lambda: [make_plain_schema(), make_duplicable_schema()],
        )
        assert out["PLAIN"] == {"count": 1}
        assert out["DUP"] == {}

    def test_validation_error_propagates(self):
        s = make_dep_schema()
        with pytest.raises(ValidationError):
            check_data_for_sogo_schemas(
                {"DEP": {"mode": "advanced"}}, lambda: [s])
