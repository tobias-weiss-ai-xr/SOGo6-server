from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast

from app.module.contact.model.enums.CardKind import CardKind
from app.module.contact.model.enums.CardSourceType import CardSourceType
from app.module.contact.serializer.CardContactDeserializerVcard4 import CardContactDeserializerVcard4
from app.module.contact.sync.CardDavFetcher import CardDavFetcher
from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_contact
from app.utils.maths.sogo_hash import generate_uuid

if TYPE_CHECKING:
    from app.manager.cache.ClientRedis import ClientRedis
    from app.module.contact.model.CardAddressBook import CardAddressBook
    from app.module.contact.model.CardContact import CardContact
    from app.module.contact.model.CardContactSyncMeta import CardContactSyncMeta
    from app.module.contact.source.ContactSources import ContactSources

SYNC_LOCK_TTL_SECONDS: int = 300  # 5 minutes


class ContactSyncEngine:
    """Synchronizes an external CardDAV address book by mirroring its vCards into the local database.

    Fetches remote vCard data via HTTPS, parses it, and compares with the local DB by UID.
    Inserts new contacts, updates modified ones, and soft-deletes removed ones.
    The sync status is tracked in sync_config.
    """

    def __init__(self, sources: ContactSources, cache: ClientRedis) -> None:
        self._sources = sources
        self._cache = cache
        self._deserializer = CardContactDeserializerVcard4()

    def sync(self, addressbook: CardAddressBook) -> None:
        """Run a full sync for a CardDAV address book.

        Acquires a Redis lock to prevent concurrent syncs on the same address book.
        Fetches remote vCards, parses them, and applies the diff.
        """
        if addressbook.source_type != CardSourceType.CARDDAV:
            raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_NOT_SUPPORTED)

        url: str | None = (addressbook.sync_config or {}).get("url")
        if not url:
            raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_SYNC_FAILED)

        lock_key: str = f"carddav_sync_lock:{addressbook.key}"
        lock_token: str = generate_uuid()
        if not self._cache.set(lock_key, lock_token, ttl=SYNC_LOCK_TTL_SECONDS, nx=True):
            raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_SYNC_FAILED)

        self._update_sync_status(addressbook, "running")
        try:
            username: str | None = (addressbook.sync_config or {}).get("username")
            password: str | None = (addressbook.sync_config or {}).get("password")
            vcard_text: str = CardDavFetcher.fetch(url, username=username, password=password)
            self._apply_diff(addressbook, vcard_text)
            self._update_sync_status(addressbook, "completed")
            logger_contact.info(
                "CardDAV sync completed for address book %s",
                addressbook.key,
            )
        except RequestException as exc:
            self._update_sync_status(addressbook, "failed", error=exc.error.m if exc.error else "Sync failed")
            raise
        except Exception:
            logger_contact.exception("Unexpected CardDAV sync error for address book %s", addressbook.key)
            self._update_sync_status(addressbook, "failed", error="Unexpected sync error")
            raise
        finally:
            stored: str | None = cast("str | None", self._cache.get(lock_key, str))
            if stored == lock_token:
                self._cache.delete(lock_key)

    def _apply_diff(self, addressbook: CardAddressBook, vcard_text: str) -> None:
        """Parse vCard text and apply insert/update/delete to the local source.

        Splits raw vCard text into individual VCARD blocks, parses each one,
        and compares with local contacts by UID.
        """
        source = self._sources.get(addressbook)
        local_by_uid: dict[str, CardContactSyncMeta] = {
            meta.uid: meta for meta in source.get_sync_metadata() if meta.uid
        }

        remote_contacts: list[CardContact] = self._parse_vcards(vcard_text)
        remote_uids: set[str] = set()

        for remote in remote_contacts:
            if not remote.uid:
                remote.uid = generate_uuid()
            remote_uids.add(remote.uid)
            remote.addressbook_key = addressbook.require_key

            if remote.uid in local_by_uid:
                meta = local_by_uid[remote.uid]
                if self._is_modified(meta, remote):
                    remote.key = meta.key
                    source.update_contact(remote)
                    logger_contact.debug("Updated contact %s in address book %s", remote.uid, addressbook.key)
            else:
                remote.apply_defaults()
                source.insert_contact(remote)
                logger_contact.debug("Inserted contact %s in address book %s", remote.uid, addressbook.key)

        # Soft-delete local contacts that no longer exist in the remote feed
        for uid, meta in local_by_uid.items():
            if uid not in remote_uids and meta.key:
                source.delete_by_key(meta.key)
                logger_contact.debug("Deleted contact %s from address book %s", uid, addressbook.key)

    def _parse_vcards(self, vcard_text: str) -> list[CardContact]:
        """Parse raw vCard text into CardContact objects.

        Iterates VCARD blocks by BEGIN/END markers, parses each with the
        vCard 4.0 deserializer. Non-contact cards (KIND:group) are skipped.
        """
        contacts: list[CardContact] = []
        blocks: list[str] = self._split_vcards(vcard_text)
        for block in blocks:
            try:
                contact = self._deserializer.deserialize(block)
                if contact.kind == CardKind.INDIVIDUAL or contact.kind == CardKind.UNDEFINED:
                    contact.apply_defaults()
                    contacts.append(contact)
                # GROUP kind cards are distribution lists; skip them for now
            except Exception:
                logger_contact.warning("Failed to parse vCard block, skipping: %s", block[:80])
        return contacts

    @staticmethod
    def _split_vcards(text: str) -> list[str]:
        """Split multi-vCard text into individual VCARD blocks by BEGIN/END markers."""
        blocks: list[str] = []
        current: list[str] = []
        in_vcard: bool = False
        for line in text.splitlines(keepends=True):
            if "BEGIN:VCARD" in line.upper():
                in_vcard = True
                current = [line]
            elif "END:VCARD" in line.upper() and in_vcard:
                current.append(line)
                blocks.append("".join(current))
                current = []
                in_vcard = False
            elif in_vcard:
                current.append(line)
        return blocks

    def _update_sync_status(
        self, addressbook: CardAddressBook, status: str, error: str | None = None,
    ) -> None:
        """Update sync_config with current status and timestamp."""
        if addressbook.sync_config is None:
            addressbook.sync_config = {}
        addressbook.sync_config["sync_status"] = status
        addressbook.sync_config["last_sync"] = datetime.now(timezone.utc).isoformat()
        if error:
            addressbook.sync_config["sync_error"] = error
        elif "sync_error" in addressbook.sync_config:
            del addressbook.sync_config["sync_error"]
        self._sources.update_sync_config(addressbook)

    @staticmethod
    def _is_modified(meta: CardContactSyncMeta, remote: CardContact) -> bool:
        """Determine if the remote contact has been modified compared to local metadata.

        Compares REV timestamps when available, otherwise falls back to updated_at.
        """
        remote_rev = remote.rev.isoformat() if remote.rev else None
        if remote_rev and meta.rev:
            return remote_rev != str(meta.rev)
        if remote.updated_at and meta.updated_at:
            if isinstance(remote.updated_at, datetime) and isinstance(meta.updated_at, datetime):
                return remote.updated_at.timestamp() > meta.updated_at.timestamp()
        # If we can't determine, always sync (conservative)
        return True
