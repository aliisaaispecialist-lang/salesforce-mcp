"""Create a Salesforce opportunity, linked to a contact.

Two writes happen here: the opportunity, then the contact link. The link can
fail after the opportunity already exists, which is why the output reports
contact_linked separately rather than a single pass/fail.

Run with a configured .env:
    PYTHONPATH=src python examples/create_opportunity.py
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

# Placeholder ids in Salesforce's own shape (001 = Account, 003 = Contact),
# not records that exist anywhere. Real usage finds these with
# search_contact.py, or omits them - both fields are optional here.
ACCOUNT_ID = "001XX000003DHPhAA"
CONTACT_ID = "003XX000004TmiQAA"


async def main() -> None:
    """Create an opportunity and print the record, including the link outcome."""
    settings = load_settings()
    async with SalesforceClient.open(settings, JwtBearerAuth()) as client:
        connector = SalesforceConnector(client, load_manifest(settings))
        # A fresh key per logical write, and approved=True standing in for the
        # human confirmation an MCP host collects before a write runs;
        # without either, create_opportunity refuses and says why.
        key = str(uuid4())
        request = ActionRequest(
            action_id="salesforce.create_opportunity",
            params={
                "name": "Acme Corp - annual renewal",
                "stage_name": "Prospecting",
                "close_date": "2026-12-01",
                "account_id": ACCOUNT_ID,
                "contact_id": CONTACT_ID,
                "amount": 25000,
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
