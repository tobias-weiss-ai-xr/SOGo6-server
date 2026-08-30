from __future__ import annotations
from typing import TYPE_CHECKING, Any

import hashlib
import base64
import secrets

import ldap

from app.config.db import tables as tbl
from app.config.settings.DomainSettings import UserSourceSettingsObj
from app.manager.ldap.ClientLdap import ClientLdap, parse_python_ldap_record
from app.service import sogo_cache
from app.utils import errors as err
from app.utils.db.Condition import NotEqualCondition
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger
from app.utils.module.importManager import import_and_instantiate_manager


def _emit_webhook(event: str, payload: dict) -> None:
    """Best-effort async webhook emitter; never raises, never blocks."""
    from app.service.webhook.WebhookService import emit_event

    emit_event(event, payload)


if TYPE_CHECKING:
    from app.config.settings.ProcessSetting import ProcessSetting
    from app.manager.db.ClientSQL import ClientSQL
    from app.utils.api.paginate_sort_filter import CollectionPaginateArgs


def _ssha_hash(password: str) -> str:
    """Generate an SSHA hash of the password (LDAP-compatible)."""
    salt = secrets.token_bytes(8)
    sha = hashlib.sha1(password.encode("utf-8"))
    sha.update(salt)
    digest = sha.digest()
    b64 = base64.b64encode(digest + salt).decode("ascii")
    return "{SSHA}" + b64


def _pick(d: dict, *keys: str) -> dict:
    """Return a new dict with only the given keys (if present in *d*)."""
    return {k: d[k] for k in keys if k in d}


