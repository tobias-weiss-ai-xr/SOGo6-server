from __future__ import annotations
from typing import Any, Generator, Tuple, List, cast

import re
import json
from datetime import datetime, timezone

import mysql.connector
from mysql.connector import Error, ProgrammingError  # pylint: disable=no-name-in-module

from app.utils.db.Table import Table, REX_VALID_NAMES
from app.utils.db.Condition import (Condition, EqualCondition, NotEqualCondition, AndCondition, OrCondition,
                                    TrueCondition, LessOrEqualCondition, GreaterOrEqualCondition,
                                    IsNullCondition, IsNotNullCondition, LikeCondition, FullTextCondition,
                                    JoinClause, Order)
from app.utils.db.FullTextValue import FullTextValue
from app.utils import errors as err
from app.utils.exceptions import RequestException, BugException
from app.utils.logger.logger import logger, logger_sql
from app.utils.api.prometheus import db_op

from .ClientSQL import ClientSQL


# Cache mapping JSON column names (data_type dict/list/json) -> True.
# On PostgreSQL these columns are JSONB and the driver returns parsed objects,
# but on MySQL they are stored as LONGTEXT and returned as raw strings. We must
# decode them on read to mirror the ``json.dumps`` applied to dict/list values
# on insert, otherwise consumers that expect parsed objects (e.g. domain
# settings) break on MySQL while working on PostgreSQL.
_JSON_COLUMN_TYPES: dict | None = None


# MySQL DATETIME/TIMESTAMP columns accept ``YYYY-MM-DD HH:MM:SS``. Callers pass
# ISO-8601 strings (e.g. ``datetime.now(timezone.utc).isoformat()`` →
# ``...T...:..:..123456+00:00``) which MariaDB/MySQL reject under
# ``STRICT_TRANS_TABLES`` with DataError 1292 "Incorrect datetime value".
# Normalise such values (and tz-aware datetime objects) to the MySQL-safe format
# before binding, so writes to datetime columns succeed. This mirrors the JSON
# normalisation above and covers all current and future call sites.
_RE_ISO_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})$"
)


def _mysql_datetime(value: Any) -> Any:
    """Convert a datetime object or ISO-8601 datetime string to MySQL's format.

    Plain strings (non-datetime) are returned unchanged.
    """
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, str) and _RE_ISO_DATETIME.match(value):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return value


def _json_column_types() -> dict:
    """Return a mapping of JSON column names (dict/list/json data_type) -> True."""
    global _JSON_COLUMN_TYPES
    if _JSON_COLUMN_TYPES is None:
        _JSON_COLUMN_TYPES = {}
        try:
            from app.config.db import tables as _tbl
            for _attr in vars(_tbl).values():
                if isinstance(_attr, Table):
                    for _col in _attr.columns:
                        if _col.data_type in ("dict", "list", "json"):
                            _JSON_COLUMN_TYPES[_col.name] = True
        except Exception:  # pragma: no cover - schema import safety net
            logger_sql.warning("Unable to build JSON column type map; JSON columns will not be decoded on read")
    return _JSON_COLUMN_TYPES


def _maybe_json_decode(value: Any, col_name: str, json_cols: dict) -> Any:
    """Decode a JSON string cell back into a Python object (MySQL TEXT storage)."""
    if isinstance(value, str) and json_cols.get(col_name):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
    return value


def str_to_varchar(max_len: int = 0) -> str:
    """
    Convert a string type to a VARCHAR()
    """
    if max_len <= 0:
        return "VARCHAR(255)"
    return f"VARCHAR({max_len})"


def list_to_json(data_type: str | None = None, extra_args: dict | None = None) -> str:
    """
    MySQL does not have a native array type similar to PostgreSQL arrays.
    We'll store lists as JSON.

    Signature intentionally accepts (data_type, extra_args) to mirror PostgreSQL
    list_to_array signature so table_to_query can call with kwargs like {"data_type": "str"}.
    """
    return "JSON"


data_type_sogo_to_mysql: dict[str, Any] = {
    "dict":     "JSON",
    "json":     "JSON",
    "str":      str_to_varchar,
    "list":     list_to_json,
    "serial":   "BIGINT AUTO_INCREMENT",
    "int8":     "SMALLINT",
    "bool":     "TINYINT(1)",
    "datetime": "DATETIME",
    "int":      "BIGINT",   # FK to serial (BIGINT AUTO_INCREMENT) in MySQL
    "text":     "MEDIUMTEXT",
    "tsvector": "MEDIUMTEXT",  # no tsvector type on MariaDB; full-text search uses a FULLTEXT index on TEXT
    "bytes":    "LONGBLOB",
}

