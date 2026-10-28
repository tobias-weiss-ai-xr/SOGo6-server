"""Tests for the PostgreSQL-backed user source (single relational DB, no LDAP).

Covers password verification (bcrypt / pbkdf2-sha256 / {scheme} prefixes) and
``check_login`` against the small ``users`` table living in the same database
the SOGo6 server already uses (SOGO_P_DB_*, db "sogo").
"""
from __future__ import annotations

from unittest import mock

from app.config.settings.DomainSettings import UserSourceSettingsObj
from app.manager.user_source.ClientPostgreSQLUserSource import (
    ClientPostgreSQLUserSource,
    DEFAULT_USERS_TABLE,
    verify_password,
    _scheme,
)
from app.utils.db.Condition import AndCondition, EqualCondition


def make_client(**overrides) -> ClientPostgreSQLUserSource:
    defaults = dict(
        db_user="sogo",
        db_pwd="pw",
        db_host="127.0.0.1",
        db_port=5432,
        db_ssl=False,
        db_enc="utf8",
    )
    defaults.update(overrides)
    return ClientPostgreSQLUserSource(**defaults)


USER_COLUMNS = {"uid", "cn", "mail", "domain", "password", "enabled"}


def _sel_from(named_rows: list[dict]) -> mock.Mock:
    """select_from_table stand-in: returns rows ordered by the requested columns."""
    def _sel(table, col_tuple, condition, **kwargs):
        return iter([tuple(r[c] for c in col_tuple) for r in named_rows])

    return mock.Mock(side_effect=_sel)


# ── password verification ────────────────────────────────────────────────
class TestPasswordVerify:
    def test_bcrypt_roundtrip(self):
        import bcrypt

        h = bcrypt.hashpw(b"geheim123", bcrypt.gensalt()).decode()
        assert verify_password("geheim123", h)            # bare bcrypt (legacy)
        assert verify_password("geheim123", f"{{bcrypt}}{h}")

    def test_pbkdf2_sha256_roundtrip(self):
        import base64
        import hashlib

        salt = base64.b64encode(b"0123456789abcdef")
        digest = base64.b64encode(
            hashlib.pbkdf2_hmac("sha256", b"s3cret", b"0123456789abcdef", 100_000)
        )
        stored = f"{{pbkdf2-sha256}}100000${salt.decode()}${digest.decode()}"
        assert verify_password("s3cret", stored)
        assert not verify_password("wrong", stored)

    def test_wrong_password_false(self):
        import bcrypt

        h = bcrypt.hashpw(b"geheim123", bcrypt.gensalt()).decode()
        assert not verify_password("falsch", h)

    def test_empty_or_unknown_scheme_fail_closed(self):
        assert not verify_password("", "irrelevant")
        assert not verify_password("x", "")
        assert not verify_password("x", "{sha1}abcdef")             # unsupported
        assert not verify_password("x", "{bcrypt}not-a-real-hash")  # malformed
        assert not verify_password("x", "{pbkdf2-sha256}oops")      # malformed

    def test_scheme_split(self):
        assert _scheme("{bcrypt}abc") == ("bcrypt", "abc")
        assert _scheme("abc") == ("", "abc")


# ── check_login against the users table ──────────────────────────────────
def _client_with_rows(rows: list[dict], domain_field: str = ""):
    client = make_client(domain_field=domain_field)
    client.connect = mock.Mock()
    client.get_table_info = mock.Mock(return_value={c: "text" for c in USER_COLUMNS})
    client.select_from_table = _sel_from(rows)
    return client


def _stored_pbkdf2(password: str) -> str:
    import base64
    import hashlib

    salt = base64.b64encode(b"0123456789abcdef")
    digest = base64.b64encode(
        hashlib.pbkdf2_hmac("sha256", password.encode(), b"0123456789abcdef", 100_000)
    ).decode()
    return f"{{pbkdf2-sha256}}100000${salt.decode()}${digest}"


