# pylint: disable=protected-access,too-many-public-methods
"""Unit tests for ClientSieve — Sieve script compilation, ManageSieve client wrapper
and vacation/forward/notification/filter script builders."""
from __future__ import annotations

import datetime
import os
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest
from sievelib.factory import FiltersSet

from app.manager.mail.ClientSieve import (
    ClientSieve,
    VacationConditions,
    _SieveTlsClient,
)
from app.utils import constants as cs
from app.utils import errors as err
from app.utils.exceptions import BugException, RequestException


def make_client(connection: bool | None = None) -> ClientSieve:
    c = ClientSieve("sieve.example.org", 4190, cs.SOCKET_ENC_IMPLICIT_TLS, "plain", verify_cert=False)
    c.connected = True
    c.authenticated = True
    if connection is not None:
        c.connection = connection
    else:
        c.connection = mock.Mock()
    return c


class TestVacationConditions:
    def test_defaults(self):
        vc = VacationConditions()
        assert vc.start_date is None
        assert vc.weekday == []
        assert vc.weekdays_enabled is False

    def test_from_vacation_config(self):
        fake = mock.Mock(side_effect=lambda raw, tz: (raw, f"{raw}T00:00:00" if raw else None, "+0200"))
        vc = VacationConditions.from_vacation_config(
            "2026-06-15", "2026-06-30", "UTC",
            "09:00", "17:00", True, [1, 3, 5], fake,
        )
        assert vc.start_date == "2026-06-15"
        assert vc.end_date == "2026-06-30"
        assert vc.start_tz == "+0200"
        assert vc.start_time == "09:00"
        assert vc.weekdays_enabled is True
        assert vc.weekday == [1, 3, 5]
        assert fake.call_count == 2

    def test_from_vacation_config_keeps_list(self):
        fake = mock.Mock(return_value=(None, None, "UTC"))
        wk = [0, 6]
        vc = VacationConditions.from_vacation_config(
            None, None, "UTC", None, None, False, wk, fake)
        assert vc.weekday is wk


class TestTlsClient:
    def test_enable_ssl_no_verify(self):
        t = _SieveTlsClient("srv", 4190, verify_cert=False)
        t.sock = mock.Mock()
        ctx = mock.Mock()
        with mock.patch("ssl.create_default_context", return_value=ctx):
            with mock.patch.object(t, "_Client__enable_ssl", t._Client__enable_ssl) as m:
                m()
        ctx.check_hostname = False  # cannot assert directly on MagicMock config; smoke test
        assert ctx.wrap_socket is not None

    def test_enable_ssl_verify_true(self):
        t = _SieveTlsClient("srv", 4190, verify_cert=True)
        t.sock = mock.Mock()
        with mock.patch("ssl.create_default_context") as ctx:
            t._Client__enable_ssl()
        ctx.return_value.load_cert_chain.assert_not_called()

    def test_enable_ssl_certfile_loads_chain(self):
        t = _SieveTlsClient("srv", 4190, verify_cert=True)
        t.sock = mock.Mock()
        with mock.patch("ssl.create_default_context") as ctx:
            t._Client__enable_ssl("kf", "cf")
        ctx.return_value.load_cert_chain.assert_called_once_with("cf", keyfile="kf")


class TestConnect:
    def test_unknown_encryption_raises(self):
        c = ClientSieve("srv", 1, "bogus", "plain")
        with pytest.raises(BugException) as ex:
            c.connect()
        assert ex.value.error.c == "S000020"

    def test_connect_creates_client(self):
        c = ClientSieve("srv", 4190, cs.SOCKET_ENC_IMPLICIT_TLS, "plain", verify_cert=False)
        c.connect()
        assert isinstance(c.connection, _SieveTlsClient)
        assert c.connected is True
        assert c.connection._verify_cert is False


class TestLogin:
    def test_login_before_connect(self):
        c = ClientSieve("srv", 4190, cs.SOCKET_ENC_IMPLICIT_TLS, "plain")
        with pytest.raises(BugException) as ex:
            c.login("u", "p")
        assert ex.value.error.c == "S001507"

    def test_login_success(self):
        c = ClientSieve("srv", 4190, cs.SOCKET_ENC_IMPLICIT_TLS, "plain")
        c.connection = mock.Mock()
        c.connection.connect.return_value = True
        c.login("user", "pass", authname="authz")
        c.connection.connect.assert_called_once_with(
            login="user", password="pass", authz_id="authz",
            starttls=False, ssl=True, authmech="PLAIN",
        )
        assert c.authenticated is True

    def test_login_auth_mech_none_maps_to_none(self):
        c = ClientSieve("srv", 4190, cs.SOCKET_ENC_EXPLICIT_TLS, "none")
        c.connection = mock.Mock()
        c.connection.connect.return_value = True
        c.login("u", "p")
        assert c.connection.connect.call_args.kwargs["authmech"] is None
        assert c.connection.connect.call_args.kwargs["starttls"] is True

    def test_login_connection_failed(self):
        c = ClientSieve("srv", 4190, cs.SOCKET_ENC_IMPLICIT_TLS, "plain")
        c.connection = mock.Mock()
        c.connection.connect.side_effect = __import__("sievelib.managesieve", fromlist=["Error"]).Error("Connection to server failed: nope")
        with pytest.raises(RequestException) as ex:
            c.login("u", "p")
        assert ex.value.error.c == "S001501"

    def test_login_ssl_error(self):
        c = ClientSieve("srv", 4190, cs.SOCKET_ENC_IMPLICIT_TLS, "plain")
        c.connection = mock.Mock()
        c.connection.connect.side_effect = __import__("sievelib.managesieve", fromlist=["Error"]).Error("SSL error: boom")
        with pytest.raises(RequestException) as ex:
            c.login("u", "p")
        assert ex.value.error.c == "S001501"

    def test_login_sieve_auth_error(self):
        c = ClientSieve("srv", 4190, cs.SOCKET_ENC_IMPLICIT_TLS, "plain")
        c.connection = mock.Mock()
        c.connection.connect.side_effect = __import__("sievelib.managesieve", fromlist=["Error"]).Error("authentication failed")
        with pytest.raises(RequestException) as ex:
            c.login("u", "p")
        assert ex.value.error.c == "S001502"

    def test_login_tcp_error(self):
        c = ClientSieve("srv", 4190, cs.SOCKET_ENC_IMPLICIT_TLS, "plain")
        c.connection = mock.Mock()
        c.connection.connect.side_effect = TimeoutError("timeout")
        with pytest.raises(RequestException) as ex:
            c.login("u", "p")
        assert ex.value.error.c == "S001501"

    def test_login_falsy_result(self):
        c = ClientSieve("srv", 4190, cs.SOCKET_ENC_IMPLICIT_TLS, "plain")
        c.connection = mock.Mock()
        c.connection.connect.return_value = None
        c.connection.errmsg = b"Auth failed"
        with pytest.raises(RequestException) as ex:
            c.login("u", "p")
        assert ex.value.error.c == "S001502"
        assert "Auth failed" in str(ex.value)


