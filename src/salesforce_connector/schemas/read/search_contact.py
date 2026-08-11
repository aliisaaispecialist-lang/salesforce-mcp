"""Finding existing contacts by name, email, phone, or company.

The only read among the five actions, and the one a model should reach for
before any of the writes: creating a contact that already exists is the most
likely way this connector does damage.
"""

from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field

from salesforce_connector.contract import ActionExample, ActionKind, RiskLevel
from salesforce_connector.schemas.envelope import (
    ActionSpec,
    ErrorGuidance,
    MissingInput,
    schema_of,
)

MIN_QUERY_LENGTH: Final = 2
MAX_PAGE_SIZE: Final = 200
DEFAULT_PAGE_SIZE: Final = 20


class SearchContactInput(BaseModel):
    """What to search for."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    query: Annotated[
        str,
        Field(
            min_length=MIN_QUERY_LENGTH,
            max_length=200,
            description=(
                "Required. One piece of text, matched against the contact's own "
                "searchable fields at once: name, email, phone, title and the like. "
                "For example 'Ada Lovelace', 'ada@example.com', or "
                "'+973 1234 5678'. Two characters minimum. This is a search, not a "
                "filter: it matches whole words, and a partial word may not match.\n\n"
                "It does not search the account's name, which lives on the Account "
                "record and not on the contact, and it does not match a record id. "
                "For either of those use salesforce_record_query_by_soql, which can "
                "filter on Account.Name or on Id directly.\n\n"
                "Do not put SOQL or SOSL syntax here; it is sent as data, never as a "
                "query."
            ),
            examples=["Ada Lovelace", "ada@example.com"],
        ),
    ]
    limit: Annotated[
        int,
        Field(
            default=DEFAULT_PAGE_SIZE,
            ge=1,
            le=MAX_PAGE_SIZE,
            description=(
                f"Optional. How many contacts to return, 1 to {MAX_PAGE_SIZE}. "
                f"Defaults to {DEFAULT_PAGE_SIZE}. Ask for more only when you intend "
                "to read them all; large results cost context and rarely help. "
                "Written in digits."
            ),
            examples=[20],
        ),
    ] = DEFAULT_PAGE_SIZE
    cursor: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional. To read the next page, send back the exact cursor from the "
                "previous result. Treat it as opaque: do not parse or edit it. Omit it "
                "for the first page. When a result comes back without a cursor, there "
                "are no more pages."
            ),
        ),
    ] = None


class ContactSummary(BaseModel):
    """One contact, reduced to the fields a caller acts on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Annotated[str, Field(description="Salesforce record id, for example 003xx000004TmiQAAS.")]
    name: Annotated[str, Field(description="Full name as Salesforce holds it.")]
    email: Annotated[str | None, Field(default=None, description="Primary email, if any.")] = None
    phone: Annotated[str | None, Field(default=None, description="Primary phone, if any.")] = None
    account_id: Annotated[
        str | None, Field(default=None, description="Owning account id, if the contact has one.")
    ] = None
    title: Annotated[str | None, Field(default=None, description="Job title, if set.")] = None


class SearchContactOutput(BaseModel):
    """Contacts that matched, and where the page stopped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contacts: Annotated[
        tuple[ContactSummary, ...],
        Field(description="Matches, most relevant first. Empty when nothing matched."),
    ]
    returned: Annotated[int, Field(description="How many contacts are in this response.")]
    next_cursor: Annotated[
        str | None,
        Field(
            default=None,
            description="Send back verbatim for the next page. Absent means no more pages.",
        ),
    ] = None


SPEC = ActionSpec(
    action_id="salesforce.contact_search_by_text",
    tool_name="salesforce_contact_search_by_text",
    title="Search Salesforce contacts",
    summary=(
        "Search Salesforce for existing contacts by name, email, phone, or another "
        "of their own fields, and return the matches with their record ids."
    ),
    when_to_use=(
        "you need a contact's Salesforce id; you want to check whether a person "
        "already exists before creating them; or the user named someone and you need "
        "to confirm which record they meant."
    ),
    when_not_to_use=(
        "you already hold the contact id, in which case salesforce_record_get_by_id "
        "reads it directly and is faster and exact; you need to match on the "
        "account's name or on any condition rather than on words, which is "
        "salesforce_record_query_by_soql; you are looking for something that is not "
        "a contact, which is salesforce_record_search_by_text; or you want to "
        "create, change, or annotate a record, which the write tools do."
    ),
    kind=ActionKind.READ,
    risk=RiskLevel.LOW,
    idempotent=True,
    requires_approval=False,
    input_schema=schema_of(SearchContactInput),
    output_schema=schema_of(SearchContactOutput),
    examples=(
        ActionExample(
            title="Find someone by name",
            arguments={"query": "Ada Lovelace"},
            result={
                "contacts": [
                    {
                        "id": "003xx000004TmiQAAS",
                        "name": "Ada Lovelace",
                        "email": "ada@example.com",
                        "phone": "+973 1234 5678",
                        "account_id": "001xx000003DGb2AAG",
                        "title": "Chief Analyst",
                    }
                ],
                "returned": 1,
            },
        ),
        ActionExample(
            title="Read the second page",
            arguments={"query": "Example Corp", "limit": 3, "cursor": "3"},
            result={
                "contacts": [{"id": "003xx000004TmiRAAS", "name": "Grace Hopper", "title": "CTO"}],
                "returned": 1,
            },
        ),
    ),
    missing_inputs=(
        MissingInput(
            field="query",
            prompt=(
                "Who should I search for in Salesforce? A name, email address, or "
                "phone number is enough."
            ),
        ),
    ),
    errors=(
        ErrorGuidance(
            code="connector.invalid_input",
            when="The search text is shorter than two characters.",
            remedy="Ask the user for more of the name or email, then call again.",
        ),
        ErrorGuidance(
            code="salesforce.permission_denied",
            when="This Salesforce user may not read contacts.",
            remedy=(
                "Do not retry. Tell the user their Salesforce profile lacks read "
                "access to Contact and that an administrator must grant it."
            ),
        ),
        ErrorGuidance(
            code="salesforce.rate_limited",
            when="The org has spent its API allowance for now.",
            remedy="Wait for the stated number of seconds, then repeat the same call.",
        ),
        ErrorGuidance(
            code="salesforce.transport_failed",
            when="Salesforce did not answer in time.",
            remedy="Wait briefly and repeat the same call. Reading again is always safe.",
        ),
        ErrorGuidance(
            code="salesforce.authentication_failed",
            when="The connector's Salesforce session is invalid or expired.",
            remedy=(
                "Do not retry. Report that the connector needs to re-authenticate; "
                "its credentials may be wrong or expired."
            ),
        ),
    ),
)
