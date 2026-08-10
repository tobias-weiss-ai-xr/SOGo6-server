"""End-to-end tests for ContactSyncEngine (CardDAV sync).

Tests the full pipeline: fetch → parse vCards → diff by UID → insert/update/delete,
with the HTTP fetcher patched but the real vCard deserializer and diff engine exercised.
Uses mocked sources/cache (same pattern as test_SyncEngine).
"""
from unittest.mock import MagicMock, patch

import pytest

from app.module.contact.model.CardAddressBook import CardAddressBook
from app.module.contact.model.CardContact import CardContact
from app.module.contact.model.CardContactSyncMeta import CardContactSyncMeta
from app.module.contact.model.enums.CardSourceType import CardSourceType
from app.module.contact.sync.ContactSyncEngine import ContactSyncEngine
from app.utils import errors as err
from app.utils.exceptions import RequestException


# A vCard 4.0 payload with two contacts
_VCARD_TWO = """BEGIN:VCARD
VERSION:4.0
UID:alice-uid
FN:Alice Johnson
N:Johnson;Alice;;;
EMAIL;TYPE=work:alice@example.com
TEL;TYPE=cell:+12025550001
END:VCARD
BEGIN:VCARD
VERSION:4.0
UID:bob-uid
FN:Bob Smith
N:Smith;Bob;;;
EMAIL;TYPE=home:bob@example.com
END:VCARD
"""

# Update: Alice's phone changed, Bob removed, Carol added
_VCARD_UPDATED = """BEGIN:VCARD
VERSION:4.0
UID:alice-uid
FN:Alice Johnson
N:Johnson;Alice;;;
EMAIL;TYPE=work:alice@example.com
TEL;TYPE=cell:+12025559999
END:VCARD
BEGIN:VCARD
VERSION:4.0
UID:carol-uid
FN:Carol Williams
N:Williams;Carol;;;
EMAIL;TYPE=work:carol@example.com
END:VCARD
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_book(**kwargs):
    """Create a CardAddressBook with CARDDAV source type and default sync_config."""
    defaults = dict(
        user_uid="testuser@example.org",
        name="CardDAV Test",
        key="carddav-test-key",
        source_type=CardSourceType.CARDDAV,
        sync_config={"url": "https://carddav.example.com/contacts/", "sync_interval_minutes": 60},
    )
    defaults.update(kwargs)
    return CardAddressBook(**defaults)


def _make_meta(uid: str, key: str | None = None) -> CardContactSyncMeta:
    """Create a sync metadata entry for a contact."""
    return CardContactSyncMeta(
        key=key or f"key-{uid}",
        uid=uid,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@patch("app.module.contact.sync.ContactSyncEngine.CardDavFetcher")
def test_sync_inserts_new_contacts(mock_fetcher):
    """First sync: two new contacts are inserted from the vCard feed."""
    mock_fetcher.fetch.return_value = _VCARD_TWO

    sources = MagicMock()
    cache = MagicMock()
    cache.set.return_value = True

    mock_source = MagicMock()
    mock_source.get_sync_metadata.return_value = []
    sources.get.return_value = mock_source

    engine = ContactSyncEngine(sources=sources, cache=cache)
    engine.sync(_make_book())

    # Two contacts inserted
    assert mock_source.insert_contact.call_count == 2
    mock_source.update_contact.assert_not_called()
    mock_source.delete_by_key.assert_not_called()

    # Verify the correct contacts were inserted
    inserted_uids = {call.args[0].uid for call in mock_source.insert_contact.call_args_list}
    assert inserted_uids == {"alice-uid", "bob-uid"}

    # Verify sync status updated (called for 'running' then 'completed')
    assert sources.update_sync_config.call_count == 2
    # Last call should be 'completed'
    call_book = sources.update_sync_config.call_args_list[-1][0][0]
    assert call_book.sync_config["sync_status"] == "completed"
    assert "last_sync" in call_book.sync_config


@patch("app.module.contact.sync.ContactSyncEngine.CardDavFetcher")
def test_sync_inserts_contacts_without_uid(mock_fetcher):
    """A vCard without UID gets one auto-generated."""
    vcard_no_uid = """BEGIN:VCARD
