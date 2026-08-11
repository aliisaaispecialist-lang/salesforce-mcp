"""Generate the happy-path case set, and refuse to generate a broken one.

A happy-path case asks one thing: given a request this connector *can* serve,
does the model reach for the right tool? Nothing else. No missing values, no
ambiguity, no request the connector cannot honour.

That isolation is the whole point, and it was learned the expensive way. The
first case set mixed everything together and scored 69.6%, of which eleven
misses turned out to be prompts that omitted a required field. The model
refused to invent one, which is correct and is what this connector is built to
do, and the eval recorded it as choosing the wrong tool. A prompt the model
cannot act on measures nothing about whether it would have chosen well.

So every prompt here carries every required value in its text, and this script
checks that rather than trusting it. `verify()` reads the required fields
straight from each action's input schema and asserts the prompt actually
mentions each one, by value. A case that cannot be satisfied never reaches the
file.

Two fields are exempt and named in `SUPPLIED_BY_THE_CALLER`, because no human
puts them in a sentence: the model generates `idempotency_key` itself, and
`approved` records a human confirmation that happens outside the request.

    python evals/build_happy_path.py            # write the file
    python evals/build_happy_path.py --check    # verify without writing
"""

# ruff: noqa: T201, E501 - it prints its report, and a prompt reads worse when wrapped.

import argparse
import json
import pathlib
import sys
from collections.abc import Mapping, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from salesforce_connector.actions.registry import BY_ID

OUT = pathlib.Path(__file__).with_name("happy_path.jsonl")

# Required by the schema, never present in a human sentence. The model mints the
# idempotency key, and approval is a person's act recorded outside the request.
SUPPLIED_BY_THE_CALLER = frozenset({"idempotency_key", "approved"})

# The literals a prompt has to contain for a given field to count as carried.
# Checked rather than assumed: a prompt that says "that contact" instead of the
# id looks fine to a reader and is unanswerable to a model.
CARRIES: Mapping[str, tuple[str, ...]] = {
    "record_id": ("003xx", "006xx", "001xx", "00Qxx", "500xx"),
    "contact_id": ("003xx",),
    "opportunity_id": ("006xx",),
    "related_to_id": ("003xx", "006xx", "001xx", "00Qxx"),
    "object_name": ("Account", "Contact", "Opportunity", "Lead", "Case", "Order"),
    "objects": ("Account", "Contact", "Opportunity", "Lead", "Case"),
    "tool_name": ("salesforce_",),
    "kind": ("read", "write"),
    "relationship": ("Account", "Contacts", "Cases", "OpportunityContactRoles"),
    "close_date": ("2026-",),
    "stage_name": ("Prospecting", "Qualify", "Negotiation", "Value Proposition"),
    "external_id_field": ("__c",),
    "external_id_value": ("A-1042", "REF-9931", "ORD-2026-0042", "CUST-88213"),
    # Anything not listed is free text and is carried by the prompt being a
    # sentence at all: a query, a name, a subject, a field value.
}

