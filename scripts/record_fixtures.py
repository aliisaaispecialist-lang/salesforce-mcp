"""Capture real Salesforce responses, scrubbed, so tests can use real shapes.

Every mocked response in this repository was written from documentation. That
is the best anyone can do without an org, and it is not the same as knowing:
a field that is absent rather than null, an error body with one more layer of
nesting, a date format that is not quite ISO -- none of those show up until
Salesforce answers for itself.

This script records the answers and removes what is specific to one org, so
the shapes can be committed and used by someone who has no org at all.

Run it once an org exists:

    python scripts/record_fixtures.py

Then **read what it wrote before committing it.** The scrubber replaces record
ids, instance hosts, and known credential-shaped keys, but it cannot know that
a contact in your org is a real person. Anything a stranger should not read
does not belong in `fixtures/`.
"""

import asyncio
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from salesforce_connector.auth.jwt_bearer import JwtBearerAuth
from salesforce_connector.config import load_settings
from salesforce_connector.errors.model import ConnectorError
from salesforce_connector.transport.client import SalesforceClient
from salesforce_connector.transport.exchange import RequestSpec

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

# A Salesforce id is 15 or 18 characters of base62 and identifies exactly one
# record in exactly one org. Every one of them goes.
RECORD_ID = re.compile(r"\b[a-zA-Z0-9]{15}(?:[a-zA-Z0-9]{3})?\b")
INSTANCE = re.compile(r"https://[a-zA-Z0-9.\-]+\.salesforce\.com")

SECRET_KEYS = frozenset(
    {"access_token", "refresh_token", "sessionId", "signature", "id_token", "assertion"}
)

# What to record: the calls the five actions actually make, plus the failures
# whose shape the error mapping depends on.
RECORDINGS: tuple[tuple[str, RequestSpec], ...] = (
    ("limits", RequestSpec(method="GET", path="limits")),
    (
        "describe_opportunity",
        RequestSpec(method="GET", path="sobjects/Opportunity/describe"),
    ),
    (
        "search_no_matches",
        RequestSpec(
            method="POST",
            path="parameterizedSearch",
            json_body={
                "q": "MCPTestNoSuchPerson",
                "fields": ["Id", "Name", "Email", "Phone", "Title", "AccountId"],
                "sobjects": [{"name": "Contact"}],
                "in": "ALL",
                "overallLimit": 5,
                "offset": 0,
            },
        ),
    ),
    (
        "error_record_not_found",
        RequestSpec(method="GET", path="sobjects/Contact/003000000000000AAA"),
    ),
    (
        "error_required_field_missing",
        RequestSpec(method="POST", path="sobjects/Contact", json_body={}, is_write=True),
    ),
)


def scrub(value: Any) -> Any:
    """Remove anything that identifies one org, one record, or one session.

    Matched on `Mapping` and `Sequence` rather than `dict` and `list`, because
    a response reaching here has already been through `freeze()`: its
    dictionaries are `MappingProxyType` and its lists are tuples, and neither
    is an instance of the concrete type. Checking for `dict` walked straight
    past every nested record without descending -- so nothing was scrubbed and
    nothing said so. The JSON encoder refusing a `mappingproxy` is the only
    reason it surfaced at all.
    """
    if isinstance(value, Mapping):
        return {
            key: "REDACTED" if key in SECRET_KEYS else scrub(inner) for key, inner in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [scrub(item) for item in value]
    if isinstance(value, str):
        return RECORD_ID.sub("0" * 18, INSTANCE.sub("https://example.my.salesforce.com", value))
    return value


async def record_one(client: SalesforceClient, name: str, spec: RequestSpec) -> dict[str, Any]:
    """Perform one call and describe what came back, failure included.

    A failure is recorded rather than raised: the shape of an error is exactly
    what `errors/mapping.py` classifies against, so it is worth as much as a
    success.
    """
    try:
        response = await client.request(spec)
    except ConnectorError as failure:
        error = failure.to_action_error()
        return {
            "name": name,
            "outcome": "error",
            "code": error.code,
            "category": error.category,
            "reason": scrub(error.reason),
        }
    return {
        "name": name,
        "outcome": "success",
        "status": response.status,
        "body": scrub(response.body),
    }


async def main() -> None:
    """Record everything, one file per call, and say what was written."""
    FIXTURES.mkdir(exist_ok=True)
    settings = load_settings()
    client = SalesforceClient.open(settings, JwtBearerAuth())
    try:
        for name, spec in RECORDINGS:
            captured = await record_one(client, name, spec)
            target = FIXTURES / f"{name}.json"
            target.write_text(json.dumps(captured, indent=2, sort_keys=True), encoding="utf-8")
            print(f"{target.name}: {captured['outcome']}")
    finally:
        await client.aclose()
    print(f"\nWritten to {FIXTURES}. Read every file before committing it.")


if __name__ == "__main__":
    asyncio.run(main())