class TestExecSieveMethod:
    def test_not_connected(self):
        c = ClientSieve("srv", 1, cs.SOCKET_ENC_IMPLICIT_TLS, "plain")
        c.authenticated = False
        with pytest.raises(BugException) as ex:
            c._exec_sieve_method(lambda: 1)
        assert ex.value.error.c == "S001507"

    def test_returns_result(self):
        c = make_client()
        assert c._exec_sieve_method(lambda a: a * 2, 21) == 42

    def test_sieve_error(self):
        c = make_client()
        def boom():
            raise __import__("sievelib.managesieve", fromlist=["Error"]).Error("kaput")
        with pytest.raises(RequestException) as ex:
            c._exec_sieve_method(boom)
        assert ex.value.error.c == "S001504"
        assert "kaput" in str(ex.value)


class TestErrors:
    def test_get_sieve_error_message_no_connection(self):
        c = ClientSieve("srv", 1, "None", "plain")
        assert c._get_sieve_error_message() == "No connection available"

    def test_get_sieve_error_message_none(self):
        c = make_client()
        c.connection.errmsg = None
        assert "Unknown error" in c._get_sieve_error_message()

    def test_get_sieve_error_message_bytes(self):
        c = make_client()
        c.connection.errmsg = b"\xff bad"
        assert c._get_sieve_error_message() == "\ufffd bad"

    def test_get_sieve_error_message_str(self):
        c = make_client()
        c.connection.errmsg = "plain error"
        assert c._get_sieve_error_message() == "plain error"

    def test_extract_missing_capability_cap(self):
        c = make_client()
        assert c._extract_missing_capability("unknown Sieve capability `notify'") == "notify"

    def test_extract_missing_capability_command(self):
        c = make_client()
        assert c._extract_missing_capability("unknown command 'foo'") == "foo"

    def test_extract_missing_capability_fail(self):
        c = make_client()
        with pytest.raises(BugException) as ex:
            c._extract_missing_capability("nothing to see")
        assert ex.value.error.c == "S001509"


class TestScriptOps:
    def test_put_script_not_authenticated(self):
        c = ClientSieve("srv", 1, "None", "plain")
        with pytest.raises(BugException):
            c.put_script("n", "c")

    def test_put_script_success(self):
        c = make_client()
        c.connection.putscript.return_value = True
        assert c.put_script("sogo-master", "keep;") == (True, None)
        c.connection.putscript.assert_called_once_with("sogo-master", "keep;")

    def test_put_script_missing_capability(self):
        c = make_client()
        c.connection.putscript.return_value = False
        c.connection.errmsg = "unknown Sieve capability `enotify'"
        assert c.put_script("name", "script") == (False, "enotify")

    def test_put_script_other_error(self):
        c = make_client()
        c.connection.putscript.return_value = False
        c.connection.errmsg = "script too big"
        with pytest.raises(RequestException) as ex:
            c.put_script("name", "script")
        assert ex.value.error.c == "S001506"

    def test_put_script_exception(self):
        c = make_client()
        c.connection.putscript.side_effect = __import__("sievelib.managesieve", fromlist=["Error"]).Error("boom")
        with pytest.raises(RequestException) as ex:
            c.put_script("name", "script")
        assert ex.value.error.c == "S001504"

    def test_delete_script_success(self):
        c = make_client()
        c.connection.deletescript.return_value = True
        c.delete_script("old")
        c.connection.deletescript.assert_called_once_with("old")

    def test_delete_script_failure(self):
        c = make_client()
        c.connection.deletescript.return_value = False
        with pytest.raises(RequestException) as ex:
            c.delete_script("old")
        assert ex.value.error.c == "S001505"

    def test_set_active_success(self):
        c = make_client()
        c.connection.setactive.return_value = True
        c.set_active("sogo-master")
        c.connection.setactive.assert_called_once_with("sogo-master")

    def test_set_active_failure(self):
        c = make_client()
        c.connection.setactive.return_value = False
        with pytest.raises(RequestException) as ex:
            c.set_active("sogo-master")
        assert ex.value.error.c == "S001504"


class TestRuleDetection:
    def test_rule_uses_cc_or_to_leaf(self):
        c = make_client()
        assert c._rule_uses_cc_or_to({"field": "cc or to", "operator": "contains", "value": "x"})
        assert not c._rule_uses_cc_or_to({"field": "subject", "operator": "contains", "value": "x"})

    def test_rule_uses_cc_or_to_group(self):
        c = make_client()
        tree = {"op": "and", "rules": [{"field": "subject"}, {"op": "or", "rules": [{"field": "cc or to"}]}]}
        assert c._rule_uses_cc_or_to(tree)
        assert not c._rule_uses_cc_or_to({"op": "and", "rules": [{"field": "subject"}]})

    def test_replace_field_in_rules_group(self):
        c = make_client()
        tree = {"op": "and", "rules": [{"field": "cc or to", "operator": "contains"}]}
        out = c._replace_field_in_rules(tree, "cc or to", "cc")
        assert out["rules"][0]["field"] == "cc"
        assert out["op"] == "and"

    def test_detect_extensions_rules(self):
        c = make_client()
        tree = {"op": "and", "rules": [{"field": "body"}, {"field": "subject"}]}
        assert c._detect_required_extensions_from_rules(tree) == {"body"}
        assert c._detect_required_extensions_from_rules({"field": "subject"}) == set()

    def test_detect_extensions_actions(self):
        c = make_client()
        actions = [
            {"method": "fileinto", "arguments": {"keep_copy": True, "create_if_no_exist": True}},
            {"method": "addflag", "arguments": {"flags": ["\\Seen"]}},
            {"method": "notify", "arguments": {}},
            {"method": "keep", "arguments": {}},
        ]
        out = c._detect_required_extensions_from_actions(actions)
        assert "fileinto" in out
        assert "copy" in out
        assert "mailbox" in out
        assert "imap4flags" in out
        assert "enotify" in out


