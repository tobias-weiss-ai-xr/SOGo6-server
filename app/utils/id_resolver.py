"""Address book ID resolver.

Distinguishes between SQL-backed address books and LDAP groups.

SQL address books use numeric IDs (e.g., ``123``).
LDAP groups use string IDs with prefixes (e.g., ``ldap:engineering-team``)
or distinguished names (e.g., ``cn=team,ou=groups,dc=example,dc=org``).

The resolver returns a ``ResolvedId`` named tuple with:
- ``source_type``: 'sql' or 'ldap'
- ``raw_id``: the original ID string
- ``normalized_id``: the normalized identifier (numeric string for SQL, CN for LDAP)
- ``is_ldap``: True if LDAP group, False if SQL address book
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# Regex patterns for ID detection
_SQL_ID_PATTERN = re.compile(r"^\d+$")
_LDAP_PREFIX_PATTERN = re.compile(r"^ldap:(.+)$", re.IGNORECASE)
_LDAP_DN_PATTERN = re.compile(r"^cn=([^,]+)", re.IGNORECASE)


@dataclass(frozen=True)
class ResolvedId:
    """Result of resolving an address book or group ID."""
    source_type: str  # 'sql' or 'ldap'
    raw_id: str
    normalized_id: str
    is_ldap: bool

    @property
    def is_sql(self) -> bool:
        """Convenience property: True if SQL address book."""
        return not self.is_ldap


def resolve_address_book_id(raw_id: str | None) -> ResolvedId:
    """Resolve an address book/group ID to its source type and normalized form.

    Rules:
    - Numeric strings (e.g., '123') are SQL address books.
    - Strings with 'ldap:' prefix are LDAP groups; the normalized form is the suffix.
    - LDAP DNs (e.g., 'cn=team,ou=groups,...') are LDAP groups; the normalized form is the CN.

    :param raw_id: The original ID string from an API parameter or database.
    :return: A ResolvedId with source type, raw_id, normalized_id, and is_ldap flag.
    """
    if not raw_id:
        return ResolvedId(
            source_type="sql",
            raw_id=raw_id or "",
            normalized_id="",
            is_ldap=False,
        )

    # Check for numeric ID (SQL address book)
    if _SQL_ID_PATTERN.match(raw_id):
        return ResolvedId(
            source_type="sql",
            raw_id=raw_id,
            normalized_id=raw_id,
            is_ldap=False,
        )

    # Check for ldap: prefix (LDAP group with explicit prefix)
    ldap_prefix_match = _LDAP_PREFIX_PATTERN.match(raw_id)
    if ldap_prefix_match:
        normalized = ldap_prefix_match.group(1)
        return ResolvedId(
            source_type="ldap",
            raw_id=raw_id,
            normalized_id=normalized,
            is_ldap=True,
        )

    # Check for LDAP DN (cn=...)
    dn_match = _LDAP_DN_PATTERN.match(raw_id)
    if dn_match:
        cn = dn_match.group(1)
        return ResolvedId(
            source_type="ldap",
            raw_id=raw_id,
            normalized_id=cn,
            is_ldap=True,
        )

    # Default to SQL for backwards compatibility
    return ResolvedId(
        source_type="sql",
        raw_id=raw_id,
        normalized_id=raw_id,
        is_ldap=False,
    )


def is_ldap_group(raw_id: str | None) -> bool:
    """Check if an ID represents an LDAP group.

    :param raw_id: The ID to check.
    :return: True if the ID is an LDAP group (prefix or DN format).
    """
    return resolve_address_book_id(raw_id).is_ldap


def is_sql_address_book(raw_id: str | None) -> bool:
    """Check if an ID represents a SQL address book.

    :param raw_id: The ID to check.
    :return: True if the ID is a numeric SQL address book ID.
    """
    return resolve_address_book_id(raw_id).is_sql


def normalize_id(raw_id: str | None) -> str:
    """Normalize an address book/group ID.

    SQL IDs remain unchanged. LDAP group IDs are normalized to their CN.

    :param raw_id: The original ID.
    :return: The normalized ID (CN for LDAP, original for SQL).
    """
    return resolve_address_book_id(raw_id).normalized_id
