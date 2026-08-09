"""Saying what a field expects in words a model cannot misread.

A JSON Schema states the type precisely and states it in a vocabulary written
for validators. `{"anyOf": [{"type": "number"}, {"type": "null"}]}` is exact,
and it is also the shape a weaker model reads as "some kind of value", which is
how `amount` arrives as the word "one" instead of the digits 45000.

So the type is said twice: once in the schema, for anything that validates, and
once in English, for whoever is composing the call. This module is the second
one, and it is derived from the first rather than written by hand, so the two
cannot drift apart.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Final

_WORDS: Final[Mapping[str, str]] = {
    "string": "text",
    "integer": "a whole number, written in digits",
    "number": "a number, written in digits",
    "boolean": "true or false",
    "array": "a list",
    "object": "an object of name and value pairs",
}

_FORMATS: Final[Mapping[str, str]] = {
    "date": "a date, written as YYYY-MM-DD",
    "date-time": "a date and time, written as YYYY-MM-DDTHH:MM:SS",
    "email": "an email address",
    "uri": "a URL",
}


def in_words(field: Mapping[str, Any], root: Mapping[str, Any] | None = None) -> str:
    """Describe what this field accepts, in a sentence rather than a schema.

    Enumerated values are listed rather than named as an enum, because a model
    that is told the permitted values does not have to guess one, and guessing
    one is what a restricted picklist rejects.
    """
    chosen = _resolved(_meaningful(field), root)
    allowed = chosen.get("enum")
    if isinstance(allowed, Sequence) and not isinstance(allowed, str) and allowed:
        return "exactly one of: " + ", ".join(str(value) for value in allowed)

    named = _FORMATS.get(str(chosen.get("format", "")))
    if named is not None:
        return named

    kind = str(chosen.get("type", ""))
    if kind == "array":
        return f"a list of {_WORDS.get(str(_items(chosen).get('type', '')), 'values')}"
    return _WORDS.get(kind, "a value")


def literal_example(field: Mapping[str, Any], root: Mapping[str, Any] | None = None) -> str | None:
    """Return one correct value for this field, written out.

    Taken from the field's own `examples`, so a field that documents itself
    well produces a good error for free and nothing has to be kept in step by
    hand.
    """
    chosen = _resolved(_meaningful(field), root)
    for source in (field, chosen):
        shown = source.get("examples")
        if isinstance(shown, Sequence) and not isinstance(shown, str) and shown:
            return repr(shown[0])
    allowed = chosen.get("enum")
    if isinstance(allowed, Sequence) and not isinstance(allowed, str) and allowed:
        return repr(allowed[0])
    return None


def _meaningful(field: Mapping[str, Any]) -> Mapping[str, Any]:
    """Look past the null branch an optional field is wrapped in.

    Pydantic renders `float | None` as an anyOf of number and null. The null
    says only that the field may be left out, which the caller already knows;
    the other branch is the one that answers what to send.
    """
    branches = field.get("anyOf")
    if not isinstance(branches, Sequence) or isinstance(branches, str):
        return field
    real = [
        branch
        for branch in branches
        if isinstance(branch, Mapping) and branch.get("type") != "null"
    ]
    return real[0] if real else field


def _items(field: Mapping[str, Any]) -> Mapping[str, Any]:
    """Describe what a list holds, tolerating a schema that does not say."""
    held = field.get("items")
    return held if isinstance(held, Mapping) else {}


def _resolved(field: Mapping[str, Any], root: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Follow a reference into the schema's own definitions.

    Pydantic lifts an enum into `$defs` and leaves a `$ref` behind, so the
    permitted values are one hop away from the field that permits them. Left
    unfollowed, the single most useful thing that can be said about a field --
    here are the four values it accepts -- is reported as "a value".

    References are local by construction: `schema_of` sets the template, and a
    test forbids a schema pointing at the network.
    """
    pointer = field.get("$ref")
    if not isinstance(pointer, str) or root is None:
        return field
    name = pointer.rsplit("/", 1)[-1]
    defined = root.get("$defs")
    if not isinstance(defined, Mapping):
        return field
    found = defined.get(name)
    return found if isinstance(found, Mapping) else field