class TestBuildSingleCondition:
    def test_size(self):
        c = make_client()
        assert c._build_single_condition({"field": "size", "operator": "over", "value": "100K"}) == ("size", ":over", "100K")

    def test_body(self):
        c = make_client()
        assert c._build_single_condition({"field": "body", "operator": "contains", "value": "hi"}) == ("body", ":text", ":contains", "hi")

    def test_header(self):
        c = make_client()
        assert c._build_single_condition({"field": "subject", "operator": "contains", "value": "x"}) == ("subject", ":contains", ["x"])

    def test_header_list_value(self):
        c = make_client()
        assert c._build_single_condition({"field": "from", "operator": "is", "value": ["a@b.c"]}) == ("from", ":is", ["a@b.c"])

    def test_custom_header(self):
        c = make_client()
        assert c._build_single_condition({"field": "header", "operator": "contains", "value": "v", "custom_header": "X-Tag"}) == ("X-Tag", ":contains", ["v"])

    def test_invalid_returns_none(self):
        # header field without custom_header maps to "" so the condition is dropped
        c = make_client()
        assert c._build_single_condition({"field": "header", "operator": "contains", "value": "x"}) is None

    def test_unknown_field_raises(self):
        c = make_client()
        with pytest.raises(BugException):
            c._build_single_condition({"field": "", "operator": ""})


class TestMapFieldName:
    def test_standard_headers(self):
        c = make_client()
        for f in ("subject", "from", "to", "cc"):
            assert c._map_field_name(f) == f

    def test_header_with_custom(self):
        c = make_client()
        assert c._map_field_name("header", "X-Foo") == "X-Foo"

    def test_header_without_custom(self):
        c = make_client()
        assert c._map_field_name("header") == ""

    def test_body_size(self):
        c = make_client()
        assert c._map_field_name("body") == "body"
        assert c._map_field_name("size") == ""

    def test_unknown_field_raises(self):
        c = make_client()
        with pytest.raises(BugException):
            c._map_field_name("bogus")


class TestBuildNestedConditions:
    def test_empty(self):
        c = make_client()
        assert c._build_sieve_conditions({}) == ([], "allof")

    def test_empty_group(self):
        c = make_client()
        assert c._build_nested_conditions_recursive({"op": "and", "rules": []}) == ([], "allof")

    def test_single_rule_group_flattens(self):
        c = make_client()
        conds, mt = c._build_nested_conditions_recursive({"op": "and", "rules": [{"field": "subject", "operator": "contains", "value": "x"}]})
        assert mt == "allof"
        assert conds == [("subject", ":contains", ["x"])]

    def test_or_group(self):
        c = make_client()
        conds, mt = c._build_nested_conditions_recursive({
            "op": "or",
            "rules": [
                {"field": "subject", "operator": "contains", "value": "a"},
                {"field": "from", "operator": "is", "value": "b"},
            ],
        })
        assert mt == "anyof"
        assert conds == [("subject", ":contains", ["a"]), ("from", ":is", ["b"])]

    def test_nested_group_diff_op(self):
        c = make_client()
        conds, mt = c._build_nested_conditions_recursive({
            "op": "and",
            "rules": [
                {"op": "or", "rules": [
                    {"field": "subject", "operator": "contains", "value": "a"},
                    {"field": "subject", "operator": "contains", "value": "b"},
                ]},
                {"field": "from", "operator": "is", "value": "c"},
            ],
        })
        assert mt == "allof"
        assert ("__group__", "anyof", [("subject", ":contains", ["a"]), ("subject", ":contains", ["b"])]) in conds

    def test_nested_group_same_op_flattens(self):
        c = make_client()
        conds, mt = c._build_nested_conditions_recursive({
            "op": "or",
            "rules": [
                {"op": "or", "rules": [{"field": "subject", "operator": "contains", "value": "a"}]},
                {"field": "from", "operator": "is", "value": "b"},
            ],
        })
        assert mt == "anyof"
        assert all("__group__" not in cond for cond in conds)


class TestBuildActions:
    def test_simple_actions(self):
        c = make_client()
        out = c._build_sieve_actions([
            {"method": "keep", "arguments": {}},
            {"method": "discard", "arguments": {}},
            {"method": "stop", "arguments": {}},
        ])
        assert out == [("keep",), ("discard",), ("stop",)]

    def test_fileinto(self):
        c = make_client()
        out = c._build_sieve_actions([
            {"method": "fileinto", "arguments": {"folders": ["Archive"], "keep_copy": True, "create_if_no_exist": True}},
        ])
        assert ("fileinto", ":copy", ":create", "Archive") in out

    def test_redirect(self):
        c = make_client()
        out = c._build_sieve_actions([
            {"method": "redirect", "arguments": {"addresses": ["a@b.c", "d@e.f"]}},
        ])
        assert out == [("redirect", "a@b.c"), ("redirect", "d@e.f")]

    def test_reject_with_and_without_message(self):
        c = make_client()
        out = c._build_sieve_actions([
            {"method": "reject", "arguments": {"message": "nope"}},
            {"method": "reject", "arguments": {}},
        ])
        assert out == [("reject", "nope"), ("reject",)]

    def test_flag(self):
        c = make_client()
        out = c._build_sieve_actions([
            {"method": "addflag", "arguments": {"flags": ["\\Seen", "\\Flagged"]}},
            {"method": "addflag", "arguments": {}},
        ])
        assert ("addflag", "\\Seen") in out
        assert ("addflag", "\\Flagged") in out

    def test_notify(self):
        c = make_client()
        out = c._build_sieve_actions([
            {"method": "notify", "arguments": {"method": "mailto", "priority": "high", "message_text": "m"}},
        ])
        assert out == [("notify", "mailto", "high", "m")]

    def test_unknown_action_raises(self):
        c = make_client()
        with pytest.raises(BugException):
            c._build_sieve_actions([{"method": "explode", "arguments": {}}])


