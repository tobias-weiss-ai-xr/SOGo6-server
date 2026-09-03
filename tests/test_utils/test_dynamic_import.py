"""
Unit tests for app.utils.dynamic_import — the class-by-name resolver used to
instantiate DB / outgoing managers from configuration.
"""
from __future__ import annotations

import pytest

from app.utils.dynamic_import import import_and_get_class
from app.utils.exceptions import AggravatedException


def test_imports_existing_module_and_class():
    from app.manager.outgoing.ClientSmtp import ClientSmtp
    cls = import_and_get_class("app.manager.outgoing", "ClientSmtp")
    assert cls is ClientSmtp


def test_import_error_raises_aggravated(caplog):
    with pytest.raises(AggravatedException) as exc:
        import_and_get_class("app.nonexistent_pkg", "NoSuchManager")
    assert "Cannot instantiate" in str(exc.value)
    assert exc.value.err()  # non-empty error code


def test_missing_class_attribute_raises_aggravated():
    # Module exists, attribute does not -> getattr NameError path
    with pytest.raises(AggravatedException):
        import_and_get_class("app.utils.constants", "NoSuchConstant")


def test_returns_the_class_object():
    from app.manager.db.ClientPostgreSQL import ClientPostgreSQL
    cls = import_and_get_class("app.manager.db", "ClientPostgreSQL")
    assert cls is ClientPostgreSQL
