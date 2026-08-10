from __future__ import annotations

from typing import Generic, TypeVar

from app.utils.serializer.Serializer import Serializer

T = TypeVar("T")


class CardListSerializer(Serializer["CardList", T], Generic[T]):
    """Abstract base class for distribution list serializers."""
