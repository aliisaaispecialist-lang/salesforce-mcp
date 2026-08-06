"""Making returned data genuinely read-only.

Pydantic's frozen=True freezes a model's attributes, not the containers inside
them, so a caller could still reach into a result's payload and change it. That
is a shallow guarantee, and a shallow guarantee about immutability is worth
very little: the bug it invites is a caller mutating a cached response and the
next reader seeing something that never came from Salesforce.

Freezing at the boundary closes it. The cost is one pass over each response.
"""

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any


def freeze(value: object) -> Any:
    """Return the same data, in a form that cannot be modified.

    Mappings become read-only views and lists become tuples, recursively.
    Strings and bytes are left alone: both are sequences, and iterating them
    element by element would turn a name into a tuple of letters.

    Args:
        value: Parsed JSON of any shape.

    Returns:
        The same data, where every container rejects mutation.
    """
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(held) for key, held in value.items()})
    if isinstance(value, (str, bytes)):
        return value
    if isinstance(value, Sequence):
        return tuple(freeze(item) for item in value)
    return value
