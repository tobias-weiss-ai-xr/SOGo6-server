"""
Unit tests for ModuleAppPassword (create / list / delete / verify round-trip).

Regression context: ``deploy/local/Dockerfile.local`` omitted ``bcrypt`` from
its hardcoded pip list (pyproject.toml declares it), so ``create`` failed with
``ModuleNotFoundError: No module named 'bcrypt'`` — masked by
InterfaceAppPassword as a misleading 404 "App Password Not Found". These tests
pin the module contract so a missing backend dependency fails loudly in CI.
"""
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from app.module.auth.ModuleAppPassword import ModuleAppPassword
from app.utils.db.Condition import EqualCondition
from app.utils.exceptions import RequestException


class FakeConn:
    def is_connected(self):
        return True


class FakeDb:
    """Minimal DB double mirroring ClientMySQL's behavior for app passwords."""

    def __init__(self):
        self.db_conn = FakeConn()
        self.rows: dict[int, tuple] = {}
        self.next_id = 1

    def connect(self):
        return None

    def insert_in_table(self, table_name, column_tuple, values_tuple):
        for values in values_tuple:
            data = dict(zip(column_tuple, values))
            record_id = self.next_id
            self.next_id += 1
            self.rows[record_id] = (
                data["hash"], data["user_uid"], data["label"],
                data["created_at"], data["last_used"], data["expires_at"],
            )

    def select_from_table(self, table_name, column_tuple, condition=None, **kwargs):
        # support both ("id","hash",...) and metadata-only selects
        want = set(column_tuple)
        out = []
        for rid, row in self.rows.items():
            full = {"id": rid, "hash": row[0], "user_uid": row[1], "label": row[2],
                    "created_at": row[3], "last_used": row[4], "expires_at": row[5]}
            cond = getattr(condition, "param_name", None)
            val = getattr(condition, "param_value", None)
            if cond and full.get(cond) != val:
                continue
            out.append(tuple(full[c] for c in column_tuple))
        return out

    def delete_row_in_table(self, table_name, condition=None, **kwargs):
        cond = getattr(condition, "param_name", None)
        value = getattr(condition, "param_value", None)
        if cond == "id" and value in self.rows:
            del self.rows[value]
            return 1
        return 0

    def update_in_table(self, table_name, column_tuple, values_list=None, condition=None, **kwargs):
        return 1


def _make_module() -> ModuleAppPassword:
    return ModuleAppPassword(FakeDb())


# ── token shape ───────────────────────────────────────────────────────────────

def test_generate_token_format():
    token = ModuleAppPassword.generate_token()
    assert token.startswith("sogo-ap-")
    assert len(token) == len("sogo-ap-") + 64  # 32 hex bytes


def test_generate_token_unique():
    assert ModuleAppPassword.generate_token() != ModuleAppPassword.generate_token()


# ── create ────────────────────────────────────────────────────────────────────

def test_create_returns_token_once_and_metadata():
    module = _make_module()
    raw_token, record = module.create("user@example.org", "Thunderbird")
    assert raw_token.startswith("sogo-ap-")
    assert record["label"] == "Thunderbird"
    assert "hash" not in record  # hash never leaves the module


def test_create_rejects_blank_label():
    module = _make_module()
    with pytest.raises(RequestException):
        module.create("user@example.org", "   ")


def test_create_stores_bcrypt_hash_not_plaintext():
    module = _make_module()
    raw_token, _ = module.create("user@example.org", "cli")
    stored = list(module._db.rows.values())[0][0]
    assert raw_token not in stored
    assert stored.startswith("$2")  # bcrypt hash prefix


# ── list ──────────────────────────────────────────────────────────────────────

def test_list_for_user_returns_metadata_only():
    module = _make_module()
    module.create("user@example.org", "a")
    module.create("user@example.org", "b")
    module.create("other@example.org", "c")  # other user
    listed = module.list_for_user("user@example.org")
    assert [x["label"] for x in listed] == ["a", "b"]
    assert all("hash" not in x for x in listed)


# ── delete ────────────────────────────────────────────────────────────────────

def test_delete_removes_record():
    module = _make_module()
    _, record = module.create("user@example.org", "doomed")
    module.delete(record["id"], "user@example.org")
    assert module.list_for_user("user@example.org") == []


def test_delete_unknown_id_raises_404_mapped_error():
    module = _make_module()
    with pytest.raises(RequestException) as excinfo:
        module.delete(9999, "user@example.org")
    assert excinfo.value.error is not None


# ── verify ────────────────────────────────────────────────────────────────────

def test_verify_round_trip_true():
    module = _make_module()
    raw_token, _ = module.create("user@example.org", "imap")
    assert module.verify("user@example.org", raw_token) is True


def test_verify_wrong_token_false():
    module = _make_module()
    module.create("user@example.org", "imap")
    assert module.verify("user@example.org", "sogo-ap-" + "0" * 64) is False


def test_verify_rejects_non_prefixed_token():
    module = _make_module()
    module.create("user@example.org", "imap")
    assert module.verify("user@example.org", "not-a-sogo-token") is False


def test_verify_expired_token_false():
    module = _make_module()
    raw_token, _ = module.create("user@example.org", "old")
    # force the single stored row to be expired
    rid = next(iter(module._db.rows))
    row = module._db.rows[rid]
    expired = datetime.now(timezone.utc) - timedelta(days=1)
    module._db.rows[rid] = (row[0], row[1], row[2], row[3], row[4], expired)
    assert module.verify("user@example.org", raw_token) is False
