"""Log an activity note against a Salesforce contact or opportunity.

Implemented as a completed Task in Salesforce, so it lands on the record's
own activity timeline rather than in a feature many orgs disable.

Run with a configured .env:
    PYTHONPATH=src python examples/add_activity_note.py
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
RELATED_TO_ID = "003XX000004TmiQAA"


async def main() -> None:
    """Log a call note against a contact and print the activity that was created."""
    settings = load_settings()
    async with SalesforceClient.open(settings, JwtBearerAuth()) as client:
        connector = SalesforceConnector(client, load_manifest(settings))
        # A fresh key per logical write, and approved=True standing in for the
        # human confirmation an MCP host collects before a write runs;
        # without either, add_activity_note refuses and says why.
        key = str(uuid4())
        request = ActionRequest(
            action_id="salesforce.add_activity_note",
            params={
                "related_to_id": RELATED_TO_ID,
                "subject": "Renewal call - agreed to 12 month extension",
                "body": "Discussed pricing for the renewal; Ada will confirm by Friday.",
                "activity_kind": "Call",
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
