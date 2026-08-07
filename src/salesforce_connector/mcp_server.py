"""The MCP adapter. It knows the protocol and nothing about Salesforce.

Deliberately the thinnest file here. It lists what the connector offers,
forwards a call, and shapes the answer into the protocol's types. There is no
endpoint, no field name, and no query anywhere in it, and a test asserts that
stays true: the moment provider knowledge appears here, the connector has
stopped being reusable and the OpenAPI document and this file have begun to
diverge.

The low-level Server is used rather than the decorator API on purpose. The
decorator derives a tool's schema from the function signature, and a pydantic
parameter lands nested under a `params` key, which measurably raises the rate
of malformed calls. Our schemas are already written, reviewed, and tested, so
they are published exactly as authored.

Everything is written to stderr. stdout carries JSON-RPC and nothing else.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Final

import mcp.server.stdio
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
    ToolAnnotations,
)

from salesforce_connector import __version__
from salesforce_connector.auth.jwt_bearer import JwtBearerAuth
from salesforce_connector.client import SalesforceClient
from salesforce_connector.config import load_settings
from salesforce_connector.connector import SalesforceConnector, load_manifest
from salesforce_connector.contract import ActionDescriptor, ActionKind, ActionRequest, ActionResult
from salesforce_connector.observability import configure_logging, get_logger

SERVER_NAME: Final = "salesforce_mcp"

# Guidance the host may show a model before it chooses anything. Cheaper than a
# routing tool: no extra round trip, and nothing that can drift from the tool
# descriptions, because it says only what no single tool can.
INSTRUCTIONS: Final = (
    "Salesforce CRM. Search for a contact before creating one: a duplicate person is "
    "the costliest mistake here. Notes attach to a contact or an opportunity, never "
    "to nothing. Every write needs an idempotency_key you generate, and if you retry "
    "after a timeout you must send the identical key or you will write the record "
    "twice."
)

# Salesforce records hold text other people wrote. It is data, and marking it
# plainly is what stops a description field from reading as an instruction.
_UNTRUSTED_OPEN: Final = "<salesforce_record_data>"
_UNTRUSTED_CLOSE: Final = "</salesforce_record_data>"

# Metadata keys carry a vendor prefix. Anything whose second label is
# `modelcontextprotocol` or `mcp` is reserved by the specification.
_META_PREFIX: Final = "salesforce-connector"


@dataclass
class AppContext:
    """What the server holds for as long as the process lives."""

    connector: SalesforceConnector


@asynccontextmanager
async def lifespan(_: Server[AppContext]) -> AsyncIterator[AppContext]:
    """Open the connector at startup and close it on the way out.

    The token lives exactly as long as this process. That is not a conversation
    or a session: the protocol is stateless and a client may interleave
    unrelated work over one connection, so nothing here may be scoped to a
    caller or remembered between calls.
    """
    configure_logging()
    log = get_logger()
    settings = load_settings()
    client = SalesforceClient.open(settings, JwtBearerAuth())
    try:
        log.info("server.started", name=SERVER_NAME, org=settings.redacted())
        yield AppContext(connector=SalesforceConnector(client, load_manifest(settings)))
    finally:
        await client.aclose()
        log.info("server.stopped", name=SERVER_NAME)


def as_tool(described: ActionDescriptor) -> Tool:
    """Publish one action as a tool, with its schemas exactly as authored."""
    return Tool(
        name=described.tool_name,
        title=described.title,
        description=described.description,
        input_schema=dict(described.input_schema),
        output_schema=dict(described.output_schema),
        annotations=_annotations(described),
    )


def _annotations(described: ActionDescriptor) -> ToolAnnotations:
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


async def list_tools(
    ctx: ServerRequestContext[AppContext],
    _params: PaginatedRequestParams | None,
) -> ListToolsResult:
    """Publish the tools, identically on every connection."""
    return ListToolsResult(
        tools=[as_tool(d) for d in ctx.lifespan_context.connector.list_actions()]
    )


async def call_tool(
    ctx: ServerRequestContext[AppContext],
    params: CallToolRequestParams,
) -> CallToolResult:
    """Run one tool and answer, whatever happened.

    A business failure comes back as a result carrying `is_error`, never as a
    protocol error. The specification is explicit that clients should hand tool
    execution errors to the model so it can correct itself; a protocol error
    can tear down the session instead.
    """
    connector = ctx.lifespan_context.connector
    request = _as_request(params, connector.list_actions())
    if request is None:
        return _refuse(f"{params.name!r} is not a tool this server offers.")
    return _as_result(await connector.execute(request))


def _as_request(
    params: CallToolRequestParams,
    described: tuple[ActionDescriptor, ...],
) -> ActionRequest | None:
    """Translate a tool call into an action call, or refuse an unknown name."""
    action_id = next((d.action_id for d in described if d.tool_name == params.name), None)
    if action_id is None:
        return None
    arguments: Mapping[str, Any] = params.arguments or {}
    return ActionRequest(
        action_id=action_id,
        params=arguments,
        idempotency_key=_string_or_none(arguments.get("idempotency_key")),
        # A host that surfaced the write to a person sets this. Absent, the
        # action refuses and says how to proceed.
        approved=bool(arguments.get("approved", False)),
    )


def _as_result(outcome: ActionResult) -> CallToolResult:
    """Shape the envelope into the protocol's own result type.

    Both representations are returned: structured content for anything parsing
    the answer, and the same data as text, because the specification asks for
    the serialised form alongside it for compatibility.
    """
    if not outcome.ok and outcome.error is not None:
        return _refuse(
            f"{outcome.error.reason}\n\nWhat to do: {outcome.error.next_step}",
            code=outcome.error.code,
            # Quota travels with a failure too. A caller deciding whether to
            # wait and retry wants to know how much allowance is left, and that
            # is exactly the call where it matters most.
            meta=_meta(outcome),
        )
    payload = dict(outcome.data)
    return CallToolResult(
        content=[TextContent(type="text", text=_wrapped(payload))],
        structured_content=payload,
        is_error=False,
        meta=_meta(outcome),
    )


def _meta(outcome: ActionResult) -> dict[str, Any] | None:
    """Carry paging position and quota beside the answer, not inside it.

    Neither belongs in the payload: the declared output schema describes what
    the action returns, and a caller validating against it should not find
    bookkeeping mixed in. The metadata channel exists for exactly this, and its
    keys carry a prefix as the specification requires.
    """
    carried: dict[str, Any] = {}
    if outcome.pagination is not None:
        carried[f"{_META_PREFIX}/pagination"] = outcome.pagination.model_dump()
    if outcome.rate_limit is not None:
        carried[f"{_META_PREFIX}/rate_limit"] = outcome.rate_limit.model_dump()
    return carried or None


def _wrapped(payload: Mapping[str, Any]) -> str:
    """Mark record content as data before a model ever reads it."""
    return f"{_UNTRUSTED_OPEN}\n{json.dumps(payload, indent=2, default=str)}\n{_UNTRUSTED_CLOSE}"


def _refuse(
    message: str,
    code: str = "connector.unknown_tool",
    meta: dict[str, Any] | None = None,
) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=f"[{code}] {message}")],
        is_error=True,
        meta=meta,
    )


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def build_server() -> Server[AppContext]:
    """Assemble the server without starting it, so a test can inspect it."""
    return Server(
        SERVER_NAME,
        version=__version__,
        title="Salesforce",
        instructions=INSTRUCTIONS,
        lifespan=lifespan,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


async def serve() -> None:
    """Talk JSON-RPC over stdin and stdout until the input closes."""
    server = build_server()
    async with mcp.server.stdio.stdio_server() as (incoming, outgoing):
        await server.run(incoming, outgoing, server.create_initialization_options())


def main() -> None:
    """Entry point. Exits quietly when the client closes the input stream."""
    try:
        asyncio.run(serve())
    except (KeyboardInterrupt, EOFError):
        return


if __name__ == "__main__":
    main()