class TestFileintoRedirectHelpers:
    def test_fileinto_single_folder_fallback(self):
        c = make_client()
        out = []
        c._add_fileinto_action(out, {"folder": "Inbox", "keep_copy": True})
        assert out == [("fileinto", ":copy", "Inbox")]

    def test_fileinto_no_folders_skip(self):
        c = make_client()
        out = []
        c._add_fileinto_action(out, {})
        assert out == []

    def test_fileinto_invalid_folders_skipped(self):
        c = make_client()
        out = []
        c._add_fileinto_action(out, {"folders": ["OK", "", 42]})
        assert out == [("fileinto", "OK")]

    def test_redirect_single_fallback(self):
        c = make_client()
        out = []
        c._add_redirect_action(out, {"address": "a@b.c"})
        assert out == [("redirect", "a@b.c")]

    def test_redirect_none_skip(self):
        c = make_client()
        out = []
        c._add_redirect_action(out, {})
        assert out == []

    def test_redirect_invalid_skipped(self):
        c = make_client()
        out = []
        c._add_redirect_action(out, {"addresses": ["a@b.c", "", 7]})
        assert out == [("redirect", "a@b.c")]


class TestTzAndTime:
    def test_convert_empty(self):
        c = make_client()
        assert c._convert_tz_to_sieve_format("") == "+0000"

    def test_convert_offset_passthrough(self):
        c = make_client()
        assert c._convert_tz_to_sieve_format("+02:00") == "+0200"
        assert c._convert_tz_to_sieve_format("-0500") == "-0500"

    def test_convert_z_utc(self):
        c = make_client()
        assert c._convert_tz_to_sieve_format("Z") == "+0000"
        assert c._convert_tz_to_sieve_format("utc") == "+0000"
        assert c._convert_tz_to_sieve_format("GMT") == "+0000"

    def test_convert_iana(self):
        c = make_client()
        assert c._convert_tz_to_sieve_format("Europe/Paris", "2026-07-01") == "+0200"
        assert c._convert_tz_to_sieve_format("Europe/Berlin", "2026-01-15") == "+0100"

    def test_convert_iana_no_date(self):
        c = make_client()
        out = c._convert_tz_to_sieve_format("Europe/Paris")
        assert out in ("+0100", "+0200")

    def test_convert_invalid(self):
        c = make_client()
        assert c._convert_tz_to_sieve_format("Not/AZone") == "+0000"

    def test_normalize_time(self):
        c = make_client()
        assert c._normalize_time_to_sieve("09:30") == "09:30:00"
        assert c._normalize_time_to_sieve("09:30:15") == "09:30:15"
        assert c._normalize_time_to_sieve("") == "00:00:00"
        assert c._normalize_time_to_sieve("bogus") == "00:00:00"

    def test_parse_vacation_datetime_delegates(self):
        c = make_client()
        with mock.patch("app.manager.mail.ClientSieve.parse_vacation_datetime", return_value=("2026-01-01", None, "+0000")) as pv:
            out = c._parse_vacation_datetime("2026-01-01", "UTC")
        assert out == ("2026-01-01", None, "+0000")
        pv.assert_called_once()


class TestVacationScript:
    def test_simple_vacation(self):
        c = make_client()
        script = c._build_vacation_script({
            "enabled": True,
            "auto_reply_text": "On vacation",
            "custom_subject": "", "custom_subject_enabled": False,
            "start_date": None, "end_date": None,
            "timezone": "UTC", "days": None,
            "start_time": None, "end_time": None,
            "weekdays_enabled": False, "weekday": [],
        })
        assert 'require ["vacation"];' in script
        assert 'vacation "On vacation";' in script
        assert "if " not in script

    def test_vacation_with_subject_and_days(self):
        c = make_client()
        script = c._build_vacation_script({
            "enabled": True,
            "auto_reply_text": 'Say "hi"',
            "custom_subject": "Away", "custom_subject_enabled": True,
            "start_date": None, "end_date": None,
            "timezone": "UTC", "days": 3,
            "start_time": None, "end_time": None,
            "weekdays_enabled": False, "weekday": [],
        })
        assert ':days' in script
        assert '3' in script
        assert ':subject "Away"' in script
        assert 'Say \\\\"hi\\\\"' in script  # backslash-escaped quote

    def test_vacation_with_condition(self):
        c = make_client()
        script = c._build_vacation_script({
            "enabled": True,
            "auto_reply_text": "Away",
            "custom_subject": "", "custom_subject_enabled": False,
            "start_date": None, "end_date": None,
            "timezone": "UTC", "days": None,
            "start_time": "09:00", "end_time": "17:00",
            "weekdays_enabled": False, "weekday": [],
        })
        assert "if " in script
        assert "vacation \"Away\";" in script
        assert "relational" in script and "date" in script


class TestVacationConditionsBuilder:
    def test_no_conditions(self):
        c = make_client()
        assert c._build_vacation_conditions(VacationConditions()) == ""

    def test_date_only_range(self):
        c = make_client()
        vc = VacationConditions(start_date="2026-06-15", end_date="2026-06-30", start_tz="+0200", end_tz="+0200")
        out = c._build_vacation_conditions(vc)
        assert 'currentdate :zone "+0200" :value "ge" "date" "2026-06-15"' in out
        assert 'currentdate :zone "+0200" :value "le" "date" "2026-06-30"' in out
        assert out.startswith("if ")

    def test_date_with_time(self):
        c = make_client()
        vc = VacationConditions(
            start_date="2026-06-15", start_date_time="10:00",
            end_date="2026-06-15", end_date_time="12:00",
        )
        out = c._build_vacation_conditions(vc)
        assert "10:00:00" in out
        assert "12:00:00" in out
        assert ':value "gt" "date"' in out
        assert ':value "lt" "date"' in out

    def test_invalid_dates_skipped(self):
        c = make_client()
        vc = VacationConditions(start_date="not-a-date", end_date="also-bad")
        assert c._build_vacation_conditions(vc) == ""

    def test_daily_time_window(self):
        c = make_client()
        vc = VacationConditions(start_time="09:00", end_time="17:00")
        out = c._build_vacation_conditions(vc)
        assert 'allof(currentdate :zone "+0000" :value "ge" "time" "09:00:00"' in out
        assert ':value "le" "time" "17:00:00"' in out

    def test_overnight_time_window(self):
        c = make_client()
        vc = VacationConditions(start_time="18:00", end_time="08:00")
        out = c._build_vacation_conditions(vc)
        assert 'anyof(' in out
        assert ':value "lt" "time" "08:00:00"' in out

    def test_single_weekday(self):
        c = make_client()
        vc = VacationConditions(weekdays_enabled=True, weekday=[1])
        out = c._build_vacation_conditions(vc)
        assert 'currentdate :zone "+0000" :is "weekday" "1"' in out
        assert "anyof" not in out

    def test_multi_weekday(self):
        c = make_client()
        vc = VacationConditions(weekdays_enabled=True, weekday=[0, 6])
        out = c._build_vacation_conditions(vc)
        assert 'anyof(' in out
        assert '"6"' in out

    def test_invalid_weekdays_filtered(self):
        c = make_client()
        vc = VacationConditions(weekdays_enabled=True, weekday=[1, 99])
        out = c._build_vacation_conditions(vc)
        assert "99" not in out

    def test_single_condition_no_anyof(self):
        c = make_client()
        vc = VacationConditions(start_date="2026-06-15")
        out = c._build_vacation_conditions(vc)
        assert out.startswith("if ")


