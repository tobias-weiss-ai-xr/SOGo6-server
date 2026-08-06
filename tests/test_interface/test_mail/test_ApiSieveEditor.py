"""Structural tests for the Sieve Editor granular filter API endpoints.

These add GET/PUT/DELETE single-filter and validate/preview/push/reorder/
templates endpoints on top of the existing filter management API.

Fixture-free structural tests following the `ApiMailboxDebug` convention.
"""
import pytest


class TestSieveEditorEndpoints:
    """Verify the Sieve Editor endpoint classes exist and expose correct methods."""

    def test_templates_endpoint(self):
        from app.api.v1.mail.ApiMailFilter import ApiMailFilterTemplatesResource
        view = ApiMailFilterTemplatesResource()
        assert hasattr(view, "get")

    def test_validate_endpoint(self):
        from app.api.v1.mail.ApiMailFilter import ApiMailFilterValidateResource
        view = ApiMailFilterValidateResource()
        assert hasattr(view, "post")

    def test_preview_endpoint(self):
        from app.api.v1.mail.ApiMailFilter import ApiMailFilterPreviewResource
        view = ApiMailFilterPreviewResource()
        assert hasattr(view, "post")

    def test_push_endpoint(self):
        from app.api.v1.mail.ApiMailFilter import ApiMailFilterPushResource
        view = ApiMailFilterPushResource()
        assert hasattr(view, "post")

    def test_reorder_endpoint(self):
        from app.api.v1.mail.ApiMailFilter import ApiMailFilterReorderResource
        view = ApiMailFilterReorderResource()
        assert hasattr(view, "patch")

    def test_single_filter_get(self):
        from app.api.v1.mail.ApiMailFilter import ApiMailFilterItemResource
        view = ApiMailFilterItemResource()
        assert hasattr(view, "get")
        assert hasattr(view, "put")
        assert hasattr(view, "delete")


class TestSieveEditorSchemas:
    """Verify the new sieve editor schemas are importable."""

    def test_schemas_importable(self):
        from app.api.v1.mail.schemas.filter import (
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
        assert FilterItemPayloadSchema().example()["name"]
        assert isinstance(FilterReorderPayloadSchema().example(), dict)
        assert isinstance(FilterValidateResponseSchema().example(), dict)

    def test_filter_item_schema_fields(self):
        from app.api.v1.mail.schemas.filter import FilterItemPayloadSchema
        fields = FilterItemPayloadSchema().load(
            {
                "name": "Test",
                "enabled": True,
                "actions": [{"method": "fileinto", "arguments": {"folders": ["INBOX"]}}],
                "rules": {"op": "and", "rules": [{"field": "from", "operator": "contains", "value": "x"}]},
            }
        )
        assert fields["name"] == "Test"
        assert fields["enabled"] is True
        assert fields["actions"][0]["method"] == "fileinto"

    def test_reorder_schema_requires_order(self):
        from app.api.v1.mail.schemas.filter import FilterReorderPayloadSchema
        import marshmallow
        with pytest.raises(marshmallow.ValidationError):
            FilterReorderPayloadSchema().load({"nope": []}, unknown=marshmallow.UNKNOWN_INCLUDE)

    def test_error_constant(self):
        from app.utils import errors as err
        assert err.ERROR_FILTER_NOT_FOUND.m
        assert err.ERROR_FILTER_NOT_FOUND.status_code == 404


class TestSieveEditorModule:
    """Verify ModuleFilter granular methods exist."""

    def test_module_methods_exist(self):
        from app.module.mail.ModuleFilter import ModuleFilter
        for method in ("get_filter", "set_filter", "delete_filter", "reorder_filters", "push_to_sieve"):
            assert hasattr(ModuleFilter, method)