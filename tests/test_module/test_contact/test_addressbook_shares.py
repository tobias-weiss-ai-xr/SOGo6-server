"""Unit tests for addressbook share semantics (ModuleContact.add_share).

Pins (round 10):
  - adding a share for a user who already has one raises
    ERROR_CONTACT_SHARE_DUPLICATE ("Share Already Exists", 409) — it used to
    reuse ERROR_CONTACT_ADDRESSBOOK_DUPLICATE ("Address Book Already
    Exists"), which misdescribed the conflict.
  - InterfaceApiContactContact.add_share returns HTTP 201 on success
    (matching the route's declared @blp.response(201, ...)).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.config.settings.ProcessSetting import ProcessSetting
from app.module.contact.model.ContactShare import ContactShare
from app.module.contact.ModuleContact import ModuleContact
from app.utils import errors as err
from app.utils.exceptions import RequestException


def _module_with(existing: ContactShare | None) -> tuple[ModuleContact, Any]:
    module = ModuleContact.__new__(ModuleContact)
    module._share_repo = MagicMock()
    module._share_repo.find_by_addressbook_and_user.return_value = existing
    module._share_repo.insert.return_value = ContactShare(
        addressbook_key="ab-1", user_uid="u2@example.org", share_level=MagicMock(name="share_level"),
    )
    return module, module._share_repo


def _share() -> ContactShare:
    return ContactShare(addressbook_key="ab-1", user_uid="u2@example.org", share_level=None)


def test_add_share_duplicate_raises_share_duplicate_error():
    module, _ = _module_with(existing=_share())
    with pytest.raises(RequestException) as exc:
        module.add_share("ab-1", _share())
    assert exc.value.error.c == "S000721"
    assert exc.value.error.m == "Share Already Exists"


def test_add_share_fresh_insert_persists():
    module, repo = _module_with(existing=None)
    created = module.add_share("ab-1", _share())
    repo.insert.assert_called_once()
    assert created is repo.insert.return_value


def test_interface_add_share_returns_201():
    """The interface must honour the route's declared 201 Created."""
    from app.interface.contact.InterfaceApiContactContact import InterfaceApiContactContact

    interface = InterfaceApiContactContact.__new__(InterfaceApiContactContact)
    interface.user_uid = "u1@example.org"
    interface.module = MagicMock()
    share = ContactShare(addressbook_key="ab-1", user_uid="u2@example.org")
    interface.module.add_share.return_value = share
    body, status = interface.add_share("ab-1", {"user_uid": "u2@example.org"})
    assert status == 201
    assert body["data"] == {"user_uid": "u2@example.org", "share_level": share.share_level.name.lower()}
