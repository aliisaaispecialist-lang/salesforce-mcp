"""Build `.env` without the key passing through an editor or a clipboard.

A private key is long, has to sit on one line, and stops being private the
moment it has been pasted somewhere. This reads it straight off disk, asks for
the two values that are not secret, hides the one that arguably is, and writes
the file itself.

Nothing is echoed. Nothing reaches shell history. The existing `.env` is never
silently replaced.
"""

import getpass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGET = REPO / ".env"
EXAMPLE = REPO / ".env.example"
KEY = REPO / "secrets" / "salesforce.key"

SANDBOX = "https://test.salesforce.com"
PRODUCTION = "https://login.salesforce.com"


def one_line_key() -> str:
    """Read the PEM and fold it onto one line, as a dotenv value must be."""
    if not KEY.exists():
        raise SystemExit(
            f"No private key at {KEY}.\n"
            "Generate one first, see Salesforce credentials in README.md:\n"
            "  openssl req -x509 -sha256 -nodes -days 365 -newkey rsa:2048 \\\n"
            "    -keyout secrets/salesforce.key -out secrets/salesforce.crt \\\n"
            '    -subj "/CN=salesforce-mcp"'
        )
    pem = KEY.read_text(encoding="utf-8").strip()
    if "BEGIN" not in pem:
        raise SystemExit(f"{KEY} does not look like a PEM private key.")
    return pem.replace("\r\n", "\n").replace("\n", "\\n")


def ask() -> tuple[str, str, str]:
    """Collect the two values that are not on disk, plus which org this is."""
    print("Two values from your Salesforce External Client App.\n")
    consumer_key = getpass.getpass("  Consumer Key (hidden as you type): ").strip()
    if not consumer_key:
        raise SystemExit("A Consumer Key is required. Nothing was written.")

    username = input("  Salesforce username: ").strip()
    if not username:
        raise SystemExit("A username is required. Nothing was written.")

    print("\n  Which org is this?")
    print("    1  Sandbox            (test.salesforce.com)")
    print("    2  Developer Edition  (login.salesforce.com)")
    kind = input("  1 or 2: ").strip()
    return consumer_key, username, kind


def compose(consumer_key: str, username: str, kind: str) -> str:
    """Fill the example template, leaving its comments intact."""
    developer_edition = kind == "2"
    values = {
        "SF_CLIENT_ID": consumer_key,
        "SF_USERNAME": username,
        "SF_PRIVATE_KEY": f'"{one_line_key()}"',
        "SF_LOGIN_URL": PRODUCTION if developer_edition else SANDBOX,
        # A Developer Edition org authenticates at the production host and holds
        # no real customer data. The guard opens deliberately, in writing.
        "SF_ALLOW_PRODUCTION": "true" if developer_edition else "false",
    }
    lines = []
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        name = line.split("=", 1)[0] if "=" in line else ""
        lines.append(f"{name}={values[name]}" if name in values else line)
    return "\n".join(lines) + "\n"


def main() -> None:
    """Write `.env`, refusing to overwrite one that already exists."""
    if TARGET.exists():
        raise SystemExit(
            f"{TARGET} already exists. Delete it first if you mean to start over.\n"
            "It is not overwritten automatically, because losing a working one "
            "costs more than retyping this command."
        )
    if not EXAMPLE.exists():
        raise SystemExit(f"{EXAMPLE} is missing. Are you in the project folder?")

    consumer_key, username, kind = ask()
    TARGET.write_text(compose(consumer_key, username, kind), encoding="utf-8")

    print(f"\nWrote {TARGET}")
    print("  Consumer Key: set, not shown")
    print(f"  Username:     {username}")
    print(f"  Private key:  read from {KEY.relative_to(REPO)}, folded onto one line")
    print("\n.env is gitignored and excluded from the Docker image.")
    print("Next: python scripts/check_connection.py")


if __name__ == "__main__":
    main()
