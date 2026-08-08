"""Asking Salesforce a question with a condition, rather than a word.

`search_contact` finds records that mention something. This finds records that
*satisfy* something, which is a different question and the one the connector
could not answer at all: how many, which ones, in what order, within what
range.

The query arrives as SOQL text the caller composed. That is a deliberate
reversal of ADR-003, which avoided SOSL precisely because a search term could
escape a query string, and it is defensible here for a reason that does not
apply to SOSL or to SQL: **the /query endpoint is read-only by construction**.
SOQL has no INSERT, UPDATE, or DELETE to express, so the worst a malformed or
malicious query can do is read -- and what it may read is already bounded by
the Salesforce profile of the user this connector authenticates as.

What remains is guarded here rather than trusted to the caller: the statement
must be a SELECT, and a query with no LIMIT gets one, because `SELECT Id FROM
Contact` against a real org means paging the whole table and spending the
org's daily API allowance on a question nobody asked precisely.
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

MIN_QUERY_LENGTH = 10


class SoqlQueryInput(BaseModel):
    """The question, written in SOQL."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    soql: Annotated[
        str,
        Field(
            min_length=MIN_QUERY_LENGTH,
            max_length=4000,
            description=(
                "Required. A SOQL SELECT statement. Compose it from what the user "
                "asked for: they describe a condition in words and you turn it into "
                "the query.\n\n"
                "SOQL is not SQL. There are no joins and no SELECT *, so name every "
                "field you want. Related fields are reached through the "
                "relationship, as in Account.Name. Date literals are built in and "
                "worth using: THIS_MONTH, LAST_N_DAYS:30, TODAY.\n\n"
                "Only SELECT is accepted; the endpoint cannot write, and anything "
                "else is refused before it is sent. If you do not add a LIMIT one "
                "is added for you, because an unbounded query pages an entire "
                "object and spends the org's API allowance.\n\n"
                "Examples: SELECT Id, Name, Email FROM Contact WHERE LastName "
                "LIKE '%Demo' ORDER BY CreatedDate DESC LIMIT 20 -- or -- "
                "SELECT COUNT() FROM Opportunity WHERE Amount > 50000 AND "
                "CloseDate = THIS_MONTH"
            ),
            examples=[
                "SELECT Id, Name, Email FROM Contact ORDER BY CreatedDate DESC LIMIT 20",
                "SELECT COUNT() FROM Opportunity WHERE CloseDate = THIS_MONTH",
            ],
        ),
    ]
    cursor: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional. To read the next page, send back the exact cursor from "
                "the previous result. Treat it as opaque: do not parse or edit it. "
                "Omit it for the first page. A result with no cursor is the last "
                "page. When paging, send the same soql as well."
            ),
        ),
    ] = None


class SoqlQueryOutput(BaseModel):
    """What matched, how many there are, and where the page stopped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    records: Annotated[
        tuple[dict[str, Any], ...],
        Field(
            description=(
                "The matching rows, each holding exactly the fields the query "
                "named. Empty for a COUNT() query, and empty when nothing matched "
                "-- read total_size to tell those apart."
            )
        ),
    ]
    returned: Annotated[int, Field(description="How many rows are in this response.")]
    total_size: Annotated[
        int,
        Field(
            description=(
                "How many rows match the query in total, across every page. For a "
                "COUNT() query this is the answer and records is empty."
            )
        ),
    ]
    next_cursor: Annotated[
        str | None,
        Field(
            default=None,
            description="Send back verbatim for the next page. Absent means no more pages.",
        ),
    ] = None


SPEC = ActionSpec(
    action_id="salesforce.soql_query",
    tool_name="salesforce_soql_query",
    title="Query Salesforce with SOQL",
    summary=(
        "Run a read-only SOQL query against any Salesforce object, to list, filter, "
        "sort, or count records."
    ),
    when_to_use=(
        "the user described a condition rather than a name: how many of something "
        "there are, which records match a filter, the newest or largest few, or "
        "anything about an object other than Contact and Opportunity."
    ),
    when_not_to_use=(
        "the user named a person and you are trying to find them, which is the "
        "search action and matches fuzzily where this matches exactly; or you "
        "already hold the record id, in which case read it directly. This tool "
        "cannot change anything, so never reach for it to create or update."
    ),
    kind=ActionKind.READ,
    risk=RiskLevel.LOW,
    idempotent=True,
    requires_approval=False,
    input_schema=schema_of(SoqlQueryInput),
    output_schema=schema_of(SoqlQueryOutput),
    examples=(
        ActionExample(
            title="Count something",
            arguments={"soql": "SELECT COUNT() FROM Contact WHERE LastName LIKE '%Demo'"},
            result={"records": [], "returned": 0, "total_size": 7},
        ),
        ActionExample(
            title="List with a filter and an order",
            arguments={
                "soql": (
                    "SELECT Id, Name, Email FROM Contact WHERE Email LIKE "
                    "'%example.com' ORDER BY CreatedDate DESC LIMIT 2"
                )
            },
            result={
                "records": [
                    {
                        "Id": "003xx000004TmiQAAS",
                        "Name": "Ada Lovelace",
                        "Email": "ada@example.com",
                    },
                    {
                        "Id": "003xx000004TmiRAAS",
                        "Name": "Grace Hopper",
                        "Email": "grace@example.com",
                    },
                ],
                "returned": 2,
                "total_size": 7,
                "next_cursor": "/services/data/v67.0/query/01gxx000000abcd",
            },
        ),
    ),
    missing_inputs=(
        MissingInput(
            field="soql",
            prompt=(
                "What would you like to know? Describe it in your own words and I "
                "will write the query, for example 'how many contacts were added "
                "this month' or 'deals closing this quarter over 50,000'."
            ),
        ),
    ),
    errors=(
        ErrorGuidance(
            code="connector.invalid_input",
            when="The statement is not a SELECT, or is too short to be a query.",
            remedy=(
                "This endpoint only reads. Rewrite it as a SELECT. To create or "
                "change a record, use one of the write tools instead."
            ),
        ),
        ErrorGuidance(
            code="salesforce.invalid_input",
            when="Salesforce rejected the SOQL: a bad field name, object, or syntax.",
            remedy=(
                "The error names the position and the problem. A field that does "
                "not exist is the usual cause, so call describe on the object to "
                "see its real field names rather than guessing again."
            ),
        ),
        ErrorGuidance(
            code="salesforce.permission_denied",
            when="This user may not read that object or one of the named fields.",
            remedy=(
                "Do not retry. Report which object was refused and that an "
                "administrator must grant read access."
            ),
        ),
        ErrorGuidance(
            code="salesforce.rate_limited",
            when="The org has spent its API allowance for now.",
            remedy=(
                "Wait the stated number of seconds, then repeat. Consider adding a "
                "tighter LIMIT: a query paging thousands of rows spends the "
                "allowance quickly."
            ),
        ),
        ErrorGuidance(
            code="salesforce.transport_failed",
            when="Salesforce did not answer in time.",
            remedy=(
                "Wait briefly and repeat the same query. Reading again is always "
                "safe. A query that repeatedly times out is usually too broad; add "
                "a WHERE clause or a smaller LIMIT."
            ),
        ),
    ),
)
