"""Update fields on an existing Salesforce contact.

Naturally idempotent - setting a field to the same value twice leaves the
same record - but it still takes an idempotency key, so a caller never has to
work out which writes are safe to repeat and which are not.

Run with a configured .env:
    PYTHONPATH=src python examples/update_contact.py
"""

# ruff: noqa: T201 - this is a script; printing the result is the point.

import asyncio
import json
from uuid import uuid4

from salesforce_connector.auth.jwt_bearer import JwtBearerAuth
from salesforce_connector.transport.client import SalesforceClient
from salesforce_connector.config import load_settings
from salesforce_connector.connector import SalesforceConnector, load_manifest
from salesforce_connector.contract import ActionRequest, ActionResult

# A placeholder id in Salesforce's own shape (003 = Contact), not a record
# that exists anywhere. Real usage finds this with search_contact.py first.
CONTACT_ID = "003XX000004TmiQAA"


async def main() -> None:
    """Update a contact's title and print the record as it stands afterwards."""
    settings = load_settings()
    async with SalesforceClient.open(settings, JwtBearerAuth()) as client:
        connector = SalesforceConnector(client, load_manifest(settings))
        # A fresh key per logical write, and approved=True standing in for the
        # human confirmation an MCP host collects before a write runs;
        # without either, update_contact refuses and says why.
        key = str(uuid4())
        request = ActionRequest(
            action_id="salesforce.update_contact",
            params={
                "contact_id": CONTACT_ID,
                "title": "Chief Mathematician",
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
