"""Unit tests for DbFileStorage.write content-type validation (parameters allowed).

The vCard export stores documents with parameter-bearing media types such as
``text/vcard; charset=utf-8; version=3.0`` — legal per RFC 9110. The
allow-list must validate the bare media type and ignore parameters
(regression for the contact.export job failing with
``Content type not allowed: text/vcard; charset=utf-8; version=3.0``).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.manager.storage.DbFileStorage import DbFileStorage
from app.utils import errors as err
from app.utils.exceptions import RequestException


def _storage() -> DbFileStorage:
    db = MagicMock()
    db.insert_in_table.return_value = None
    return DbFileStorage(db)


def _match(exc: RequestException, expected) -> bool:
    return exc.error is expected or getattr(exc.error, "c", None) == getattr(expected, "c", None)


def test_save_accepts_parameterized_media_type():
    """text/vcard with charset/version parameters must be accepted."""
    storage = _storage()
    storage.write("key-1", b"BEGIN:VCARD", "text/vcard; charset=utf-8; version=3.0", "source")
    assert storage._db.insert_in_table.called


def test_save_accepts_bare_media_types():
    """Plain type/subtype values keep working."""
    storage = _storage()
    for content_type in ("text/calendar", "application/json", "image/png"):
        storage.write("key-bare", b"x", content_type, "source")
    assert storage._db.insert_in_table.call_count == 3


def test_save_still_rejects_disallowed_base_type():
    """The allow-list still applies to the bare type (parameters don't sneak by).

    NOTE: `application/x-executable` is accepted by the pattern (x- subtype
    tokens match); only foreign top-level families are rejected.
    """
    storage = _storage()
    for content_type in ("message/rfc822", "example/blob; charset=utf-8"):
        with pytest.raises(RequestException) as exc:
            storage.write("key-x", b"x", content_type, "source")
        assert _match(exc.value, err.ERROR_FILE_TYPE_NOT_ALLOWED)


def test_save_still_rejects_garbage_content_type():
    storage = _storage()
    with pytest.raises(RequestException) as exc:
        storage.write("key-y", b"x", "not-a-media-type", "source")
    assert _match(exc.value, err.ERROR_FILE_TYPE_NOT_ALLOWED)
