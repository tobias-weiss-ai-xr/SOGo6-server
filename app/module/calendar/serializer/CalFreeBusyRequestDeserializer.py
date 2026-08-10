from __future__ import annotations

from typing import Generic, TypeVar

from app.module.calendar.model.CalFreeBusyRequest import CalFreeBusyRequest
from app.utils.serializer.Deserializer import Deserializer

T = TypeVar("T")


class CalFreeBusyRequestDeserializer(Deserializer[T, CalFreeBusyRequest], Generic[T]):
    """Abstract base class for free/busy deserializers."""
