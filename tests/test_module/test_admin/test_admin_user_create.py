"""
Regression: admin user creation must reject login names that can never work.

Bug (2026-08-30): ``ModuleAdminUser.create_user`` built the LDAP DN from the
raw ``uid`` field, but the login flow binds ``uid=<login-username>,<base_dn>``
where the username is the full email. Creating a user with a bare uid (e.g.
``"jdoe"``) returned 200 and stored ``uid=jdoe,...`` — an account that can
never log in, with no error anywhere. The uid is now validated up front:
it must be the full email-format login and must match ``mail``.

These tests pin the validation with a mocked LDAP client (no server needed):
the checks must fire BEFORE any directory access.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.module.admin.ModuleAdminUser import ModuleAdminUser
from app.utils.errors import ERROR_VALIDATION_ERROR
from app.utils.exceptions import RequestException


def _module() -> ModuleAdminUser:
    mod = ModuleAdminUser.__new__(ModuleAdminUser)
    return mod


def _valid_body(**overrides) -> dict:
    body = {
        "uid": "newbie@example.org",
        "cn": "New Bie",
        "sn": "Bie",
        "givenName": "New",
        "mail": "newbie@example.org",
        "password": "s3cret!Pass",
    }
    body.update(overrides)
    return body


def test_create_user_rejects_bare_uid():
    with pytest.raises(RequestException) as ex, patch.object(ModuleAdminUser, "_get_ldap_client") as ldap:
        _module().create_user(_valid_body(uid="jdoe", mail="jdoe@example.org"))
    assert ex.value.error is ERROR_VALIDATION_ERROR
    ldap.assert_not_called(), "validation must fire before any LDAP access"


def test_create_user_rejects_uid_mail_mismatch():
    with pytest.raises(RequestException) as ex, patch.object(ModuleAdminUser, "_get_ldap_client"):
        _module().create_user(_valid_body(uid="other@example.org"))
    assert ex.value.error is ERROR_VALIDATION_ERROR


def test_create_user_accepts_email_uid_and_stores_ssha_password():
    client = MagicMock()
    client._search.return_value = []  # no existing users -> uid/gid auto-assign
    client.base_dn = "ou=users,dc=example,dc=org"
    client.filter = None
    client.ldap_conn.add_s.return_value = None
    with patch.object(ModuleAdminUser, "_get_ldap_client", return_value=client):
        result = _module().create_user(_valid_body())
    assert result["dn"] == "uid=newbie@example.org,ou=users,dc=example,dc=org"
    assert result["uid"] == "newbie@example.org"
    # exactly one LDAP add with the hashed password
    (dn, entry_items), _ = client.ldap_conn.add_s.call_args
    entry = dict(entry_items)
    assert dn == "uid=newbie@example.org,ou=users,dc=example,dc=org"
    assert entry["userPassword"][0].startswith(b"{SSHA}"), "password must never be stored in plaintext"
    assert entry["userPassword"][0] != b"s3cret!Pass"
