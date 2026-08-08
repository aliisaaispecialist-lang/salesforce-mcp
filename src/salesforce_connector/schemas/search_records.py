"""Searching any object by words, rather than only contacts.

`search_contact` reaches the same endpoint and is fixed to Contact, with a
field list chosen for contacts and a result shaped for the contact tools. This
is the same search with the object as an argument, for the accounts, leads,
opportunities and custom objects the other tool cannot see.

The overlap is settled in one direction and stated on both: a question about a
person goes to `search_contact`, because it returns the contact fields the
write tools expect. Everything else comes here.

The field list is an argument rather than a table in the code, because there is
no list that suits every object. `Name` does not exist on Task, which calls it
`Subject`, and assuming otherwise fails the search rather than narrowing it.
"""

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from salesforce_connector.contract import ActionExample, ActionKind, RiskLevel
from salesforce_connector.schemas.envelope import (
    ActionSpec,
    ErrorGuidance,
    MissingInput,
    schema_of,
)

MIN_TERM_LENGTH = 2
MAX_RESULTS = 200
DEFAULT_FIELDS = ("Id", "Name")


class SearchRecordsInput(BaseModel):
    """What to look for, and where."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    object_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=80,
            description=(
                "Required. The object to search, spelled as Salesforce spells it: "
                "Account, Lead, Opportunity, Case, Task, or a custom object ending "
                "__c. For Contact use salesforce_search_contact instead, which "
                "returns the contact fields the contact tools need."
            ),
            examples=["Account", "Lead", "Opportunity"],
        ),
    ]
    query: Annotated[
        str,
        Field(
            min_length=MIN_TERM_LENGTH,
            max_length=200,
            description=(
                "Required. The words to search for, as the user said them: a "
                "company name, a subject line, part of a title. This matches the "
                "way a search box matches, not the way a filter matches, so a "
                "partial word finds records containing it.\n\n"
                "For a condition rather than words, such as a date range or an "
                "amount over a threshold, use salesforce_soql_query."
            ),
            examples=["Example Corp", "renewal"],
        ),
    ]
    fields: Annotated[
        tuple[str, ...],
        Field(
            default=DEFAULT_FIELDS,
            max_length=25,
            description=(
                "Optional, defaults to Id and Name. The fields to return, named as "
                "Salesforce names them. Not every object has Name: a Task calls it "
                "Subject, and asking for a field an object does not have fails the "
                "search. Call salesforce_describe_object first if you are unsure."
            ),
            examples=[["Id", "Name", "Industry"], ["Id", "Subject", "Status"]],
        ),
    ] = DEFAULT_FIELDS
    limit: Annotated[
        int,
        Field(
            default=20,
            ge=1,
            le=MAX_RESULTS,
            description="Optional, defaults to 20. How many records to return at most.",
        ),
    ] = 20
    cursor: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional. To read the next page, send back the exact cursor from "
                "the previous result. Treat it as opaque. Omit it for the first "
                "page; a result with no cursor is the last page."
            ),
        ),
    ] = None


class SearchRecordsOutput(BaseModel):
    """What the search found."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    records: Annotated[
        tuple[dict[str, Any], ...],
        Field(
            description=(
                "The matching records, each holding the fields that were asked "
                "for. Empty means nothing matched, which for a search is an "
                "answer rather than a failure."
            )
        ),
    ]
    returned: Annotated[int, Field(description="How many records are in this response.")]
    next_cursor: Annotated[
        str | None,
        Field(
            default=None,
            description="Send back verbatim for the next page. Absent means no more pages.",
        ),
    ] = None


SPEC = ActionSpec(
    action_id="salesforce.search_records",
    tool_name="salesforce_search_records",
    title="Search any Salesforce object by words",
    summary=(
        "Find records of any object by free text, the way a search box finds them, "
        "and return the fields that were asked for."
    ),
    when_to_use=(
        "the user named something in words and you need to find it: an account by "
        "company name, a lead by surname, a case by its subject. Use it to turn a "
        "name into a record id before a tool that needs one."
    ),
    when_not_to_use=(
        "the object is Contact, which is salesforce_search_contact and returns the "
        "fields the contact tools expect; the user described a condition rather "
        "than words, such as everything closing this month, which is "
        "salesforce_soql_query; or you already hold the record id, in which case "
        "salesforce_get_record reads it directly."
    ),
    kind=ActionKind.READ,
    risk=RiskLevel.LOW,
    idempotent=True,
    requires_approval=False,
    input_schema=schema_of(SearchRecordsInput),
    output_schema=schema_of(SearchRecordsOutput),
    examples=(
        ActionExample(
            title="Find an account by name",
            arguments={
                "object_name": "Account",
                "query": "Example Corp",
                "fields": ["Id", "Name", "Industry"],
            },
            result={
                "records": [
                    {
                        "Id": "001xx000003DGb2AAG",
                        "Name": "Example Corp",
                        "Industry": "Technology",
                    }
                ],
                "returned": 1,
                "next_cursor": None,
            },
        ),
    ),
    missing_inputs=(
        MissingInput(
            field="object_name",
            prompt="Which Salesforce object should I search? For example Account or Lead.",
        ),
        MissingInput(
            field="query",
            prompt="What should I search for? A name or part of one is enough.",
        ),
    ),
    errors=(
        ErrorGuidance(
            code="connector.invalid_input",
            when=(
                "The object does not exist, one of the named fields does not exist "
                "on it, or the search term is too short."
            ),
            remedy=(
                "Search for at least two characters. If a field was rejected, call "
                "salesforce_describe_object on the object and use names it actually "
                "lists rather than retrying the same list."
            ),
        ),
        ErrorGuidance(
            code="salesforce.permission_denied",
            when="This user may not search that object.",
            remedy=(
                "Do not retry. Report which object was refused and that an "
                "administrator must grant read access."
            ),
        ),
        ErrorGuidance(
            code="salesforce.rate_limited",
            when="The org has spent its API allowance for now.",
            remedy="Wait the stated number of seconds, then repeat the same call.",
        ),
        ErrorGuidance(
            code="salesforce.transport_failed",
            when="Salesforce did not answer in time.",
            remedy="Wait briefly and repeat. Searching changes nothing, so retrying is safe.",
        ),
    ),
)
