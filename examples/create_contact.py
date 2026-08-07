"""Create a Salesforce contact.

A write action: Salesforce accepts a bare last name, so this is also the
easiest way to create a near-duplicate person by accident. Real usage
searches first; this script skips that step only because it has no org to
search.

Run with a configured .env:
    PYTHONPATH=src python examples/create_contact.py
"""

# ruff: noqa: T201 - this is a script; printing the result is the point.

import asyncio
import json
from uuid import uuid4

from salesforce_connector.auth.jwt_bearer import JwtBearerAuth
from salesforce_connector.client import SalesforceClient
from salesforce_connector.config import load_settings
from salesforce_connector.connector import SalesforceConnector, load_manifest
from salesforce_connector.contract import ActionRequest, ActionResult


async def main() -> None:
    """Create a contact and print what Salesforce returned."""
    settings = load_settings()
    async with SalesforceClient.open(settings, JwtBearerAuth()) as client:
        connector = SalesforceConnector(client, load_manifest(settings))
        # A fresh key per logical write: resending this exact key after a
        # timeout returns the original result instead of a second contact.
        # approved=True stands in for the human confirmation an MCP host
        # collects before a write runs; without either, create_contact
        # refuses and says so.
        key = str(uuid4())
        request = ActionRequest(
            action_id="salesforce.create_contact",
            params={
                "last_name": "Lovelace",
                "first_name": "Ada",
                "email": "ada@example.com",
                "idempotency_key": key,
            },
            idempotency_key=key,
            approved=True,
        )
        result = await connector.execute(request)
        _report(result)


def _report(result: ActionResult) -> None:
    """Print the payload on success, or the reason and next step on failure."""
    if result.ok:
        print(json.dumps(result.data, indent=2))
        return

    error = result.error
    if error is None:  # the envelope guarantees an error accompanies a failure
        raise RuntimeError("a failed result carried no error")
    print(f"failed: {error.reason}")
    print(f"next step: {error.next_step}")


if __name__ == "__main__":
    asyncio.run(main())