VERSION:4.0
FN:No UID Contact
EMAIL;TYPE=work:no@example.com
END:VCARD
"""
    mock_fetcher.fetch.return_value = vcard_no_uid

    sources = MagicMock()
    cache = MagicMock()
    cache.set.return_value = True

    mock_source = MagicMock()
    mock_source.get_sync_metadata.return_value = []
    sources.get.return_value = mock_source

    engine = ContactSyncEngine(sources=sources, cache=cache)
    engine.sync(_make_book())

    assert mock_source.insert_contact.call_count == 1
    inserted: CardContact = mock_source.insert_contact.call_args[0][0]
    assert inserted.uid is not None  # auto-generated
    assert inserted.display_name == "No UID Contact"


@patch("app.module.contact.sync.ContactSyncEngine.CardDavFetcher")
def test_sync_updates_and_deletes(mock_fetcher):
    """Second sync: update Alice, remove Bob, insert Carol."""
    mock_fetcher.fetch.return_value = _VCARD_TWO

    sources = MagicMock()
    cache = MagicMock()
    cache.set.return_value = True

    mock_source = MagicMock()
    # First sync: no local data
    mock_source.get_sync_metadata.return_value = []
    sources.get.return_value = mock_source

    engine = ContactSyncEngine(sources=sources, cache=cache)
    engine.sync(_make_book())

    # Second sync: now Alice exists locally
    mock_source.get_sync_metadata.return_value = [
        _make_meta("alice-uid", key="alice-key"),
        _make_meta("bob-uid", key="bob-key"),
    ]
    mock_source.insert_contact.reset_mock()
    mock_source.update_contact.reset_mock()
    mock_source.delete_by_key.reset_mock()
    mock_fetcher.fetch.return_value = _VCARD_UPDATED

    engine.sync(_make_book())

    # Alice updated (phone changed)
    mock_source.update_contact.assert_called_once()
    updated: CardContact = mock_source.update_contact.call_args[0][0]
    assert updated.uid == "alice-uid"
    assert updated.key == "alice-key"  # same key preserved
    assert updated.phones[0].number == "+12025559999"

    # Carol inserted (new)
    mock_source.insert_contact.assert_called_once()
    inserted: CardContact = mock_source.insert_contact.call_args[0][0]
    assert inserted.uid == "carol-uid"

    # Bob deleted (removed from feed)
    mock_source.delete_by_key.assert_called_once_with("bob-key")


@patch("app.module.contact.sync.ContactSyncEngine.CardDavFetcher")
def test_sync_empty_feed_deletes_all(mock_fetcher):
    """Empty vCard feed removes all local contacts (mirror semantics)."""
    mock_fetcher.fetch.return_value = _VCARD_TWO

    sources = MagicMock()
    cache = MagicMock()
    cache.set.return_value = True

    mock_source = MagicMock()
    mock_source.get_sync_metadata.return_value = []
    sources.get.return_value = mock_source

    engine = ContactSyncEngine(sources=sources, cache=cache)
    engine.sync(_make_book())

    # Reset and set local data
    mock_source.get_sync_metadata.return_value = [
        _make_meta("alice-uid", key="alice-key"),
        _make_meta("bob-uid", key="bob-key"),
    ]
    mock_source.delete_by_key.reset_mock()
    mock_fetcher.fetch.return_value = ""

    engine.sync(_make_book())

    assert mock_source.delete_by_key.call_count == 2
    deleted_keys = {call.args[0] for call in mock_source.delete_by_key.call_args_list}
    assert deleted_keys == {"alice-key", "bob-key"}


@patch("app.module.contact.sync.ContactSyncEngine.CardDavFetcher")
def test_sync_rejects_local_addressbook(mock_fetcher):
    """Syncing a LOCAL address book raises NOT_SUPPORTED."""
    sources = MagicMock()
    cache = MagicMock()
    cache.set.return_value = True

    engine = ContactSyncEngine(sources=sources, cache=cache)
    with pytest.raises(RequestException) as exc:
        engine.sync(_make_book(source_type=CardSourceType.LOCAL))
    assert exc.value.error == err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED


@patch("app.module.contact.sync.ContactSyncEngine.CardDavFetcher")
def test_sync_rejects_missing_url(mock_fetcher):
    """An address book without a sync_config URL raises SYNC_FAILED."""
    sources = MagicMock()
    cache = MagicMock()
    cache.set.return_value = True

    engine = ContactSyncEngine(sources=sources, cache=cache)
    with pytest.raises(RequestException) as exc:
        engine.sync(_make_book(sync_config={"sync_status": "pending"}))
    assert exc.value.error == err.ERROR_CONTACT_ADDRESSBOOK_SYNC_FAILED


@patch("app.module.contact.sync.ContactSyncEngine.CardDavFetcher")
def test_sync_skips_group_cards(mock_fetcher):
    """Group/List vCards (KIND:group) are not imported as contacts."""
    vcard_with_group = _VCARD_TWO + """BEGIN:VCARD
