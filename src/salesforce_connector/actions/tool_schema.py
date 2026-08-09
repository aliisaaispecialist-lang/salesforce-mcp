"""Explaining one tool, with each field's type written out in words.

The schema is already published and already correct. What it is not is
unmissable: an optional number is an `anyOf` of number and null, and a model
skimming that sends the word "one". So every field is restated here as a
sentence a model cannot read two ways, and the sentence is derived from the
schema rather than written beside it, which is what keeps them from drifting.

Required fields come first. A caller reads top-down and the things it must
supply are the things it should see first.
"""

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from salesforce_connector.actions.action import Action
from salesforce_connector.contract import ActionDescriptor
from salesforce_connector.errors.model import ErrorContext, InvalidInputError
from salesforce_connector.schemas import plain_types
from salesforce_connector.schemas import tool_schema as schema


class ToolSchema(Action):
    """Report one tool's fields, types, and a worked call."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.ToolSchemaInput
    output_model: ClassVar[type] = schema.ToolSchemaOutput

    async def _execute(self, params: schema.ToolSchemaInput) -> Mapping[str, Any]:
        described = _named(params.tool_name)
        return {
            "tool_name": described.tool_name,
            "purpose": _line(described.description, 0),
            "use_when": _after("Use this when: ", described.description),
            "do_not_use_when": _after("Do not use this when: ", described.description),
            "changes_data": described.kind.value != "read",
            "needs_approval": described.requires_approval,
            "fields": _fields(described.input_schema),
            "example_call": _example_call(described),
            "errors": _errors(described),
        }


def _named(tool_name: str) -> ActionDescriptor:
    """Find the tool, or refuse in a way that can be corrected in one step.

    Deferred import: this action is itself in the registry, so importing it at
    module level would be a cycle.
    """
    from salesforce_connector.actions import registry

    published = registry.descriptors()
    found = next((one for one in published if one.tool_name == tool_name), None)
    if found is not None:
        return found
    raise InvalidInputError(
        f"{tool_name!r} is not a tool this connector publishes.",
        ErrorContext(
            next_step="Use one of: " + ", ".join(one.tool_name for one in published) + ".",
            invalid_fields=("tool_name",),
        ),
    )


def _fields(input_schema: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Describe every field, the ones that must be supplied first."""
    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", ()))
    described = [
        {
            "name": name,
            "type": plain_types.in_words(field, input_schema),
            "required": name in required,
            "example": plain_types.literal_example(field, input_schema),
            "description": str(field.get("description", "")),
        }
        for name, field in properties.items()
        if isinstance(field, Mapping)
    ]
    return tuple(sorted(described, key=lambda one: not one["required"]))


def _example_call(described: ActionDescriptor) -> Mapping[str, Any]:
    """Return the tool's own worked call, if it has one."""
    return dict(described.examples[0].arguments) if described.examples else {}


def _errors(described: ActionDescriptor) -> tuple[Mapping[str, str], ...]:
    """Restate the failures from the tool's rendered description.

    The descriptor carries the description rather than the spec, so the error
    guidance is read back out of the one line per failure that the description
    already renders: `- code: when remedy`.
    """
    lines = _section("Failures and what to do:", described.description)
    return tuple(_as_error(line) for line in lines if line.startswith("- "))


def _as_error(line: str) -> Mapping[str, str]:
    code, _, rest = line[2:].partition(": ")
    return {"code": code.strip(), "guidance": rest.strip()}


def _section(heading: str, description: str) -> Sequence[str]:
    """Return the lines following a heading, to the end of the description."""
    lines = description.splitlines()
    if heading not in lines:
        return ()
    return lines[lines.index(heading) + 1 :]


def _line(description: str, index: int) -> str:
    lines = description.splitlines()
    return lines[index].strip() if index < len(lines) else ""


def _after(label: str, description: str) -> str:
    for line in description.splitlines():
        if line.startswith(label):
            return line[len(label) :].strip()
    return ""
