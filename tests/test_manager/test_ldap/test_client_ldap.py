# pylint: disable=invalid-sequence-index
"""Unit tests for ClientLdap (23% -> high).

Covers filter building, escaping, record parsing, connect/bind/search/close
flows and all error branches using a fake LDAP connection.
"""
from __future__ import annotations

import os

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.manager.ldap.ClientLdap import (
    ClientLdap,
    condition_to_filter,
    ldap_escape,
    parse_python_ldap_record,
)
from app.utils import errors as err
from app.utils import exceptions as exc
from app.utils.db import Condition


def make_client(**overrides):
    kwargs = dict(
        ldap_host="ldap.example.org",
        ldap_port=389,
        ldap_enc="None",
        ldap_bind_dn="cn=admin,dc=example,dc=org",
        ldap_bind_pwd="adminpw",
        ldap_base_dn="dc=example,dc=org",
        ldap_scope="SUB",
        ldap_uid="uid",
        ldap_id="uid",
        ldap_cn="cn",
        ldap_mails=["mail"],
    )
    kwargs.update(overrides)
    return ClientLdap(**kwargs)


def make_conn():
    conn = MagicMock()
    conn.simple_bind_s.return_value = "bind-result"
    conn.search_s.return_value = [
        ("uid=alice,dc=example,dc=org", {"uid": [b"alice"], "mail": [b"alice@example.org"]})
    ]
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# ldap_escape
# ─────────────────────────────────────────────────────────────────────────────

class TestLdapEscape:
    def test_int_passthrough(self):
        assert ldap_escape(42) == 42

    def test_datetime_to_timestamp(self):
        d = datetime(2024, 1, 1, 0, 0, 0)
        assert ldap_escape(d) == int(d.timestamp())

    def test_string_escaped(self):
        assert ldap_escape("a(b)c") == "a\\28b\\29c"

    def test_wildcard_restored(self):
        assert ldap_escape("a*b", with_wildcard=True) == "a*b"


# ─────────────────────────────────────────────────────────────────────────────
# condition_to_filter
# ─────────────────────────────────────────────────────────────────────────────

class TestConditionToFilter:
    def test_equal(self):
        c = Condition.EqualCondition("uid", "alice")
        assert condition_to_filter(c) == "(uid=alice)"

    def test_not_equal(self):
        c = Condition.NotEqualCondition("uid", "alice")
        assert condition_to_filter(c) == "(uid!=alice)"

    def test_less_or_equal(self):
        c = Condition.LessOrEqualCondition("age", "30")
        assert condition_to_filter(c) == "(age<=30)"

    def test_greater_or_equal(self):
        c = Condition.GreaterOrEqualCondition("age", "18")
        assert condition_to_filter(c) == "(age>=18)"

    def test_and(self):
        c = Condition.AndCondition(
            Condition.EqualCondition("uid", "a"),
            Condition.EqualCondition("mail", "x"),
        )
        assert condition_to_filter(c) == "(&(uid=a)(mail=x))"

    def test_or(self):
        c = Condition.OrCondition(
            Condition.EqualCondition("uid", "a"),
            Condition.EqualCondition("uid", "b"),
        )
        assert condition_to_filter(c) == "(|(uid=a)(uid=b))"

    def test_nested(self):
        c = Condition.OrCondition(
            Condition.AndCondition(
                Condition.EqualCondition("a", "1"),
                Condition.EqualCondition("b", "2"),
            ),
            Condition.EqualCondition("c", "3"),
        )
        assert condition_to_filter(c) == "(|(&(a=1)(b=2))(c=3))"

    def test_unknown_condition_raises_bug(self):
        class FakeCond:
            pass

        with pytest.raises(exc.BugException):
            condition_to_filter(FakeCond())


# ─────────────────────────────────────────────────────────────────────────────
# parse_python_ldap_record
# ─────────────────────────────────────────────────────────────────────────────

class TestParseRecord:
    def test_parses_bytes_to_str(self):
        record = ("uid=x,dc=example,dc=org", {"uid": [b"x"], "mail": [b"a@b.c", b"d@e.f"]})
        out = parse_python_ldap_record(record)
        assert out == {
            "uid": ["x"],
            "mail": ["a@b.c", "d@e.f"],
            "dn": ["uid=x,dc=example,dc=org"],
        }


# ─────────────────────────────────────────────────────────────────────────────
# __init__
# ─────────────────────────────────────────────────────────────────────────────

