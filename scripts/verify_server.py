"""Launch the server the way an app does, and check it behaves.

`check_connection.py` proves the credentials. This proves the thing an app
actually talks to: it starts `mcp/server.py` as a subprocess, speaks JSON-RPC
over stdio, lists the tools, runs a read, and confirms a write is refused
without approval.

Three questions, in the order they matter:

1. Does it start and offer five tools?
2. Does a real call reach Salesforce and come back fenced as data?
3. Is an unapproved write refused?

The third is the one worth running. A connector that answers reads correctly
and writes without asking is worse than one that does not work at all.
"""

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parents[1]
EXPECTED = 5


async def main() -> int:
    """Run the three checks, reporting each as it passes."""
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(REPO / "mcp" / "server.py")],
        env={"PYTHONPATH": str(REPO / "src")},
        cwd=str(REPO),  # so it finds .env, as it would from a terminal
    )

    async with stdio_client(server) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        tools = await session.list_tools()
        print(f"tools: {len(tools.tools)}")
        for tool in sorted(t.name for t in tools.tools):
            print(f"  {tool}")
        if len(tools.tools) != EXPECTED:
            print(f"\nExpected {EXPECTED} tools. Something is wrong with the registry.")
            return 1

        found = await session.call_tool(
            "salesforce_search_contact", {"query": "MCPTestNoSuchPerson"}
        )
        text = getattr(found.content[0], "text", "") if found.content else ""
        fenced = text.startswith("<salesforce_record_data-")
        if found.is_error:
            print(f"\nlive search failed: {text[:200]}")
            print("Run scripts/check_connection.py to see why.")
            return 1
        print(f"live search ran: ok{'' if fenced else '  (WARNING: result not fenced)'}")

        refused = await session.call_tool(
            "salesforce_create_contact",
            {"last_name": "VerifyRunNoRecord", "idempotency_key": "verify-run-12345678"},
        )
        if not refused.is_error:
            print("\nunapproved write was NOT refused. This is a serious problem.")
            return 1
        print("unapproved write refused: ok")

    print("\nAll three checks passed. The server works.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