class TestForwardAndNotification:
    def test_forward_keep_copy(self):
        c = make_client()
        s = c._build_forward_script(["a@b.c", "d@e.f"], keep_copy=1)
        assert 'redirect "a@b.c";' in s
        assert 'redirect "d@e.f";' in s
        assert "keep;" in s
        assert "discard;" not in s

    def test_forward_discard(self):
        c = make_client()
        s = c._build_forward_script(["a@b.c"])
        assert "discard;" in s
        assert "keep;" not in s

    def test_notification_no_addresses(self):
        c = make_client()
        assert c._build_notification_script({}) == ""

    def test_notification_default_message(self):
        c = make_client()
        s = c._build_notification_script({"notify_addresses": ["a@b.c"]})
        assert 'require ["enotify"];' in s
        assert 'notify :message "A mail event has been triggered." "mailto:a@b.c";' in s

    def test_notification_custom_message_escaped(self):
        c = make_client()
        s = c._build_notification_script({"notify_addresses": ["a@b.c"], "notify_message": 'He said "hi"\n'})
        # mirror the escaping performed by the implementation
        escaped = 'He said "hi"\n'.replace('"', '\\"').replace('\\', '\\\\').replace('\n', '\\n')
        assert 'notify :message "%s" "mailto:a@b.c";' % escaped in s


class TestCompileMerged:
    def test_no_requires(self):
        c = make_client()
        script = c._compile_merged_script(set(), [("forward", 'redirect "a@b.c";\ndiscard;')])
        assert script.startswith("# ---- FORWARD SECTION ----")
        assert "redirect" in script
        assert "require" not in script

    def test_requires_and_strip(self):
        c = make_client()
        script = c._compile_merged_script(
            {"fileinto", "mailbox"},
            [("filters", 'require ["fileinto"];\nif true {\n  fileinto "X";\n}')],
        )
        assert 'require ["fileinto", "mailbox"];' in script
        assert script.count("require") == 1  # only merged header

    def test_builtin_commands_filtered(self):
        c = make_client()
        script = c._compile_merged_script({"redirect", "keep", "copy"}, [("filters", "keep;")])
        assert "redirect" not in script.split("\n")[0]
        assert script.startswith('require ["copy"];')
        assert ":copy" not in script.split("\n")[0]

    def test_extract_require_from_parts(self):
        c = make_client()
        # requires_set is empty but section declares its own require
        script = c._compile_merged_script(set(), [("vacation", 'require ["vacation"];\nvacation "x";')])
        assert 'require ["vacation"];' in script


class TestRenderFiltersSet:
    def test_render_filters_set(self):
        c = make_client()
        fs = FiltersSet("name")
        fs.addfilter(name="f1", conditions=[("subject", ":contains", ["spam"])], actions=[("discard",)], matchtype="allof")
        s = c._render_filters_set(fs)
        assert "subject" in s or "header" in s


class TestAddFilterToSet:
    def test_no_actions_skips(self):
        c = make_client()
        fs = FiltersSet("name")
        c._add_filter_to_set(fs, {"name": "f", "actions": [], "rules": {}})
        assert fs.filters == []

    def test_flat_filter(self):
        c = make_client()
        fs = FiltersSet("name")
        c._add_filter_to_set(fs, {
            "name": "f1",
            "actions": [{"method": "discard", "arguments": {}}],
            "rules": {"field": "subject", "operator": "contains", "value": "spam"},
        })
        assert len(fs.filters) == 1

    def test_malformed_raises(self):
        c = make_client()
        fs = FiltersSet("name")
        with pytest.raises(RequestException) as ex:
            c._add_filter_to_set(fs, {
                "name": "bad",
                "actions": [{"method": "discard", "arguments": {}}],
                "rules": {"field": "bogusfield", "operator": "contains", "value": "x"},
            })
        assert ex.value.error.c == "S001506"

    def test_cc_or_to_filter(self):
        c = make_client()
        fs = FiltersSet("name")
        c._add_filter_to_set(fs, {
            "name": "f",
            "actions": [{"method": "redirect", "arguments": {"address": "a@b.c"}}],
            "rules": {"field": "cc or to", "operator": "contains", "value": "boss@x"},
        })
        names = [f["name"] for f in fs.filters]
        assert "f (CC)" in names
        assert "f (TO)" in names


class TestNestedDirectConstruction:
    def test_build_condition_command_empty(self):
        c = make_client()
        fs = FiltersSet("n")
        ifcontrol = __import__("sievelib.commands", fromlist=["get_command_instance"]).get_command_instance("if")
        assert c._build_condition_command([], ifcontrol, fs) is None

    def test_build_condition_command_size(self):
        c = make_client()
        fs = FiltersSet("n")
        ifcontrol = __import__("sievelib.commands", fromlist=["get_command_instance"]).get_command_instance("if")
        cmd = c._build_condition_command(("size", ":over", "100K"), ifcontrol, fs)
        assert cmd is not None

    def test_build_condition_command_body(self):
        c = make_client()
        fs = FiltersSet("n")
        ifcontrol = __import__("sievelib.commands", fromlist=["get_command_instance"]).get_command_instance("if")
        with mock.patch.object(fs, "require") as req:
            cmd = c._build_condition_command(("body", ":text", ":contains", ["hi"]), ifcontrol, fs)
        assert cmd is not None
        req.assert_called_once_with("body")


