"""Unit tests for the wired contact ACL path (ContactAclEngine <-> sogo6_acl).

Covers the migration wiring with a mocked ClientSQL (no live DB required),
following the pattern of tests/unit/test_factory/test_share.py:

- unified path: a sogo6_acl entry (type='addressbook') is resolved by a real
  ShareContact backed by a mocked ClientSQL via ShareContact.has_right()
  (edit right -> MODIFY, view right -> VIEW), flowing into get_share_level
  and check_permission;
- legacy fallback: an empty sogo6_acl falls back to a mocked legacy
  RepositoryContactShare and yields the legacy share level; when both sources
  are empty the engine denies.
"""

from unittest.mock import MagicMock

import pytest

from app.auth.User import User
from app.config.db import tables as tbl
from app.factory.share import CONTACT_RESOURCE_TYPE, ShareContact
from app.module.contact.acl.ContactAclEngine import ContactAclEngine
from app.module.contact.model.CardAddressBook import CardAddressBook
from app.module.contact.model.ContactShare import ContactShare
from app.module.contact.model.enums.ContactShareLevel import ContactShareLevel
from app.module.contact.repository.RepositoryContactShare import RepositoryContactShare
from app.utils import errors as err
from app.utils.exceptions import RequestException

OWNER_UID = "alice@example.org"
ACTING_UID = "bob@example.org"
ADDRESSBOOK_KEY = "ab-42"

# API-shaped rights blobs as stored in sogo6_acl.rights (ContactShareRightsSchema).
EDIT_RIGHTS = {
    "can_view": True,
    "can_create_objects": True,
    "can_edit_objects": True,
    "can_erase_objects": False,
}
VIEW_ONLY_RIGHTS = {
    "can_view": True,
    "can_create_objects": False,
    "can_edit_objects": False,
    "can_erase_objects": False,
}


def _acl_db(rows):
    """Mocked ClientSQL whose select_from_table returns the given sogo6_acl rows."""
    db = MagicMock()
    db.select_from_table.return_value = rows
    return db


def _acl_row(rights):
    """One sogo6_acl row in ALL_ACL_COL order: (id, type, key, owner, to_user, rights)."""
    return (1, CONTACT_RESOURCE_TYPE, ADDRESSBOOK_KEY, OWNER_UID, ACTING_UID, rights)


def _share_contact(rows):
    return ShareContact(db=_acl_db(rows))


def _legacy_repo(share=None):
    repo = MagicMock(spec=RepositoryContactShare)
    repo.find_by_addressbook_and_user.return_value = share
    return repo


def _addressbook():
    return CardAddressBook(user_uid=OWNER_UID, name="Alice Book", key=ADDRESSBOOK_KEY)


def _user():
    return User(uid=ACTING_UID)


def _assert_acl_queried(engine_db):
    """Assert every select went to sogo6_acl (the unified table), not the legacy one."""
    assert engine_db.select_from_table.call_args_list
    for call in engine_db.select_from_table.call_args_list:
        assert call.kwargs.get("table") is tbl.TABLE_ACL


class TestContactUnifiedPath:
    """Non-owner resolution through a ShareContact-backed sogo6_acl entry."""

    def test_edit_right_maps_to_modify(self):
        share_contact = _share_contact([_acl_row(EDIT_RIGHTS)])
        engine = ContactAclEngine(
            share_repo=_legacy_repo(), share_contact=share_contact,
        )

        level = engine.get_share_level(_addressbook(), _user())

        assert level is ContactShareLevel.MODIFY
        # MODIFY satisfies both VIEW and MODIFY requirements.
        engine.check_permission(level, ContactShareLevel.VIEW)
        engine.check_permission(level, ContactShareLevel.MODIFY)

    def test_view_only_right_maps_to_view(self):
        share_contact = _share_contact([_acl_row(VIEW_ONLY_RIGHTS)])
        engine = ContactAclEngine(share_contact=share_contact)

        level = engine.get_share_level(_addressbook(), _user())

        assert level is ContactShareLevel.VIEW
        engine.check_permission(level, ContactShareLevel.VIEW)
        # VIEW does not satisfy a MODIFY requirement.
        with pytest.raises(RequestException) as exc_info:
            engine.check_permission(level, ContactShareLevel.MODIFY)
        assert exc_info.value.error == err.ERROR_CONTACT_ACCESS_DENIED

    def test_unified_path_skips_legacy_repository(self):
        legacy_repo = _legacy_repo()
        share_contact = _share_contact([_acl_row(EDIT_RIGHTS)])
        engine = ContactAclEngine(share_repo=legacy_repo, share_contact=share_contact)

        engine.get_share_level(_addressbook(), _user())

        legacy_repo.find_by_addressbook_and_user.assert_not_called()
        _assert_acl_queried(share_contact._repo._db)


class TestContactLegacyFallback:
    """Empty sogo6_acl (has_right -> False for every right) falls back to the legacy repository."""

    def test_empty_acl_falls_back_to_legacy_share(self):
        legacy_share = ContactShare(
            user_uid=ACTING_UID,
            addressbook_key=ADDRESSBOOK_KEY,
            share_level=ContactShareLevel.VIEW,
        )
        legacy_repo = _legacy_repo(share=legacy_share)
        share_contact = _share_contact([])  # empty sogo6_acl
        engine = ContactAclEngine(share_repo=legacy_repo, share_contact=share_contact)

        level = engine.get_share_level(_addressbook(), _user())

        assert level is ContactShareLevel.VIEW
        # The unified table was consulted first, then the legacy repo with
        # (addressbook key, acting user uid).
        _assert_acl_queried(share_contact._repo._db)
        legacy_repo.find_by_addressbook_and_user.assert_called_once_with(
            ADDRESSBOOK_KEY, ACTING_UID,
        )

    def test_fallback_modify_share_level_drives_check_permission(self):
        legacy_share = ContactShare(
            user_uid=ACTING_UID,
            addressbook_key=ADDRESSBOOK_KEY,
            share_level=ContactShareLevel.MODIFY,
        )
        engine = ContactAclEngine(
            share_repo=_legacy_repo(share=legacy_share),
            share_contact=_share_contact([]),
        )

        level = engine.get_share_level(_addressbook(), _user())

        assert level is ContactShareLevel.MODIFY
        engine.check_permission(level, ContactShareLevel.MODIFY)

    def test_no_share_contact_injected_uses_legacy_directly(self):
        # Engines not yet wired with a ShareContact keep the legacy-only path.
        legacy_share = ContactShare(
            user_uid=ACTING_UID,
            addressbook_key=ADDRESSBOOK_KEY,
            share_level=ContactShareLevel.MODIFY,
        )
        engine = ContactAclEngine(share_repo=_legacy_repo(share=legacy_share))

        level = engine.get_share_level(_addressbook(), _user())

        assert level is ContactShareLevel.MODIFY

    def test_denied_when_acl_and_legacy_both_empty(self):
        engine = ContactAclEngine(
            share_repo=_legacy_repo(share=None),
            share_contact=_share_contact([]),
        )

        level = engine.get_share_level(_addressbook(), _user())

        assert level is None
        with pytest.raises(RequestException) as exc_info:
            engine.check_permission(level, ContactShareLevel.VIEW)
        assert exc_info.value.error == err.ERROR_CONTACT_ACCESS_DENIED
