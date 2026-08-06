"""Keeping the work that finished, when the work that followed did not.

Some actions are more than one call. Creating an opportunity and then linking a
contact to it is two writes, and the second can fail after the first has taken
effect. Starting over would create a second opportunity; reporting plain
failure would hide one that exists.

A journal records each step as it completes. A resumed attempt asks what is
already done and skips it, so recovery continues from the last finished step
rather than from the beginning. What could not be completed is named in the
result, so a partial write is never reported as either success or clean
failure.

The same idea covers reads: an interrupted page walk resumes from the cursor it
reached instead of starting at the first page.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from salesforce_connector.immutable import freeze


class Checkpoint(BaseModel):
    """One step that finished, and what it produced."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step: str
    data: Mapping[str, Any]

    @field_validator("data", mode="after")
    @classmethod
    def _stays_frozen(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        """Re-freeze after validation.

        Pydantic validates a Mapping field into a plain dict, which quietly
        undoes the freeze applied on the way in.
        """
        frozen: Mapping[str, Any] = freeze(value)
        return frozen


class Journal:
    """The steps of one operation that have completed."""

    def __init__(self) -> None:
        self._done: dict[str, Checkpoint] = {}
        self._order: list[str] = []

    def record(self, step: str, data: Mapping[str, Any] | None = None) -> Checkpoint:
        """Mark a step finished, keeping whatever it produced."""
        checkpoint = Checkpoint(step=step, data=freeze(data or {}))
        if step not in self._done:
            self._order.append(step)
        self._done[step] = checkpoint
        return checkpoint

    def is_done(self, step: str) -> bool:
        """Say whether a step has already finished, so a resume can skip it."""
        return step in self._done

    def find(self, step: str) -> Checkpoint | None:
        """Return what a completed step produced, if it completed."""
        return self._done.get(step)

    def completed(self) -> tuple[str, ...]:
        """Name every finished step, in the order they finished."""
        return tuple(self._order)

    def last(self) -> Checkpoint | None:
        """Return the furthest point reached, which is where a resume begins."""
        return self._done[self._order[-1]] if self._order else None
