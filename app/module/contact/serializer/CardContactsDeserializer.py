from __future__ import annotations

from typing import Generic, TypeVar

from app.utils.serializer.Deserializer import Deserializer

T = TypeVar("T")


class CardContactsDeserializer(Deserializer[T, "list[CardContact]"], Generic[T]):
    """Abstract base class for deserializers that produce a list of contacts."""
