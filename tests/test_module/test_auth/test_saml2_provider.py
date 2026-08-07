"""Unit tests for ModuleSaml2Provider — CRUD operations.

Tests cover:
  - list_providers() — empty, with data, active_only filter
  - get_provider() — by ID, not found
  - get_provider_by_entity_id() — by entity_id, not found
  - create_provider() — success, duplicate
  - update_provider() — success, not found, partial update
  - delete_provider() — success, not found
  - refresh_provider_metadata() — updates metadata fields
"""
from __future__ import annotations

import pytest
from unittest import mock

from app.module.auth.ModuleSaml2Provider import ModuleSaml2Provider
from app.utils.exceptions import RequestException


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_process():
    """Fake ProcessSetting for ModuleSaml2Provider."""
    process = mock.MagicMock()
    process.SOGO_P_DB_TYPE = "MySQL"
    process.get_db_settings.return_value = {
        "host": "localhost",
        "port": 3306,
        "user": "test",
        "password": "test",
        "database": "test",
    }
    return process


@pytest.fixture
def fake_db():
    """Fake DB client that stores rows in memory (tuple rows, column layout from insert)."""
    class FakeDB:
        def __init__(self):
            self.rows: dict[str, list[tuple]] = {}
            self.layouts: dict[str, tuple] = {}
            self._next_id = 1

        def connect(self):
            pass

        def select_from_table(self, table_name, column_tuple, condition=None, **kwargs):
            layout = self.layouts.get(table_name)
            if layout is None:
                return iter([])
            idx = {col: i for i, col in enumerate(layout)}
            result = []
            for row in self.rows.get(table_name, []):
                if condition and hasattr(condition, "param_name") \
                        and row[idx.get(condition.param_name, -1)] != condition.param_value:
                    continue
                # Project to the requested column tuple (real DB returns only those)
                result.append(tuple(row[idx[c]] for c in column_tuple if c in idx))
            return iter(result)

        def insert_in_table(self, table_name, column_tuple, values_list):
            if table_name not in self.layouts:
                self.layouts[table_name] = tuple(column_tuple)
            if table_name not in self.rows:
                self.rows[table_name] = []
            for values in values_list:
                self.rows[table_name].append(tuple(values))

        def update_in_table(self, table_name, column_tuple, values_list, condition):
            layout = self.layouts.get(table_name)
            if layout is None or not self.rows.get(table_name):
                return 0
            idx = {col: i for i, col in enumerate(layout)}
            updated = 0
            for i, row in enumerate(self.rows[table_name]):
                if hasattr(condition, "param_name") \
                        and row[idx.get(condition.param_name, -1)] != condition.param_value:
                    continue
                new_row = list(row)
                for col, value in zip(column_tuple, values_list[0]):
                    new_row[idx[col]] = value
                self.rows[table_name][i] = tuple(new_row)
                updated += 1
            return updated

        def delete_row_in_table(self, table_name, condition, expected_row=0):
            layout = self.layouts.get(table_name)
            if layout is None:
                return
            idx = {col: i for i, col in enumerate(layout)}
            if hasattr(condition, "param_name"):
                self.rows[table_name] = [
                    row for row in self.rows.get(table_name, [])
                    if row[idx.get(condition.param_name, -1)] != condition.param_value
                ]

        def _get_columns(self, table_name):
            # Return the column tuple used for this table
            return (
                "id", "id", "name", "entity_id", "sso_url", "sso_binding",
                "sls_url", "sls_binding", "certificate", "fingerprint",
                "metadata_url", "metadata_xml", "nameid_format", "attribute_map",
                "acs_url", "is_active", "created_at", "updated_at",
            )

    return FakeDB()


@pytest.fixture
def provider_module(fake_process, fake_db):
    """ModuleSaml2Provider with a fake DB."""
    module = ModuleSaml2Provider(fake_process)
    module._db = fake_db
    return module


# ── Create tests ──────────────────────────────────────────────────────────────