data_type_mysql_to_sogo: dict[str, str] = {
    "json":       "dict",
    "varchar":    "str",
    "char":       "str",
    "text":       "text",
    "mediumtext": "text",
    "longtext":   "text",  # MariaDB uses LONGTEXT for JSON type
    "int":        "int",
    "integer":    "int",
    "bigint":     "int",
    "smallint":   "int8",
        "tinyint(1)": "bool",
    "datetime":   "datetime",
    "tinyint": "int",
    "longblob":   "bytes",
    "mediumblob": "bytes",
    "blob":       "bytes",
}


def table_to_query(table: Table) -> str:
    """
    Return the SQL string to create a table in MySQL
    """
    if not isinstance(table, Table):
        logger_sql.error("Try generate a table without the class Table")
        raise BugException(f": {__name__} Try generate a table without the class Table")

    sql_all_column: List[str] = []
    for column in table.columns:
        # Get mysql data type
        data_type = data_type_sogo_to_mysql[column.data_type]
        if isinstance(data_type, str):
            column_type = data_type
        elif callable(data_type):
            if column.extra_args is None:
                column_type = data_type()
            else:
                column_type = data_type(**column.extra_args)
        else:
            raise BugException("Invalid data type mapping for mysql")

        sql_column = f"`{column.name}` {column_type}"

        if not column.is_nullable:
            sql_column += " NOT NULL"
        else:
            # for testing clarity
            sql_column += " "

        if column.is_unique:
            sql_column += " UNIQUE"

        sql_all_column.append(sql_column)

    if table.primary_keys:
        pk = ", ".join(f"`{p}`" for p in table.primary_keys)
        sql_all_column.append(f"PRIMARY KEY ({pk})")

    sql_query = f"CREATE TABLE `{table.name}` ({', '.join(sql_all_column)}) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC"
    return sql_query


def _col_ref(name: str) -> str:
    """Build a backtick-quoted column reference, supporting qualified names (table.column).

    Each component is validated against REX_VALID_NAMES to prevent SQL injection.
    """
    parts: list[str] = name.split(".", 1) if "." in name else [name]
    for part in parts:
        if not re.match(REX_VALID_NAMES, part):
            raise BugException(f"Invalid column/table name component: {part}")
    if len(parts) == 2:
        return f"`{parts[0]}`.`{parts[1]}`"
    return f"`{parts[0]}`"


def _boolean_prefix(terms: list[str]) -> str:
    """Boolean-mode search string requiring each term as a prefix (joe -> +joe*)."""
    return " ".join(f"+{term}*" for term in terms)


