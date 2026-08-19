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

**Two settings decide whether this measures anything.** `plan` mode suppresses
write tool calls outright, so every write case scores as a refusal; the mode
must be one that permits a call. And without the one-shot instruction below,
a careful agent reads before it writes and searches before it creates, so the
first call is a read on a task whose answer is a write. Each of those masked
the other: with recon happening, `plan` and `dontAsk` produced identical
results, and the mode looked irrelevant. It is not.

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

# Without this the eval measures caution rather than choice. Asked to create a
# contact, a careful agent searches first -- which is exactly what this
# connector's own `instructions` tell it to do -- and asked to update a record
# it reads the record first. Both are right, and both make the *first* tool a
# read on a task whose answer is a write. Scoring the first call then reports a
# well-behaved agent as having picked wrong every time.
#
# So the model is asked for its choice, not its plan. What survives is the
# question the names and descriptions have to answer: which one tool does this?
ONE_SHOT = (
    "Call exactly one tool: the single tool that performs what the user asked. "
    "Do not first call a tool to search, read, verify, list, or check whether "
    "something exists -- assume any id or name in the request is valid. If no "
    "available tool performs what was asked, call no tool at all and say so."
)
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


def command(prompt: str, config: pathlib.Path, model: str, effort: str, mode: str) -> list[str]:
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
        "--append-system-prompt",
        ONE_SHOT,
        "--permission-mode",
        mode,
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model,
        "--effort",
        effort,
    ]


def chosen(
    prompt: str, config: pathlib.Path, model: str, effort: str, mode: str = "dontAsk"
) -> tuple[str | None, dict[str, Any], float, str | None]:
    """Return the first Salesforce tool the model reached for, its arguments, and what went wrong.

    The subprocess is killed as soon as that tool appears. Letting it run on
    would spend turns watching a placeholder credential fail, which is neither
    the question being asked nor free.

    The third value is why a case has no answer, when it has none. A run that
    is rate limited or that errors also produces no tool call, and scoring that
    as "chose nothing" would count a failed run as a correct refusal and move
    the abstention number in the flattering direction. A case that could not be
    asked is not a case the model got wrong; it is a case that did not run.
    """
    running = subprocess.Popen(  # noqa: S603
        command(prompt, config, model, effort, mode),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    picked: str | None = None
    sent: dict[str, Any] = {}
    spent = 0.0
    trouble: str | None = None
    try:
        for line in running.stdout or ():
            event = _parsed(line)
            if event is None:
                continue
            trouble = trouble or _trouble_in(event)
            if event.get("type") == "result":
                spent = float(event.get("total_cost_usd") or 0.0)
            found = _tool_in(event)
            if found is not None:
                picked = found[0].removeprefix(PREFIX)
                sent = found[1]
                break
    finally:
        running.kill()
        running.wait(timeout=10)
    if picked is not None:
        return picked, sent, spent, None
    return None, sent, spent, trouble


def _parsed(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return None
    # A line can be valid JSON and still not be an event: the CLI prints arrays
    # and bare strings too, and returning one of those would fail later, further
    # from the cause.
    return parsed if isinstance(parsed, dict) else None


def _trouble_in(event: dict[str, Any]) -> str | None:
    """Name the reason this run could not answer, if it could not.

    Two shapes matter. A rate limit arrives as its own event with a status
    that is not `allowed`, and a run that fails arrives as a `result` whose
    subtype is not `success`.
    """
    if event.get("type") == "rate_limit_event":
        status = str(event.get("rate_limit_info", {}).get("status", ""))
        return f"rate limited ({status})" if status and status != "allowed" else None
    if event.get("type") == "result":
        subtype = str(event.get("subtype", ""))
        if subtype and subtype != "success":
            return f"run failed ({subtype})"
        if event.get("is_error"):
            return "run failed (is_error)"
    return None


def _tool_in(event: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """The Salesforce tool named in this event and the arguments sent to it.

    The arguments come back as well as the name because they answer a separate
    question at no extra cost: picking the right tool and then filling it in
    wrongly is still a failed call, and the same run can score both.
    """
    if event.get("type") != "assistant":
        return None
    for block in event.get("message", {}).get("content", []):
        if block.get("type") == "tool_use" and str(block.get("name", "")).startswith(PREFIX):
            sent = block.get("input")
            return str(block["name"]), sent if isinstance(sent, dict) else {}
    return None
