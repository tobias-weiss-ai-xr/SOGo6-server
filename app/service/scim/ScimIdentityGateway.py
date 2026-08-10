"""SCIM identity gateway — thin adapter between SCIM 2.0 and the LDAP user source.

Wraps ModuleAdminUser (real OpenLDAP writes) so the SCIM endpoint layer stays
pure protocol. Every create/read/update/delete reaches the configured LDAP
directory; there is no simulated user store anywhere in this path.
"""
from __future__ import annotations

from typing import Any

from app.module.admin.ModuleAdminUser import ModuleAdminUser


class ScimIdentityGateway:
    """Per-request adapter over ModuleAdminUser (LDAP-backed)."""

    def __init__(self, process_settings) -> None:
        self.module = ModuleAdminUser(process_settings)

    # ---- real LDAP operations ------------------------------------------- #

    def list_users(self, query: str = "", page: int = 1, per_page: int = 20) -> tuple[int, list[dict[str, Any]]]:
        """Search + paginate the LDAP directory; returns (total, records)."""
        return self.module.list_users(query=query or None, page=page, per_page=per_page)

    def get_user(self, uid: str) -> dict[str, Any]:
        """One LDAP record by uid. Raises RequestException when absent."""
        return self.module.get_user(uid)

    def create_user(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create the entry in LDAP; returns {dn, uid}."""
        return self.module.create_user(data)

    def update_user(self, uid: str, data: dict[str, Any]) -> dict[str, Any]:
        """Modify real LDAP attributes; returns {uid}."""
        return self.module.update_user(uid, data)

    def delete_user(self, uid: str) -> dict[str, Any]:
        """Remove the entry from LDAP; returns {uid}."""
        return self.module.delete_user(uid)


def record_values(record: dict[str, Any], key: str) -> str:
    """First scalar of an LDAP attribute (list-of-values or bare string)."""
    value = record.get(key)
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else ""
    return str(value) if value is not None else ""