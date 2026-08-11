"""Search Salesforce for a contact by name, email, or phone.

The only read among the five actions, and the one to reach for before any
write: creating a contact that already exists is the costliest mistake this
connector can make.

Run with a configured .env:
    PYTHONPATH=src python examples/search_contact.py
"""

# ruff: noqa: T201 - this is a script; printing the result is the point.

import asyncio
import json

from salesforce_connector.auth.jwt_bearer import JwtBearerAuth
from salesforce_connector.config import load_settings
from salesforce_connector.connector import SalesforceConnector, load_manifest
from salesforce_connector.contract import ActionRequest, ActionResult
from salesforce_connector.transport.client import SalesforceClient


async def main() -> None:
    """Search for a contact and print what came back."""
    settings = load_settings()
    async with SalesforceClient.open(settings, JwtBearerAuth()) as client:
        connector = SalesforceConnector(client, load_manifest(settings))
        request = ActionRequest(
            action_id="salesforce.contact_search_by_text",
            params={"query": "Ada Lovelace", "limit": 5},
        )
        result = await connector.execute(request)
        _report(result)


def _report(result: ActionResult) -> None:
    """Print the payload on success, or the reason and next step on failure."""
    if result.ok:
        print(json.dumps(result.data, indent=2))
        pagination = result.pagination
        if pagination is not None and pagination.has_more:
            print(f"\nMore results exist; pass cursor={pagination.next_cursor!r} to continue.")
        return

    error = result.error
    if error is None:  # the envelope guarantees an error accompanies a failure
        raise RuntimeError("a failed result carried no error")
    print(f"failed: {error.reason}")
    print(f"next step: {error.next_step}")


if __name__ == "__main__":
    asyncio.run(main())