class TestCheckLogin:
    def test_success_returns_contact_tuple(self):
        client = _client_with_rows([{
            "uid": "ada", "cn": "Ada Demo", "mail": "ada@opensme.home",
            "domain": "opensme.home", "password": _stored_pbkdf2("geheim123"), "enabled": True,
        }])
        ok, policy, contact = client.check_login("ada", "geheim123", "opensme.home")
        assert ok is True
        assert policy == {}
        assert contact["cn"] == ["Ada Demo"]
        assert contact["mail"] == ["ada@opensme.home"]

    def test_unknown_uid_false(self):
        client = _client_with_rows([])
        ok, *_ = client.check_login("nobody", "x", "opensme.home")
        assert ok is False

    def test_wrong_password_false(self):
        client = _client_with_rows([{
            "uid": "ada", "cn": "Ada", "mail": "ada@example", "domain": "opensme.home",
            "password": "{bcrypt}whatever", "enabled": True,
        }])
        ok, *_ = client.check_login("ada", "falsch", "opensme.home")
        assert ok is False
    def test_multiple_rows_false(self):
        client = _client_with_rows([
            {"uid": "ada", "cn": "A", "mail": "a@example", "domain": "opensme.home",
             "password": "{bcrypt}x", "enabled": True},
            {"uid": "ada", "cn": "B", "mail": "b@example", "domain": "opensme.home",
             "password": "{bcrypt}y", "enabled": True},
        ])
        ok, *_ = client.check_login("ada", "x", "opensme.home")
        assert ok is False

    def test_disabled_user_false(self):
        client = _client_with_rows([{
            "uid": "ada", "cn": "Ada", "mail": "ada@example", "domain": "opensme.home",
            "password": "{bcrypt}x", "enabled": False,
        }])
        ok, *_ = client.check_login("ada", "x", "opensme.home")
        assert ok is False

    def test_table_missing_fails_closed(self):
        client = make_client()
        client.connect = mock.Mock()
        client.get_table_info = mock.Mock(return_value=None)
        client.select_from_table = mock.Mock()
        ok, *_ = client.check_login("ada", "x", "opensme.home")
        assert ok is False

    def test_domain_filter_adds_condition(self):
        client = make_client(domain_field="domain")
        client.connect = mock.Mock()
        client.get_table_info = mock.Mock(return_value={c: "text" for c in USER_COLUMNS})
        client.select_from_table = mock.Mock(return_value=iter([]))
        client.check_login("ada", "x", "opensme.home")
        _table, _cols, condition = client.select_from_table.call_args.args[:3]
        assert isinstance(condition, AndCondition)
        assert condition.conditions[0].param_name == "uid"
        assert condition.conditions[0].param_value == "ada"
        assert condition.conditions[1].param_name == "domain"
        assert condition.conditions[1].param_value == "opensme.home"

    def test_defaults_match_users_table(self):
        assert DEFAULT_USERS_TABLE == "users"
        assert make_client().table == "users"
        assert make_client().uid_field == "uid"
        assert make_client().cn_field == "cn"
        assert make_client().mail_fields == ["mail"]
        assert make_client().password_field == "password"

    def test_ensure_users_table_runs_idempotent_ddl(self):
        client = make_client()
        conn = mock.Mock()
        conn.closed = False
        client.db_conn = conn
        client.ensure_users_table()
        conn.execute.assert_called_once()
        assert "CREATE TABLE IF NOT EXISTS users" in conn.execute.call_args[0][0]
        conn.commit.assert_called_once()


# ── settings mapping (get_user_source_settings → module_args) ────────────
class TestSettingsMapping:
    @staticmethod
    def _patch_process_db(monkeypatch):
        """Point DomainSettings.process_config at a fake DB-settings holder."""
        from types import SimpleNamespace

        from app.config.settings import DomainSettings as DomainSettingsModule

        fake_db = {
            "db_user": "sogo", "db_pwd": "pw", "db_host": "sogo-db",
            "db_port": 5432, "db_name": "sogo", "db_ssl": False, "db_enc": "utf8",
        }
        monkeypatch.setattr(
            DomainSettingsModule, "process_config",
            SimpleNamespace(get_db_settings=lambda: fake_db),
        )

    def test_postgresql_fallback_carries_auth_mapping(self, monkeypatch):
        self._patch_process_db(monkeypatch)
        settings = UserSourceSettingsObj({
            "US_NAME": "users-table",
            "US_TYPE": "postgresql",
            "US_CAN_AUTH": True,
            "US_MAIL": ["mail"],
            "US_PWD_ALGO": "bcrypt",
            "US_SQL_PREPEND_PWD_SCHEME": True,
        })
        args = settings.get_user_source_settings("postgresql")
        # single-DB: same database, plus the users-table mapping
        assert args["db_user"] == "sogo"
        assert args["db_host"] == "sogo-db"
        assert args["table"] == "users"
        assert args["uid_field"] == "uid"
        assert args["mail_fields"] == ["mail"]
        assert args["pwd_algo"] == "bcrypt"
        assert args["prepend_pwd_scheme"] is True

    @mock.patch.dict("os.environ", {}, clear=False)
    def test_postgresql_url_parses_and_carries_mapping(self):
        settings = UserSourceSettingsObj({
            "US_NAME": "url-table",
            "US_TYPE": "postgresql",
            "US_CAN_AUTH": True,
            "US_SQL_USER_URL": "postgresql://us:pw@dbhost:5433/sogo",
            "US_SQL_DOMAIN_FIELD": "domain",
        })
        args = settings.get_user_source_settings("postgresql")
        assert args["db_user"] == "us"
        assert args["db_host"] == "dbhost"
        assert args["db_port"] == 5433
        assert args["domain_field"] == "domain"
