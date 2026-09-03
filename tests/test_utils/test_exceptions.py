"""
Unit tests for app.utils.exceptions — the SOGo error/exception contract.

Regression coverage for Bug #51: several callers raise RequestException with
``m=`` / ``error_msg=`` message aliases and an explicit ``http_status=``
override (shared-mailbox send 403/404, admin email-auth), but the base class
accepted neither — those paths blew up with TypeError (→500). These tests pin
the full call convention surface so every caller style works and the
``http_status`` override survives.
"""
from __future__ import annotations

import pytest

from app.utils import errors as err
from app.utils.exceptions import (
    AggravatedException,
    BugException,
    RequestException,
    SogoException,
)

NOT_FOUND = err.ERROR_NOT_FOUND  # S000003, 404


# ---------------------------------------------------------------------------
# Construction conventions
# ---------------------------------------------------------------------------

def test_default_message_comes_from_error():
    exc = SogoException(error=NOT_FOUND)
    assert str(exc) == NOT_FOUND.m
    assert exc.http_status == 404
    assert exc.err() == "S000003"


def test_message_kwarg_wins_over_error_message():
    exc = SogoException("custom", error=NOT_FOUND)
    assert str(exc) == "custom"
    assert exc.http_status == 404


def test_positional_message():
    exc = SogoException("pos msg")
    assert str(exc) == "pos msg"


def test_m_alias_sets_message():
    # The shared-mailbox send paths use this convention.
    exc = SogoException(m="Shared mailbox not found", error=err.ERROR_SHARED_MAILBOX_NOT_FOUND)
    assert str(exc) == "Shared mailbox not found"
    assert exc.http_status == 404


def test_error_msg_alias_sets_message():
    exc = SogoException(error_msg="boom", error=NOT_FOUND)
    assert str(exc) == "boom"


def test_message_priority_over_aliases():
    exc = SogoException("canonical", m="alias", error_msg="also alias", error=NOT_FOUND)
    assert str(exc) == "canonical"


# ---------------------------------------------------------------------------
# http_status override (Bug #51)
# ---------------------------------------------------------------------------

def test_http_status_override_beats_error_status():
    # non-member shared mailbox: 403 while reusing the NOT_FOUND error code
    exc = SogoException(
        m="Access denied", error=err.ERROR_SHARED_MAILBOX_NOT_FOUND, http_status=403)
    assert exc.http_status == 403
    assert exc.error.c == err.ERROR_SHARED_MAILBOX_NOT_FOUND.c


def test_http_status_defaults_to_error_status():
    exc = SogoException(error=NOT_FOUND)
    assert exc.http_status == 404
    exc2 = SogoException(error=err.ERROR_UNKOWN)
    assert exc2.http_status == err.ERROR_UNKOWN.h


# ---------------------------------------------------------------------------
# Subclasses
# ---------------------------------------------------------------------------

def test_request_exception_with_m_and_http_status():
    exc = RequestException(
        m="Shared mailbox not found", error=err.ERROR_SHARED_MAILBOX_NOT_FOUND, http_status=404)
    assert isinstance(exc, SogoException)
    assert exc.err() == "S000383"
    assert exc.http_status == 404


def test_aggravated_exception_is_sogo_exception():
    exc = AggravatedException("db down", error=err.ERROR_CONFIG_ERROR)
    assert str(exc) == "db down"
    assert exc.err() == err.ERROR_CONFIG_ERROR.c


def test_bug_exception_is_sogo_exception():
    exc = BugException("unexpected", error=err.ERROR_UNKOWN)
    assert isinstance(exc, SogoException)


def test_exceptions_are_raiseable_and_catchable():
    with pytest.raises(SogoException) as caught:
        raise RequestException(
            m="no row", error=err.ERROR_TMP_DRAFT_NOT_FOUND, http_status=404)
    assert caught.value.err() == "S000371"
    assert caught.value.http_status == 404
