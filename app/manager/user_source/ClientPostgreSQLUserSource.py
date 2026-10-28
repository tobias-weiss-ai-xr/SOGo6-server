from __future__ import annotations

import base64
import hashlib
import hmac
import re
from typing import Any

from app.manager.user_source.ClientUserSource import ClientUserSource
from app.manager.db.ClientPostgreSQL import ClientPostgreSQL
from app.utils.db.Condition import AndCondition, EqualCondition
from app.utils import exceptions as exc
from app.utils import errors as err
from app.utils.logger.logger import logger_api

# ── The "one relational database with a small users table" (no LDAP) ─────
# The webmail login is resolved against a tiny `users` table living in the
# SAME database the SOGo6 server already uses (SOGO_P_DB_*, db "sogo").
# Column names can be overridden through the postgresql user-source settings
# (US_UID / US_MAIL / US_SQL_DOMAIN_FIELD); the defaults match the seeded
# table (see admin bootstrap / seed SQL).
DEFAULT_USERS_TABLE = "users"
DEFAULT_UID_COLUMN = "uid"
DEFAULT_CN_COLUMN = "cn"
DEFAULT_MAIL_COLUMNS = ("mail",)
DEFAULT_PASSWORD_COLUMN = "password"

# The minimal schema the login path relies on. Idempotent; run via
# `ensure_users_table()` during bootstrap (never from the hot login path).
USERS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS users (
    uid         VARCHAR(255) PRIMARY KEY,
    cn          VARCHAR(255) NOT NULL,
    mail        VARCHAR(255) NOT NULL,
    domain      VARCHAR(255) NOT NULL DEFAULT '',
    password    VARCHAR(255) NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE
);
"""

SCHEME_RE = re.compile(r"^\{([^}]+)\}(.*)$", re.DOTALL)


def _scheme(value: str) -> tuple[str, str]:
    """Split an optional ``{scheme}`` prefix from a stored password."""
    match = SCHEME_RE.match(value)
    if not match:
        return "", value
    return match.group(1), match.group(2)


def verify_password(cleartext: str, stored: str) -> bool:
    """Fail-closed password verification for the SQL user source.

    Supported storage forms:
      - ``{bcrypt}<bcrypt hash>`` or a bare bcrypt hash (legacy)
      - ``{pbkdf2-sha256}$iterations$salt_b64$digest_b64``

    Any other/unknown scheme, malformed value or empty input is rejected —
    the login path must never weaken because a stored hash is unrecognisable.
    """
    if not cleartext or not stored:
        return False
    scheme, value = _scheme(stored)
    try:
        if scheme in ("", "bcrypt"):
            import bcrypt

            return bcrypt.checkpw(cleartext.encode("utf-8"), value.encode("utf-8"))
        if scheme == "pbkdf2-sha256":
            iterations_s, salt_b64, digest_b64 = value.split("$", 2)
            iterations = int(iterations_s)
            salt = base64.b64decode(salt_b64)
            digest = base64.b64decode(digest_b64)
            computed = hashlib.pbkdf2_hmac(
                "sha256", cleartext.encode("utf-8"), salt, iterations
            )
            return hmac.compare_digest(computed, digest)
    except Exception as exc_:  # pylint: disable=broad-except
        # Any decode failure must be a failed login, never a 500.
        logger_api.warning("SQL user source password check failed: %s", exc_)
        return False
    logger_api.warning("SQL user source: unsupported password scheme %r", scheme)
    return False


class ClientPostgreSQLUserSource(ClientPostgreSQL, ClientUserSource):
    """Webmail user source backed by the relational DB SOGo6 already uses.

    Implements the ``ClientUserSource`` contract (``check_login``) on top of
    the application's PostgreSQL client: ``uid`` + ``password`` are verified
    against the small ``users`` table and the contact info (``cn``/``mail``)
    is read from the same row. This replaces the LDAP dependency for webmail
    logins — exactly one relational database, and it holds the users.

    Settings shape (built by ``UserSourceSettingsObj.get_user_source_settings``
    for ``US_TYPE=postgresql``): the ``db_*`` connection params plus the
    users-table mapping (table, uid_field, cn_field, mail_fields,
    domain_field, password_field, pwd_algo, prepend_pwd_scheme).
    """

    def __init__(
        self,
        db_user: str,
        db_pwd: str,
        db_host: str,
        db_port: int,
        db_ssl: bool,
        db_enc: str,
        db_name: str | None = None,
        table: str = DEFAULT_USERS_TABLE,
        uid_field: str = DEFAULT_UID_COLUMN,
        cn_field: str = DEFAULT_CN_COLUMN,
        mail_fields: list[str] | None = None,
        domain_field: str = "",
        password_field: str = DEFAULT_PASSWORD_COLUMN,
        pwd_algo: str = "",
        prepend_pwd_scheme: bool = True,
        extra_filter: str = "",
    ) -> None:
        super().__init__(
            db_user, db_pwd, db_host, db_port, db_ssl, db_enc, db_name
        )
        self.table = table
        self.uid_field = uid_field or DEFAULT_UID_COLUMN
        self.cn_field = cn_field or DEFAULT_CN_COLUMN
        self.mail_fields = list(mail_fields or DEFAULT_MAIL_COLUMNS)
        self.domain_field = domain_field
        self.password_field = password_field or DEFAULT_PASSWORD_COLUMN
        self.pwd_algo = pwd_algo
        self.prepend_pwd_scheme = prepend_pwd_scheme
        self.extra_filter = extra_filter

    # ------------------------------------------------------------------
    # ClientUserSource contract
    # ------------------------------------------------------------------

    def check_login(
        self, username: str, password: str, domain: str
    ) -> tuple[bool, dict, dict[str, list[str]]]:
        """Verify ``username``/``password`` against the users table.

        Returns the ClientUserSource contract: ``(bool, policy_dict,
        contact_dict)`` where contact carries at least ``cn`` and ``mail`` as
        lists (mirrors ClientLdap.check_login). Always fail-closed; source
        errors degrade to a failed login instead of a 500.
        """
        if not username or not password:
            return False, {}, {}

        try:
            columns = self._resolve_columns()
        except exc.RequestException:
            logger_api.warning(
                "SQL user source %s not usable for login: table/column missing",
                self.table,
            )
            return False, {}, {}

        condition: Any = EqualCondition(self.uid_field, username)
        if self.domain_field:
            condition = AndCondition(condition, EqualCondition(self.domain_field, domain))

        try:
            rows = list(self.select_from_table(self.table, columns, condition))
        except exc.RequestException as e:
            logger_api.warning("SQL user source %s query failed: %s", self.table, e)
            return False, {}, {}

        if len(rows) != 1:
            if len(rows) > 1:
                logger_api.warning(
                    "SQL user source: %s matches %d rows for uid %r — refusing",
                    self.table, len(rows), username,
                )
            return False, {}, {}

        row = dict(zip(columns, rows[0]))

        if not verify_password(password, str(row.get(self.password_field, ""))):
            return False, {}, {}
        if not row.get("enabled", True):
            return False, {}, {}

        contact: dict[str, list[str]] = {
            self.cn_field: [str(row[self.cn_field])],
        }
        for mail_col in self.mail_fields:
            if mail_col in row:
                contact[mail_col] = [str(row[mail_col])]
        # "mail" is the canonical key the caller reads (fill_user_with_contact_info)
        if "mail" not in contact and self.mail_fields:
            contact["mail"] = contact.get(self.mail_fields[0], [])
        return True, {}, contact

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _resolve_columns(self) -> tuple[str, ...]:
        """Resolve the column list, validating them against the live schema."""
        if self.db_conn is None or self.db_conn.closed:
            self.connect()
        info = self.get_table_info(self.table)
        if info is None:
            raise exc.RequestException(
                f"users table '{self.table}' not found in the relational DB"
            )
        wanted: list[str] = []
        for col in (self.uid_field, self.cn_field, self.password_field):
            if col not in info:
                raise exc.RequestException(
                    f"users table '{self.table}' lacks required column '{col}'"
                )
            wanted.append(col)
        for col in [*self.mail_fields,
                    self.domain_field if self.domain_field else None,
                    "enabled"]:
            if col and col in info and col not in wanted:
                wanted.append(col)
        return tuple(wanted)

    def ensure_users_table(self) -> None:
        """Create the users table if missing (idempotent; bootstrap only)."""
        if self.db_conn is None or self.db_conn.closed:
            self.connect()
        self.db_conn.execute(USERS_TABLE_DDL)  # type: ignore[union-attr]
        self.db_conn.commit()  # type: ignore[union-attr]
