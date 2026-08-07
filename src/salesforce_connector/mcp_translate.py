"""Turning our types into the protocol's, and back.

Split from the server so that one file is wiring and this one is translation.
Everything here is a pure function of its argument, which is why the adapter's
behaviour can be asserted without starting a server or opening a stream.

Nothing in this module knows anything about Salesforce. A test asserts that,
because the moment an endpoint or a field name appears here the core has
stopped being reusable.
"""

import json
import secrets
from collections.abc import Mapping
from typing import Any, Final

from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

from salesforce_connector.contract import ActionDescriptor, ActionKind, ActionResult

# Salesforce records hold text other people wrote. It is data, and marking it
# plainly is what stops a description field from reading as an instruction.
# Each response closes its own fence with a nonce, so the markers are prefixes
# rather than complete tags.
UNTRUSTED_OPEN: Final = "<salesforce_record_data"
UNTRUSTED_CLOSE: Final = "</salesforce_record_data"
_NONCE_BYTES: Final = 6

# Metadata keys carry a vendor prefix. Anything whose second label is
# `modelcontextprotocol` or `mcp` is reserved by the specification.
META_PREFIX: Final = "salesforce-connector"

UNKNOWN_TOOL: Final = "connector.unknown_tool"


def as_tool(described: ActionDescriptor) -> Tool:
    """Publish one action as a tool, with its schemas exactly as authored."""
    return Tool(
        name=described.tool_name,
        title=described.title,
        description=described.description,
        input_schema=dict(described.input_schema),
        output_schema=dict(described.output_schema),
        annotations=annotations_for(described),
    )


def annotations_for(described: ActionDescriptor) -> ToolAnnotations:
    """State honestly what a tool does, since a host may gate on this.

    Hints are derived from the action's own declaration rather than written
    twice: a read is read-only, a write is destructive in the sense that
    matters here, which is that running it again is not free.
    """
    reads = described.kind is ActionKind.READ
    return ToolAnnotations(
        title=described.title,
        read_only_hint=reads,
        destructive_hint=not reads,
        idempotent_hint=described.idempotent,
        open_world_hint=True,
    )


def as_result(outcome: ActionResult) -> CallToolResult:
    """Shape the envelope into the protocol's own result type.

    A success carries both representations: structured content for anything
    parsing the answer, and the same data as text, which the specification asks
    for alongside it. A failure is a result carrying is_error, never a protocol
    error, because clients hand tool execution errors to the model so it can
    correct itself.
    """
    if not outcome.ok and outcome.error is not None:
        return refuse(
            f"{outcome.error.reason}\n\nWhat to do: {outcome.error.next_step}",
            code=outcome.error.code,
            # Quota travels with a failure too. A caller deciding whether to
            # wait and retry wants to know how much allowance is left, and that
            # is exactly the call where it matters most.
            meta=meta_of(outcome),
        )
    payload = dict(outcome.data)
    return CallToolResult(
        content=[TextContent(type="text", text=wrapped(payload))],
        structured_content=payload,
        is_error=False,
        meta=meta_of(outcome),
    )


def meta_of(outcome: ActionResult) -> dict[str, Any] | None:
    """Carry paging position and quota beside the answer, not inside it.

    Neither belongs in the payload: the declared output schema describes what
    the action returns, and a caller validating against it should not find
    bookkeeping mixed in.
    """
    carried: dict[str, Any] = {}
    if outcome.pagination is not None:
        carried[f"{META_PREFIX}/pagination"] = outcome.pagination.model_dump()
    if outcome.rate_limit is not None:
        carried[f"{META_PREFIX}/rate_limit"] = outcome.rate_limit.model_dump()
    return carried or None


def wrapped(payload: Mapping[str, Any]) -> str:
    """Mark record content as data before a model ever reads it.

    The fence carries a nonce, and that is not decoration. A fixed marker can
    be written into a Salesforce field: a contact whose description contains
    the closing tag would end the fence early and have everything after it read
    as though it came from us rather than from the record. The nonce is
    generated per response and cannot be guessed by whoever wrote the record,
    so the fence cannot be closed from the inside.
    """
    nonce = secrets.token_hex(_NONCE_BYTES)
    body = json.dumps(payload, indent=2, default=str)
    return f"{UNTRUSTED_OPEN}-{nonce}>\n{body}\n{UNTRUSTED_CLOSE}-{nonce}>"


def refuse(
    message: str,
    code: str = UNKNOWN_TOOL,
    meta: dict[str, Any] | None = None,
) -> CallToolResult:
    """Answer a call that cannot proceed, in a form the model can act on."""
    return CallToolResult(
        content=[TextContent(type="text", text=f"[{code}] {message}")],
        is_error=True,
        meta=meta,
    )
