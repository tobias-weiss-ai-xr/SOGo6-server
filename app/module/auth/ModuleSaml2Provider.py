"""SAML2 provider management module.

CRUD operations for SAML2 IdP trust relationships stored in the
``sogo6_saml2_providers`` table.  Each record represents one IdP that
SOGo can trust for SAML2 SSO.  When a ``metadata_url`` is set the
provider configuration can be auto-refreshed from the IdP's metadata
XML.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.config.db import tables as tbl
from app.utils.db.Condition import EqualCondition, TrueCondition
from app.utils.exceptions import RequestException
from app.utils import errors as err
from app.utils.logger.logger import logger_api
from app.utils.module.importManager import import_and_instantiate_manager

if TYPE_CHECKING:
    from app.config.settings.ProcessSetting import ProcessSetting
    from app.manager.db.ClientSQL import ClientSQL


class ModuleSaml2Provider:
    """Manage SAML2 IdP provider records in the database."""

    def __init__(self, process: ProcessSetting) -> None:
        self._process = process
        self._db: ClientSQL | None = None

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _get_db(self) -> ClientSQL:
        """Lazily instantiate and connect the DB client."""
        if self._db is None:
            db_type = f"Client{self._process.SOGO_P_DB_TYPE}"
            self._db = import_and_instantiate_manager(
                module_path="app.manager.db",
                module_and_class_name=db_type,
                module_args=self._process.get_db_settings(),
            )
            self._db.connect()
        return self._db

    @staticmethod
    def _row_to_dict(row: tuple[Any, ...], columns: tuple[str, ...]) -> dict[str, Any]:
        """Convert a DB row tuple to a dict using column names."""
        return dict(zip(columns, row))

    def _columns(self) -> tuple[str, ...]:
        return (
            tbl.COL_SAML2_ID.name,
            tbl.COL_SAML2_NAME.name,
            tbl.COL_SAML2_ENTITY_ID.name,
            tbl.COL_SAML2_SSO_URL.name,
            tbl.COL_SAML2_SSO_BINDING.name,
            tbl.COL_SAML2_SLS_URL.name,
            tbl.COL_SAML2_SLS_BINDING.name,
            tbl.COL_SAML2_CERTIFICATE.name,
            tbl.COL_SAML2_FINGERPRINT.name,
            tbl.COL_SAML2_METADATA_URL.name,
            tbl.COL_SAML2_METADATA_XML.name,
            tbl.COL_SAML2_NAMEID_FORMAT.name,
            tbl.COL_SAML2_ATTRIBUTE_MAP.name,
            tbl.COL_SAML2_ACS_URL.name,
            tbl.COL_SAML2_IS_ACTIVE.name,
            tbl.COL_SAML2_CREATED_AT.name,
            tbl.COL_SAML2_UPDATED_AT.name,
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list_providers(self, active_only: bool = False) -> list[dict[str, Any]]:
        """Return all SAML2 providers."""
        db = self._get_db()
        if active_only:
            condition = EqualCondition(tbl.COL_SAML2_IS_ACTIVE.name, True)
        else:
            condition = TrueCondition()
        rows = list(db.select_from_table(
            tbl.TABLE_SAML2_PROVIDERS.name,
            self._columns(),
            condition=condition,
            sort_by=tbl.COL_SAML2_NAME.name,
        ))
        return [self._row_to_dict(r, self._columns()) for r in rows]

    def get_provider(self, provider_id: str) -> dict[str, Any] | None:
        """Return a single provider by ID, or None."""
        db = self._get_db()
        condition = EqualCondition(tbl.COL_SAML2_ID.name, provider_id)
        rows = list(db.select_from_table(
            tbl.TABLE_SAML2_PROVIDERS.name,
            self._columns(),
            condition=condition,
        ))
        if not rows:
            return None
        return self._row_to_dict(rows[0], self._columns())

    def get_provider_by_entity_id(self, entity_id: str) -> dict[str, Any] | None:
        """Return a single provider by IdP entity ID, or None."""
        db = self._get_db()
        condition = EqualCondition(tbl.COL_SAML2_ENTITY_ID.name, entity_id)
        rows = list(db.select_from_table(
            tbl.TABLE_SAML2_PROVIDERS.name,
            self._columns(),
            condition=condition,
        ))
        if not rows:
            return None
        return self._row_to_dict(rows[0], self._columns())

    def create_provider(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new SAML2 provider."""
        db = self._get_db()
        now = datetime.now(timezone.utc).isoformat()

        provider_id = data.get("id") or data.get("entity_id", "")
        if not provider_id:
            raise RequestException("SAML2 provider requires id or entity_id", err.ERROR_SAML_NOT_CONFIGURED)

        # Check for duplicate
        if self.get_provider(provider_id):
            raise RequestException(f"SAML2 provider '{provider_id}' already exists", err.ERROR_SAML_NOT_CONFIGURED)

        columns = (
            tbl.COL_SAML2_ID.name,
            tbl.COL_SAML2_NAME.name,
            tbl.COL_SAML2_ENTITY_ID.name,
            tbl.COL_SAML2_SSO_URL.name,
            tbl.COL_SAML2_SSO_BINDING.name,
            tbl.COL_SAML2_SLS_URL.name,
            tbl.COL_SAML2_SLS_BINDING.name,
            tbl.COL_SAML2_CERTIFICATE.name,
            tbl.COL_SAML2_FINGERPRINT.name,
            tbl.COL_SAML2_METADATA_URL.name,
            tbl.COL_SAML2_METADATA_XML.name,
            tbl.COL_SAML2_NAMEID_FORMAT.name,
            tbl.COL_SAML2_ATTRIBUTE_MAP.name,
            tbl.COL_SAML2_ACS_URL.name,
            tbl.COL_SAML2_IS_ACTIVE.name,
            tbl.COL_SAML2_CREATED_AT.name,
            tbl.COL_SAML2_UPDATED_AT.name,
        )
        values = [[
            provider_id,
            data.get("name", ""),
            data.get("entity_id", ""),
            data.get("sso_url", ""),
            data.get("sso_binding", "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"),
            data.get("sls_url", ""),
            data.get("sls_binding", ""),
            data.get("certificate", ""),
            data.get("fingerprint", ""),
            data.get("metadata_url", ""),
            data.get("metadata_xml", ""),
            data.get("nameid_format", "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"),
            data.get("attribute_map", {}),
            data.get("acs_url", ""),
            data.get("is_active", True),
            now,
            now,
        ]]

        db.insert_in_table(tbl.TABLE_SAML2_PROVIDERS.name, columns, values)
        logger_api.info("Created SAML2 provider: %s", provider_id)
        return self.get_provider(provider_id) or {}

    def update_provider(self, provider_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing SAML2 provider."""
        existing = self.get_provider(provider_id)
        if not existing:
            raise RequestException(f"SAML2 provider '{provider_id}' not found", err.ERROR_SAML_PROVIDER_NOT_FOUND)

        db = self._get_db()
        now = datetime.now(timezone.utc).isoformat()

        # Build update columns/values from the data dict
        updatable = {
            "name": tbl.COL_SAML2_NAME.name,
            "entity_id": tbl.COL_SAML2_ENTITY_ID.name,
            "sso_url": tbl.COL_SAML2_SSO_URL.name,
            "sso_binding": tbl.COL_SAML2_SSO_BINDING.name,
            "sls_url": tbl.COL_SAML2_SLS_URL.name,
            "sls_binding": tbl.COL_SAML2_SLS_BINDING.name,
            "certificate": tbl.COL_SAML2_CERTIFICATE.name,
            "fingerprint": tbl.COL_SAML2_FINGERPRINT.name,
            "metadata_url": tbl.COL_SAML2_METADATA_URL.name,
            "metadata_xml": tbl.COL_SAML2_METADATA_XML.name,
            "nameid_format": tbl.COL_SAML2_NAMEID_FORMAT.name,
            "attribute_map": tbl.COL_SAML2_ATTRIBUTE_MAP.name,
            "acs_url": tbl.COL_SAML2_ACS_URL.name,
            "is_active": tbl.COL_SAML2_IS_ACTIVE.name,
        }

        columns: list[str] = []
        values: list[Any] = []
        for key, col_name in updatable.items():
            if key in data:
                columns.append(col_name)
                values.append(data[key])
        columns.append(tbl.COL_SAML2_UPDATED_AT.name)
        values.append(now)

        condition = EqualCondition(tbl.COL_SAML2_ID.name, provider_id)
        db.update_in_table(tbl.TABLE_SAML2_PROVIDERS.name, tuple(columns), [values], condition)
        logger_api.info("Updated SAML2 provider: %s", provider_id)
        return self.get_provider(provider_id) or {}

    def delete_provider(self, provider_id: str) -> bool:
        """Delete a SAML2 provider."""
        existing = self.get_provider(provider_id)
        if not existing:
            raise RequestException(f"SAML2 provider '{provider_id}' not found", err.ERROR_SAML_PROVIDER_NOT_FOUND)

        db = self._get_db()
        condition = EqualCondition(tbl.COL_SAML2_ID.name, provider_id)
        db.delete_row_in_table(tbl.TABLE_SAML2_PROVIDERS.name, condition)
        logger_api.info("Deleted SAML2 provider: %s", provider_id)
        return True

    def refresh_provider_metadata(self, provider_id: str, metadata_xml: str,
                                   sso_url: str = "", certificate: str = "",
                                   fingerprint: str = "") -> dict[str, Any]:
        """Refresh a provider's metadata fields after fetching new metadata."""
        update_data: dict[str, Any] = {"metadata_xml": metadata_xml}
        if sso_url:
            update_data["sso_url"] = sso_url
        if certificate:
            update_data["certificate"] = certificate
        if fingerprint:
            update_data["fingerprint"] = fingerprint
        return self.update_provider(provider_id, update_data)