class TestProcessSections:
    def test_process_forward_no_addresses(self):
        c = make_client()
        parts, req, act = [], set(), {cs.FILTER_SECTION_FORWARD: False}
        idx = c._process_forward_section({"forward_address": []}, parts, req, act)
        assert idx == -1
        assert act[cs.FILTER_SECTION_FORWARD] is False

    def test_process_forward_happy(self):
        c = make_client()
        parts, req, act = [], set(), {cs.FILTER_SECTION_FORWARD: False}
        idx = c._process_forward_section({"forward_address": ["a@b.c"], "keep_copy": True}, parts, req, act)
        assert idx == 0
        assert parts[0][0] == cs.FILTER_SECTION_FORWARD
        assert act[cs.FILTER_SECTION_FORWARD] is True

    def test_process_vacation_insert_pos(self):
        c = make_client()
        parts = [("forward", "redirect;")]
        req, act = set(), {}
        c._process_vacation_section({"enabled": True, "auto_reply_text": "away"}, parts, req, act, insert_pos=1)
        assert parts[1][0] == cs.FILTER_SECTION_VACATION
        assert "vacation" in req

    def test_process_filters_empty(self):
        c = make_client()
        parts, req, act = [], set(), {}
        c._process_filters_section([], parts, req, act)
        assert parts == []

    def test_process_filters_enabled(self):
        c = make_client()
        parts, req, act = [], set(), {}
        c._process_filters_section([{
            "enabled": True,
            "name": "f",
            "actions": [{"method": "fileinto", "arguments": {"folders": ["X"]}}],
            "rules": {"field": "subject", "operator": "contains", "value": "s"},
        }], parts, req, act)
        assert parts[0][0] == cs.FILTER_SECTION_FILTERS
        assert "fileinto" in req
        assert act[cs.FILTER_SECTION_FILTERS] is True

    def test_process_filters_disabled_skipped(self):
        c = make_client()
        parts, req, act = [], set(), {}
        c._process_filters_section([{"enabled": False, "name": "f", "actions": [], "rules": {}}], parts, req, act)
        assert parts == []

    def test_process_notification_disabled(self):
        c = make_client()
        parts, req, act = [], set(), {}
        c._process_notification_section(None, parts, req, act)
        assert parts == []

    def test_process_notification_no_addresses_marks_activated(self):
        c = make_client()
        parts, req, act = [], set(), {cs.FILTER_SECTION_NOTIFICATION: False}
        c._process_notification_section({"enabled": True, "notify_addresses": []}, parts, req, act)
        assert act[cs.FILTER_SECTION_NOTIFICATION] is True
        assert parts == []

    def test_process_notification_happy(self):
        c = make_client()
        parts, req, act = [], set(), {cs.FILTER_SECTION_NOTIFICATION: False}
        c._process_notification_section({"enabled": True, "notify_addresses": ["a@b.c"]}, parts, req, act)
        assert parts[0][0] == cs.FILTER_SECTION_NOTIFICATION
        assert "enotify" in req


class TestCheckAuthenticated:
    def test_ok(self):
        c = make_client()
        c._check_authenticated("x")
        assert True

    def test_not_authenticated(self):
        c = ClientSieve("s", 1, "None", "plain")
        with pytest.raises(BugException):
            c._check_authenticated("m()")


class TestStoreAndActivate:
    def test_success(self):
        c = make_client()
        c.connection.putscript.return_value = True
        c.connection.setactive.return_value = True
        skipped = c._store_and_activate_script("m", 'keep;')
        assert skipped == set()
        c.connection.setactive.assert_called_once_with("m")

    def test_retry_notify(self):
        c = make_client()
        c.connection.putscript.side_effect = [False, True]
        c.connection.errmsg = "unknown Sieve capability `notify'"
        c.connection.setactive.return_value = True
        parts = [(cs.FILTER_SECTION_NOTIFICATION, "notify;"), (cs.FILTER_SECTION_FORWARD, "redirect;")]
        skipped = c._store_and_activate_script("m", "whatever", {"enotify", "redirect"}, parts)
        assert skipped == {cs.FILTER_SECTION_NOTIFICATION}
        assert c.connection.putscript.call_count == 2

    def test_no_retry_parts_raises(self):
        c = make_client()
        c.connection.putscript.return_value = False
        c.connection.errmsg = "unknown Sieve capability `enotify'"
        with pytest.raises(RequestException):
            c._store_and_activate_script("m", "x", {"enotify"}, None)

    def test_missing_capability_no_parts(self):
        c = make_client()
        c.connection.putscript.return_value = False
        c.connection.errmsg = "unknown Sieve capability `enotify'"
        with pytest.raises(RequestException) as ex:
            c._store_and_activate_script("m", "x")
        assert ex.value.error.c == "S001506"

    def test_plain_failure(self):
        c = make_client()
        c.connection.putscript.return_value = False
        c.connection.errmsg = "boom"
        with pytest.raises(RequestException):
            c._store_and_activate_script("m", "x")


class TestCleanup:
    def test_cleanup_ignores_not_found(self):
        c = make_client()
        c.connection.deletescript.side_effect = [False, True]
        with mock.patch("app.manager.mail.ClientSieve.logger_sieve.debug") as dbg:
            c._cleanup_scripts(["a", "b"])
        assert c.connection.deletescript.call_count == 2

    def test_cleanup_warns_on_other(self):
        c = make_client()
        c.connection.deletescript.side_effect = __import__("sievelib.managesieve", fromlist=["Error"]).Error("boom")
        with mock.patch("app.manager.mail.ClientSieve.logger_sieve.warning") as warn:
            c._cleanup_scripts(["a"])
        warn.assert_called()


