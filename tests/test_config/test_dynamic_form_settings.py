"""Unit tests for DynamicFormSettings (schema → dynamic form conversion).

Tests the conversion of marshmallow schemas to JSON-ready dictionaries for
dynamic UI form generation. Covers field type detection, constraint extraction,
dependency formatting, and the two main functions:
- create_dynamic_dict_for_settings
- create_values_dict_for_settings
"""
import pytest
from marshmallow import fields, validate

from app.config.settings.DynamicFormSettings import (
    DATA_TYPE,
    VALIDATE_TYPE,
    fetch_inner_data_type,
    validate_one_of_to_constraint,
    validate_range_to_constraint,
    validate_url_to_constraint,
    validate_contains_only_to_constraint,
    create_dynamic_dict_for_settings,
    create_values_dict_for_settings,
)
from app.config.settings.SogoSchema import SogoSchema


class FakeSchema(SogoSchema):
    """Minimal fake schema for testing."""
    subparent = "TEST_SETTINGS"
    dependencies = {}
    is_secret = set()
    is_required = set()
    is_duplicable = False
    
    test_string = fields.String()
    test_int = fields.Integer()
    test_bool = fields.Boolean()
    test_email = fields.Email()
    test_url = fields.Url()
    test_list = fields.List(fields.String())
    test_dict = fields.Dict()
    test_float = fields.Float()


class TestDataTypeMapping:
    def test_data_type_map(self):
        assert DATA_TYPE[fields.Boolean] == "bool"
        assert DATA_TYPE[fields.Integer] == "number"
        assert DATA_TYPE[fields.List] == "list"
        assert DATA_TYPE[fields.Email] == "email"
        assert DATA_TYPE[fields.String] == "str"
        assert DATA_TYPE[fields.Url] == "url"
        assert DATA_TYPE[fields.Dict] == "dict"
        assert DATA_TYPE[fields.Float] == "float"


class TestFetchInnerDataType:
    def test_list_of_string(self):
        field = fields.List(fields.String())
        assert fetch_inner_data_type(field) == "list[str]"

    def test_list_of_integer(self):
        field = fields.List(fields.Integer())
        assert fetch_inner_data_type(field) == "list[number]"

    def test_list_of_boolean(self):
        field = fields.List(fields.Boolean())
        assert fetch_inner_data_type(field) == "list[bool]"

    def test_nested_list(self):
        field = fields.List(fields.List(fields.String()))
        # Should recurse
        assert "list" in fetch_inner_data_type(field)


class TestValidateOneOfToConstraint:
    def test_choices(self):
        validator = validate.OneOf(["a", "b", "c"])
        result = validate_one_of_to_constraint(validator)
        assert result == {"choices": ["a", "b", "c"]}


class TestValidateRangeToConstraint:
    def test_min_max_inclusive(self):
        validator = validate.Range(min=0, max=100)
        result = validate_range_to_constraint(validator)
        assert result == {"min_inclusive": 0, "max_inclusive": 100}

    def test_min_exclusive(self):
        validator = validate.Range(min=0, min_inclusive=False)
        result = validate_range_to_constraint(validator)
        assert result == {"min": 0}

    def test_max_exclusive(self):
        validator = validate.Range(max=100, max_inclusive=False)
        result = validate_range_to_constraint(validator)
        assert result == {"max": 100}

    def test_only_min(self):
        validator = validate.Range(min=5)
        result = validate_range_to_constraint(validator)
        assert result == {"min_inclusive": 5}

    def test_only_max(self):
        validator = validate.Range(max=50)
        result = validate_range_to_constraint(validator)
        assert result == {"max_inclusive": 50}


class TestValidateUrlToConstraint:
    def test_single_scheme(self):
        validator = validate.URL(schemes=["http"])
        result = validate_url_to_constraint(validator)
        assert result == {"prefix": "http://"}

    def test_multiple_schemes(self):
        validator = validate.URL(schemes=["http", "https"])
        result = validate_url_to_constraint(validator)
        # Multiple schemes return prefixes list
        assert "prefixes" in result
        assert "http://" in result["prefixes"]


class TestValidateContainsOnlyToConstraint:
    def test_contains_only(self):
        validator = validate.ContainsOnly(["x", "y"])
        result = validate_contains_only_to_constraint(validator)
        assert result == {"choices": ["x", "y"], "len_min": 1, "len_max": 2}


