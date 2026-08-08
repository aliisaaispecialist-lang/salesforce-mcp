"""Put known records in the org, so a search has a right answer to compare to.

An empty org makes every test look the same: "no results" is indistinguishable
from "the search is broken". These records give each prompt an expected
outcome, printed here so you can check what came back rather than trusting it.

    python scripts/seed_demo_data.py            # load them
    python scripts/seed_demo_data.py --remove   # take them out again

Every record's surname ends in `Demo`, so the cleanup can find exactly what
this script created and nothing else in the org.
"""

import argparse
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from salesforce_connector.auth.jwt_bearer import JwtBearerAuth
from salesforce_connector.client import SalesforceClient
from salesforce_connector.config import load_settings
from salesforce_connector.exchange import RequestSpec

CONTACTS = [
    {"FirstName": "Ada", "LastName": "LovelaceDemo", "Email": "ada@example.com",
     "Phone": "+973 1111 1111", "Title": "Chief Analyst"},
    {"FirstName": "Grace", "LastName": "HopperDemo", "Email": "grace@example.com",
     "Phone": "+973 2222 2222", "Title": "Rear Admiral"},
    {"FirstName": "Alan", "LastName": "TuringDemo", "Email": "alan@example.com",
     "Title": "Cryptanalyst"},
    # Four sharing a surname, so a paged search has more than one page to walk.
    {"FirstName": "Katherine", "LastName": "PagerDemo", "Email": "kat@example.com"},
    {"FirstName": "Dorothy", "LastName": "PagerDemo", "Email": "dot@example.com"},
    {"FirstName": "Mary", "LastName": "PagerDemo", "Email": "mary@example.com"},
    {"FirstName": "Annie", "LastName": "PagerDemo", "Email": "annie@example.com"},
]


async def load(client: SalesforceClient) -> None:
    """Create every record and print what a search should now find."""
    made = []
    for fields in CONTACTS:
        response = await client.request(
            RequestSpec(method="POST", path="sobjects/Contact", json_body=fields, is_write=True)
        )
        made.append((response.body["id"], f"{fields.get('FirstName','')} {fields['LastName']}"))

    print(f"Created {len(made)} contacts:\n")
    for record_id, name in made:
        print(f"  {record_id}  {name}")

    print("\nWhat to expect now:\n")
    print('  "search for Ada Lovelace"      -> 1 result, ada@example.com, Chief Analyst')
    print('  "search for Grace Hopper"      -> 1 result, Rear Admiral')
    print('  "search for PagerDemo"         -> 4 results, enough to page through')
    print('  "search for Napoleon"          -> 0 results, and that is correct')
    print("\nSearch is index-backed, so allow a few seconds before the first one.")


async def remove(client: SalesforceClient) -> None:
    """Delete everything this script created, and nothing else."""
    found = await client.request(
        RequestSpec(
            method="GET",
            path="query",
            params={"q": "SELECT Id, Name FROM Contact WHERE LastName LIKE '%Demo'"},
        )
    )
    records = found.body.get("records", [])
    if not records:
        print("Nothing to remove.")
        return
    for record in records:
        await client.request(
            RequestSpec(method="DELETE", path=f"sobjects/Contact/{record['Id']}", is_write=True)
        )
        print(f"  deleted {record['Id']}  {record['Name']}")
    print(f"\nRemoved {len(records)} demo contacts.")


async def main() -> None:
    """Load or remove, against whichever org `.env` points at."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--remove", action="store_true", help="delete them instead")
    args = parser.parse_args()

    client = SalesforceClient.open(load_settings(), JwtBearerAuth())
    try:
        await (remove(client) if args.remove else load(client))
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