VERSION:4.0
UID:group-uid
FN:My Team
KIND:group
MEMBER:urn:uuid:alice-uid
MEMBER:urn:uuid:bob-uid
END:VCARD
"""
    mock_fetcher.fetch.return_value = vcard_with_group

    sources = MagicMock()
    cache = MagicMock()
    cache.set.return_value = True

    mock_source = MagicMock()
    mock_source.get_sync_metadata.return_value = []
    sources.get.return_value = mock_source

    engine = ContactSyncEngine(sources=sources, cache=cache)
    engine.sync(_make_book())

    # Only two individual contacts inserted, not the group
    assert mock_source.insert_contact.call_count == 2
    inserted_uids = {call.args[0].uid for call in mock_source.insert_contact.call_args_list}
    assert "group-uid" not in inserted_uids


@patch("app.module.contact.sync.ContactSyncEngine.CardDavFetcher")
def test_sync_concurrent_lock_rejected(mock_fetcher):
    """A concurrent sync attempt is rejected when the Redis lock is held."""
    sources = MagicMock()
    cache = MagicMock()
    cache.set.return_value = False  # lock not acquired

    engine = ContactSyncEngine(sources=sources, cache=cache)
    with pytest.raises(RequestException) as exc:
        engine.sync(_make_book())
    assert exc.value.error == err.ERROR_CONTACT_ADDRESSBOOK_SYNC_FAILED


@patch("app.module.contact.sync.ContactSyncEngine.CardDavFetcher")
def test_sync_releases_lock_on_failure(mock_fetcher):
    """The Redis lock is released even when sync fails."""
    # Track the lock token that the engine sets so we can return it from cache.get
    stored_token: list[str] = []
    def _set_side_effect(key, token, **kwargs):
        stored_token.append(token)
        return True
    def _get_side_effect(key, type_cast=None):
        return stored_token[0] if stored_token else None

    mock_fetcher.fetch.side_effect = RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_SYNC_FAILED)

    sources = MagicMock()
    cache = MagicMock()
    cache.set.side_effect = _set_side_effect
    cache.get.side_effect = _get_side_effect

    engine = ContactSyncEngine(sources=sources, cache=cache)

    with pytest.raises(RequestException):
        engine.sync(_make_book())

    # Lock should be deleted after failure
    cache.delete.assert_called_once()


@patch("app.module.contact.sync.ContactSyncEngine.CardDavFetcher")
def test_sync_accepts_vcard3_format(mock_fetcher):
    """vCard 3.0 data is parsed through the vCard 4.0 deserializer (tolerant)."""
    vcard3 = """BEGIN:VCARD
VERSION:3.0
UID:v3-uid
FN:V3 Contact
N:Contact;V3;;;
TEL;TYPE=CELL:+12025551111
END:VCARD
"""
    mock_fetcher.fetch.return_value = vcard3

    sources = MagicMock()
    cache = MagicMock()
    cache.set.return_value = True

    mock_source = MagicMock()
    mock_source.get_sync_metadata.return_value = []
    sources.get.return_value = mock_source

    engine = ContactSyncEngine(sources=sources, cache=cache)
    engine.sync(_make_book())

    assert mock_source.insert_contact.call_count == 1
    inserted: CardContact = mock_source.insert_contact.call_args[0][0]
    assert inserted.uid == "v3-uid"
    assert inserted.display_name == "V3 Contact"
    assert inserted.phones[0].number == "+12025551111"
