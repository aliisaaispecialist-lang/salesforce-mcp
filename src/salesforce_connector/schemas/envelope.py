"""The vocabulary every action's schema is written in.

A tool is only as usable as its description, and a model reads nothing else.
Each specification therefore carries four things the literature identifies as
the difference between a tool that works and one that quietly does not:

- a name that cannot be confused with a sibling;
- a description saying what the tool does, when to reach for it, and just as
  importantly when not to, so a model choosing between five actions has a
  reason to reject four of them;
- for every required field, what to do when its value cannot be determined,
  rather than leaving the model to invent one;
- for every failure the tool can produce, the remedy, so an error is a next
  step rather than a dead end.

The missing-input declarations feed elicitation: when a required value is
absent, the action asks the user for exactly that value and revalidates,
instead of guessing or failing.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Any, Final

from pydantic import BaseModel, ConfigDict

from salesforce_connector.contract import ActionExample, ActionId, ActionKind, RiskLevel, ToolName
from salesforce_connector.schemas import plain_types


def _one_field(name: str, schema: Mapping[str, Any], required: frozenset[str]) -> str:
    """One field, as a model needs to read it: name, type, an example, and why."""
    held = schema.get("properties", {}).get(name)
    field = held if isinstance(held, Mapping) else {}
    mark = "required" if name in required else "optional"
    said = plain_types.in_words(field, schema)
    shown = plain_types.literal_example(field, schema)
    example = f" e.g. {shown}" if shown else ""
    detail = (
        str(field.get("description", "")).splitlines()[0].strip()
        if field.get("description")
        else ""
    )
    return f"{name} ({mark}, {said}){example}{': ' + detail if detail else ''}"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MissingInput(_Frozen):
    """What to ask the user when a required value cannot be determined.

    Restricted to the primitive types elicitation permits: a form schema may
    only be a flat object of strings, numbers, booleans, or enums.
    """

    field: str
    prompt: str
    json_type: str = "string"
    choices: tuple[str, ...] = ()


# What to do about a failure, decided by its code rather than written out
# seventeen times. Whether to retry, to wait, to change the call, or to stop is
# a property of the failure itself, so restating it per tool would only create
# seventy chances to disagree with the taxonomy. The tool-specific half stays
# in `remedy`, which says what to do *here*.
_RESPONSE: Final[Mapping[str, str]] = {
    "salesforce.rate_limited": "WAIT, then repeat the identical call.",
    "salesforce.transport_failed": "RETRY the identical call.",
    "connector.invalid_input": "FIX THE CALL. Retrying it unchanged fails identically.",
    "salesforce.record_not_found": "DO NOT RETRY. Find the right record first.",
    "salesforce.permission_denied": "DO NOT RETRY. Report it; only an administrator can fix it.",
    "salesforce.conflict": "DO NOT RETRY UNCHANGED. Act on what already exists.",
    "salesforce.authentication_failed": "STOP. The server is misconfigured, not the call.",
    "connector.configuration_invalid": "STOP. The server is misconfigured, not the call.",
    "connector.escalate_to_human": "STOP and hand this to a person.",
}
_UNKNOWN_RESPONSE: Final = "Read the message; it says what to do."


class ErrorGuidance(_Frozen):
    """One failure this tool can produce, and what to do about it."""

    code: str
    when: str
    remedy: str

    def response(self) -> str:
        """Retry, wait, change the call, or stop: decided by the code."""
        return _RESPONSE.get(self.code, _UNKNOWN_RESPONSE)


class ActionSpec(_Frozen):
    """Everything a consumer needs to expose one action correctly.

    The MCP tool definition, the OpenAPI operation, and the README section are
    all generated from this, so a change lands in all three or in none.
    """

    action_id: ActionId
    tool_name: ToolName
    title: str
    summary: str
    when_to_use: str
    when_not_to_use: str
    kind: ActionKind
    risk: RiskLevel
    idempotent: bool
    requires_approval: bool
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    errors: Sequence[ErrorGuidance]
    manual_recovery: str = ""
    """What a person must do by hand when this action cannot be completed.

    Every write that changes state needs one. Chapter 6's rule is that a tool
    which creates or modifies something has either a rollback tool or a
    documented manual procedure, and this connector has no rollback tools: it
    cannot un-create a contact, and offering to would be worse than saying so.

    So this is the procedure, written for the person who has to carry it out
    rather than for the model. It is attached to the escalation after the
    retries are exhausted, at the one moment somebody actually needs it.

    Reads leave it empty. There is nothing to recover from a failed search.
    """

    missing_inputs: Sequence[MissingInput] = ()
    examples: tuple[ActionExample, ...] = ()

    def description(self) -> str:
        """Render the single description string a model will actually read.

        The first example is rendered inline. A worked call is the cheapest
        correction available for the mistakes a schema alone invites -- a field
        left out, a date in the wrong shape, an id from the wrong object -- and
        it costs a handful of tokens in the one place a model is certain to
        look.
        """
        return "\n".join(
            (
                self.summary,
                "",
                f"Use this when: {self.when_to_use}",
                f"Do not use this when: {self.when_not_to_use}",
                f"You need: {self._needed()}",
                *self._fields_of(self.input_schema, "Inputs"),
                *self._fields_of(self.output_schema, "Returns"),
                *self._worked_example(),
                *self._failures(),
                *self._last_resort(),
            )
        )

    def _fields_of(self, schema: Mapping[str, Any], heading: str) -> tuple[str, ...]:
        """List one schema's fields in words, required ones marked.

        Both schemas are already published beside the description, and this
        repeats them on purpose. A JSON Schema is written for a validator: the
        type of `amount` is `{"anyOf": [{"type": "number"}, {"type": "null"}]}`,
        which is exact and is also the shape a model skims as "some value".
        Here the same field reads "a number, written in digits", which is the
        form that stops a deal worth 45000 arriving as the word "one".

        Derived from the schema rather than written beside it, so the two
        cannot come to disagree.
        """
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping) or not properties:
            return ()
        required = frozenset(schema.get("required", ()))
        lines = [f"  - {_one_field(name, schema, required)}" for name in properties]
        return ("", f"{heading}:", *lines)

    def _failures(self) -> tuple[str, ...]:
        """Every failure this tool can produce, and the response to each.

        Three things per failure, because a code on its own is a dead end: why
        it happens, whether to retry or wait or stop, and what to do here.
        """
        if not self.errors:
            return ()
        lines: list[str] = []
        for error in self.errors:
            lines.append(f"  - {error.code} -- {error.response()}")
            lines.append(f"      why: {error.when}")
            lines.append(f"      do:  {error.remedy}")
        return ("", "Failures, why each happens, and what to do:", *lines)

    def _last_resort(self) -> tuple[str, ...]:
        """The manual procedure, for a write that cannot be completed at all.

        Written for the person who has to carry it out. It was reachable only
        by escalating, which meant a model could not warn a user in advance
        that a failure here has a manual cost.
        """
        if not self.manual_recovery:
            return ()
        return ("", f"If it cannot be completed at all: {self.manual_recovery}")

    def _needed(self) -> str:
        """Name what a caller must hold before this tool can be called at all.

        The required fields are in the schema, and a model that reads the
        schema will find them. The question this answers is the earlier one,
        asked while choosing rather than while filling in: do I have what this
        needs, or do I have to go and find it first? A tool that wants a record
        id is not a candidate when all the user gave is a name, and saying so
        in the description is what stops the call being attempted and failed.

        Derived from the schema rather than written by hand, so it cannot come
        to disagree with the validator.
        """
        required = tuple(self.input_schema.get("required", ()))
        if not required:
            return "nothing; every field is optional."
        return f"{', '.join(required)}."

    def _worked_example(self) -> tuple[str, ...]:
        """Render the first example, or nothing if this action has none."""
        if not self.examples:
            return ()
        shown = self.examples[0]
        return (
            "",
            f"Example -- {shown.title}",
            f"  call: {json.dumps(shown.arguments, sort_keys=True)}",
            f"  returns: {json.dumps(shown.result, sort_keys=True)}",
        )

    def find_missing_input(self, field: str) -> MissingInput | None:
        """Return how to ask for a field, if this action knows how."""
        return next((entry for entry in self.missing_inputs if entry.field == field), None)


def schema_of(model: type[BaseModel]) -> Mapping[str, Any]:
    """Produce the JSON Schema for a model, in the dialect MCP expects.

    MCP defaults to 2020-12 when no `$schema` is present, which is what
    pydantic emits, so the dialect is correct by omission. References are
    inlined so that no consumer is ever asked to dereference a `$ref`, which
    the specification forbids doing over the network.
    """
    return model.model_json_schema(ref_template="#/$defs/{model}")


APPROVED_DESCRIPTION = (
    "Optional, defaults to false. Set to true only after a person has seen and "
    "confirmed this write. A write arriving without it is refused, and the "
    "refusal says so. It is declared here because a tool must not ask for an "
    "argument its own schema does not offer: a caller working from the schema "
    "alone would have no way to supply it."
)

IDEMPOTENCY_KEY_FIELD = "idempotency_key"

IDEMPOTENCY_KEY_DESCRIPTION = (
    "A unique id you generate for this logical write, for example a UUID. "
    "Required. If you retry this call after a timeout or an unclear failure, "
    "send the identical value: the connector recognises it and returns the "
    "original outcome instead of writing a second record. Generate a new value "
    "only when you genuinely intend a separate record."
)
