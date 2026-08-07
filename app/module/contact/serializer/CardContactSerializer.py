from __future__ import annotations

from typing import Generic, TypeVar

from app.utils.serializer.Serializer import Serializer

T = TypeVar("T")


class CardContactSerializer(Serializer["CardContact", T], Generic[T]):
    """Abstract base class for contact serializers."""
