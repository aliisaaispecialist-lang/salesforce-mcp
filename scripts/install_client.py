"""Register this connector with a desktop LLM app, from one command.

    python scripts/install_client.py claude-desktop
    python scripts/install_client.py --list

Every MCP host wants the same three things -- a command, its arguments, and
some environment -- and then disagrees about where to write them, what to call
the key, and occasionally what format the file is in. That disagreement is the
entire reason this script exists. There is nothing clever here; it is the same
config, spelled the way each host reads it.

Three rules it follows without being asked:

- **Never clobber.** The existing file is backed up first, and every other key
  in it is preserved. Most of these files hold other servers and a large tree
  of unrelated settings.
- **Never invent credentials.** Values come from `.env`; if they are missing,
  it says which and stops.
- **Say where it wrote.** The path is printed, so undoing it is one file copy.

Run `--dry-run` to see the config without writing anything.
"""

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SERVER = REPO / "mcp" / "server.py"

REQUIRED = ("SF_CLIENT_ID", "SF_USERNAME", "SF_PRIVATE_KEY")
OPTIONAL = ("SF_LOGIN_URL", "SF_ALLOW_PRODUCTION", "SF_API_VERSION")

HOME = Path.home()
WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"


@dataclass(frozen=True)
class Client:
    """One host: where its config lives, and what it calls things."""

    name: str
    path: Path
    key: str = "mcpServers"
    fmt: str = "json"
    note: str = ""
    nested_command: bool = False
    """Zed wraps command, args and env inside a `command` object."""

    verified: bool = False
    """True only where this script's output has actually been run by a host."""

    aliases: tuple[str, ...] = field(default_factory=tuple)


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming"))


def clients() -> tuple[Client, ...]:
    """Every host this knows, with its config path on this platform."""
    claude_desktop = (
        _appdata() / "Claude" / "claude_desktop_config.json"
        if WINDOWS
        else HOME / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        if MACOS
        else HOME / ".config" / "Claude" / "claude_desktop_config.json"
    )
    return (
        Client(
            "claude-desktop",
            claude_desktop,
            verified=True,
            note="Quit fully from the tray icon and reopen; closing the window is not enough.",
        ),
        Client(
            "cursor",
            HOME / ".cursor" / "mcp.json",
            note="Project-scoped alternative: .cursor/mcp.json inside the project.",
        ),
        Client(
            "vscode",
            REPO / ".vscode" / "mcp.json",
            key="servers",
            note="VS Code Copilot agent mode. Written into this project's .vscode/.",
            aliases=("code", "copilot"),
        ),
        Client(
            "windsurf",
            HOME / ".codeium" / "windsurf" / "mcp_config.json",
        ),
        Client(
            "zed",
            HOME / ".config" / "zed" / "settings.json",
            key="context_servers",
            nested_command=True,
        ),
        Client(
            "gemini",
            HOME / ".gemini" / "settings.json",
            note="Gemini CLI. Qwen Code is a fork of it and uses ~/.qwen/settings.json.",
            aliases=("gemini-cli",),
        ),
        Client(
            "qwen",
            HOME / ".qwen" / "settings.json",
            note="Qwen Code, which inherits Gemini CLI's config format.",
        ),
        Client(
            "codex",
            HOME / ".codex" / "config.toml",
            key="mcp_servers",
            fmt="toml",
            note="OpenAI Codex CLI. TOML rather than JSON, and the key uses underscores.",
            aliases=("openai",),
        ),
    )


def find(name: str) -> Client:
    """Resolve a host by name or alias, listing the known ones if it is neither."""
    for client in clients():
        if name == client.name or name in client.aliases:
            return client
    known = ", ".join(c.name for c in clients())
    raise SystemExit(f"Unknown client {name!r}.\nKnown: {known}\nOr run --list.")


def credentials() -> dict[str, str]:
    """Read what the server needs from `.env`, unquoting as dotenv would.

    A host launches the server from its own working directory, so `.env` is
    usually out of reach and the values have to travel in the config itself.
    """
    source = REPO / ".env"
    if not source.exists():
        raise SystemExit(f"No {source} yet. Copy .env.example to .env and fill it in first.")

    found: dict[str, str] = {}
    for line in source.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        name, value = name.strip(), value.strip()
        if not value or name not in (*REQUIRED, *OPTIONAL):
            continue
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1].replace("\\n", "\n")
        found[name] = value

    missing = [name for name in REQUIRED if name not in found]
    if missing:
        raise SystemExit(f"{source} is missing: {', '.join(missing)}. See QUICKSTART.md step 4.")
    return found