class TestInit:
    def test_fields_set(self):
        c = make_client(ldap_enc="None")
        assert c.host == "ldap.example.org"
        assert c.port == 389
        assert c.bind_dn == "cn=admin,dc=example,dc=org"
        assert c.base_dn == "dc=example,dc=org"
        assert c.ldap_main_mail == "mail"
        assert c.binded is False
        assert c.filter is None

    def test_filter_condition_converted(self):
        c = make_client(ldap_filter=Condition.EqualCondition("objectClass", "person"))
        assert c.filter == "(objectClass=person)"

    def test_invalid_scope_key(self):
        with pytest.raises(KeyError):
            make_client(ldap_scope="bogus")


# ─────────────────────────────────────────────────────────────────────────────
# connect
# ─────────────────────────────────────────────────────────────────────────────

class TestConnect:
    @patch("app.manager.ldap.ClientLdap.ldap")
    def test_plain_connect(self, l):
        c = make_client(ldap_enc="None")
        c.connect()
        l.initialize.assert_called_once_with("ldap://ldap.example.org:389", trace_level=0)
        assert c.connected is True
        assert c.ldap_conn is not None
        l.initialize.return_value.start_tls_s.assert_not_called()

    @patch("app.manager.ldap.ClientLdap.ldap")
    def test_implicit_tls_uri(self, l):
        c = make_client(ldap_enc="SSL/TLS")
        c.connect()
        l.initialize.assert_called_once_with("ldaps://ldap.example.org:389", trace_level=0)
        # TLS cert option set
        l.initialize.return_value.set_option.assert_called()

    @patch("app.manager.ldap.ClientLdap.ldap")
    def test_explicit_tls_starts_tls(self, l):
        c = make_client(ldap_enc="StartTLS")
        c.connect()
        l.initialize.return_value.set_option.assert_called()
        l.initialize.return_value.start_tls_s.assert_called_once()
        l.initialize.return_value.start_tls_s.return_value = None

    @patch("ldap.initialize")
    def test_verbose_trace_level(self, init):
        import logging

        from app.manager.ldap.ClientLdap import logger_ldap

        old = logger_ldap.level
        logger_ldap.setLevel(logging.INFO)
        try:
            c = make_client(ldap_enc="None")
            c.connect()
            init.assert_called_once_with("ldap://ldap.example.org:389", trace_level=2)
        finally:
            logger_ldap.setLevel(old)

    @patch("ldap.initialize")
    def test_connect_error_raises_request(self, init):
        class FakeLDAPError(Exception):
            pass

        init.side_effect = FakeLDAPError("boom")
        c = make_client()
        with patch("app.manager.ldap.ClientLdap.ldap.LDAPError", FakeLDAPError):
            with pytest.raises(exc.RequestException) as e:
                c.connect()
        assert e.value.error.c == err.ERROR_LDAP_CANNOT_CONNECT.c


# ─────────────────────────────────────────────────────────────────────────────
# _bind
# ─────────────────────────────────────────────────────────────────────────────

class TestBind:
    def test_invalid_dn_format_raises(self):
        c = make_client()
        with pytest.raises(exc.RequestException) as e:
            c._bind("not a dn", "pw")
        assert e.value.error.c == err.ERROR_LDAP_BIND_WRONG_CRED.c

    def test_success(self):
        c = make_client()
        c.ldap_conn = MagicMock()
        c.ldap_conn.simple_bind_s.return_value = "ok"
        ok, ret = c._bind("cn=admin,dc=example,dc=org", "pw")
        assert ok is True
        assert ret == "ok"
        assert c.binded is True

    def test_invalid_credentials_throw(self):
        from ldap import INVALID_CREDENTIALS

        c = make_client()
        c.ldap_conn = MagicMock()
        c.ldap_conn.simple_bind_s.side_effect = INVALID_CREDENTIALS("bad")
        with pytest.raises(exc.RequestException) as e:
            c._bind("cn=admin,dc=example,dc=org", "pw")
        assert e.value.error.c == err.ERROR_LDAP_BIND_WRONG_CRED.c

    def test_invalid_credentials_no_throw(self):
        from ldap import INVALID_CREDENTIALS

        c = make_client()
        c.ldap_conn = MagicMock()
        c.ldap_conn.simple_bind_s.side_effect = INVALID_CREDENTIALS("bad")
        ok, ret = c._bind("cn=admin,dc=example,dc=org", "pw", throw_error=False)
        assert ok is False
        assert ret == {}

    def test_other_ldap_error(self):
        from ldap import LDAPError

        c = make_client()
        c.ldap_conn = MagicMock()
        c.ldap_conn.simple_bind_s.side_effect = LDAPError("server down")
        with pytest.raises(exc.RequestException) as e:
            c._bind("cn=admin,dc=example,dc=org", "pw")
        assert e.value.error.c == err.ERROR_LDAP_CANNOT_BIND.c

    def test_no_connection_raises_bug(self):
        c = make_client()
        with pytest.raises(exc.BugException):
            c._bind("cn=admin,dc=example,dc=org", "pw")

    def test_pwd_policy_control_added(self):
        c = make_client(ldap_pwd_policy=True)
        c.ldap_conn = MagicMock()
        ok, _ = c._bind("cn=admin,dc=example,dc=org", "pw", use_admin=False)
        assert ok is True
        # serverctrls passed with ppolicy control
        call_kwargs = c.ldap_conn.simple_bind_s.call_args.kwargs
        assert call_kwargs.get("serverctrls") is not None

    def test_pwd_policy_admin_no_control(self):
        c = make_client(ldap_pwd_policy=True)
        c.ldap_conn = MagicMock()
        c._bind("cn=admin,dc=example,dc=org", "pw", use_admin=True)
        call_kwargs = c.ldap_conn.simple_bind_s.call_args.kwargs
        assert call_kwargs.get("serverctrls") is None