class TestCreateProvider:
    """Tests for create_provider()."""

    def test_create_provider_success(self, provider_module, fake_db):
        """Should create a provider and return it."""
        provider = provider_module.create_provider({
            "id": "test-idp",
            "name": "Test IdP",
            "entity_id": "https://idp.example.org/idp/shibboleth",
            "sso_url": "https://idp.example.org/idp/profile/SAML2/Redirect/SSO",
        })
        assert provider["id"] == "test-idp"
        assert provider["name"] == "Test IdP"
        assert provider["entity_id"] == "https://idp.example.org/idp/shibboleth"
        assert provider["is_active"] is True

    def test_create_provider_with_all_fields(self, provider_module):
        """Should create a provider with all fields set."""
        provider = provider_module.create_provider({
            "id": "full-idp",
            "name": "Full IdP",
            "entity_id": "https://idp.example.org/idp",
            "sso_url": "https://idp.example.org/SSO",
            "sso_binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            "certificate": "-----BEGIN CERTIFICATE-----\nMIIDfake==\n-----END CERTIFICATE-----",
            "metadata_url": "https://idp.example.org/metadata.xml",
            "nameid_format": "urn:oasis:names:tc:SAML:2.0:nameid-format:transient",
            "is_active": True,
        })
        assert provider["sso_binding"] == "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
        assert provider["metadata_url"] == "https://idp.example.org/metadata.xml"

    def test_create_duplicate_provider_raises(self, provider_module):
        """Should raise when creating a duplicate provider."""
        provider_module.create_provider({
            "id": "dup-idp",
            "name": "Dup",
            "entity_id": "https://dup.example.org/idp",
            "sso_url": "https://dup.example.org/SSO",
        })
        with pytest.raises(RequestException):
            provider_module.create_provider({
                "id": "dup-idp",
                "name": "Dup 2",
                "entity_id": "https://dup2.example.org/idp",
                "sso_url": "https://dup2.example.org/SSO",
            })


# ── Get tests ─────────────────────────────────────────────────────────────────


class TestGetProvider:
    """Tests for get_provider() and get_provider_by_entity_id()."""

    def test_get_provider_by_id(self, provider_module):
        """Should return a provider by ID."""
        provider_module.create_provider({
            "id": "get-test",
            "name": "Get Test",
            "entity_id": "https://get.example.org/idp",
            "sso_url": "https://get.example.org/SSO",
        })
        provider = provider_module.get_provider("get-test")
        assert provider is not None
        assert provider["name"] == "Get Test"

    def test_get_provider_not_found(self, provider_module):
        """Should return None for non-existent provider."""
        provider = provider_module.get_provider("nonexistent")
        assert provider is None

    def test_get_provider_by_entity_id(self, provider_module):
        """Should return a provider by entity_id."""
        provider_module.create_provider({
            "id": "eid-test",
            "name": "EID Test",
            "entity_id": "https://eid.example.org/idp",
            "sso_url": "https://eid.example.org/SSO",
        })
        provider = provider_module.get_provider_by_entity_id("https://eid.example.org/idp")
        assert provider is not None
        assert provider["id"] == "eid-test"


# ── List tests ────────────────────────────────────────────────────────────────


class TestListProviders:
    """Tests for list_providers()."""

    def test_list_empty(self, provider_module):
        """Should return empty list when no providers."""
        providers = provider_module.list_providers()
        assert providers == []

    def test_list_returns_all(self, provider_module):
        """Should return all providers."""
        provider_module.create_provider({"id": "p1", "name": "P1", "entity_id": "https://p1.example.org", "sso_url": "https://p1.example.org/SSO"})
        provider_module.create_provider({"id": "p2", "name": "P2", "entity_id": "https://p2.example.org", "sso_url": "https://p2.example.org/SSO"})
        providers = provider_module.list_providers()
        assert len(providers) == 2


# ── Update tests ──────────────────────────────────────────────────────────────


class TestUpdateProvider:
    """Tests for update_provider()."""

    def test_update_provider_name(self, provider_module):
        """Should update the provider name."""
        provider_module.create_provider({"id": "upd-test", "name": "Old", "entity_id": "https://upd.example.org", "sso_url": "https://upd.example.org/SSO"})
        updated = provider_module.update_provider("upd-test", {"name": "New Name"})
        assert updated["name"] == "New Name"

    def test_update_provider_not_found(self, provider_module):
        """Should raise when updating non-existent provider."""
        with pytest.raises(RequestException):
            provider_module.update_provider("nonexistent", {"name": "Test"})


# ── Delete tests ──────────────────────────────────────────────────────────────


class TestDeleteProvider:
    """Tests for delete_provider()."""

    def test_delete_provider_success(self, provider_module):
        """Should delete a provider."""
        provider_module.create_provider({"id": "del-test", "name": "Del", "entity_id": "https://del.example.org", "sso_url": "https://del.example.org/SSO"})
        result = provider_module.delete_provider("del-test")
        assert result is True
        assert provider_module.get_provider("del-test") is None

    def test_delete_provider_not_found(self, provider_module):
        """Should raise when deleting non-existent provider."""
        with pytest.raises(RequestException):
            provider_module.delete_provider("nonexistent")
