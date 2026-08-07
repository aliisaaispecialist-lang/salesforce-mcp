"""The MCP adapter: what it serves, and for how long.

Deliberately thin. It opens the connector at startup, lists what the connector
offers, forwards a call, and closes on the way out. The translation between our
types and the protocol's lives next door in `mcp_translate`, and neither file
contains an endpoint, a field name, or a query.

The low-level Server is used rather than the decorator API on purpose. The
decorator derives a tool's schema from the function signature, and a pydantic
parameter lands nested under a `params` key, which measurably raises the rate
of malformed calls. Our schemas are already written and tested, so they are
published exactly as authored. It also gets dual-era support for free: the same
loop serves the legacy handshake and the modern per-request envelope, and the
client's first request decides which.

Everything is written to stderr. stdout carries JSON-RPC and nothing else.
"""

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Final

import mcp.server.stdio
from mcp.server import Server, ServerRequestContext
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams

from salesforce_connector import __version__
from salesforce_connector.approval import ApprovalGate
from salesforce_connector.auth.jwt_bearer import JwtBearerAuth
from salesforce_connector.client import SalesforceClient
from salesforce_connector.config import load_settings
from salesforce_connector.connector import SalesforceConnector, load_manifest
from salesforce_connector.contract import ActionDescriptor, ActionRequest
from salesforce_connector.mcp_approval import WriteApproval
from salesforce_connector.mcp_translate import as_result, as_tool, refuse
from salesforce_connector.observability import configure_logging, get_logger

SERVER_NAME: Final = "salesforce_mcp"

# Guidance a host may show a model before it chooses anything. This is the
# cheap half of a routing tool: no extra round trip on every call, and nothing
# that can drift from the tool descriptions, because it says only what no
# single tool can say about itself.
INSTRUCTIONS: Final = (
    "Salesforce CRM. Search for a contact before creating one: a duplicate person is "
    "the costliest mistake here. Notes attach to a contact or an opportunity, never "
    "to nothing. Every write needs an idempotency_key you generate, and if you retry "
    "after a timeout you must send the identical key or you will write the record "
    "twice."
)


@dataclass
class AppContext:
    """What the server holds for as long as the process lives."""

    connector: SalesforceConnector
    approval: WriteApproval


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
        yield AppContext(
            connector=SalesforceConnector(client, load_manifest(settings)),
            # One gate per process. Its signing key dies with the process, so a
            # restart invalidates every approval in flight, which is correct.
            approval=WriteApproval(ApprovalGate()),
        )
    finally:
        await client.aclose()
        log.info("server.stopped", name=SERVER_NAME)


async def list_tools(
    ctx: ServerRequestContext[AppContext],
    _params: PaginatedRequestParams | None,
) -> ListToolsResult:
    """Publish the tools, identically on every connection."""
    described = ctx.lifespan_context.connector.list_actions()
    return ListToolsResult(tools=[as_tool(action) for action in described])


async def call_tool(
    ctx: ServerRequestContext[AppContext],
    params: CallToolRequestParams,
) -> CallToolResult:
    """Run one tool and answer, whatever happened.

    Approval comes before execution, never inside it: a write the user turns
    down must not reach the connector at all.
    """
    context = ctx.lifespan_context
    described = _descriptor(params.name, context.connector.list_actions())
    if described is None:
        return refuse(f"{params.name!r} is not a tool this server offers.")
    settled = await context.approval.granted(ctx, described, _as_request(params, described))
    if isinstance(settled, CallToolResult):
        return settled
    return as_result(await context.connector.execute(settled))


def _descriptor(
    tool_name: str,
    described: tuple[ActionDescriptor, ...],
) -> ActionDescriptor | None:
    """Find the action a tool name stands for, if this server offers one."""
    return next((d for d in described if d.tool_name == tool_name), None)


def _as_request(params: CallToolRequestParams, described: ActionDescriptor) -> ActionRequest:
    """Translate a tool call into an action call."""
    arguments: Mapping[str, Any] = params.arguments or {}
    return ActionRequest(
        action_id=described.action_id,
        params=arguments,
        idempotency_key=_string_or_none(arguments.get("idempotency_key")),
        # A host that surfaced the write to a person sets this. Absent, the
        # server asks the client to ask, and if it cannot be asked the action
        # refuses and says how to proceed.
        approved=bool(arguments.get("approved", False)),
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
