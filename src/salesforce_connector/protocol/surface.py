"""What a client is shown, and what it is refused.

Every tool is published at connection time, with its description and both
schemas. That is roughly twenty thousand tokens of reading spent before the
user has said anything, because a client fetches the list when it starts and
the protocol gives a server no way to ask what the user wants first.

This connector used to answer that with a router of its own: a surface that
published two doors and let a model ask which tools existed before reading any
of them. That is gone. Routing is Executor's job now, and it does it better:
it indexes this catalogue once, shares it with every agent on the machine, and
hands a model a search instead of a list. Two routers in a row would have meant
generated code opening a door for no reason, and a catalogue holding four
entries instead of seventeen, which is exactly what its search needs to see.

So this module publishes everything and spends its attention on the other half
of the problem, which the gateway cannot solve for us: refusing a call that
names something this connector cannot do, in terms a model can act on.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher, get_close_matches
from typing import Any, Final

from mcp.types import Tool

from salesforce_connector.contract import ActionDescriptor, ActionKind
from salesforce_connector.protocol.translate import UNKNOWN_TOOL, as_tool

TOOL_SCHEMA_GUIDE: Final = "salesforce_tool_describe_by_name"

# How alike two action words must be before one is offered as a correction
# for the other. Chosen from the measurements in `_near_miss`, with the
# nearest unsafe pair at 0.50 and the furthest safe one at 0.91.
_SAME_ACTION: Final = 0.85


@dataclass(frozen=True)
class Resolution:
    """What a tool call turned out to mean."""

    described: ActionDescriptor | None = None
    arguments: Mapping[str, Any] = ()  # type: ignore[assignment]
    refusal: str | None = None
    code: str | None = None


def published(described: tuple[ActionDescriptor, ...]) -> list[Tool]:
    """Return every tool, identically on every connection."""
    return [_closed(as_tool(action), described) for action in described]


def resolved(
    name: str, arguments: Mapping[str, Any], described: tuple[ActionDescriptor, ...]
) -> Resolution:
    """Work out which action a call names, or why none of them will do."""
    found = _named(name, described)
    if found is None:
        return Resolution(refusal=unavailable(name, described), code=UNKNOWN_TOOL)
    return Resolution(described=found, arguments=arguments)


def unavailable(asked: str, described: tuple[ActionDescriptor, ...]) -> str:
    """Say that a named tool does not exist, and what does.

    Written for the case that actually happens: a user asks for something this
    connector cannot do, and the model reaches for a name that sounds like it
    should exist. Three things have to be in the answer.

    The set, so the model can see the boundary rather than guess at it again.
    A near miss when there is one, because a plural or a missing prefix is the
    common case and naming it saves a round trip. And a plain instruction not
    to approximate: without it, a model refused salesforce_delete_contact will
    reach for salesforce_record_update_by_id and blank the fields instead, which is
    a worse outcome than the refusal it was given.
    """
    near = _near_miss(asked, _names(described))
    suggestion = f" Did you mean {near}?" if near else ""
    return (
        f"{asked} is not something this connector can do."
        f"{suggestion}\n\n"
        f"{_available(described)}\n\n"
        f"Do not substitute a different tool to approximate what was asked. "
        f"Approximating a delete with an update is worse than the refusal it "
        f"replaces.\n\n"
        f"If nothing above does it, do not stop at 'I cannot'. Say plainly that "
        f"this connector is not permitted to do it, then hand the work back to "
        f"the person: they can do it themselves in Salesforce. Every result "
        f"naming a record carries a direct link to it as "
        f"`salesforce-connector/record_url`; give them that link when you have "
        f"one, otherwise tell them to open Salesforce and search for the "
        f"record. Deleting, merging and converting are all in the record's own "
        f"Actions menu."
    )


def _closed(tool: Tool, described: tuple[ActionDescriptor, ...]) -> Tool:
    """Replace a free-text tool name with the closed set of real ones.

    `salesforce_tool_describe_by_name` takes the name of another tool. Declared as a
    string, that field invites a model to write whatever it believes exists,
    and a plausible invention -- salesforce_delete_contact, say -- looks
    exactly like a real name until the call is made. Declared as an enum, the
    set is visible at the moment of choosing and a client that validates
    against the schema refuses the invention before it is sent.

    The enum cannot live in the schema module: it would have to read the
    registry that is built from that module. Here the full set is already in
    hand, which is why the closing happens at publication.
    """
    if tool.name != TOOL_SCHEMA_GUIDE:
        return tool
    return tool.model_copy(
        update={"input_schema": _with_enum(tool.input_schema, "tool_name", _names(described))}
    )


def _with_enum(schema: Mapping[str, Any], field: str, allowed: list[str]) -> dict[str, Any]:
    """Return the schema with one property narrowed to a fixed set of values."""
    closed = dict(schema)
    properties = dict(closed.get("properties", {}))
    described = properties.get(field)
    if not isinstance(described, Mapping):
        return closed
    properties[field] = {**described, "enum": allowed}
    closed["properties"] = properties
    return closed


def _names(described: tuple[ActionDescriptor, ...], kind: ActionKind | None = None) -> list[str]:
    """Every tool name, or every name of one kind, in the order published."""
    return [one.tool_name for one in described if kind is None or one.kind is kind]


def _near_miss(asked: str, allowed: list[str]) -> str | None:
    """Suggest a real name only when the mistake was spelling, not intent.

    Text similarity alone is not safe here. `salesforce_delete_contact` is one
    word away from `salesforce_contact_update_by_id`, so a plain closest match
    answers a request to delete a record by proposing the tool that overwrites
    one. That is precisely the substitution the refusal goes on to forbid, and
    offering it in the same breath would be worse than saying nothing.

    So a suggestion has to agree about the action. Not exactly, because the
    typo is often in the action itself -- `contact_creates` for
    `contact_create` -- but closely, and the gap between the two cases is
    wide enough to sit a threshold in. Measured on this tool set:

        creates / create   0.92     delete / update   0.50
        searchs / search   0.92     update / upsert   0.50
        updates / update   0.92     search / query    0.36

    Everything a person could plausibly mistype scores above 0.9; every pair
    of genuinely different actions scores at or below 0.5. Note where
    `update` and `upsert` land, because those two are the dangerous pair in
    this connector and 0.85 keeps them apart.
    """
    close = get_close_matches(asked, allowed, n=1, cutoff=0.7)
    if close and _same_action(_action(asked), _action(close[0])):
        return close[0]
    return None


def _same_action(asked: str, found: str) -> bool:
    """True when two action words differ only by a slip of the fingers."""
    return SequenceMatcher(None, asked, found).ratio() >= _SAME_ACTION


def _action(tool_name: str) -> str:
    """The action word in a tool name.

    Names are `salesforce_<object>_<action>_by_<key>`, so the action is the
    second segment, not the first. Reading the first would compare objects:
    `salesforce_contact_delete_by_id` and `salesforce_contact_update_by_id`
    would agree, and the guard would suggest the overwrite in answer to the
    delete, which is the one thing it exists to prevent.
    """
    parts = tool_name.removeprefix("salesforce_").split("_")
    return parts[1] if len(parts) > 1 else parts[0]


def _available(described: tuple[ActionDescriptor, ...]) -> str:
    """List what does exist, split by kind."""
    reads = _names(described, ActionKind.READ)
    writes = _names(described, ActionKind.WRITE)
    return (
        f"This connector does exactly {len(described)} things and nothing else.\n"
        f"Reads: {', '.join(reads)}.\n"
        f"Writes: {', '.join(writes)}."
    )


def _named(tool_name: str, described: tuple[ActionDescriptor, ...]) -> ActionDescriptor | None:
    return next((one for one in described if one.tool_name == tool_name), None)
