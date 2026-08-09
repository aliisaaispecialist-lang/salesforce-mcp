"""How much of the connector a client is shown when it connects.

Every tool is published at connection time, with its description and both
schemas. That is roughly twenty-one thousand tokens of reading spent before
the user has said anything, because the client fetches the list when it starts
and the protocol gives a server no way to ask what the user wants first.

So there are two surfaces, and the org picks one.

`full` publishes all seventeen. Every client validates each call against that
tool's own schema, and a host that gates on the destructive hint sees which
tools change data. This is the default because it is what the connector
declares it offers.

`router` publishes four: the two that describe the others, and two doors, one
for reading and one for writing. A model asks which tools exist, reads the one
it wants, and calls it through the matching door. About two thousand tokens
instead of twenty-one.

Two doors rather than one, deliberately. A single door would have to be
declared either read-only or destructive, and either declaration would be false
half the time -- so a host that refuses destructive tools would either block
every read or permit every write. With one door per kind, the hint is true, and
`resolved` enforces it: the read door refuses a write, whatever it is asked
for.

What does not change in either surface: the argument still meets the tool's own
model, the same approval is still required before a write runs, and the same
error still comes back. The door decides what is visible, never what is
allowed.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from mcp.types import Tool, ToolAnnotations

from salesforce_connector.contract import ActionDescriptor, ActionKind
from salesforce_connector.protocol.translate import as_tool

FULL: Final = "full"
ROUTER: Final = "router"

READ_DOOR: Final = "salesforce_read"
WRITE_DOOR: Final = "salesforce_write"
# The two that answer "which tools are there" and "what does this one take".
# Published in both surfaces, because in `router` they are the only way in and
# in `full` they are still the cheapest way to choose.
GUIDES: Final = ("salesforce_list_tools", "salesforce_tool_schema")

_DOORS: Final[Mapping[str, ActionKind]] = {
    READ_DOOR: ActionKind.READ,
    WRITE_DOOR: ActionKind.WRITE,
}


@dataclass(frozen=True)
class Resolution:
    """What a tool call turned out to mean."""

    described: ActionDescriptor | None = None
    arguments: Mapping[str, Any] = ()  # type: ignore[assignment]
    refusal: str | None = None


def published(described: tuple[ActionDescriptor, ...], surface: str) -> list[Tool]:
    """Return the tools a client is shown for this surface."""
    if surface != ROUTER:
        return [as_tool(action) for action in described]
    guides = [as_tool(action) for action in described if action.tool_name in GUIDES]
    return [*guides, _door(READ_DOOR), _door(WRITE_DOOR)]


def resolved(
    name: str, arguments: Mapping[str, Any], described: tuple[ActionDescriptor, ...]
) -> Resolution:
    """Work out which action a call names, opening a door if it went through one.

    A door carries the real tool name in its arguments, so everything after
    this point -- validation, approval, execution, the error -- is the same
    code that runs when the tool was called directly.
    """
    wanted = _DOORS.get(name)
    if wanted is None:
        return Resolution(described=_named(name, described), arguments=arguments)

    asked = arguments.get("tool_name")
    if not isinstance(asked, str) or not asked:
        return Resolution(
            refusal=(
                f"{name} needs tool_name: the tool you want to run. Call "
                f"salesforce_list_tools to see which exist."
            )
        )
    inner = _named(asked, described)
    if inner is None:
        return Resolution(refusal=f"{asked!r} is not a tool this server offers.")
    if inner.kind is not wanted:
        # The hint on each door has to stay true, or a host that refuses
        # destructive tools would be refusing the wrong thing.
        other = WRITE_DOOR if wanted is ActionKind.READ else READ_DOOR
        return Resolution(
            refusal=(
                f"{asked} is a {inner.kind.value} tool and {name} only runs "
                f"{wanted.value} tools. Call it through {other} instead."
            )
        )
    return Resolution(described=inner, arguments=_inner_arguments(arguments))


def _inner_arguments(arguments: Mapping[str, Any]) -> Mapping[str, Any]:
    """Take the arguments meant for the tool, not for the door."""
    given = arguments.get("arguments")
    return given if isinstance(given, Mapping) else {}


def _named(tool_name: str, described: tuple[ActionDescriptor, ...]) -> ActionDescriptor | None:
    return next((one for one in described if one.tool_name == tool_name), None)


def _door(name: str) -> Tool:
    """Describe one door, in the terms a model needs to use it."""
    kind = _DOORS[name]
    reads = kind is ActionKind.READ
    doing = "reads from Salesforce" if reads else "changes Salesforce"
    return Tool(
        name=name,
        title=f"Run a Salesforce tool that {doing}",
        description=_door_description(kind),
        input_schema=_door_schema(kind),
        annotations=ToolAnnotations(
            title=f"Run a Salesforce tool that {doing}",
            read_only_hint=reads,
            destructive_hint=not reads,
            # A door is only as idempotent as whatever it was asked to run.
            idempotent_hint=False,
            open_world_hint=True,
        ),
    )


def _door_description(kind: ActionKind) -> str:
    reads = kind is ActionKind.READ
    other = WRITE_DOOR if reads else READ_DOOR
    return "\n".join(
        (
            f"Run one of the Salesforce tools that {'read' if reads else 'write'}.",
            "",
            "Three steps, in order:",
            f"1. salesforce_list_tools with kind={kind.value} to see what exists.",
            "2. salesforce_tool_schema with the one you chose, to see its fields "
            "and the exact type each expects.",
            "3. this tool, with that name and those arguments.",
            "",
            f"Use this when: the work {'only reads' if reads else 'changes something'}.",
            f"Do not use this when: the tool you want is a "
            f"{'write' if reads else 'read'}, which is {other}; or you do not "
            f"know the tool name yet, which is salesforce_list_tools.",
            "",
            "Failures and what to do:",
            "- connector.invalid_input: the tool name is wrong, or its arguments "
            "are. The message names what was wrong and what to send instead; "
            "salesforce_tool_schema shows the types.",
            "- connector.approval_required: a write needs the user to confirm it. "
            "Ask, then send approved true inside arguments with the same "
            "idempotency_key.",
        )
    )


def _door_schema(kind: ActionKind) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": (
                    f"Required. The tool to run, named exactly as "
                    f"salesforce_list_tools reported it, including the "
                    f"salesforce_ prefix. It must be a {kind.value} tool."
                ),
            },
            "arguments": {
                "type": "object",
                "description": (
                    "Required. The arguments for that tool, exactly as its own "
                    "schema describes them. Call salesforce_tool_schema first "
                    "if you are unsure: a number means digits, a date means "
                    "YYYY-MM-DD, and a listed set means one of those values."
                ),
            },
        },
        "required": ["tool_name", "arguments"],
        "additionalProperties": False,
    }
