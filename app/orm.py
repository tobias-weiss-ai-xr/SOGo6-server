"""Minimal ORM base layer for the SOGo 6 backend.

Exports PydanticBaseModel as the base class for validated data models.
The legacy placeholder classes Acl and db_session have been removed as
they were never used and only remained for import compatibility.
"""
from __future__ import annotations

from pydantic import BaseModel as PydanticBaseModel

__all__ = ["PydanticBaseModel"]
