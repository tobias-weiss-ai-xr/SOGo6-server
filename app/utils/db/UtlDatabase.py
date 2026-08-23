"""Raw SQL utility wrapper around the configured DB manager.

Provides ``execute_write`` / ``execute_read_one`` / ``execute_read_all`` used
by modules that run hand-written SQL (e.g. the WebAuthn module). Delegates to
the process-configured ``Client<DB_TYPE>`` manager and its live connection.
"""
from __future__ import annotations


from app.config.settings.ProcessSetting import process_config
from app.utils.module.importManager import import_and_instantiate_manager


class UtlDatabase:
    """Small facade over the configured SQL client for raw statements."""

    def __init__(self) -> None:
        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        """Instantiate and connect the configured SQL manager (lazy, once)."""
        if self._client is not None:
            return
        sogo_db_type = f"Client{process_config.SOGO_P_DB_TYPE}"
        self._client = import_and_instantiate_manager(
            module_path="app.manager.db",
            module_and_class_name=sogo_db_type,
            module_args=process_config.get_db_settings(),
        )
        self._client.connect()

    def _connection(self):
        """Return the live DB connection of the client."""
        self._init_client()
        if getattr(self._client, "db_conn", None) is None:
            self._client.connect()
        return self._client.db_conn

    def execute_write(self, sql: str, params: tuple | list | None = None) -> int:
        """Execute an INSERT/UPDATE/DELETE (or DDL) statement.

        :param sql: Raw SQL statement (may contain ``%s`` placeholders).
        :type sql: str
        :param params: Bound parameters, if any.
        :type params: tuple | list | None
        :return: Number of affected rows (0 for DDL).
        :rtype: int
        """
        conn = self._connection()
        with conn.cursor() as cur:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            conn.commit()
            try:
                return cur.rowcount if cur.rowcount is not None else 0
            except Exception:  # noqa: BLE001 - rowcount can be unavailable on some drivers
                return 0

    def _row_to_dict(self, cur, row):
        """Normalize a DBAPI row into a dict keyed by column name.

        Different drivers (sqlite3, mysql-connector, psycopg) return tuples by
        default; the WebAuthn module (the only consumer of this facade) expects
        dict rows. Drivers that already return dicts are passed through.
        """
        if row is None:
            return None
        if isinstance(row, dict):
            return row
        cols = [d[0] for d in (cur.description or [])]
        return dict(zip(cols, row))

    def execute_read_one(self, sql: str, params: tuple | list | None = None) -> dict | None:
        """Execute a SELECT and return the first row as a dict (or None).

        :param sql: Raw SELECT statement.
        :type sql: str
        :param params: Bound parameters, if any.
        :type params: tuple | list | None
        :return: First row as a dict keyed by column name, or None.
        :rtype: dict | None
        """
        conn = self._connection()
        with conn.cursor() as cur:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            return self._row_to_dict(cur, cur.fetchone())

    def execute_read_all(self, sql: str, params: tuple | list | None = None) -> list[dict]:
        """Execute a SELECT and return all rows as dicts.

        :param sql: Raw SELECT statement.
        :type sql: str
        :param params: Bound parameters, if any.
        :type params: tuple | list | None
        :return: All rows as dicts keyed by column name.
        :rtype: list[dict]
        """
        conn = self._connection()
        with conn.cursor() as cur:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            rows = cur.fetchall()
            return [self._row_to_dict(cur, r) for r in rows] if rows else []
