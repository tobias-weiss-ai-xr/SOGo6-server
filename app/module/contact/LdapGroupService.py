"""LDAP-backed group service for contact distribution lists (F3).

Domain logic for operating on LDAP ``groupOfNames`` distribution lists that
coexist with SQL-backed address books.

Address books / lists are identified by an ``addressbook_key`` that the
:mod:`app.utils.id_resolver` classifies:

- numeric ids (e.g. ``123``)  -> SQL-backed address books (not handled here)
- ``ldap:<cn>`` or a full DN ``cn=<cn>,ou=groups,...`` -> LDAP group

Membership is stored on the ``member`` attribute of the ``groupOfNames``
entry (written with python-ldap extended modify operations). This service
publishes ``get_members`` / ``add_member`` / ``remove_member`` on top of a
python-ldap connection exposed by :class:`app.manager.ldap.ClientLdap` and
keeps the ``member`` values in sync with the directory.

The LDAP client is injected (constructor or :meth:`from_user_source`), so unit
tests can pass a fake client — no live LDAP / MySQL required. The class is used
by :class:`app.interface.contact.InterfaceApiContactContact` as the
domain-logic partner for LDAP list member operations.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import ldap

from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.id_resolver import is_ldap_group, resolve_address_book_id
from app.utils.logger.logger import logger_ldap

if TYPE_CHECKING:
    from app.config.settings.DomainSettings import UserSourceSettingsObj
    from app.manager.ldap.ClientLdap import ClientLdap

# Object class used when searching for a group entry.
_GROUP_OBJECT_CLASS = "groupOfNames"
# LDAP attribute holding the member DNs.
_MEMBER_ATTR = "member"


def _looks_like_dn(value: str) -> bool:
    """Heuristic: a contact id that already is a distinguished name."""
    return "=" in value


class LDAPGroupService:
    """LDAP group operations (get/add/remove members) for contact lists.

    :param process_settings: Process settings (kept for API compatibility; the
        production LDAP client is normally injected through the factories).
    :param user_domain_settings: Domain settings dict (kept for compatibility).
    :param client: An optional already-connected LDAP client (duck-typed: needs
        ``ldap_conn``, ``search_entries`` and ``base_dn``). When omitted the
        service has no live connection and member operations raise.
    :param groups_base: Base DN under which groups live. Defaults to
        ``"ou=groups,{base_dn}"`` (derived from the client base_dn).
    :param users_base: Base DN under which member users live. Defaults to the
        client base_dn.
    """

    def __init__(
        self,
        process_settings: Any | None = None,
        user_domain_settings: dict | None = None,
        client: Any | None = None,
        groups_base: str | None = None,
        users_base: str | None = None,
    ) -> None:
        self.process_settings = process_settings
        self.user_domain_settings = user_domain_settings or {}
        self._client: Any | None = client
        base_dn: str = getattr(client, "base_dn", "") or "" if client is not None else ""
        self._groups_base: str = groups_base or (f"ou=groups,{base_dn}" if base_dn else "")
        self._users_base: str = users_base or base_dn

    def __del__(self) -> None:  # pragma: no cover - defensive teardown
        if self._client is not None:
            try:
                close = getattr(self._client, "close", None)
                if close is not None:
                    close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_user_source(cls, user_source: UserSourceSettingsObj) -> LDAPGroupService:
        """Build a connected service from a domain LDAP user source.

        Instantiates and connects a :class:`ClientLdap` from the source's
        settings, binds with the admin credentials (required for writes) and
        derives the groups/users base from the source configuration.

        :param user_source: The domain's LDAP ``UserSourceSettingsObj``.
        :raises RequestException: If the source is not LDAP or has no bind DN.
        """
        if user_source.US_TYPE != "ldap":
            raise RequestException(
                f"User source {user_source.US_UID} is not an LDAP source",
                error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED,
            )

        from app.manager.ldap.ClientLdap import ClientLdap

        us_config: dict[str, Any] = user_source.get_user_source_settings("ldap")
        client: ClientLdap = ClientLdap(**us_config)
        client.connect()
        client._bind(user_source.US_LDAP_BIND_DN, user_source.US_LDAP_BIND_DN_PWD, use_admin=True)

        base_dn: str = client.base_dn or ""
        groups_base: str = getattr(user_source, "US_LDAP_GROUPS_BASE", None) or f"ou=groups,{base_dn}"
        users_base: str = getattr(user_source, "US_LDAP_USERS_BASE", None) or base_dn
        return cls(client=client, groups_base=groups_base, users_base=users_base)

    @classmethod
    def from_user_sources(cls, user_sources: dict | None) -> LDAPGroupService:
        """Build a connected service from the request's user-sources mapping.

        Picks the first LDAP source from ``user_sources`` (a dict of
        ``UserSourceSettingsObj``) and delegates to :meth:`from_user_source`.

        :raises RequestException: If no LDAP user source is configured.
        """
        if not user_sources:
            raise RequestException("No LDAP user source configured", error=err.ERROR_LDAP_CANNOT_CONNECT)
        for user_source in user_sources.values():
            if user_source.US_TYPE == "ldap":
                return cls.from_user_source(user_source)
        raise RequestException("No LDAP user source configured", error=err.ERROR_LDAP_CANNOT_CONNECT)

    # ------------------------------------------------------------------
    # Connection & setup
    # ------------------------------------------------------------------

    def _get_ldap_client(self) -> Any:
        """Return the bound LDAP client backing this service."""
        if self._client is None or getattr(self._client, "ldap_conn", None) is None:
            raise RequestException("LDAP client not available", error=err.ERROR_LDAP_CANNOT_CONNECT)
        return self._client

    # ------------------------------------------------------------------
    # DN helpers
    # ------------------------------------------------------------------

    def _build_group_dn(self, cn: str) -> str:
        """Build the full DN for a group from its CN."""
        return f"cn={cn},{self._groups_base}"

    def _build_member_dn(self, contact_id: str) -> str:
        """Build the full member DN from a contact identifier.

        Accepts a full DN (returned as-is), an email address (local part used
        as uid) or a plain uid; otherwise builds ``uid=<uid>,<users_base>``.
        """
        if not contact_id:
            raise RequestException("Empty contact id", error=err.ERROR_CONTACT_LIST_MEMBER_INVALID)
        if _looks_like_dn(contact_id):
            return contact_id
        uid: str = contact_id.split("@", 1)[0]
        return f"uid={uid},{self._users_base}"

    def to_dn(self, uid: str) -> str:
        """Public helper: turn a uid into the member DN under the users base."""
        return self._build_member_dn(uid)

    # ------------------------------------------------------------------
    # ID resolution
    # ------------------------------------------------------------------

    def _is_ldap(self, list_id: str) -> bool:
        """True if the list id refers to an LDAP group (not a SQL address book)."""
        return is_ldap_group(list_id)

    def _resolve_cn(self, list_id: str) -> str:
        """Extract the CN from an ldap: prefix, a DN, or a plain CN id."""
        return resolve_address_book_id(list_id).normalized_id

    # ------------------------------------------------------------------
    # Member operations
    # ------------------------------------------------------------------

    def get_members(self, list_id: str) -> list[str]:
        """Return all member DNs of an LDAP group.

        :param list_id: The group id (``ldap:`` prefix, DN, or CN).
        :return: List of member DNs (decoded strings).
        :raises RequestException: If the id is a SQL address book or the group
            is missing.
        """
        if not self._is_ldap(list_id):
            raise RequestException(
                f"List {list_id} is not an LDAP group (SQL address book)",
                error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND,
            )

        group_dn = self._build_group_dn(self._resolve_cn(list_id))
        client = self._get_ldap_client()

        try:
            entries = client.search_entries(
                base_dn=group_dn,
                l_filter=f"(objectClass={_GROUP_OBJECT_CLASS})",
                attributes=[_MEMBER_ATTR],
            )
        except RequestException:
            raise
        except Exception as e:  # pragma: no cover - defensive
            logger_ldap.error("Failed to search group %s: %s", group_dn, e)
            raise RequestException(f"Failed to search group: {e}", error=err.ERROR_LDAP_CANNOT_SEARCH) from e

        if not entries:
            raise RequestException(f"Group not found: {group_dn}", error=err.ERROR_CONTACT_LIST_NOT_FOUND)

        return list(entries[0].get(_MEMBER_ATTR, []))

    def add_member(self, list_id: str, contact_id: str) -> str:
        """Add a member (by uid) to an LDAP group (idempotent).

        :param list_id: The group id (``ldap:`` prefix, DN, or CN).
        :param contact_id: The member uid / email / DN.
        :return: The member DN that was added.
        :raises RequestException: If the id is a SQL address book, the group
            does not exist, or the LDAP modification fails.
        """
        group_dn, member_dn = self._resolve_for_modify(list_id, contact_id)
        client = self._get_ldap_client()

        try:
            mod_list = [(ldap.MOD_ADD, _MEMBER_ATTR, member_dn.encode())]
            client.ldap_conn.modify_s(group_dn, mod_list)  # type: ignore[union-attr]
        except (ldap.ALREADY_EXISTS, ldap.TYPE_OR_VALUE_EXISTS):
            # Member already present; idempotent success.
            logger_ldap.debug("Member %s already in group %s", member_dn, group_dn)
        except ldap.NO_SUCH_OBJECT:
            logger_ldap.error("LDAP group not found: %s", group_dn)
            raise RequestException(f"Group not found: {group_dn}", error=err.ERROR_LDAP_GROUP_NOT_FOUND) from None
        except ldap.LDAPError as e:
            logger_ldap.error("Failed to add member %s to group %s: %s", member_dn, group_dn, e)
            raise RequestException(f"Failed to add member to group: {e}", error=err.ERROR_LDAP_MODIFY_FAILED) from e

        logger_ldap.info("Added member %s to LDAP group %s", member_dn, group_dn)
        return member_dn

    def remove_member(self, list_id: str, contact_id: str) -> str:
        """Remove a member (by uid) from an LDAP group (idempotent).

        :param list_id: The group id (``ldap:`` prefix, DN, or CN).
        :param contact_id: The member uid / email / DN to remove.
        :return: The member DN that was removed.
        :raises RequestException: If the id is a SQL address book, the group
            does not exist, or the LDAP modification fails.
        """
        group_dn, member_dn = self._resolve_for_modify(list_id, contact_id)
        client = self._get_ldap_client()

        try:
            mod_list = [(ldap.MOD_DELETE, _MEMBER_ATTR, member_dn.encode())]
            client.ldap_conn.modify_s(group_dn, mod_list)  # type: ignore[union-attr]
        except (ldap.NO_SUCH_OBJECT, ldap.NO_SUCH_ATTRIBUTE):
            # Member (or group) already absent; idempotent success.
            logger_ldap.debug("Member %s not in group %s", member_dn, group_dn)
        except ldap.LDAPError as e:
            logger_ldap.error("Failed to remove member %s from group %s: %s", member_dn, group_dn, e)
            raise RequestException(f"Failed to remove member from group: {e}", error=err.ERROR_LDAP_MODIFY_FAILED) from e

        logger_ldap.info("Removed member %s from LDAP group %s", member_dn, group_dn)
        return member_dn

    def _resolve_for_modify(self, list_id: str, contact_id: str) -> tuple[str, str]:
        """Common routing + DN resolution used by add/remove member.

        :raises RequestException: If the id is a SQL address book.
        """
        if not self._is_ldap(list_id):
            raise RequestException(
                f"List {list_id} is not an LDAP group (SQL address book)",
                error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_FOUND,
            )
        group_dn = self._build_group_dn(self._resolve_cn(list_id))
        member_dn = self._build_member_dn(contact_id)
        return group_dn, member_dn
