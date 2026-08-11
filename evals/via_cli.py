"""Ask Claude Code the question instead of the API, and stop at the answer.

Two reasons this exists alongside the API runner.

It is more faithful. The API runner rebuilds the tool list into a `tools`
array, which is close to what a client sees but is a reconstruction. This one
launches the real server, lets Claude Code perform the real handshake and the
real `tools/list`, and measures the descriptions as they actually arrive. It
also measures them inside a host that has its own system prompt and its own
tools, which is how the connector will really be used.

And it bills the Claude Code subscription rather than an API account, which
matters when the API account has no credits left.

Two hazards, both closed here rather than left to the person running it.

**It must not be allowed to roam.** Placeholder credentials make every call
fail, and a model that has just failed to reach Salesforce starts debugging:
in the first trial run it grepped `.env` for `SF_PRIVATE_KEY`. So the
filesystem and shell tools are denied, and the run is killed the moment the
first Salesforce tool is chosen. There is no `--max-turns` in this CLI, so
that kill is the only bound on cost and on wandering.

**The choice is the first Salesforce tool, not the first tool.** Where MCP
tools arrive deferred, the model reaches for `ToolSearch` first to load a
schema. That is a real step in a real host, so it is allowed, and it is not
what is being scored.
"""

import json
import pathlib
import subprocess
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]
PREFIX = "mcp__salesforce__"

# Everything that could read a secret or run a command. ToolSearch survives
# because a deferred tool cannot be chosen without it, and it is never scored.
DENIED = (
    "Bash,PowerShell,Read,Write,Edit,NotebookEdit,Glob,Grep,"
    "Task,WebFetch,WebSearch,Skill,Workflow,SendMessage"
)


def server_config() -> dict[str, Any]:
    """Launch the real connector, with credentials that cannot reach an org.

    The same placeholders CI uses. `tools/list` needs no Salesforce call, so
    the whole tool surface is published, and any tool that is actually invoked
    fails at authentication rather than touching a real record.
    """
    return {
        "mcpServers": {
            "salesforce": {
                "command": "python",
                "args": [str(REPO / "mcp" / "server.py")],
                "env": {
                    "PYTHONPATH": str(REPO / "src"),
                    "SF_CLIENT_ID": "placeholder",
                    "SF_USERNAME": "placeholder@example.com.sandbox",
                    "SF_PRIVATE_KEY": "placeholder",
                },
            }
        }
    }


def written_config(where: pathlib.Path) -> pathlib.Path:
    where.write_text(json.dumps(server_config(), indent=2), encoding="utf-8")
    return where


def command(prompt: str, config: pathlib.Path, model: str, effort: str) -> list[str]:
    return [
        "claude",
        "-p",
        prompt,
        "--mcp-config",
        str(config),
        # Only our server. Without this the run inherits every MCP server the
        # machine happens to have configured, and the numbers stop being about
        # this connector.
        "--strict-mcp-config",
        "--disallowedTools",
        DENIED,
        "--permission-mode",
        "plan",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model,
        "--effort",
        effort,
    ]


def chosen(prompt: str, config: pathlib.Path, model: str, effort: str) -> tuple[str | None, float]:
    """Return the first Salesforce tool the model reached for, and what it cost.

    The subprocess is killed as soon as that tool appears. Letting it run on
    would spend turns watching a placeholder credential fail, which is neither
    the question being asked nor free.
    """
    running = subprocess.Popen(  # noqa: S603
        command(prompt, config, model, effort),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    picked: str | None = None
    spent = 0.0
    try:
        for line in running.stdout or ():
            event = _parsed(line)
            if event is None:
                continue
            if event.get("type") == "result":
                spent = float(event.get("total_cost_usd") or 0.0)
            found = _tool_in(event)
            if found is not None:
                picked = found.removeprefix(PREFIX)
                break
    finally:
        running.kill()
        running.wait(timeout=10)
    return picked, spent


def _parsed(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _tool_in(event: dict[str, Any]) -> str | None:
    """The Salesforce tool named in this event, if it names one."""
    if event.get("type") != "assistant":
        return None
    for block in event.get("message", {}).get("content", []):
        if block.get("type") == "tool_use" and str(block.get("name", "")).startswith(PREFIX):
            return str(block["name"])
    return None