# ─────────────────────────────────────────────────────────────────────────────
# _get_base_dn
# ─────────────────────────────────────────────────────────────────────────────

class TestGetBaseDn:
    def test_requires_connection(self):
        c = make_client()
        with pytest.raises(exc.BugException):
            c._get_base_dn("alice", "example.org")

    def test_default_builds_dn(self):
        c = make_client()
        c.connected = True
        c.ldap_conn = MagicMock()
        dn = c._get_base_dn("alice", "example.org")
        assert dn == "uid=alice,dc=example,dc=org"

    def test_domain_substitution(self):
        c = make_client(ldap_base_dn="dc=%d,dc=org")
        c.connected = True
        c.ldap_conn = MagicMock()
        dn = c._get_base_dn("alice", "example.org")
        assert dn == "uid=alice,dc=example.org,dc=org"

    def test_bind_fields_search(self):
        c = make_client(ldap_bind_fields=["uid", "mail"])
        c.connected = True
        c.ldap_conn = MagicMock()
        c._search_dn = MagicMock(return_value=[("uid=alice,dc=example,dc=org", {"dn": []})])
        c._bind = MagicMock(return_value=(True, "x"))
        dn = c._get_base_dn("alice", "example.org")
        assert c._bind.called
        # filter combines bind fields OR with (uid=alice)(mail=alice)
        assert "(|(uid=alice)(mail=alice))" in c._search_dn.call_args[0][1]

    def test_bind_fields_combines_additional_filter(self):
        c = make_client(
            ldap_bind_fields=["uid", "mail"],
            ldap_filter=Condition.EqualCondition("objectClass", "person"),
        )
        c.connected = True
        c.ldap_conn = MagicMock()
        c._search_dn = MagicMock(return_value=[("uid=alice,dc=example,dc=org", {"dn": []})])
        c._bind = MagicMock(return_value=(True, "x"))
        c._get_base_dn("alice", "example.org")
        f = c._search_dn.call_args[0][1]
        assert f == "(&(|(uid=alice)(mail=alice))(objectClass=person))"


# ─────────────────────────────────────────────────────────────────────────────
# check_login
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckLogin:
    def test_wrong_password(self):
        c = make_client()
        c._get_base_dn = MagicMock(return_value="uid=alice,dc=example,dc=org")
        c._bind = MagicMock(return_value=(False, {}))
        ok, _, contact = c.check_login("alice", "wrong", "example.org")
        assert ok is False
        assert contact == {}

    def test_success_returns_contact(self):
        c = make_client()
        c._get_base_dn = MagicMock(return_value="uid=alice,dc=example,dc=org")
        c._bind = MagicMock(return_value=(True, "ok"))
        c._search = MagicMock(return_value=[
            ("uid=alice,dc=example,dc=org", {"uid": [b"alice"], "mail": [b"a@b.c"]})
        ])
        ok, _, contact = c.check_login("alice", "pw", "example.org")
        assert ok is True
        assert contact["uid"] == ["alice"]

    def test_bind_as_user_skips_admin_rebind(self):
        c = make_client(ldap_bind_as_user=True)
        c._get_base_dn = MagicMock(return_value="uid=alice,dc=example,dc=org")
        c._bind = MagicMock(return_value=(True, "ok"))
        c._search = MagicMock(return_value=[
            ("uid=alice,dc=example,dc=org", {"uid": [b"alice"]})
        ])
        ok, _, _ = c.check_login("alice", "pw", "example.org")
        assert ok is True
        # only one bind
        assert c._bind.call_count == 1

    def test_no_records_raises_bug(self):
        c = make_client()
        c._get_base_dn = MagicMock(return_value="uid=x,dc=example,dc=org")
        c._bind = MagicMock(return_value=(True, "ok"))
        c._search = MagicMock(return_value=[])
        with pytest.raises(exc.BugException):
            c.check_login("alice", "pw", "example.org")

    def test_multiple_records_raises_aggravated(self):
        c = make_client()
        c._get_base_dn = MagicMock(return_value="uid=x,dc=example,dc=org")
        c._bind = MagicMock(return_value=(True, "ok"))
        c._search = MagicMock(return_value=[
            ("uid=a,dc=example,dc=org", {"uid": [b"a"]}),
            ("uid=b,dc=example,dc=org", {"uid": [b"b"]}),
        ])
        with pytest.raises(exc.AggravatedException) as e:
            c.check_login("alice", "pw", "example.org")
        assert e.value.error.c == err.ERROR_LDAP_NOT_UNIQUE_USER.c


