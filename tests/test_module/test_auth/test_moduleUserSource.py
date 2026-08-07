"""Tests for ModuleUserSource contact lookups.

Covers the previously-stubbed ``_get_contact_info_for_user_from_user_source``:
LDAP lookup via admin-bound search, non-LDAP sources, missing source_id and
the end-to-end ``get_contact_info_for_user`` flow.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config.settings.DomainSettings import UserSourceSettingsObj
from app.module.auth.ModuleUserSource import ModuleUserSource

LDAP_SETTINGS = {
    "US_NAME": "ldap-1",
    "US_TYPE": "ldap",
    "US_LDAP_BASE_DN": "dc=example,dc=com",
    "US_LDAP_UID": "uid",
    "US_LDAP_CN": "cn",
    "US_MAIL": ["mail"],
}


def _module_with(settings: dict) -> ModuleUserSource:
    """Build a module whose user source id is ``ldap-1`` (matches make_user)."""
    return ModuleUserSource({"ldap-1": UserSourceSettingsObj(settings)})


def make_module(settings: dict) -> ModuleUserSource:
    return _module_with(settings)


class FakeLdapClient:
    """Minimal ClientLdap stand-in recording the lookup calls."""

    def __init__(self, records=None):
        self.records = records or []
        self.closed = False
        self.last_filter = None
        self.last_base = None

    def connect(self):
        pass

    def search_entries(self, base_dn=None, l_filter=None):
        self.last_base = base_dn
        self.last_filter = l_filter
        return self.records

    def close(self):
        self.closed = True


def patch_client(monkeypatch, fake) -> None:
    monkeypatch.setattr(
        "app.module.auth.ModuleUserSource.import_and_instantiate_manager",
        lambda **kwargs: fake,
    )


def make_user(**overrides) -> SimpleNamespace:
    defaults = dict(
        uid="user1",
        source_id="ldap-1",
        mail=None,
        cn=None,
        anonymous=False,
        extra_mail=None,
        extra_info=None,
        login_mail_server=None,
        login_mail_outgoing=None,
        login_mail_filtering=None,
        imap_host=None,
        authenticated=False,
        access=SimpleNamespace(),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestContactLookup:
    def test_ldap_source_returns_matching_contact(self, monkeypatch):
        fake = FakeLdapClient([{"dn": "uid=user1,dc=example,dc=com", "cn": ["John Doe"], "mail": ["john@example.com"]}])
        module = _module_with(LDAP_SETTINGS)
        patch_client(monkeypatch, fake)

        contact = module._get_contact_info_for_user_from_user_source(make_user(source_id="ldap-1"))

        assert contact["cn"] == ["John Doe"]
        assert contact["mail"] == ["john@example.com"]
        assert "dn" not in contact  # the DN must not leak into contact data
        assert fake.last_filter == "(uid=user1)"
        assert fake.last_base == "dc=example,dc=com"
        assert fake.closed is True

    def test_ldap_source_no_match_returns_empty(self, monkeypatch):
        module = _module_with(LDAP_SETTINGS)
        patch_client(monkeypatch, FakeLdapClient([]))

        contact = module._get_contact_info_for_user_from_user_source(make_user(source_id="ldap-1"))

        assert contact == {}

    def test_ldap_source_filters_entries_without_cn_or_mail(self, monkeypatch):
        """An LDAP record lacking cn/mail cannot fill contact info → skipped."""
        module = _module_with(LDAP_SETTINGS)
        patch_client(monkeypatch, FakeLdapClient([{"dn": "...", "uid": ["user1"]}]))
        assert module._get_contact_info_for_user_from_user_source(make_user(source_id="ldap-1")) == {}

    def test_ldap_lookup_error_returns_empty(self, monkeypatch):
        class BrokenClient(FakeLdapClient):
            def search_entries(self, base_dn=None, l_filter=None):
                raise RuntimeError("ldap down")

        module = _module_with(LDAP_SETTINGS)
        patch_client(monkeypatch, BrokenClient())
        assert module._get_contact_info_for_user_from_user_source(make_user(source_id="ldap-1")) == {}

    def test_sql_source_not_implemented_yet_returns_empty(self, monkeypatch):
        module = _module_with({"US_NAME": "sql-1", "US_TYPE": "mysql"})
        bogus_client = FakeLdapClient()  # must never be used
        monkeypatch.setattr(
            "app.module.auth.ModuleUserSource.import_and_instantiate_manager",
            lambda **kw: (_ for _ in ()).throw(AssertionError("sql client must not be built")),
        )
        assert module._get_contact_info_for_user_from_user_source(make_user(source_id="sql-1")) == {}

    def test_missing_source_id_returns_empty(self):
        module = _module_with(LDAP_SETTINGS)
        assert module._get_contact_info_for_user_from_user_source(make_user(source_id="")) == {}
        assert module._get_contact_info_for_user_from_user_source(make_user(source_id="ghost")) == {}


class TestGetContactInfoForUser:
    def test_full_flow_populates_user(self, monkeypatch):
        module = make_module(LDAP_SETTINGS)
        patch_client(
            monkeypatch,
            FakeLdapClient([{"cn": ["John Doe"], "mail": ["john@example.com"]}]),
        )
        user = make_user(source_id="ldap-1")
        module.get_contact_info_for_user(user)

        assert user.anonymous is False
        assert user.cn == "John Doe"
        assert user.mail == "john@example.com"

    def test_unknown_user_is_anonymous(self, monkeypatch):
        module = make_module(LDAP_SETTINGS)
        patch_client(monkeypatch, FakeLdapClient([]))
        user = make_user(source_id="ldap-1")
        module.get_contact_info_for_user(user)

        assert user.anonymous is True

class TestCheckLogin:
    """check_login: US_CAN_AUTH must gate authentication (regression for
    the inverted-condition bug where disabled sources still authed)."""

    def _module(self, can_auth: bool) -> ModuleUserSource:
        settings = dict(LDAP_SETTINGS)
        settings["US_CAN_AUTH"] = can_auth
        return _module_with(settings)

    def _stub(self, module, monkeypatch, result: bool):
        calls = {"n": 0}
        def fake_login(source_settings, user):
            calls["n"] += 1
            return (result, {}, {"cn": ["X"]})
        monkeypatch.setattr(module, "_make_us_check_login", fake_login)
        monkeypatch.setattr(module, "fill_user_with_contact_info", lambda u, i: None)
        monkeypatch.setattr(module, "fill_user_with_source_info", lambda u, i: None)
        return calls

    def test_can_auth_true_authenticates_via_primary(self, monkeypatch):
        module = self._module(can_auth=True)
        calls = self._stub(module, monkeypatch, result=True)
        user = make_user(uid="user1", source_id="ldap-1")

        assert module.check_login(user) is True
        assert user.authenticated is True
        assert calls["n"] >= 1  # primary source was consulted

    def test_can_auth_true_auth_failure_returns_false(self, monkeypatch):
        module = self._module(can_auth=True)
        calls = self._stub(module, monkeypatch, result=False)
        user = make_user(uid="user1", source_id="ldap-1")

        assert module.check_login(user) is False
        assert getattr(user, "authenticated", False) is False
        assert calls["n"] >= 1

    def test_can_auth_false_does_not_attempt_login(self, monkeypatch):
        module = self._module(can_auth=False)
        calls = self._stub(module, monkeypatch, result=True)
        user = make_user(uid="user1", source_id="ldap-1")

        # disabled source: no auth attempt, no authenticated flag
        assert module.check_login(user) is False
        assert getattr(user, "authenticated", False) is False
        assert calls["n"] == 0
