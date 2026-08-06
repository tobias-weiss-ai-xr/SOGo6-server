"""Minimal ORM base layer for the SOGo 6 backend.

Historically ``app.orm`` was imported by ``ModuleWebAuthn`` but never created,
which made the whole ``app`` package unimportable at runtime. This module
provides the required exports:

- ``PydanticBaseModel`` — base class for validated data models.
- ``Acl`` — placeholder marker base class kept for import compatibility.
- ``db_session`` — placeholder session object kept for import compatibility.
"""
from __future__ import annotations

from pydantic import BaseModel as PydanticBaseModel


class Acl:
    """Placeholder ACL base class (kept for import compatibility)."""


class _DbSession:
    """Placeholder DB session object (kept for import compatibility)."""


db_session = _DbSession()

__all__ = ["Acl", "PydanticBaseModel", "db_session"]