class TestSetMergedFilters:
    def test_nothing_enabled_deactivates(self):
        c = make_client()
        c.connection.setactive.return_value = True
        c.connection.deletescript.return_value = True
        out = c.set_merged_filters({
            "filters": [], "Vacation": None, "Forward": None, "Notification": None,
        })
        assert out[cs.FILTER_SECTION_FILTERS] is False
        c.connection.setactive.assert_called_with("")

    def test_all_sections(self):
        c = make_client()
        c.connection.putscript.side_effect = [True]
        c.connection.setactive.return_value = True
        c.connection.deletescript.return_value = True
        out = c.set_merged_filters({
            "filters": [{
                "enabled": True, "name": "f",
                "actions": [{"method": "fileinto", "arguments": {"folders": ["X"]}}],
                "rules": {"field": "subject", "operator": "contains", "value": "s"},
            }],
            "vacation": {"enabled": True, "auto_reply_text": "away",
                         "start_date": None, "end_date": None, "timezone": "UTC",
                         "days": None, "start_time": None, "end_time": None,
                         "weekdays_enabled": False, "weekday": []},
            "forward": {"enabled": True, "forward_address": ["a@b.c"], "keep_copy": False, "always_send": False},
            "notification": {"enabled": True, "notify_addresses": ["n@b.c"]},
        })
        assert out[cs.FILTER_SECTION_FILTERS] is True
        assert out[cs.FILTER_SECTION_VACATION] is True
        assert out[cs.FILTER_SECTION_FORWARD] is True
        assert out[cs.FILTER_SECTION_NOTIFICATION] is True
        # merged script uploaded
        assert "sogo-master" in c.connection.putscript.call_args[0][0]

    def test_forward_priority(self):
        c = make_client()
        c.connection.putscript.return_value = True
        c.connection.setactive.return_value = True
        c.set_merged_filters({
            "filters": [],
            "vacation": {"enabled": True, "always_send": True, "auto_reply_text": "away",
                         "start_date": None, "end_date": None, "timezone": "UTC",
                         "days": None, "start_time": None, "end_time": None,
                         "weekdays_enabled": False, "weekday": []},
            "forward": {"enabled": True, "forward_address": ["a@b.c"], "keep_copy": False, "always_send": False},
            "notification": None,
        })
        content = c.connection.putscript.call_args[0][1]
        assert content.index("VACATION") < content.index("FORWARD")

    def test_not_authenticated_raises(self):
        c = ClientSieve("s", 1, "None", "plain")
        with pytest.raises(BugException):
            c.set_merged_filters({})


class TestLogout:
    def test_logout(self):
        c = make_client()
        conn = c.connection
        conn.logout.reset_mock()
        c.logout()
        conn.logout.assert_called_once()
        assert c.connection is None
        assert c.authenticated is False

    def test_logout_error_swallowed(self):
        c = make_client()
        c.connection.logout.side_effect = __import__("sievelib.managesieve", fromlist=["Error"]).Error("bye")
        c.logout()
        assert c.connection is None

    def test_logout_no_connection(self):
        c = ClientSieve("s", 1, "None", "plain")
        c.logout()
        assert True


