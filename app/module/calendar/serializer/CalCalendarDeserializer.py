from __future__ import annotations

from typing import Generic, TypeVar

from app.utils.serializer.Deserializer import Deserializer

T = TypeVar("T")


class CalCalendarDeserializer(Deserializer[T, "CalCalendar"], Generic[T]):
    """Abstract base class for deserializers that parse a source into a calendar collection."""