CASES: Mapping[str, Sequence[str]] = {
    "salesforce_contact_search_by_text": (
        "Find contacts matching Ada Lovelace",
        "Search our contacts for anyone called Okonkwo",
        "Look up the contact whose email is ada@example.com",
        "Which contacts match the text Fabrikam?",
    ),
    "salesforce_record_search_by_text": (
        "Search Lead records for the text Northwind",
        "Find any Case records mentioning refund request",
        "Look through Account records for Contoso",
        "Search Opportunity records for the phrase annual renewal",
    ),
    "salesforce_record_query_by_soql": (
        "Run this SOQL: SELECT Id, Name FROM Account WHERE Industry = 'Retail' LIMIT 10",
        "Query SELECT Id, StageName FROM Opportunity WHERE Amount > 50000",
        "Give me the results of SELECT Name, Email FROM Contact WHERE CreatedDate = LAST_MONTH",
        "Execute SELECT Id FROM Case WHERE Status = 'New' ORDER BY CreatedDate DESC LIMIT 5",
    ),
    "salesforce_record_get_by_id": (
        "Show me Account 001xx000003DGb2AAG",
        "Pull up Contact 003xx000004TmiQAAS",
        "What is on Opportunity 006xx000004TmiQAAS?",
        "Fetch the Lead record 00Qxx000004TmiQAAS",
    ),
    "salesforce_record_get_related_by_id": (
        "Show me the Account related to Contact 003xx000004TmiQAAS",
        "List the Contacts related to Account 001xx000003DGb2AAG",
        "Get the OpportunityContactRoles related to Opportunity 006xx000004TmiQAAS",
        "Which Cases are related to Account 001xx000003DGb2AAG?",
    ),
    "salesforce_record_count_by_object": (
        "How many Account records do we have?",
        "Count the Contact records",
        "Give me the record count for Lead and Case",
        "How many Opportunity records exist?",
    ),
    "salesforce_object_describe_by_name": (
        "Describe the Opportunity object",
        "What fields does the Contact object have?",
        "Show me the metadata for the Account object",
        "Which fields on the Lead object are writable?",
    ),
    "salesforce_tool_list_by_kind": (
        "List your read tools",
        "Which of your tools are write tools?",
        "Show me every read tool you have",
        "List all tools of kind write",
    ),
    "salesforce_tool_describe_by_name": (
        "Describe the tool salesforce_opportunity_create",
        "Show me the schema for salesforce_contact_update_by_id",
        "What is the input schema of salesforce_record_upsert_by_external_id?",
        "Give me the full spec for the tool salesforce_contact_search_by_text",
    ),
    "salesforce_contact_create": (
        "Create a contact with last name Hopper",
        "Add a new contact, first name Grace, last name Hopper, email grace@example.com",
        "Register a new contact called Ada Lovelace",
        "Make a contact record for Chinua Okonkwo, phone +973 1234 5678",
    ),
    "salesforce_contact_update_by_id": (
        "Set the phone number on contact 003xx000004TmiQAAS to +973 1700 1000",
        "Update contact 003xx000004TmiQAAS, change the email to ada@example.com",
        "Change the title on contact 003xx000004TmiQAAS to Head of Engineering",
        "On contact 003xx000004TmiQAAS, set the department to Research",
    ),
    "salesforce_opportunity_create": (
        "Create an opportunity called Contoso expansion, stage Prospecting, closing 2026-11-30, worth 45000",
        "Open a new deal named Northwind support renewal at the Qualify stage, close date 2026-12-31",
        "Log an opportunity Fabrikam pilot, stage Value Proposition, closing 2026-10-15",
        "New opportunity: Tailspin migration, stage Negotiation, close date 2026-09-30, amount 120000",
    ),
    "salesforce_opportunity_create_with_contact_by_id": (
        "Create an opportunity Contoso pilot, stage Prospecting, closing 2026-09-30, and put contact 003xx000004TmiQAAS on it",
        "New deal called Adventure Works renewal, Qualify stage, close date 2026-12-01, with contact 003xx000004TmiQAAS attached",
        "Set up opportunity Fabrikam expansion at stage Negotiation closing 2026-11-15 with contact 003xx000004TmiQAAS as the decision maker",
        "In one step, create the opportunity Woodgrove upgrade, stage Prospecting, close 2026-10-01, and link contact 003xx000004TmiQAAS",
    ),
    "salesforce_opportunity_link_contact_by_id": (
        "Attach contact 003xx000004TmiQAAS to opportunity 006xx000004TmiQAAS",
        "Link contact 003xx000004TmiQAAS onto the existing opportunity 006xx000004TmiQAAS",
        "Add contact 003xx000004TmiQAAS as a contact role on opportunity 006xx000004TmiQAAS",
        "Associate opportunity 006xx000004TmiQAAS with contact 003xx000004TmiQAAS",
    ),
    "salesforce_activity_create_by_related_id": (
        "Log a call on contact 003xx000004TmiQAAS with the subject Discovery call",
        "Add a note to opportunity 006xx000004TmiQAAS with the subject Pricing agreed",
        "Record an activity against account 001xx000003DGb2AAG with subject Quarterly review",
        "Log against lead 00Qxx000004TmiQAAS an activity with the subject Left voicemail",
    ),
    "salesforce_record_update_by_id": (
        "On the Lead record 00Qxx000004TmiQAAS, set Description to 'Met at the Riyadh expo'",
        "Update Case 500xx000004TmiQAAS, set Status to Escalated",
        "Change the Industry field on Account 001xx000003DGb2AAG to Manufacturing",
        "Set Rating to Hot on Lead 00Qxx000004TmiQAAS",
    ),
    "salesforce_record_upsert_by_external_id": (
        "Upsert an Account keyed on ERP_Id__c = A-1042, set Name to Contoso Gulf",
        "Sync the Contact whose CRM_Ref__c is REF-9931, set LastName to Okonkwo and Email to c.okonkwo@example.com",
        "Create or update the Order where ExternalOrderId__c is ORD-2026-0042, setting Status to Shipped",
        "Write the Account with Billing_Ref__c of CUST-88213, set Name to Fabrikam Industries",
    ),
}


def required_of(tool_name: str) -> tuple[str, ...]:
    """The fields a prompt must carry for this tool, read from its own schema."""
    spec = next(a.spec for a in BY_ID.values() if a.spec.tool_name == tool_name)
    return tuple(
        field
        for field in spec.input_schema.get("required", ())
        if field not in SUPPLIED_BY_THE_CALLER
    )


def missing_from(prompt: str, tool_name: str) -> list[str]:
    """Which required fields this prompt fails to supply a value for."""
    lowered = prompt.lower()
    absent = []
    for field in required_of(tool_name):
        wanted = CARRIES.get(field)
        if wanted is None:
            continue  # free text; the sentence itself carries it
        if not any(literal.lower() in lowered for literal in wanted):
            absent.append(field)
    return absent


def verify() -> list[str]:
    """Every complaint about the case set, so they can all be fixed at once."""
    complaints = []
    covered = set(CASES)
    published = {action.spec.tool_name for action in BY_ID.values()}
    for absent in sorted(published - covered):
        complaints.append(f"{absent}: no happy-path case at all")
    for extra in sorted(covered - published):
        complaints.append(f"{extra}: not a published tool")
    for tool_name, prompts in CASES.items():
        if tool_name not in published:
            continue
        for prompt in prompts:
            for field in missing_from(prompt, tool_name):
                complaints.append(f"{tool_name}: prompt does not carry {field!r}\n      {prompt}")
    return complaints


def main() -> None:
    parsed = argparse.ArgumentParser(description=__doc__)
    parsed.add_argument("--check", action="store_true", help="verify without writing the file")
    args = parsed.parse_args()

    complaints = verify()
    if complaints:
        print(f"{len(complaints)} problems, nothing written:\n")
        for one in complaints:
            print(f"  - {one}")
        raise SystemExit(1)

    lines = [
        json.dumps({"prompt": prompt, "expect": tool_name, "note": "happy path"})
        for tool_name, prompts in CASES.items()
        for prompt in prompts
    ]
    total = len(lines)
    print(f"{total} cases across {len(CASES)} tools, every required field carried")
    if args.check:
        return
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written to {OUT}")


if __name__ == "__main__":
    main()