def condition_to_query(condition: Condition, add_where: bool = False) -> Tuple[str, List[Any]]:  # pylint: disable=too-many-statements
    """
    Convert Condition objects into a SQL WHERE fragment and a list of parameter values.

    Returns: (sql_fragment, params)
    Example: ("WHERE (`col1` = %s AND `col2` != %s)", [val1, val2])
    """
    params: List[Any] = []

    if isinstance(condition, EqualCondition):
        sql_condition = f"{_col_ref(condition.param_name)} = %s"
        params.append(condition.param_value)
    elif isinstance(condition, NotEqualCondition):
        sql_condition = f"{_col_ref(condition.param_name)} != %s"
        params.append(condition.param_value)
    elif isinstance(condition, AndCondition):
        sql_condition = "("
        first = True
        for cond in condition.conditions:
            cond_sql, cond_params = condition_to_query(cond)
            if cond_sql.strip().upper().startswith("WHERE "):
                cond_sql = cond_sql.strip()[6:]
            if first:
                sql_condition += f"{cond_sql}"
                first = False
            else:
                sql_condition += f" AND {cond_sql}"
            params.extend(cond_params)
        sql_condition += ")"
    elif isinstance(condition, OrCondition):
        sql_condition = "("
        first = True
        for cond in condition.conditions:
            cond_sql, cond_params = condition_to_query(cond)
            if cond_sql.strip().upper().startswith("WHERE "):
                cond_sql = cond_sql.strip()[6:]
            if first:
                sql_condition += f"{cond_sql}"
                first = False
            else:
                sql_condition += f" OR {cond_sql}"
            params.extend(cond_params)
        sql_condition += ")"
    elif isinstance(condition, LessOrEqualCondition):
        sql_condition = f"{_col_ref(condition.param_name)} <= %s"
        params.append(condition.param_value)
    elif isinstance(condition, GreaterOrEqualCondition):
        sql_condition = f"{_col_ref(condition.param_name)} >= %s"
        params.append(condition.param_value)
    elif isinstance(condition, IsNullCondition):
        sql_condition = f"{_col_ref(condition.param_name)} IS NULL"
    elif isinstance(condition, IsNotNullCondition):
        sql_condition = f"{_col_ref(condition.param_name)} IS NOT NULL"
    elif isinstance(condition, LikeCondition):
        sql_condition = f"{_col_ref(condition.param_name)} LIKE %s"
        params.append(condition.pattern)
    elif isinstance(condition, FullTextCondition):
        terms = condition.terms()
        if not terms:
            sql_condition = "1 = 0"
        else:
            sql_condition = f"MATCH ({_col_ref(condition.param_name)}) AGAINST (%s IN BOOLEAN MODE)"
            params.append(_boolean_prefix(terms))
    elif isinstance(condition, TrueCondition):
        sql_condition = "1 = 1"
    else:
        logger_sql.error("Unknown Condition type %s", type(condition))
        raise BugException("Unknown Condition type")

    if add_where:
        sql_condition = "WHERE " + sql_condition

    return sql_condition, params


