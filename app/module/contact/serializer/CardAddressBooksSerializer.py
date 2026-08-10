from __future__ import annotations

from typing import Generic, TypeVar

from app.utils.serializer.Serializer import Serializer

T = TypeVar("T")


class CardAddressBooksSerializer(Serializer["list[CardAddressBook]", T], Generic[T]):
    """Abstract base class for serializers that convert a list of address books."""