# ─────────────────────────────────────────────────────────────────────────────
# _search / _search_dn
# ─────────────────────────────────────────────────────────────────────────────

class TestSearch:
    def test_search_requires_connection(self):
        c = make_client()
        with pytest.raises(exc.BugException):
            c._search("base")
        with pytest.raises(exc.BugException):
            c._search_dn("base", "(a=b)")

    def test_search_ok(self):
        c = make_client()
        c.connected = True
        c.ldap_conn = make_conn()
        ret = c._search("base", "(uid=alice)", ["uid"])
        assert ret[0][0].startswith("uid=alice")
        c.ldap_conn.search_s.assert_called_once_with("base", c.scope,
                                                     filterstr="(uid=alice)", attrlist=["uid"])

    def test_search_no_such_object_returns_empty(self):
        from ldap import NO_SUCH_OBJECT

        c = make_client()
        c.connected = True
        c.ldap_conn = MagicMock()
        c.ldap_conn.search_s.side_effect = NO_SUCH_OBJECT
        assert c._search("base", "(a=b)") == []

    def test_search_ldap_error_raises_request(self):
        from ldap import LDAPError

        c = make_client()
        c.connected = True
        c.ldap_conn = MagicMock()
        c.ldap_conn.search_s.side_effect = LDAPError("boom")
        with pytest.raises(exc.RequestException) as e:
            c._search("base", "(a=b)")
        assert e.value.error.c == err.ERROR_LDAP_CANNOT_SEARCH.c

    def test_search_dn_ok(self):
        c = make_client()
        c.connected = True
        c.ldap_conn = make_conn()
        c._search_dn("base", "(a=b)")
        c.ldap_conn.search_s.assert_called_once_with("base", c.scope,
                                                     filterstr="(a=b)", attrlist=["dn"])


# ─────────────────────────────────────────────────────────────────────────────
# search_entries
# ─────────────────────────────────────────────────────────────────────────────

class TestSearchEntries:
    def test_requires_connect(self):
        c = make_client()
        with pytest.raises(exc.BugException):
            c.search_entries()

    def test_returns_parsed(self):
        c = make_client()
        c.connected = True
        c.ldap_conn = make_conn()
        c._bind = MagicMock(return_value=(True, "ok"))
        c._search = MagicMock(return_value=[
            ("uid=a,dc=example,dc=org", {"uid": [b"a"], "cn": [b"Alice"]})
        ])
        entries = c.search_entries()
        assert entries == [{"uid": ["a"], "cn": ["Alice"],
                            "dn": ["uid=a,dc=example,dc=org"]}]
        assert c._bind.call_args[0][0] == "cn=admin,dc=example,dc=org"

    def test_default_base_dn(self):
        c = make_client()
        c.connected = True
        c.ldap_conn = make_conn()
        c._bind = MagicMock(return_value=(True, "ok"))
        c._search = MagicMock(return_value=[])
        c.search_entries()
        c._search.assert_called_once_with("dc=example,dc=org", None, None)


# ─────────────────────────────────────────────────────────────────────────────
# close
# ─────────────────────────────────────────────────────────────────────────────

class TestClose:
    def test_unbinds_when_bound(self):
        c = make_client()
        c.ldap_conn = MagicMock()
        c.binded = True
        c.close()
        c.ldap_conn.unbind_s.assert_called_once()

    def test_no_unbind_when_not_bound(self):
        c = make_client()
        c.ldap_conn = MagicMock()
        c.binded = False
        c.close()
        c.ldap_conn.unbind_s.assert_not_called()

    def test_noop_without_connection(self):
        c = make_client()
        c.close()  # should not raise