class ClientMySQL(ClientSQL):
    """
    MySQL implementation of ClientSQL
    """

    def __init__(self, db_user: str, db_pwd: str, db_host: str, db_port: int, db_ssl: bool, db_enc: str):
        """
        Init the MySQL client.
        
        :param db_ssl: If True, SSL connection will be used
        """
        self.db_user = db_user
        self.db_pwd = db_pwd
        self.db_host = db_host
        self.db_port = db_port
        self.db_ssl = db_ssl
        self.db_enc = db_enc
        self.safe_conn_string: str = f"mysql://SOGO_M_DB_USER:SOGO_M_DB_PWD@{db_host}:{db_port}/sogo?charset={db_enc}"
        self.db_conn: Any = None

    def _get_conn_config(self) -> dict:
        """Build connection config (not cached to avoid credential leakage in object inspection)."""
        config = {
            "user": self.db_user,
            "password": self.db_pwd,
            "host": self.db_host,
            "port": self.db_port,
            "database": "sogo",
            "connection_timeout": 5,
            "use_pure": True,
            "charset": self.db_enc,
        }
        # Enable SSL if configured - set ssl_disabled to False to enable SSL
        # MySQL Connector/Python enables SSL by default when server supports it,
        # but we can explicitly control it with ssl_disabled parameter
        if self.db_ssl:
            config["ssl_disabled"] = False
        else:
            config["ssl_disabled"] = True
        return config

    def connect(self) -> None:
        """
        Connect to the MySQL database and check if this is OK.
        """
        try:
            self.db_conn = mysql.connector.connect(**self._get_conn_config())
        except Error as e:
            logger.error("Cannot connect to %s reason: %s", self.safe_conn_string, repr(e))
            raise RequestException("MySQL database connection error") from e

    def get_table_info(self, table_name: str) -> dict | None:
        """
        Return None if the table was not found.
        If found, return a dict as {"column_name": "data_type", ...}
        """
        if not re.match(REX_VALID_NAMES, table_name):
            logger_sql.error("Trying to get a table info from an invalid table name: %s", table_name)
            raise BugException(f"Trying to get a table info from an invalid table name: {table_name}")

        if self.db_conn is None or not self.db_conn.is_connected():
            self.connect()

        ret: dict = {}
        sql_query = "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s"

        params = cast(Tuple[str, str], ("sogo", str(table_name)))

        logger_sql.info("QUERY COMMAND: %s -- params=%s", sql_query, params)

        if self.db_conn is not None:
            cursor = self.db_conn.cursor()
            try:
                cursor.execute(sql_query, params)
                all_record = cursor.fetchall()
                logger_sql.info("QUERY RESULT: %s", all_record)
            except Error as e:
                logger_sql.error("Error when fetching table info: %s", e)
                all_record = []
            finally:
                cursor.close()

            for col_name, data_type in all_record:
                data_type_lower = str(data_type).lower()
                ret[col_name] = data_type_mysql_to_sogo.get(data_type_lower, "str")

        return ret

    def create_table(self, table: Table) -> None:
        """
        Create a table in MySQL. Table should already be sql-exploit free (names validated).
        """
        if self.db_conn is None or not self.db_conn.is_connected():
            self.connect()

        sql_query = table_to_query(table)
        logger_sql.info("QUERY: %s", sql_query)

        if self.db_conn is not None:
            cursor = self.db_conn.cursor()
            try:
                cursor.execute(sql_query)
                self.db_conn.commit()
            except ProgrammingError as e:
                if "already exists" in str(e).lower():
                    logger_sql.warning("Attempted to create a table that already exist %s, the schema may be different", table.name)
                else:
                    logger_sql.error("Error when creating table %s: %s", table.name, e)
                    self.db_conn.rollback()
                    raise RequestException("Error when creating table") from e
            except Error as e:
                logger_sql.error("Error when creating table %s: %s", table.name, e)
                self.db_conn.rollback()
                raise RequestException("Error when creating table") from e
            finally:
                cursor.close()

    def create_indexes(self, table: Table) -> None:
        """Create all indexes defined on the table. Existing indexes are silently skipped."""
        if not table.index:
            return
        if self.db_conn is None or not self.db_conn.is_connected():
            self.connect()
        for idx in table.index:
            cols = ", ".join(f"`{c}`" for c in idx.columns)
            if idx.fulltext:
                sql_query = f"CREATE FULLTEXT INDEX `{idx.name}` ON `{table.name}` ({cols})"
            else:
                unique_kw = "UNIQUE " if idx.unique else ""
                sql_query = f"CREATE {unique_kw}INDEX `{idx.name}` ON `{table.name}` ({cols})"
            logger_sql.info("QUERY INDEX: %s", sql_query)
            if self.db_conn is not None:
                cursor = self.db_conn.cursor()
                try:
                    cursor.execute(sql_query)
                    self.db_conn.commit()
                except ProgrammingError as e:
                    if "duplicate" in str(e).lower() or "exists" in str(e).lower():
                        logger_sql.info("Index %s already exists on %s, skipping", idx.name, table.name)
                    else:
                        logger_sql.error("Error creating index %s on %s: %s", idx.name, table.name, e)
                except Error as e:
                    logger_sql.error("Error creating index %s on %s: %s", idx.name, table.name, e)
                finally:
                    cursor.close()

    def create_several_table(self, table_list: list[Table]) -> None:
        """
        Create several tables and their indexes
        """
        if self.db_conn is None or not self.db_conn.is_connected():
            self.connect()

        for table in table_list:
            self.create_table(table)
            self.create_indexes(table)

    @db_op("insert_in_table")
    def insert_in_table(self, table_name: str, column_tuple: tuple[str, ...], values_tuple: list[list[Any]]) -> int:
        """
        Insert one or more rows into a table
        """
        ret = 0
        if self.db_conn is None or not self.db_conn.is_connected():
            self.connect()

        insert_len = len(column_tuple)
        sql_all_values: List[Any] = []
        placeholders_per_row = "(" + ", ".join(["%s"] * insert_len) + ")"
        sql_all_placeholder = []

        for values in values_tuple:
            if (value_len := len(values)) != insert_len:
                logger_sql.error("Try to insert more or less data than the columns. Column size: %s, data_size: %s", insert_len, value_len)
                raise BugException(f"Try to insert more or less data than the columns. Column size: {insert_len}, data_size: {value_len}")
            for idx, value in enumerate(values):
                if isinstance(value, FullTextValue):
                    values[idx] = value.text
                elif isinstance(value, dict) or isinstance(value, list):
                    values[idx] = json.dumps(value)
                else:
                    values[idx] = _mysql_datetime(value)
            sql_all_placeholder.append(placeholders_per_row)
            sql_all_values.extend(values)

        columns_sql = ", ".join(f"`{c}`" for c in column_tuple)
        sql_query = f"INSERT INTO `{table_name}` ({columns_sql}) VALUES {', '.join(sql_all_placeholder)}"

        logger_sql.info("QUERY COMMAND: %s -- params=%s", sql_query, sql_all_values)

        if self.db_conn is not None:
            cursor = self.db_conn.cursor()
            try:
                cursor.execute(sql_query, tuple(sql_all_values))
                ret = cursor.rowcount or 0
                if ret == 0:
                    logger_sql.info("QUERY RESULT: None inserted")
                else:
                    logger_sql.info("QUERY RESULT: inserted %s rows", ret)
                self.db_conn.commit()
            except Error as e:
                logger_sql.error("Error (%s) when inserting table %s: %s", type(e), table_name, e)
                self.db_conn.rollback()
            finally:
                cursor.close()

        return ret

    @db_op("update_in_table")
    def update_in_table(self, table_name: str, column_tuple: tuple, values_list: list, condition: Condition) -> int:
        """
        Update rows in a table
        """
        ret = 0
        if self.db_conn is None or not self.db_conn.is_connected():
            self.connect()

        # Check column len and values len
        insert_len = len(column_tuple)
        if (value_len := len(values_list)) != insert_len:
            logger_sql.error("Try to update more or less data than the specified columns. Column size: %s, data_size: %s", insert_len, value_len)
            raise BugException(f"Try to update more or less data than the specified columns. Column size: {insert_len}, data_size: {value_len}")

        # Prepare set expressions and convert dict/list to json strings
        set_parts = []
        params: List[Any] = []
        for idx, col in enumerate(column_tuple):
            val = values_list[idx]
            if isinstance(val, FullTextValue):
                val = val.text
            elif isinstance(val, dict) or isinstance(val, list):
                val = json.dumps(val)
            else:
                val = _mysql_datetime(val)
            set_parts.append(f"`{col}` = %s")
            params.append(val)

        cond_sql, cond_params = condition_to_query(condition, add_where=True)
        params.extend(cond_params)

        # Create and execute the query
        sql_query = f"UPDATE `{table_name}` SET {', '.join(set_parts)} {cond_sql}"

        if self.db_conn is not None:
            logger_sql.info("QUERY COMMAND: %s -- params=%s", sql_query, params)
            cursor = self.db_conn.cursor()
            try:
                cursor.execute(sql_query, tuple(params))
                ret = cursor.rowcount or 0
                if ret == 0:
                    logger_sql.info("QUERY RESULT: None updated")
                else:
                    logger_sql.info("QUERY RESULT: updated %s rows", ret)
                self.db_conn.commit()
            except Error as e:
                logger_sql.error("Error (%s) when updating table %s: %s", type(e), table_name, e)
                self.db_conn.rollback()
            finally:
                cursor.close()

        return ret

    @db_op("select_from_table")
    def select_from_table(self, table_name: str, column_tuple: tuple[str, ...], condition: Condition,
                          offset: int = 0, limit: int = 0,
                          sort_by: str | None = None, order: Order = Order.ASC,
                          rank_by: FullTextCondition | None = None) -> Generator[tuple[Any, ...], None, None]:
        """
        Select values from a table under conditions

        offset = 0 means no offset
        limit = 0 means no limit (all rows)

        :param table_name: Name of the table
        :type table_name: str
        :param column_tuple: Tuple of the column name to select
        :type column_tuple: tuple[str, ...]
        :param condition: Condition on the query
        :type condition: Condition
        :param offset: Number of rows to skip, defaults to 0
        :type offset: int
        :param limit: Maximum number of rows to return, defaults to 0 (no limit)
        :type limit: int
        :param sort_by: Column name to sort by, defaults to None
        :type sort_by: str | None
        :param order: Sort direction (ASC or DESC), defaults to Order.ASC
        :type order: Order
        :yield: A generator, each item is a tuple with the values corresponding to the column_tuple param
        :rtype: Generator[tuple[Any, ...], None, None]
        """
        if self.db_conn is None or not self.db_conn.is_connected():
            self.connect()
        if len(column_tuple) == 0:
            columns_sql = "*"
        else:
            if len(column_tuple) == 1 and column_tuple[0] == "*":
                columns_sql = "*"
            else:
                columns_sql = ", ".join(f"`{c}`" for c in column_tuple)

        cond_sql, params = condition_to_query(condition, add_where=True)

        # Build ORDER BY clause. rank_by (full-text relevance) takes precedence; sort_by is
        # kept as a secondary, stable tiebreaker. The rank placeholder is appended after the
        # WHERE params since ORDER BY follows WHERE in the statement.
        order_terms = []
        if rank_by is not None:
            rank_terms = rank_by.terms()
            if rank_terms:
                order_terms.append(f"MATCH ({_col_ref(rank_by.param_name)}) AGAINST (%s IN BOOLEAN MODE) DESC")
                params.append(_boolean_prefix(rank_terms))
        if sort_by:
            order_terms.append(f"{_col_ref(sort_by)} {'ASC' if order == Order.ASC else 'DESC'}")
        order_clause = f" ORDER BY {', '.join(order_terms)}" if order_terms else ""

        # Build LIMIT and OFFSET clauses
        # Validate that limit and offset are integers to prevent SQL injection
        if not isinstance(limit, int) or limit < 0:
            raise BugException(f"Invalid limit value: {limit}. Must be non-negative integer", err.ERROR_INVALID_LIMIT)
        if not isinstance(offset, int) or offset < 0:
            raise BugException(f"Invalid offset value: {offset}. Must be non-negative integer", err.ERROR_INVALID_OFFSET)
        
        limit_clause = ""
        if limit > 0:
            limit_clause = f" LIMIT {limit}"

        offset_clause = ""
        if offset > 0:
            offset_clause = f" OFFSET {offset}"

        sql_query = f"SELECT {columns_sql} FROM `{table_name}` {cond_sql}{order_clause}{limit_clause}{offset_clause}"

        logger_sql.info("QUERY COMMAND: %s -- params=%s", sql_query, params)

        if self.db_conn is not None:
            cursor = self.db_conn.cursor()
            try:
                cursor.execute(sql_query, tuple(params))
                rows_fetched = cursor.rowcount
                col_names = [d[0] for d in cursor.description] if cursor.description else []
                json_cols = _json_column_types()
                if rows_fetched == 0:
                    logger_sql.info("QUERY RESULT: empty")
                else:
                    logger_sql.info("QUERY RESULT: fetch %s rows", rows_fetched)
                while True:
                    record = cursor.fetchone()
                    if record is None:
                        break
                    yield tuple(_maybe_json_decode(v, n, json_cols) for n, v in zip(col_names, record))
            except Error as e:
                logger_sql.error("Error when selecting table %s: %s", table_name, e)
            finally:
                cursor.close()

    @db_op("select_from_several_table")
    def select_from_several_table(  # pylint: disable=too-many-locals
        self,
        table_name: str,
        joins: list[JoinClause],
        column_tuple: tuple[str, ...],
        condition: Condition,
        sort_by: str | None = None,
        order: Order = Order.ASC,
        limit: int = 0,
    ) -> Generator[tuple[Any, ...], None, None]:
        """Select values from several tables using INNER JOIN.

        Column names and condition param_names may be qualified (table.column).
        """
        if self.db_conn is None or not self.db_conn.is_connected():
            self.connect()

        join_parts: list[str] = []
        for j in joins:
            if not re.match(REX_VALID_NAMES, j.table):
                raise BugException(f"Invalid JOIN table name: {j.table}")
            join_parts.append(f" INNER JOIN `{j.table}` ON {_col_ref(j.left_col)} = {_col_ref(j.right_col)}")

        cond_sql, params = condition_to_query(condition, add_where=True)
        order_clause = f" ORDER BY {_col_ref(sort_by)} {'ASC' if order == Order.ASC else 'DESC'}" if sort_by else ""
        limit_clause = f" LIMIT {limit}" if limit > 0 else ""

        sql_query = (f"SELECT {', '.join(_col_ref(c) for c in column_tuple)} "
                     f"FROM `{table_name}`{''.join(join_parts)} {cond_sql}{order_clause}{limit_clause}")

        logger_sql.info("QUERY JOIN: %s -- params=%s", sql_query, params)

        if self.db_conn is not None:
            cursor = self.db_conn.cursor()
            try:
                cursor.execute(sql_query, tuple(params))
                col_names = [d[0].split(".")[-1] for d in cursor.description] if cursor.description else []
                json_cols = _json_column_types()
                if cursor.rowcount == 0:
                    logger_sql.info("QUERY JOIN RESULT: empty")
                else:
                    logger_sql.info("QUERY JOIN RESULT: fetch %s rows", cursor.rowcount)
                while True:
                    record = cursor.fetchone()
                    if record is None:
                        break
                    yield tuple(_maybe_json_decode(v, n, json_cols) for n, v in zip(col_names, record))
            except Error as e:
                logger_sql.error("Error in select_from_several_table: %s", e)
            finally:
                cursor.close()

    @db_op("count_row_in_table")
    def count_row_in_table(self, table_name: str, condition: Condition, column_name: str = "*") -> int:
        """
        Count rows in a table under conditions

        :param table_name: Name of the table
        :type table_name: str
        :param condition: Condition on the query
        :type condition: Condition
        :param column_name: Name of the column, or "*" by default
        :type column_name: str
        :return: A number indicates the number of rows of the result
        :rtype: int
        """
        if self.db_conn is None or not self.db_conn.is_connected():
            self.connect()

        if column_name == "*":
            count_query = "COUNT(*)"
        else:
            count_query = f"COUNT(`{column_name}`)"

        cond_sql, params = condition_to_query(condition, add_where=True)
        sql_query = f"SELECT {count_query} FROM `{table_name}` {cond_sql}"

        logger_sql.info("QUERY COMMAND: %s -- params=%s", sql_query, params)

        count_ret = 0
        if self.db_conn is not None:
            cursor = self.db_conn.cursor()
            try:
                cursor.execute(sql_query, tuple(params))
                record = cursor.fetchone()
                if record:
                    count_ret = record[0]
                logger_sql.info("QUERY RESULT: COUNT: %s rows", count_ret)
            except Error as e:
                logger_sql.error("Error when counting rows in table %s: %s", table_name, e)
            finally:
                cursor.close()

        return count_ret

    @db_op("delete_row_in_table")
    def delete_row_in_table(self, table_name: str, condition: Condition, expected_row: int = 0) -> int:
        """
        Delete rows in a table.

        Condition cannot be of type TrueCondition

        Set expected_row to a value greater than 0 to check beforehand with a COUNT if your condition
        returns the expected number of rows. 0 or negative values will not trigger any check.

        Example:
        If you're sure that only one row will be deleted, set expected_row=1 and this method
        will check before the delete query if, indeed, only 1 row will be deleted.

        :param table_name: Name of the table
        :type table_name: str
        :param condition: Condition for the query
        :type condition: Condition
        :param expected_row: Expected number of rows to be deleted, defaults to 0
        :type expected_row: int, optional
        :raises BugException: raise if the condition is of type TrueCondition
        :raises RequestException: raise if the expected number of rows doesn't match
        :return: number of rows deleted
        :rtype: int
        """
        if isinstance(condition, TrueCondition):
            raise BugException("Condition for delete query is always True", err.ERROR_QUERY_DELETION_CONDITION)

        if self.db_conn is None or not self.db_conn.is_connected():
            self.connect()

        if expected_row > 0:
            # First count the rows to be deleted and check if it matches
            row_affected = self.count_row_in_table(table_name, condition)
            if expected_row != row_affected:
                raise RequestException(f"Expected number of row deleted is different! expected: {expected_row}, real {row_affected}", err.ERROR_QUERY_DELETION_ROWS)

        cond_sql, params = condition_to_query(condition, add_where=True)
        sql_query = f"DELETE FROM `{table_name}` {cond_sql}"

        logger_sql.info("QUERY COMMAND: %s -- params=%s", sql_query, params)

        count_ret = 0
        if self.db_conn is not None:
            cursor = self.db_conn.cursor()
            try:
                cursor.execute(sql_query, tuple(params))
                count_ret = cursor.rowcount or 0
                if count_ret == 0:
                    logger_sql.info("QUERY RESULT: None deleted")
                else:
                    logger_sql.info("QUERY RESULT: deleted %s rows", count_ret)
                self.db_conn.commit()
            except Error as e:
                logger_sql.error("Error when deleting rows from table %s: %s", table_name, e)
                self.db_conn.rollback()
            finally:
                cursor.close()

        return count_ret

    def close(self) -> None:
        """
        Close the connection to the database 
        """
        if self.db_conn is not None and self.db_conn.is_connected():
            try:
                self.db_conn.close()
            except Error as e:
                logger_sql.error("Error while closing mysql connection: %s", e)
