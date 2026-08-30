"""
Unit tests for ModuleFilter persistence semantics — specifically that an
idempotent UPDATE (identical stored content, e.g. re-pushing sieve filters)
is NOT treated as a failure.

Regression: POST /mailboxes/0/filters/push returned 500 S000318
"User Profile Update Failed" every time the stored filters column was
unchanged, because MySQL reports 0 affected rows for a no-op UPDATE and
``_write_filters`` treated that as a failed persistence.
"""
from types import SimpleNamespace
from unittest import mock

import pytest

from app.module.mail.ModuleFilter import ModuleFilter
from app.utils import errors as err
from app.utils.exceptions import RequestException


class FakeSqlManager:
    """Minimal stand-in for ClientSQL covering select/update on the user table."""

    def __init__(self, filters_value, user_row_exists=True, update_affected=1):
        self.filters_value = filters_value
        self.user_row_exists = user_row_exists
        self.update_affected = update_affected

    def connect(self):
        return None

    def select_from_table(self, table_name, column_tuple, condition):
        if not self.user_row_exists:
            return []
        if column_tuple and column_tuple[0].endswith("filters"):
            # [(filters_value,)]
            return [(self.filters_value,)]
        # existence probe on uid
        return [("uid",)]

    def update_in_table(self, table_name, column_tuple, values_list, condition):
        return self.update_affected


def _make_module(fake_db, filters_value=None):
    user = SimpleNamespace(uid="testuser@example.org", login_mail_filtering="", password="pw")
    mail_settings = SimpleNamespace(SOGO_D_MAIL_FILTERING_TYPE="sieve")
    process_settings = SimpleNamespace(
        SOGO_P_DB_TYPE="MySQL", get_db_settings=lambda: {}
    )
    with mock.patch(
        "app.module.mail.ModuleFilter.import_and_instantiate_manager", return_value=fake_db
    ):
        module = ModuleFilter(user, mail_settings, process_settings)
    return module


def test_write_filters_succeeds_when_row_affected():
    fake_db = FakeSqlManager(filters_value={"filters": []})
    module = _make_module(fake_db)
    # No exception expected.
    module._write_filters({"filters": []})


def test_write_filters_idempotent_noop_is_success_when_row_exists():
    fake_db = FakeSqlManager(
        filters_value={"filters": [{"name": "a"}]}, update_affected=0
    )
    module = _make_module(fake_db)
    # 0 affected rows but the user row exists -> must NOT raise (regression fix).
    module._write_filters({"filters": [{"name": "a"}]})


def test_write_filters_raises_when_row_missing():
    fake_db = FakeSqlManager(
        filters_value=None, user_row_exists=False, update_affected=0
    )
    module = _make_module(fake_db)
    with pytest.raises(RequestException) as exc_info:
        module._write_filters({"filters": [{"name": "a"}]})
    assert exc_info.value.error == err.ERROR_USER_PROFILE_UPDATE_FAILED


def test_push_to_sieve_idempotent_does_not_5xx():
    """push_to_sieve re-persists the same content; must not raise on no-op."""
    content = {
        "filters": [{"name": "zz-e2e-spamtrap", "enabled": True}],
        "Vacation": {"enabled": True},
    }
    fake_db = FakeSqlManager(filters_value=content, update_affected=0)

    class FakeSieveClient:
        def connect(self):
            return None

        def login(self, *a, **k):
            return None

        def logout(self):
            return None

        def set_merged_filters(self, *a, **k):
            # all sections activate successfully on the (fake) sieve server
            return {"filters": True, "Vacation": True, "Forward": True, "Notification": True}

        def set_section(self, *a, **k):
            return None

    module = _make_module(fake_db)
    with mock.patch.object(
        module, "_open_filtering_client", return_value=FakeSieveClient()
    ):
        result = module.push_to_sieve()
    assert result == content