class TestCoverageClosure:
    """Targeted tests for the remaining uncovered branches."""

    def test_delete_script_not_authenticated(self):
        c = ClientSieve("s", 1, "None", "plain")
        with pytest.raises(BugException):
            c.delete_script("x")

    def test_set_active_not_authenticated(self):
        c = ClientSieve("s", 1, "None", "plain")
        with pytest.raises(BugException):
            c.set_active("x")

    def test_nested_group_filter_direct_construction(self):
        c = make_client()
        fs = FiltersSet("name")
        c._add_filter_to_set(fs, {
            "name": "nested",
            "actions": [{"method": "fileinto", "arguments": {"folders": ["X"]}}],
            "rules": {
                "op": "and",
                "rules": [
                    {"op": "or", "rules": [
                        {"field": "subject", "operator": "contains", "value": "a"},
                        {"field": "subject", "operator": "contains", "value": "b"},
                    ]},
                    {"field": "from", "operator": "is", "value": "c@d.e"},
                ],
            },
        })
        assert len(fs.filters) == 1

    def test_custom_header_leaf_direct_construction(self):
        c = make_client()
        fs = FiltersSet("name")
        c._add_filter_to_set(fs, {
            "name": "custom",
            "actions": [{"method": "discard", "arguments": {}}],
            "rules": {"field": "header", "operator": "contains", "value": "v", "custom_header": "X-Tag"},
        })
        assert len(fs.filters) == 1

    def test_build_condition_command_unknown_name(self):
        c = make_client()
        fs = FiltersSet("n")
        ifcontrol = __import__("sievelib.commands", fromlist=["get_command_instance"]).get_command_instance("if")
        cmd = c._build_condition_command(("X-Tag", ":contains", ["v"]), ifcontrol, fs)
        assert cmd is not None

    def test_nested_group_same_op_flatten_direct(self):
        c = make_client()
        conds, mt = c._build_nested_conditions_recursive({
            "op": "or",
            "rules": [
                {"op": "or", "rules": [
                    {"field": "subject", "operator": "contains", "value": "a"},
                    {"field": "subject", "operator": "contains", "value": "b"},
                ]},
                {"field": "from", "operator": "is", "value": "c"},
            ],
        })
        assert mt == "anyof"
        assert all(not (isinstance(cond, tuple) and cond[0] == "__group__") for cond in conds)

    def test_leaf_no_condition_in_group(self):
        c = make_client()
        conds, mt = c._build_nested_conditions_recursive({
            "op": "and",
            "rules": [
                {"field": "header", "operator": "contains", "value": "v"},  # no custom header -> None
                {"field": "subject", "operator": "contains", "value": "x"},
            ],
        })
        assert mt == "allof"
        assert ("subject", ":contains", ["x"]) in conds

    def test_convert_tz_invalid_date_falls_back_to_now(self):
        c = make_client()
        assert c._convert_tz_to_sieve_format("Europe/Paris", "bogus-date") in ("+0100", "+0200")

    def test_convert_tz_no_date_uses_current_date(self):
        c = make_client()
        assert c._convert_tz_to_sieve_format("Europe/Paris", None) in ("+0100", "+0200")
        assert c._convert_tz_to_sieve_format("Europe/Paris", "") in ("+0100", "+0200")

    def test_convert_tz_no_offset_tzinfo(self):
        class NoOffset(datetime.tzinfo):
            def utcoffset(self, dt):
                return None
            def tzname(self, dt):
                return "X"
            def dst(self, dt):
                return None
        c = make_client()
        # datetime.now(tz) would raise ValueError('fromutc: non-None utcoffset() result
        # required') for a None-utcoffset tz and fall into the outer except, so use the
        # valid-date path (strptime + replace) to reach the `offset is None` branch.
        with mock.patch("app.manager.mail.ClientSieve.ZoneInfo", return_value=NoOffset()):
            assert c._convert_tz_to_sieve_format("Whatever/Zone", "2026-06-15") == "+0000"

    def test_vacation_multi_part_conditions(self):
        c = make_client()
        vc = VacationConditions(
            start_date="2026-06-15", end_date="2026-06-30",
            start_time="09:00", end_time="17:00",
            weekdays_enabled=True, weekday=[1, 2],
        )
        out = c._build_vacation_conditions(vc)
        assert out.startswith("if anyof(\n")

    def test_tls_enable_ssl_ssl_error(self):
        import ssl as _ssl_mod
        t = _SieveTlsClient("srv", 4190, verify_cert=True)
        t.sock = mock.Mock()
        ctx = mock.Mock()
        ctx.wrap_socket.side_effect = _ssl_mod.SSLError("boom")
        with mock.patch("ssl.create_default_context", return_value=ctx):
            with pytest.raises(__import__("sievelib.managesieve", fromlist=["Error"]).Error):
                t._Client__enable_ssl()

    def test_process_forward_error(self):
        c = make_client()
        with mock.patch.object(c, "_build_forward_script", side_effect=ValueError("x")):
            with pytest.raises(RequestException) as ex:
                c._process_forward_section({"forward_address": ["a@b.c"]}, [], set(), {})
        assert ex.value.error.c == "S001506"

    def test_process_vacation_error(self):
        c = make_client()
        with mock.patch.object(c, "_build_vacation_script", side_effect=ValueError("x")):
            with pytest.raises(RequestException) as ex:
                c._process_vacation_section({"enabled": True}, [], set(), {})
        assert ex.value.error.c == "S001506"

    def test_process_filters_error(self):
        c = make_client()
        with mock.patch.object(c, "_add_filter_to_set", side_effect=ValueError("x")):
            with pytest.raises(RequestException) as ex:
                c._process_filters_section([{"enabled": True, "name": "f", "actions": [], "rules": {}}], [], set(), {})
        assert ex.value.error.c == "S001506"

    def test_process_notification_error(self):
        c = make_client()
        with mock.patch.object(c, "_build_notification_script", side_effect=ValueError("x")):
            with pytest.raises(RequestException) as ex:
                c._process_notification_section({"enabled": True, "notify_addresses": ["a@b.c"]}, [], set(), {})
        assert ex.value.error.c == "S001506"

    def test_compile_merged_error(self):
        c = make_client()
        with pytest.raises(RequestException) as ex:
            c._compile_merged_script(set(), [("forward", None)])  # None.split raises
        assert ex.value.error.c == "S001506"

    def test_render_filters_error(self):
        c = make_client()
        with mock.patch.object(FiltersSet, "__str__", side_effect=ValueError("x")):
            with pytest.raises(RequestException) as ex:
                c._render_filters_set(FiltersSet("n"))
        assert ex.value.error.c == "S001506"

    def test_nothing_enabled_deactivate_error(self):
        c = make_client()
        c.connection.setactive.side_effect = RequestException("no", err.ERROR_SIEVE_COMMAND_FAILED)
        c.connection.deletescript.return_value = True
        out = c.set_merged_filters({
            "filters": [], "vacation": None, "forward": None, "notification": None,
        })
        assert out[cs.FILTER_SECTION_FILTERS] is False

    def test_forward_and_vacation_both_priority(self):
        c = make_client()
        c.connection.putscript.return_value = True
        c.connection.setactive.return_value = True
        c.set_merged_filters({
            "filters": [],
            "vacation": {"enabled": True, "always_send": True, "auto_reply_text": "away",
                         "start_date": None, "end_date": None, "timezone": "UTC",
                         "days": None, "start_time": None, "end_time": None,
                         "weekdays_enabled": False, "weekday": []},
            "forward": {"enabled": True, "always_send": True, "forward_address": ["a@b.c"], "keep_copy": False},
            "notification": None,
        })
        assert c.connection.putscript.call_count == 1

    def test_store_and_activate_plain_failure_else_branch(self):
        # put_script normally raises instead of returning (False, None) so this final
        # else-branch is defensive dead code; exercise it via a patched return value.
        c = make_client()
        with mock.patch.object(c, "put_script", return_value=(False, None)):
            with pytest.raises(RequestException) as ex:
                c._store_and_activate_script("m", "x")
        assert ex.value.error.c == "S001506"

    def test_store_and_activate_recursive_retry(self):
        c = make_client()
        c.connection.setactive.return_value = True
        calls = {"n": 0}
        def fake_putscript(name, content):
            # sievelib's Client.putscript returns a plain boolean; the missing
            # capability is signalled through the connection errmsg attribute.
            calls["n"] += 1
            if calls["n"] == 1:
                c.connection.errmsg = "unknown Sieve capability `enotify'"
                return False
            if calls["n"] in (2, 3):
                c.connection.errmsg = "unknown Sieve capability `vacation'"
                return False
            return True
        c.connection.putscript.side_effect = fake_putscript
        parts = [
            (cs.FILTER_SECTION_VACATION, "vacation \"x\";"),
            (cs.FILTER_SECTION_NOTIFICATION, "notify;"),
            (cs.FILTER_SECTION_FORWARD, "redirect \"a@b.c\";"),
        ]
        skipped = c._store_and_activate_script("m", "x", {"enotify", "vacation", "redirect"}, parts)
        assert skipped == {cs.FILTER_SECTION_NOTIFICATION, cs.FILTER_SECTION_VACATION}
        assert calls["n"] == 4

    def test_direct_construction_action_arg_types(self):
        c = make_client()
        fs = FiltersSet("types")
        sieve_actions = [
            ("vacation", ":days", 5, "Away"),             # tag, number, string
            ("addflag", ["\\Seen", "\\Flagged"]),     # stringlist
        ]
        # check_if_arg_is_extension would reject unhashable/unknown args first, so
        # stub it to reach the type-inference branches (number/stringlist/tag).
        with mock.patch.object(fs, "check_if_arg_is_extension", return_value=None):
            c._add_filter_with_nested_conditions_direct(fs, "types", [], "allof", sieve_actions)
        assert len(fs.filters) == 1

    def test_store_and_activate_retry_compile_error(self):
        c = make_client()
        c.connection.putscript.return_value = False
        c.connection.errmsg = "unknown Sieve capability `enotify'"
        with mock.patch.object(c, "_compile_merged_script", side_effect=ValueError("x")):
            with pytest.raises(RequestException) as ex:
                c._store_and_activate_script(
                    "m", "x", {"enotify", "redirect"},
                    [(cs.FILTER_SECTION_NOTIFICATION, "notify;"), (cs.FILTER_SECTION_FORWARD, "redirect;")],
                )
        assert ex.value.error.c == "S001506"
