"""Holding a single value to a length before it is handed to a model.

Row counts have always been bounded: `soql_query` and `get_related` both stop
at `max_query_rows`, and the search actions take a limit. The width of a row
was not. A Salesforce long text area holds thirty-two thousand characters, and
a record with three of them filled is a single result that costs more context
than the rest of the conversation.

Shortening rather than dropping, and marked where it happens. A value that
vanished would read as an empty field, which is a different fact about the
record and a worse one to be wrong about. A value that says it was cut can be
read for what it is, and the caller is told which fields to go and read in full
if the tail mattered.

This bounds width. Length is bounded by the row ceilings above. There is no
separate cap on the whole payload, deliberately: reaching a byte budget by
dropping records would silently change the answer to the question that was
asked, and a caller cannot tell that from a genuinely short result.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Final

MARKER: Final = "[... shortened by the connector: {shown} of {held} characters]"

_UNNAMED: Final = "a value"


class _Shortening:
    """One pass over one result, remembering what it had to cut."""

    def __init__(self, ceiling: int) -> None:
        self._ceiling = ceiling
        self.cut: list[str] = []

    def walk(self, value: Any, name: str) -> Any:
        if isinstance(value, str):
            return self._held(value, name)
        if isinstance(value, Mapping):
            return {key: self.walk(held, str(key)) for key, held in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            # The name travels down, so a long description inside a list of
            # records is reported as Description rather than as its index.
            return [self.walk(item, name) for item in value]
        return value

    def _held(self, value: str, name: str) -> str:
        """Cut one string, leaving it able to say that it was cut."""
        if len(value) <= self._ceiling:
            return value
        if name not in self.cut:
            self.cut.append(name)
        marker = MARKER.format(shown=self._ceiling, held=len(value))
        return f"{value[: self._ceiling]}{marker}"


def shortened(value: Any, ceiling: int) -> tuple[Any, list[str]]:
    """Return the value with every over-long string held to `ceiling`.

    Args:
        value: Anything an action returns: a mapping, a sequence, a scalar.
        ceiling: The longest a single string may be before it is shortened.

    Returns:
        The same shape with long strings shortened, and the field names that
        were shortened, in order and without repeats, so the caller can be told
        which ones to read in full.
    """
    pass_over = _Shortening(ceiling)
    return pass_over.walk(value, _UNNAMED), pass_over.cut


def notice(cut: Sequence[str], ceiling: int) -> str:
    """Say which fields were shortened, and where the rest of them still is."""
    return (
        f"Longer than {ceiling} characters and shortened here: "
        f"{', '.join(cut)}. What is below is the start of each, not all of it. "
        f"Nothing in Salesforce was changed, so read the record directly if the "
        f"rest matters."
    )