class ModuleAdminUser:
    """
    Module to handle admin operations on users.

    Supports both session management (via Redis cache) and
    user CRUD (via LDAP user source).
    """

    def __init__(self, process_settings: ProcessSetting | None = None) -> None:
        self.process_settings = process_settings

    # ── LDAP helpers ──────────────────────────────────────────────────────────

    def _get_ldap_client(self) -> ClientLdap:
        """
        Read the default domain settings from the database, extract the
        first LDAP user source and return a connected ``ClientLdap`` instance.

        :return: A connected LDAP client
        :rtype: ClientLdap
        :raises RequestException: If no LDAP user source is configured
        """
        if not self.process_settings:
            raise RequestException("Process settings not available", error=err.ERROR_CONFIG_ERROR)

        sogo_db_type = f"Client{self.process_settings.SOGO_P_DB_TYPE}"
        sogo_db_manager: ClientSQL = import_and_instantiate_manager(
            module_path="app.manager.db",
            module_and_class_name=sogo_db_type,
            module_args=self.process_settings.get_db_settings(),
        )
        sogo_db_manager.connect()

        # Read the default domain settings (single-row table)
        cond = NotEqualCondition(param_name=tbl.COL_SETTINGS_UNIQUE.name, param_value=0)
        result = list(
            sogo_db_manager.select_from_table(
                table_name=tbl.TABLE_SETTINGS.name,
                column_tuple=(tbl.COL_SETTINGS_DOMAIN_DEFAULT.name,),
                condition=cond,
            )
        )
        sogo_db_manager.close()

        if not result:
            raise RequestException("No domain settings found in database", error=err.ERROR_CONFIG_ERROR)

        domain_settings: dict = result[0][0] if isinstance(result[0], (tuple, list)) else result[0]
        if not domain_settings:
            raise RequestException("Default domain settings are empty", error=err.ERROR_CONFIG_ERROR)

        # Find the first LDAP user source
        # The domain settings store user sources under the "USER_SOURCE" key,
        # with source IDs as sub-keys (e.g. "ldap_main").
        user_sources: dict = domain_settings.get("USER_SOURCE", {})
        if not user_sources:
            raise RequestException("No user sources configured in domain settings", error=err.ERROR_CONFIG_ERROR)

        ldap_source = None
        ldap_source_id = None
        for source_id, source_cfg in user_sources.items():
            if source_cfg.get("US_TYPE") == "ldap":
                ldap_source = UserSourceSettingsObj(source_cfg)
                ldap_source_id = source_id
                break

        if not ldap_source:
            raise RequestException("No LDAP user source configured", error=err.ERROR_CONFIG_ERROR)

        us_config = ldap_source.get_user_source_settings("ldap")
        client: ClientLdap = ClientLdap(**us_config)
        client.connect()
        # Bind as admin
        client._bind(ldap_source.US_LDAP_BIND_DN, ldap_source.US_LDAP_BIND_DN_PWD, use_admin=True)

        logger.debug("Connected to LDAP for user management (source=%s)", ldap_source_id)
        return client

    @staticmethod
    def _attrs_for_list() -> list[str]:
        """Attributes fetched when listing/searching users."""
        return ["uid", "cn", "sn", "givenName", "mail", "uidNumber", "gidNumber", "homeDirectory"]

    # ── User CRUD ─────────────────────────────────────────────────────────────

    def list_users(self, query: str | None = None, page: int = 1, per_page: int = 20,
                   sort_by: str = "uid", sort_order: str = "asc") -> tuple[int, list[dict[str, Any]]]:
        """
        Search and paginate users from the LDAP directory.

        :param query: Optional search string (matches uid, cn, sn, givenName, mail)
        :param page: Page number (1-based)
        :param per_page: Items per page
        :param sort_by: Field to sort by
        :param sort_order: 'asc' or 'desc'
        :return: Tuple of (total_count, list of user dicts)
        """
        client = self._get_ldap_client()
        try:
            base_dn = client.base_dn
            # Build filter
            if query:
                escaped = query.replace("\\", "\\\\").replace("*", "\\*").replace("(", "\\(").replace(")", "\\)")
                filter_str = (
                    f"(&{client.filter or ''}"
                    f"(|(uid=*{escaped}*)(cn=*{escaped}*)"
                    f"(sn=*{escaped}*)(givenName=*{escaped}*)"
                    f"(mail=*{escaped}*)))"
                )
            else:
                filter_str = client.filter or "(objectClass=inetOrgPerson)"

            raw = client._search(base_dn, l_filter=filter_str, attributes=self._attrs_for_list())
        finally:
            client.close()

        # Parse records
        users = [parse_python_ldap_record(r) for r in raw]

        # Sort
        reverse = sort_order.lower() == "desc"
        try:
            users.sort(key=lambda u: (u.get(sort_by) or [""])[0], reverse=reverse)
        except (KeyError, IndexError):
            pass  # best-effort: keep fallback/default value on failure

        total = len(users)

        # Paginate
        start = (page - 1) * per_page
        end = start + per_page
        page_users = users[start:end]

        logger.debug("list_users: found %d user(s), returning %d", total, len(page_users))
        return total, page_users

    def get_user(self, uid: str) -> dict[str, Any]:
        """
        Return a single user by *uid* (the LDAP ``uid`` attribute value).

        :param uid: The user ID to look up
        :return: User record dict
        :raises RequestException: If the user is not found
        """
        client = self._get_ldap_client()
        try:
            escaped_uid = uid.replace("\\", "\\\\").replace("*", "\\*").replace("(", "\\(").replace(")", "\\)")
            filter_str = f"(&{client.filter or ''}(uid={escaped_uid}))"
            raw = client._search(client.base_dn, l_filter=filter_str)
        finally:
            client.close()

        if not raw:
            raise RequestException(f"User '{uid}' not found", error=err.ERROR_USER_PROFILE_NOT_FOUND)

        return parse_python_ldap_record(raw[0])

    def create_user(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Create a new user entry in LDAP.

        :param data: User data (uid, cn, sn, givenName, mail, password, …)
        :return: Dict with ``dn`` and ``uid`` of the created entry
        """
        uid = data["uid"]
        mail = data["mail"]

        # The login flow binds DN "uid=<login-username>,<base_dn>" where the
        # username is the full email — the uid IS the login name (platform
        # convention: every seeded entry uses the email as uid/RDN). A bare
        # uid (e.g. "jdoe") would create an account that can never log in,
        # so reject it up front instead of returning a misleading 200.
        if "@" not in uid or "." not in uid.rsplit("@", 1)[-1]:
            raise RequestException(
                f"User uid '{uid}' must be the full email-format login "
                f"(e.g. '{uid}@example.org') — it is used verbatim as the "
                f"LDAP RDN and as the login name",
                error=err.ERROR_VALIDATION_ERROR,
            )
        if uid != mail:
            raise RequestException(
                f"User uid '{uid}' and mail '{mail}' must match — the uid "
                f"is the login name users type at sign-in",
                error=err.ERROR_VALIDATION_ERROR,
            )

        client = self._get_ldap_client()
        try:
            cn = data["cn"]
            sn = data["sn"]
            given_name = data.get("givenName", cn)
            password = data["password"]

            uid_number = data.get("uidNumber")
            gid_number = data.get("gidNumber")
            home_dir = data.get("homeDirectory") or f"/home/{uid.split('@')[0] if '@' in uid else uid}"

            # Determine next available UID/GID if not provided
            if uid_number is None or gid_number is None:
                # Search for max existing uidNumber/gidNumber
                try:
                    all_raw = client._search(client.base_dn, l_filter=client.filter or "(objectClass=inetOrgPerson)",
                                            attributes=["uidNumber", "gidNumber"])
                    existing_ids = [parse_python_ldap_record(r) for r in all_raw]
                    max_uid = max(
                        (int(v[0]) for u in existing_ids if (v := u.get("uidNumber"))),
                        default=1000,
                    )
                    max_gid = max(
                        (int(v[0]) for u in existing_ids if (v := u.get("gidNumber"))),
                        default=1000,
                    )
                except Exception:
                    max_uid = 1000
                    max_gid = 1000

                uid_number = uid_number or (max_uid + 1)
                gid_number = gid_number or (max_gid + 1)

            # Build the DN
            dn = f"uid={uid},{client.base_dn}"

            # Build entry
            entry = {
                "objectClass": [b"inetOrgPerson", b"posixAccount", b"shadowAccount"],
                "uid": [uid.encode("utf-8")],
                "cn": [cn.encode("utf-8")],
                "sn": [sn.encode("utf-8")],
                "givenName": [given_name.encode("utf-8")],
                "mail": [mail.encode("utf-8")],
                "uidNumber": [str(uid_number).encode("utf-8")],
                "gidNumber": [str(gid_number).encode("utf-8")],
                "homeDirectory": [home_dir.encode("utf-8")],
                "userPassword": [_ssha_hash(password).encode("utf-8")],
            }

            if client.ldap_conn is not None:
                client.ldap_conn.add_s(dn, list(entry.items()))
            else:
                raise RequestException("LDAP connection is not available", error=err.ERROR_LDAP_CANNOT_CONNECT)

            logger.debug("Created LDAP user: %s", dn)
            _emit_webhook("user.created", {"uid": uid, "mail": data.get("mail", "")})
            return {"dn": dn, "uid": uid}
        finally:
            client.close()

    def update_user(self, uid: str, data: dict[str, Any]) -> dict[str, Any]:
        """
        Update an existing user's attributes in LDAP.

        :param uid: The user ID to update
        :param data: Dict of attributes to modify (cn, sn, givenName, mail, password)
        :return: Dict with ``uid`` of the updated entry
        :raises RequestException: If the user is not found
        """
        client = self._get_ldap_client()
        try:
            escaped_uid = uid.replace("\\", "\\\\").replace("*", "\\*").replace("(", "\\(").replace(")", "\\)")
            filter_str = f"(&{client.filter or ''}(uid={escaped_uid}))"
            raw = client._search(client.base_dn, l_filter=filter_str, attributes=["dn"])
            if not raw:
                raise RequestException(f"User '{uid}' not found", error=err.ERROR_USER_PROFILE_NOT_FOUND)

            dn = raw[0][0]

            # Build modifications
            mod_list = []
            for attr, value in data.items():
                if value is None:
                    continue
                if attr == "password":
                    mod_list.append(("userPassword", [_ssha_hash(value).encode("utf-8")]))
                elif attr == "shadowExpire":
                    # Real LDAP account-deactivation attribute (posixAccount):
                    # 1 disables the account; None removes the attribute (enables).
                    if value is None or value == "":
                        mod_list.append(("shadowExpire", None))
                    else:
                        mod_list.append(("shadowExpire", [str(value).encode("utf-8")]))
                elif attr in ("cn", "sn", "givenName", "mail"):
                    mod_list.append((attr, [value.encode("utf-8")]))
                elif attr in ("uidNumber", "gidNumber"):
                    mod_list.append((attr, [str(value).encode("utf-8")]))

            if mod_list and client.ldap_conn is not None:
                client.ldap_conn.modify_s(dn, [(ldap.MOD_REPLACE, a, v) for a, v in mod_list])
                logger.debug("Updated LDAP user: %s (attrs=%s)", dn, [a for a, _ in mod_list])
            elif not mod_list:
                logger.warning("update_user: no attributes to update for %s", uid)

            _emit_webhook("user.updated", {"uid": uid, "mail": data.get("mail", "")})
            return {"uid": uid}
        finally:
            client.close()

    def delete_user(self, uid: str) -> dict[str, Any]:
        """
        Delete a user entry from LDAP.

        :param uid: The user ID to delete
        :return: Dict with ``uid`` of the deleted entry
        :raises RequestException: If the user is not found
        """
        client = self._get_ldap_client()
        try:
            escaped_uid = uid.replace("\\", "\\\\").replace("*", "\\*").replace("(", "\\(").replace(")", "\\)")
            filter_str = f"(&{client.filter or ''}(uid={escaped_uid}))"
            raw = client._search(client.base_dn, l_filter=filter_str, attributes=["dn"])
            if not raw:
                raise RequestException(f"User '{uid}' not found", error=err.ERROR_USER_PROFILE_NOT_FOUND)

            dn = raw[0][0]

            if client.ldap_conn is not None:
                client.ldap_conn.delete_s(dn)
            else:
                raise RequestException("LDAP connection is not available", error=err.ERROR_LDAP_CANNOT_CONNECT)

            logger.debug("Deleted LDAP user: %s", dn)
            _emit_webhook("user.deleted", {"uid": uid})
            return {"uid": uid}
        finally:
            client.close()

    # ── Session Management (unchanged from previous) ──────────────────────────

    def get_active_users(self, collection_param: CollectionPaginateArgs) -> tuple[int, list[dict]]:
        # ... (existing code)
        cache = sogo_cache()

        total_count, active_users = cache.zset_paginate_hashes(
            first=collection_param.first_item,
            last=collection_param.last_item,
            sort_by=collection_param.sort_by,
            sort_order=collection_param.sort_order
        )
        cache.close()

        logger.debug("%d active user session(s) (total: %d)", len(active_users), total_count)
        return total_count, active_users

    def revoke_users(self, uids: list[str] | None = None, redis_keys: list[str] | None = None) -> int:
        # ... (existing code)
        cache = sogo_cache()

        if uids is not None:
            try:
                revoked_count = cache.revoke_user_sessions_by_uid(uids)
            except Exception as e:
                raise RequestException(str(e), error=err.ERROR_CACHE_REVOKE_FAILED) from e

            logger.debug("Revoked %d session(s) for uid(s): %s", revoked_count, uids)
            return revoked_count

        if redis_keys is not None:
            try:
                revoked_count = cache.revoke_user_sessions_by_key(redis_keys)
            except Exception as e:
                raise RequestException(str(e), error=err.ERROR_CACHE_REVOKE_KEY_FAILED) from e

            logger.debug("Revoked %d session(s) for redis key(s): %s", revoked_count, redis_keys)
            return revoked_count

        cache.close()

        raise RequestException(
            "Exactly one of 'uid' or 'redis_key' must be provided",
            error=err.ERROR_REVOKE_BODY_INVALID,
        )

    def revoke_inactive_users(self, timestamp: int) -> int:
        # ... (existing code)
        cache = sogo_cache()

        revoked_count = cache.revoke_user_sessions_by_activity(timestamp)

        cache.close()

        logger.debug("Revoked %d inactive session(s) older than %d", revoked_count, timestamp)
        return revoked_count
