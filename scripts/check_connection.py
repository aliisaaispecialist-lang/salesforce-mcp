"""Ask Salesforce whether the credentials work, before any client is involved.

Reads the org's limits endpoint, which changes nothing, so it is safe to run as
often as you like. It exists because the three things that go wrong during
setup, the app, the pre-authorisation, and the username, all produce errors
that look alike from inside a chat client and are easy to read there.

Exits 0 when the org answers, 1 when it does not, so it can gate a script.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from salesforce_connector.auth.jwt_bearer import JwtBearerAuth
from salesforce_connector.config import load_settings
from salesforce_connector.connector import (
    SalesforceConnector,
    load_manifest,
)
from salesforce_connector.errors.model import ConfigurationError
from salesforce_connector.transport.client import SalesforceClient

CAUSES = {
    "user hasn't approved this consumer": (
        "The app's Permitted Users is not set to 'Admin approved users are "
        "pre-authorized'. QUICKSTART step 3c."
    ),
    "user is not admin approved": (
        "Permitted Users is set, but your user is not assigned to the app. "
        "Assign it to a profile or permission set that includes you."
    ),
    "invalid_client_id": (
        "The Consumer Key is wrong, or the app was deleted. Copy it again from "
        "the app's OAuth settings."
    ),
    "invalid_grant": (
        "One of three things: the app has not finished propagating (wait up to "
        "10 minutes after saving), the username is not the Salesforce username, "
        "or the key and certificate are not a pair."
    ),
    "invalid_assertion": "The private key does not match the uploaded certificate.",
}


def explain(message: str) -> str:
    """Name the likely cause, since these errors all read alike."""
    lowered = message.lower()
    for needle, cause in CAUSES.items():
        if needle.lower() in lowered:
            return cause
    return "See the troubleshooting table at the end of QUICKSTART.md."


async def main() -> int:
    """Try the connection and report it in a form worth acting on."""
    try:
        settings = load_settings()
    except ConfigurationError as missing:
        print(f"Configuration is incomplete.\n  {missing}")
        print("\nRun: python scripts/make_env.py")
        return 1

    client = SalesforceClient.open(settings, JwtBearerAuth())
    try:
        connector = SalesforceConnector(client, load_manifest(settings))
        result = await connector.test_connection(settings)
    finally:
        await client.aclose()

    if result.ok:
        print(f"ok=True  {result.message}")
        print("\nNext: python scripts/install_client.py --list")
        return 0

    print(f"ok=False\n  {result.message}\n")
    print(f"Likely cause: {explain(result.message)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
