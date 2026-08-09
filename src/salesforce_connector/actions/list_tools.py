"""Listing the connector's own tools, filtered by what the caller means to do.

The only two actions that never reach Salesforce. They answer from the registry
instead, which makes them the one place a stale answer is possible: a tool
added to the registry and forgotten here would be invisible to anything that
routes through this. So nothing is listed by hand. The registry is the source,
and a test asserts that every registered tool appears in the output.
"""

from collections.abc import Mapping
from typing import Any, ClassVar

from salesforce_connector.actions.action import Action
from salesforce_connector.contract import ActionDescriptor, ActionKind
from salesforce_connector.schemas import list_tools as schema

NEXT_ACTION = (
    "Call salesforce_tool_schema with the tool_name you chose to see its fields "
    "and the exact type each one expects, then call that tool."
)


class ListTools(Action):
    """Name the tools that read, or the tools that write."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.ListToolsInput
    output_model: ClassVar[type] = schema.ListToolsOutput

    async def _execute(self, params: schema.ListToolsInput) -> Mapping[str, Any]:
        listed = [
            _summary(described) for described in _published() if _matches(described, params.kind)
        ]
        return {
            "kind": params.kind,
            "tools": tuple(listed),
            "returned": len(listed),
            "next_action": NEXT_ACTION,
        }


def _published() -> tuple[ActionDescriptor, ...]:
    """Read the registry, at call time rather than at import time.

    These actions are themselves in the registry, so importing it at module
    level would be a cycle. Deferring the import to the call also means the
    answer cannot be a snapshot taken before the registry finished being built.
    """
    from salesforce_connector.actions import registry

    return registry.descriptors()


def _matches(described: ActionDescriptor, kind: str) -> bool:
    if kind == "all":
        return True
    return described.kind.value == kind


def _summary(described: ActionDescriptor) -> Mapping[str, Any]:
    """Reduce one tool to the line a caller chooses from."""
    writes = described.kind is not ActionKind.READ
    return {
        "name": described.tool_name,
        "purpose": _first_sentence(described.description),
        "use_when": _after("Use this when: ", described.description),
        "required_inputs": tuple(described.input_schema.get("required", ())),
        "changes_data": writes,
        "needs_approval": described.requires_approval,
    }


def _first_sentence(description: str) -> str:
    """Take the summary line, which is the first thing every description says."""
    return description.split("\n", 1)[0].strip()


def _after(label: str, description: str) -> str:
    """Pull one labelled line out of the rendered description.

    Read from the rendered text rather than the spec so that this and the
    published tool description cannot disagree about what a tool is for: there
    is one wording, and both show the same one.
    """
    for line in description.splitlines():
        if line.startswith(label):
            return line[len(label) :].strip()
    return ""
