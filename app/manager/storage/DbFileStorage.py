from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from app.config.db.tables import (
    COL_FS_CONTENT_HASH,
    COL_FS_CONTENT_TYPE,
    COL_FS_CREATED_AT,
    COL_FS_DATA,
    COL_FS_KEY,
    COL_FS_SOURCE,
    COL_FS_UPDATED_AT,
    TABLE_FILE_STORAGE,
)
from app.utils.db.Condition import AndCondition, EqualCondition, LessOrEqualCondition
from app.utils.exceptions import RequestException
from app.utils import errors as err

if TYPE_CHECKING:
    from app.manager.db.ClientSQL import ClientSQL


class DbFileStorage:
    """Generic binary blob store backed by the sogo6_file_storage table (key -> raw bytes + MIME).

    Knows nothing about its callers; the SQL client is injected.
    Applies size and security validations before storing files.
    """

    # Maximum file size: 100MB (can be overridden via class attribute if needed)
    MAX_FILE_SIZE: int = 100 * 1024 * 1024  # 100 MB
    
    # Allowed MIME type pattern (can be extended)
    ALLOWED_CONTENT_TYPE_PATTERN: re.Pattern[str] = re.compile(
        r'^(application|audio|font|image|text|video)/[a-zA-Z0-9+\-\.]+$'
    )
    
    # Key pattern (alphanumeric, hyphens, underscores, dots)
    ALLOWED_KEY_PATTERN: re.Pattern[str] = re.compile(r'^[a-zA-Z0-9\-_.]+$')

    def __init__(self, db: ClientSQL, max_file_size: int | None = None) -> None:
        self._db = db
        if max_file_size is not None:
            self.MAX_FILE_SIZE = max_file_size

    @staticmethod
    def _hash(data: bytes) -> str:
        """Return the sha256 hex digest used to compare payloads without loading them."""
        return hashlib.sha256(data).hexdigest()

    def write(self, key: str, data: bytes, content_type: str, source: str) -> None:
        """Persist a binary payload under a (fresh) key, with its owner source, MIME type and content hash.
        
        :param key: Unique identifier for the file (validated)
        :param data: Binary content to store
        :param content_type: MIME type of the content
        :param source: Source identifier (e.g., user UID, system module)
        :raises RequestException: If validation fails (size, content type, key format)
        """
        # Validate key format
        if not self.ALLOWED_KEY_PATTERN.match(key):
            raise RequestException(
                f"Invalid file key format: {key[:50]}",
                err.ERROR_FILE_TYPE_NOT_ALLOWED
            )
        
        # Validate file size
        if len(data) > self.MAX_FILE_SIZE:
            raise RequestException(
                f"File size ({len(data)} bytes) exceeds maximum allowed ({self.MAX_FILE_SIZE} bytes)",
                err.ERROR_FILE_TOO_LARGE
            )
        
        # Validate content type
        if not self.ALLOWED_CONTENT_TYPE_PATTERN.match(content_type):
            raise RequestException(
                f"Content type not allowed: {content_type}",
                err.ERROR_FILE_TYPE_NOT_ALLOWED
            )
        
        now: datetime = datetime.now(timezone.utc)
        self._db.insert_in_table(
            table_name=TABLE_FILE_STORAGE.name,
            column_tuple=(COL_FS_KEY.name, COL_FS_SOURCE.name, COL_FS_DATA.name, COL_FS_CONTENT_TYPE.name,
                          COL_FS_CONTENT_HASH.name, COL_FS_CREATED_AT.name, COL_FS_UPDATED_AT.name),
            values_tuple=[[key, source, data, content_type, self._hash(data), now, now]],
        )

    def is_equal(self, key: str, data: bytes, source: str) -> bool:
        """Return True when the payload stored under (key, source) has the same content as data.

        Compares the stored sha256 against the hash of data, reading only the hash column - the
        blob itself is never loaded. False when the key is absent. Scoped to `source` so one owner
        can never probe another owner's blob.
        """
        rows = list(self._db.select_from_table(
            table_name=TABLE_FILE_STORAGE.name,
            column_tuple=(COL_FS_CONTENT_HASH.name,),
            condition=self._key_in_source(key, source),
            limit=1,
        ))
        return bool(rows) and rows[0][0] == self._hash(data)

    def read(self, key: str, source: str) -> tuple[bytes, str] | None:
        """Return the (bytes, content_type) stored under (key, source), or None when absent."""
        rows = list(self._db.select_from_table(
            table_name=TABLE_FILE_STORAGE.name,
            column_tuple=(COL_FS_DATA.name, COL_FS_CONTENT_TYPE.name),
            condition=self._key_in_source(key, source),
            limit=1,
        ))
        if not rows:
            return None
        data, content_type = rows[0]
        return bytes(data), content_type  # coerce a memoryview (PostgreSQL bytea) to bytes

    def delete(self, key: str, source: str) -> None:
        """Remove the payload stored under (key, source) (no-op when absent)."""
        self._db.delete_row_in_table(
            table_name=TABLE_FILE_STORAGE.name,
            condition=self._key_in_source(key, source),
        )

    @staticmethod
    def _key_in_source(key: str, source: str) -> AndCondition:
        """Condition matching a single blob by key AND owner source (keeps point access source-scoped)."""
        return AndCondition(
            EqualCondition(COL_FS_KEY.name, key),
            EqualCondition(COL_FS_SOURCE.name, source),
        )

    def all_keys(self, source: str) -> set[str]:
        """Return every key stored under `source` (used to detect blobs no owner references any more)."""
        rows = self._db.select_from_table(
            table_name=TABLE_FILE_STORAGE.name,
            column_tuple=(COL_FS_KEY.name,),
            condition=EqualCondition(COL_FS_SOURCE.name, source),
        )
        return {row[0] for row in rows}

    def purge_older_than(self, max_age_seconds: int, source: str) -> int:
        """Delete `source` blobs older than `max_age_seconds` (by created_at); return how many were removed."""
        cutoff: datetime = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        return self._db.delete_row_in_table(
            table_name=TABLE_FILE_STORAGE.name,
            condition=AndCondition(
                EqualCondition(COL_FS_SOURCE.name, source),
                LessOrEqualCondition(COL_FS_CREATED_AT.name, cutoff),
            ),
        )