class TestCreateDynamicDictForSettings:
    def test_basic_structure(self):
        schema = FakeSchema()
        result = create_dynamic_dict_for_settings(schema)
        assert "TEST_SETTINGS" in result
        assert "is_duplicable" in result
        assert isinstance(result["TEST_SETTINGS"], list)
        assert result["is_duplicable"] is False

    def test_field_names_preserved(self):
        schema = FakeSchema()
        result = create_dynamic_dict_for_settings(schema)
        field_names = {f["name"] for f in result["TEST_SETTINGS"]}
        assert "test_string" in field_names
        assert "test_int" in field_names
        assert "test_bool" in field_names
        assert "test_email" in field_names
        assert "test_url" in field_names
        assert "test_list" in field_names
        assert "test_dict" in field_names
        assert "test_float" in field_names

    def test_data_types_mapped(self):
        schema = FakeSchema()
        result = create_dynamic_dict_for_settings(schema)
        fields_dict = {f["name"]: f for f in result["TEST_SETTINGS"]}
        assert fields_dict["test_string"]["data_type"] == "str"
        assert fields_dict["test_int"]["data_type"] == "number"
        assert fields_dict["test_bool"]["data_type"] == "bool"
        assert fields_dict["test_email"]["data_type"] == "email"
        assert fields_dict["test_url"]["data_type"] == "url"
        assert fields_dict["test_list"]["data_type"] == "list[str]"
        assert fields_dict["test_dict"]["data_type"] == "dict"
        assert fields_dict["test_float"]["data_type"] == "float"

    def test_default_values(self):
        class SchemaWithDefaults(SogoSchema):
            subparent = "DEFAULTS_TEST"
            dependencies = {}
            is_secret = set()
            is_required = set()
            is_duplicable = False
            str_field = fields.String(dump_default="default_str")
            int_field = fields.Integer(dump_default=42)
            bool_field = fields.Boolean(dump_default=True)

        schema = SchemaWithDefaults()
        result = create_dynamic_dict_for_settings(schema)
        fields_dict = {f["name"]: f for f in result["DEFAULTS_TEST"]}
        assert fields_dict["str_field"]["default"] == "default_str"
        assert fields_dict["int_field"]["default"] == 42
        assert fields_dict["bool_field"]["default"] is True

    def test_required_field(self):
        class SchemaRequired(SogoSchema):
            subparent = "REQUIRED_TEST"
            dependencies = {}
            is_secret = set()
            is_required = {"req_field"}
            is_duplicable = False
            req_field = fields.String()

        schema = SchemaRequired()
        result = create_dynamic_dict_for_settings(schema)
        fields_dict = {f["name"]: f for f in result["REQUIRED_TEST"]}
        assert fields_dict["req_field"]["required"] is True

    def test_constraints_from_validator(self):
        class SchemaWithConstraints(SogoSchema):
            subparent = "CONSTRAINTS_TEST"
            dependencies = {}
            is_secret = set()
            is_required = set()
            is_duplicable = False
            choice_field = fields.String(validate=validate.OneOf(["a", "b"]))
            range_field = fields.Integer(validate=validate.Range(min=0, max=10))

        schema = SchemaWithConstraints()
        result = create_dynamic_dict_for_settings(schema)
        fields_dict = {f["name"]: f for f in result["CONSTRAINTS_TEST"]}
        assert fields_dict["choice_field"]["constraints"] == {"choices": ["a", "b"]}
        assert fields_dict["range_field"]["constraints"] == {"min_inclusive": 0, "max_inclusive": 10}

    def test_url_constraints(self):
        class SchemaUrl(SogoSchema):
            subparent = "URL_TEST"
            dependencies = {}
            is_secret = set()
            is_required = set()
            is_duplicable = False
            url_field = fields.Url()

        schema = SchemaUrl()
        result = create_dynamic_dict_for_settings(schema)
        fields_dict = {f["name"]: f for f in result["URL_TEST"]}
        # URL validator adds prefix constraint
        assert fields_dict["url_field"]["constraints"] is not None

    def test_dependency_format(self):
        class SchemaDep(SogoSchema):
            subparent = "DEP_TEST"
            dependencies = {"cond_field": ("parent_field", "value")}
            is_secret = set()
            is_required = set()
            is_duplicable = False
            cond_field = fields.String()

        schema = SchemaDep()
        result = create_dynamic_dict_for_settings(schema)
        fields_dict = {f["name"]: f for f in result["DEP_TEST"]}
        assert fields_dict["cond_field"]["depends"] == "parent_field%%%equal%%%value"

    def test_secret_field(self):
        class SchemaSecret(SogoSchema):
            subparent = "SECRET_TEST"
            dependencies = {}
            is_secret = {"secret_field"}
            is_required = set()
            is_duplicable = False
            secret_field = fields.String()

        schema = SchemaSecret()
        result = create_dynamic_dict_for_settings(schema)
        fields_dict = {f["name"]: f for f in result["SECRET_TEST"]}
        assert fields_dict["secret_field"]["data_type"] == "secret"

    def test_duplicable_schema(self):
        class SchemaDup(SogoSchema):
            subparent = "DUP_TEST"
            dependencies = {}
            is_secret = set()
            is_required = set()
            is_duplicable = True
            field = fields.String()

        schema = SchemaDup()
        result = create_dynamic_dict_for_settings(schema)
        assert result["is_duplicable"] is True


class TestCreateValuesDictForSettings:
    def test_basic_values(self):
        class SchemaValues(SogoSchema):
            subparent = "VALUES_TEST"
            dependencies = {}
            is_secret = set()
            is_required = set()
            is_duplicable = False
            str_field = fields.String(dump_default="hello")
            int_field = fields.Integer(dump_default=100)

        schema = SchemaValues()
        result = create_values_dict_for_settings(schema)
        assert result["VALUES_TEST"]["str_field"] == "hello"
        assert result["VALUES_TEST"]["int_field"] == 100

    def test_missing_default(self):
        class SchemaMissing(SogoSchema):
            subparent = "MISSING_TEST"
            dependencies = {}
            is_secret = set()
            is_required = set()
            is_duplicable = False
            field = fields.String()

        schema = SchemaMissing()
        result = create_values_dict_for_settings(schema)
        # Missing defaults become None
        assert result["MISSING_TEST"]["field"] is None

    def test_duplicable_creates_list(self):
        class SchemaDupValues(SogoSchema):
            subparent = "DUP_VAL_TEST"
            dependencies = {}
            is_secret = set()
            is_required = set()
            is_duplicable = True
            field = fields.String(dump_default="x")

        schema = SchemaDupValues()
        result = create_values_dict_for_settings(schema)
        assert isinstance(result["DUP_VAL_TEST"], list)
        assert len(result["DUP_VAL_TEST"]) == 1
        assert result["DUP_VAL_TEST"][0]["field"] == "x"
