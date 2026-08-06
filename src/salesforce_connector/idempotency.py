"""Remembering what a key has already done.

The failure this exists for: a write is sent, Salesforce applies it, and the
response is lost to a timeout. The caller believes nothing happened and tries
again. Without a record, the second attempt creates a second record.

An entry is written before the call and settled after it, so a repeat of the
same key can be answered three ways: it finished and here is what it produced;
it failed and may be tried again; or it was in flight and its fate is unknown,
which is the only case a caller must investigate rather than assume.

The honest limit of this module: it lives in memory, so it protects a retry
within one process and nothing more. If the container restarts mid-write, this
record is gone. Real protection comes from the provider, by writing through an
external id so Salesforce itself refuses to create a second record - see
client.py. This is the second line, not the first.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from salesforce_connector.immutable import freeze


class KeyState(StrEnum):
    """What is known about a key's operation."""

    IN_FLIGHT = "in_flight"  # sent, fate unknown; verify before acting
    COMPLETED = "completed"  # finished; the recorded result stands
    FAILED = "failed"  # did not take effect; safe to try again


class LedgerEntry(BaseModel):
    """One key, and what became of the call that used it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    state: KeyState
    result: Mapping[str, Any] | None = None

    @field_validator("result", mode="after")
    @classmethod
    def _stays_frozen(cls, value: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
        """Re-freeze after validation.

        Pydantic validates a Mapping field into a plain dict, which quietly
        undoes the freeze applied on the way in. Freezing here is the last
        word, so a recorded result cannot be edited afterwards.
        """
        return freeze(value) if value is not None else None


class IdempotencyLedger:
    """What each key has already achieved, for the life of the process."""

    def __init__(self) -> None:
        self._entries: dict[str, LedgerEntry] = {}

    def find(self, key: str) -> LedgerEntry | None:
        """Return what is known about a key.

        Named find_ because absence is ordinary: most keys are new.
        """
        return self._entries.get(key)

    def begin(self, key: str) -> LedgerEntry:
        """Record that a key's call is about to be sent.

        Returns the existing entry untouched if the key has been seen, so a
        completed operation is never started a second time.
        """
        existing = self._entries.get(key)
        if existing is not None:
            return existing
        entry = LedgerEntry(key=key, state=KeyState.IN_FLIGHT)
        self._entries[key] = entry
        return entry

    def complete(self, key: str, result: Mapping[str, Any]) -> LedgerEntry:
        """Record that a key's call succeeded, and what it produced."""
        entry = LedgerEntry(key=key, state=KeyState.COMPLETED, result=freeze(result))
        self._entries[key] = entry
        return entry

    def fail(self, key: str) -> LedgerEntry:
        """Record that a key's call did not take effect."""
        entry = LedgerEntry(key=key, state=KeyState.FAILED)
        self._entries[key] = entry
        return entry