def entry(client: Client) -> dict[str, Any]:
    """The server as this host wants it spelled.

    Zed is the odd one: it nests everything under a `command` object whose
    executable is called `path`, where every other host puts `command`,
    `args`, and `env` side by side.
    """
    executable = sys.executable
    args = [str(SERVER)]
    env = {"PYTHONPATH": str(REPO / "src"), **credentials()}
    if client.nested_command:
        return {"command": {"path": executable, "args": args, "env": env}}
    return {"command": executable, "args": args, "env": env}


def as_toml(name: str, body: dict[str, Any], key: str) -> str:
    """Render one server as TOML, for the hosts that read it.

    Hand-written rather than pulled from a library: this is one table with
    three keys, and `tomllib` in the standard library reads TOML without
    writing it.
    """
    args = ", ".join(json.dumps(a) for a in body["args"])
    lines = [
        f"\n[{key}.{name}]",
        f"command = {json.dumps(body['command'])}",
        f"args = [{args}]",
        "",
        f"[{key}.{name}.env]",
        *(f"{k} = {json.dumps(v)}" for k, v in body["env"].items()),
    ]
    return "\n".join(lines) + "\n"


def write_json(client: Client, body: dict[str, Any]) -> None:
    """Merge into the existing file, preserving everything already there."""
    config: dict[str, Any] = {}
    if client.path.exists():
        shutil.copy2(client.path, backup_for(client.path))
        try:
            config = json.loads(client.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as bad:
            raise SystemExit(f"{client.path} is not valid JSON ({bad}). Fix it first.") from bad

    existing = sorted(config.get(client.key, {}))
    config.setdefault(client.key, {})["salesforce"] = body
    client.path.parent.mkdir(parents=True, exist_ok=True)
    client.path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    if existing:
        print(f"  kept alongside: {', '.join(existing)}")


def write_toml(client: Client, body: dict[str, Any]) -> None:
    """Append the table, after removing any table this script wrote before."""
    rendered = as_toml("salesforce", body, client.key)
    if client.path.exists():
        shutil.copy2(client.path, backup_for(client.path))
        current = client.path.read_text(encoding="utf-8")
        marker = f"[{client.key}.salesforce]"
        if marker in current:
            raise SystemExit(
                f"{client.path} already has {marker}. Remove it and run this again, "
                "rather than have two definitions disagree."
            )
        rendered = current.rstrip("\n") + "\n" + rendered
    client.path.parent.mkdir(parents=True, exist_ok=True)
    client.path.write_text(rendered, encoding="utf-8")


def backup_for(path: Path) -> Path:
    """Where the untouched original is kept, so undoing this is one file copy."""
    return path.with_suffix(path.suffix + ".backup")


def show(client: Client, body: dict[str, Any]) -> None:
    """Print the config without writing it, with the key redacted."""
    shown = json.loads(json.dumps(body))
    env = shown["command"]["env"] if client.nested_command else shown["env"]
    env["SF_PRIVATE_KEY"] = "<PEM, kept out of this output>"
    if client.fmt == "toml":
        print(as_toml("salesforce", shown, client.key))
    else:
        print(json.dumps({client.key: {"salesforce": shown}}, indent=2))


def catalogue() -> None:
    """Print every known host, where its config lives, and how sure we are."""
    print("Known hosts:\n")
    for known in clients():
        mark = "verified" if known.verified else "from its documented format"
        print(f"  {known.name:16} {known.path}")
        print(f"  {'':16} key: {known.key} ({known.fmt}, {mark})")
        if known.note:
            print(f"  {'':16} {known.note}")
        print()
    print("Usage: python scripts/install_client.py <name> [--dry-run]")


def install(client: Client) -> None:
    """Write the config and say exactly what happened and where."""
    body = entry(client)
    if client.fmt == "toml":
        write_toml(client, body)
    else:
        write_json(client, body)

    print(f"Registered with {client.name}.")
    print(f"  wrote:  {client.path}")
    if backup_for(client.path).exists():
        print(f"  backup: {backup_for(client.path).name}")
    if not client.verified:
        print("  note:   written from this host's documented format, not verified here.")
    if client.note:
        print(f"  {client.note}")
    print("\nRestart the app. You should then see five salesforce_* tools.")


def main() -> None:
    """Parse the arguments and do one of the three things this script does."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("client", nargs="?", help="which host to register with")
    parser.add_argument("--list", action="store_true", help="show every known host")
    parser.add_argument("--dry-run", action="store_true", help="print the config, write nothing")
    args = parser.parse_args()

    if args.list or not args.client:
        catalogue()
        return

    client = find(args.client)
    if args.dry_run:
        show(client, entry(client))
        print(f"\nWould write to: {client.path}")
        return
    install(client)


if __name__ == "__main__":
    main()
