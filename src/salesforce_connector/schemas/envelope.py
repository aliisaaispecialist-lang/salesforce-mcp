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

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from salesforce_connector.contract import ActionId, ActionKind, RiskLevel, ToolName


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


class ErrorGuidance(_Frozen):
    """One failure this tool can produce, and what to do about it."""

    code: str
    when: str
    remedy: str


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
    missing_inputs: Sequence[MissingInput] = ()

    def description(self) -> str:
        """Render the single description string a model will actually read."""
        return "\n".join(
            (
                self.summary,
                "",
                f"Use this when: {self.when_to_use}",
                f"Do not use this when: {self.when_not_to_use}",
                "",
                "Failures and what to do:",
                *(f"- {error.code}: {error.when} {error.remedy}" for error in self.errors),
            )
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
