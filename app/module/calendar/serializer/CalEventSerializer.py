from __future__ import annotations

from typing import Generic, TypeVar

from app.utils.serializer.Serializer import Serializer

T = TypeVar("T")


class CalEventSerializer(Serializer["CalEvent", T], Generic[T]):
    """Abstract base class for calendar event serializers."""
