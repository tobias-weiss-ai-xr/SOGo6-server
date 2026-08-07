from __future__ import annotations

from typing import Generic, TypeVar

from app.utils.serializer.Deserializer import Deserializer

T = TypeVar("T")


class CalEventsDeserializer(Deserializer[T, "list[CalEvent]"], Generic[T]):
    """Abstract base class for deserializers that parse a string into a list of events."""
