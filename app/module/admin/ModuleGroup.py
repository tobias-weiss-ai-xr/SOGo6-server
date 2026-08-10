"""LDAP-backed group management for Student Groups.

This module provides real LDAP group operations so that the Student Groups API
syncs with the directory instead of fabricating group memberships in Redis.

Groups are represented as LDAP `groupOfNames` (RFC 2256) entries under a
configurable groups base DN (default ou=groups). Student Groups are relied
upon by the `ApiStudentGroups` endpoints; the old implementation kept only
Redis records with no directory sync.

Note: Uses the same process_settings pattern as ModuleAdminUser to locate
      the configured LDAP user source.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.config.db import tables as tbl
from app.config.settings.DomainSettings import UserSourceSettingsObj
from app.manager.ldap.ClientLdap import ClientLdap
from app.utils.db.Condition import NotEqualCondition
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger
from app.utils.module.importManager import import_and_instantiate_manager

if TYPE_CHECKING:
    from app.config.settings.ProcessSetting import ProcessSetting

# Default group object classes and attributes
_GROUP_OBJECT_CLASSES = [b"top", b"groupOfNames"]
_GROUPEREQUED_ATTRS = [b"cn"]


def _group_dn(cn: str, groups_base: str) -> str:
    """Build DN for a group: cn=...,ou=groups,dc=...
    Groups base usually ends with ou=groups,dc=example,dc=org; we append cn=NAME."""
    return f"cn={cn},{groups_base}"


def _member_dn(uid: str, users_base: str) -> str:
    """Build DN for a user member: uid=...,ou=users,dc=...
    The users_base is the LDAP base_dn for user entries."""
    return f"uid={uid},{users_base}"


class ModuleGroup:
    """LDAP group CRUD operations for Student/Shared groups."""

    def __init__(self, process_settings: ProcessSetting | None = None) -> None:
        self.process_settings = process_settings
        self._client: ClientLdap | None = None
        self._groups_base: str = ""
        self._users_base: str = ""

    # ------------------------------------------------------------
    # Connection & setup
    # ------------------------------------------------------------
    def _get_ldap_client(self) -> ClientLdap:
        """Return a connected ClientLdap using the default LDAP user source."""
        if self._client and self._client.connected and self._client.binded:
            return self._client

        if not self.process_settings:
            raise RequestException("Process settings not available", error=None)

        # Build SQL client to fetch domain settings (same flow as ModuleAdminUser)
        sogo_db_type = f"Client{self.process_settings.SOGO_P_DB_TYPE}"
        sogo_db_manager = import_and_instantiate_manager(
            module_path="app.manager.db",
            module_and_class_name=sogo_db_type,
            module_args=self.process_settings.get_db_settings(),
        )
        sogo_db_manager.connect()
        try:
            cond = NotEqualCondition(param_name=tbl.COL_SETTINGS_UNIQUE.name, param_value=0)
            result = list(
                sogo_db_manager.select_from_table(
                    table_name=tbl.TABLE_SETTINGS.name,
                    column_tuple=(tbl.COL_SETTINGS_DOMAIN_DEFAULT.name,),
                    condition=cond,
                )
            )
            domain_settings: dict = result[0][0] if result else {}
        finally:
            sogo_db_manager.close()

        if not domain_settings:
            raise RequestException("No domain settings found", error=None)

        user_sources: dict = domain_settings.get("USER_SOURCE", {})
        ldap_source = None
        for source_id, source_cfg in user_sources.items():
            if source_cfg.get("US_TYPE") == "ldap":
                ldap_source = UserSourceSettingsObj(source_cfg)
                break

        if not ldap_source:
            raise RequestException("No LDAP user source configured", error=None)

        us_config = ldap_source.get_user_source_settings("ldap")
        client: ClientLdap = ClientLdap(**us_config)
        client.connect()
        client._bind(ldap_source.US_LDAP_BIND_DN, ldap_source.US_LDAP_BIND_DN_PWD, use_admin=True)

        # Build bases
        base_dn = client.base_dn
        # groups_base: typically ou=groups,dc=... — configured via US_LDAP_GROUPS_BASE?
        #      or derived as ou=groups,{base_dn}. Fallback to base_dn if not configured.
        groups_base = getattr(ldap_source, "US_LDAP_GROUPS_BASE", None) or f"ou=groups,{base_dn}"
        users_base = getattr(ldap_source, "US_LDAP_USERS_BASE", None) or base_dn
        self._groups_base = groups_base
        self._users_base = users_base
        self._client = client
        logger.debug("ModuleGroup: connected to LDAP (groups_base=%s)", groups_base)
        return client

    # ------------------------------------------------------------
    # Group CRUD
    # ------------------------------------------------------------
    def create_group(self, cn: str, description: str | None = None, mail: str | None = None) -> str:
        """Create a new groupOfNames entry under the groups base DN.

        :param cn: Group common name (RFC 2256 cn attribute)
        :param description: Optional description
        :param mail: Optional group mail address
        :return: Group DN
        """
        client = self._get_ldap_client()
        dn = _group_dn(cn, self._groups_base)

        mods = [
            (b"objectClass", _GROUP_OBJECT_CLASSES),
            (b"cn", [cn.encode()]),
        ]
        if description:
            mods.append((b"description", [description.encode()]))
        if mail:
            mods.append((b"mail", [mail.encode()]))

        # python-ldap modlist: list of (attr, values) tuples, both as bytes
        client.ldap_conn.add_s(dn, mods)  # type: ignore[union-attr]
        logger.info("LDAP group created: dn=%s", dn)
        return dn

    def delete_group(self, dn: str) -> None:
        """Delete a group entry by DN."""
        client = self._get_ldap_client()
        client.ldap_conn.delete_s(dn)  # type: ignore[union-attr]
        logger.info("LDAP group deleted: dn=%s", dn)

    def get_group(self, dn: str) -> dict:
        """Fetch group entry attributes by DN.

        Returns a dict: keys are lower-case attribute names, values are lists of strings,
        plus a 'dn' key.
        """
        client = self._get_ldap_client()
        entries = client.search_entries(base_dn=dn, l_filter="(objectClass=groupOfNames)", attributes=None)
        if not entries:
            raise RequestException(f"Group not found: {dn}", error=None)
        return entries[0]

    def search_groups(self, base: str | None = None, filter_str: str | None = None) -> list[dict]:
        """Search for groups; returns list of parsed entry dicts."""
        client = self._get_ldap_client()
        base_dn = base or self._groups_base
        return client.search_entries(base_dn=base_dn, l_filter=filter_str or "(objectClass=groupOfNames)", attributes=None)

    # ------------------------------------------------------------
    # Membership
    # ------------------------------------------------------------
    def add_member(self, group_dn: str, member_dn: str) -> None:
        """Add a member (DN) to a groupOfNames group."""
        client = self._get_ldap_client()
        mod_list = [(b"member", [(b"add", [member_dn.encode()])])]
        client.ldap_conn.modify_s(group_dn, mod_list)  # type: ignore[union-attr]
        logger.info("LDAP member added: %s to %s", member_dn, group_dn)

    def remove_member(self, group_dn: str, member_dn: str) -> None:
        """Remove a member (DN) from a groupOfNames group."""
        client = self._get_ldap_client()
        mod_list = [(b"member", [(b"remove", [member_dn.encode()])])]
        try:
            client.ldap_conn.modify_s(group_dn, mod_list)  # type: ignore[union-attr]
        except Exception as e:
            # member may not be present; log and ignore
            logger.warning("Failed to remove member %s from %s: %s", member_dn, group_dn, e)
        logger.info("LDAP member removed: %s from %s", member_dn, group_dn)

    def get_members(self, group_dn: str) -> list[str]:
        """List all member DNs of a groupOfNames group."""
        group = self.get_group(group_dn)
        return group.get("member", [])  # already decoded strings

    # ------------------------------------------------------------
    # Util: lookup user DN by email (uid in LDAP)
    # ------------------------------------------------------------
    def user_dn_from_email(self, email: str) -> str | None:
        """Resolve a user's DN from their email address.

        Assumes email = uid@domain; uid is the LDAP uid attribute.
        """
        client = self._get_ldap_client()
        # local-part = uid
        uid = email.split("@")[0]
        entries = client.search_entries(
            base_dn=self._users_base,
            l_filter=f"(&(uid={uid})(objectClass=inetOrgPerson))",
            attributes=["dn", "uid", "mail"],
        )
        if entries:
            return entries[0].get("dn", [None])[0]
        return None

    def user_dn_from_uid(self, uid: str) -> str | None:
        """Resolve a DN from a uid directly."""
        return _member_dn(uid, self._users_base)
