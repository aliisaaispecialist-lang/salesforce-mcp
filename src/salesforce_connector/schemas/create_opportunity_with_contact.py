"""Opening a deal and attaching its contact as one write that cannot half-fail.

`create_opportunity` and `link_contact_to_opportunity` are two tools because
splitting them let each failure be seen and acted on. That split has one cost,
and it is the reason this exists: between the two calls there is a moment where
the deal exists and nobody is attached to it, and if the second call fails the
org keeps a deal with no contact until somebody notices.

Salesforce can apply both as one unit. Either both land or neither does, and
there is no state in between for anybody to notice later.

The two shapes are not interchangeable and the rule is stated on both tools. If
the contact id is already known, this is the right call: one step, no gap. If
it is not, the chain is the right call, because it lets the deal be created now
and the person found afterwards.
"""

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from salesforce_connector.contract import ActionExample, ActionKind, RiskLevel
from salesforce_connector.schemas.envelope import (
    ActionSpec,
    ErrorGuidance,
    MissingInput,
    schema_of,
)

MIN_KEY_LENGTH = 8
_ID_LENGTH = (15, 18)


class CreateOpportunityWithContactInput(BaseModel):
    """The deal, and the person it is for."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=120,
            description=(
                "Required. What the deal is called. Use something a person would "
                "recognise in a list, usually the account and what it is for."
            ),
            examples=["Example Corp - annual renewal"],
        ),
    ]
    stage_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=80,
            description=(
                "Required. The sales stage. Stages are configured per org, so do not "
                "assume the Salesforce defaults: call salesforce_describe_object on "
                "Opportunity and use a value it reports. A stage this org does not "
                "have fails the whole write, including the contact link."
            ),
        ),
    ]
    close_date: Annotated[
        date,
        Field(
            description=(
                "Required. Expected close date, written as YYYY-MM-DD. Ask the "
                "user rather than inventing one; a date invented here becomes a "
                "forecast somebody relies on."
            ),
            examples=["2026-12-01"],
        ),
    ]
    contact_id: Annotated[
        str,
        Field(
            min_length=_ID_LENGTH[0],
            max_length=_ID_LENGTH[1],
            description=(
                "Required. The person the deal is for. Find them with "
                "salesforce_search_contact first. A contact id starts 003; if you do "
                "not have one, use salesforce_create_opportunity instead and attach "
                "the contact afterwards."
            ),
        ),
    ]
    amount: Annotated[
        float | None,
        Field(
            default=None,
            ge=0,
            description=(
                "Optional. Value of the deal, in the org's currency, written in "
                "digits rather than words."
            ),
            examples=[45000],
        ),
    ] = None
    account_id: Annotated[
        str | None,
        Field(
            default=None,
            min_length=_ID_LENGTH[0],
            max_length=_ID_LENGTH[1],
            description="Optional. The company the deal belongs to. An account id starts 001.",
        ),
    ] = None
    role: Annotated[
        str | None,
        Field(
            default=None,
            max_length=80,
            description=(
                "Optional. The contact's part in the deal, such as Decision Maker. "
                "Leave it out unless the user said one: roles are a restricted "
                "picklist in most orgs, and a value this org does not have fails "
                "the whole write."
            ),
        ),
    ] = None
    idempotency_key: Annotated[
        str,
        Field(
            min_length=MIN_KEY_LENGTH,
            max_length=128,
            description=(
                "Required. A unique string for this deal. Reuse it when retrying so "
                "the same deal is not opened twice."
            ),
        ),
    ]
    approved: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "Optional, defaults to false, but the call is refused without it. "
                "Confirmation that the user asked for this deal to be created."
            ),
        ),
    ] = False


class CreateOpportunityWithContactOutput(BaseModel):
    """The deal and the link, both of which now exist or neither of which does."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Annotated[str, Field(description="Record id of the created opportunity.")]
    name: Annotated[str, Field(description="Name as stored.")]
    stage_name: Annotated[str, Field(description="Stage as stored.")]
    contact_id: Annotated[str, Field(description="The contact that was attached.")]
    contact_role_id: Annotated[
        str, Field(description="Record id of the contact role joining the two.")
    ]
    created: Annotated[
        bool,
        Field(
            description=(
                "True if this call created the deal. False means the identical key "
                "had already created it and this is the original outcome."
            )
        ),
    ]


SPEC = ActionSpec(
    action_id="salesforce.create_opportunity_with_contact",
    tool_name="salesforce_create_opportunity_with_contact",
    title="Create a Salesforce opportunity and attach its contact together",
    summary=(
        "Open a deal and attach the person it is for in a single write that either "
        "fully succeeds or changes nothing at all."
    ),
    when_to_use=(
        "the user asked to open a deal for a specific person and you already have "
        "that person's contact id. One call, and no moment where the deal exists "
        "without them."
    ),
    when_not_to_use=(
        "you do not have the contact id yet, in which case use "
        "salesforce_create_opportunity now and attach the contact afterwards with "
        "salesforce_link_contact_to_opportunity; the deal is not for a particular "
        "person, which is salesforce_create_opportunity on its own; or the deal "
        "already exists and only needs a contact attached, which is "
        "salesforce_link_contact_to_opportunity."
    ),
    kind=ActionKind.WRITE,
    risk=RiskLevel.MEDIUM,
    idempotent=False,
    requires_approval=True,
    input_schema=schema_of(CreateOpportunityWithContactInput),
    output_schema=schema_of(CreateOpportunityWithContactOutput),
    examples=(
        ActionExample(
            title="Open a deal for a known contact",
            arguments={
                "name": "Example Corp - annual renewal",
                "stage_name": "Qualify",
                "close_date": "2026-12-01",
                "contact_id": "003xx000004TmiQAAS",
                "amount": 45000,
                "idempotency_key": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                "approved": True,
            },
            result={
                "id": "006xx000004TmiQAAS",
                "name": "Example Corp - annual renewal",
                "stage_name": "Qualify",
                "contact_id": "003xx000004TmiQAAS",
                "contact_role_id": "00Kxx0000011AAAI",
                "created": True,
            },
        ),
    ),
    manual_recovery=(
        "Nothing was left half-done: this write applies both records or neither, so "
        "there is no orphaned deal to clean up. Search Opportunities for the name to "
        "confirm, then create it from Opportunities > New and add the person under "
        "Related > Contact Roles. "
    ),
    missing_inputs=(
        MissingInput(field="name", prompt="What should the opportunity be called?"),
        MissingInput(field="stage_name", prompt="Which sales stage is this opportunity at?"),
        MissingInput(
            field="close_date",
            prompt="What is the expected close date? Use YYYY-MM-DD.",
        ),
        MissingInput(
            field="contact_id",
            prompt=(
                "Who is this deal for? A name or email is enough and I will search "
                "for their record."
            ),
        ),
    ),
    errors=(
        ErrorGuidance(
            code="connector.invalid_input",
            when=(
                "The stage or role is not a value this org accepts, or a required "
                "field is missing. The message names which of the two writes was "
                "rejected."
            ),
            remedy=(
                "Nothing was created, so fix the named value and call again with the "
                "same idempotency key. For a rejected stage or role, call "
                "salesforce_describe_object on Opportunity and use a value it lists."
            ),
        ),
        ErrorGuidance(
            code="salesforce.record_not_found",
            when="The contact id or account id does not refer to a record that exists.",
            remedy=(
                "Nothing was created. Search for the contact again rather than "
                "retrying the same id, then call again."
            ),
        ),
        ErrorGuidance(
            code="salesforce.permission_denied",
            when="This user may not create opportunities or contact roles.",
            remedy=(
                "Do not retry. Report which of the two was refused and that an "
                "administrator must grant create access."
            ),
        ),
        ErrorGuidance(
            code="salesforce.rate_limited",
            when="The org has spent its API allowance for now.",
            remedy="Wait the stated number of seconds, then repeat with the same idempotency key.",
        ),
        ErrorGuidance(
            code="salesforce.transport_failed",
            when="Salesforce did not answer in time.",
            remedy=(
                "Repeat with the identical idempotency key. Either both records exist or "
                "neither does, so there is no partial state to inspect first."
            ),
        ),
        ErrorGuidance(
            code="connector.escalate_to_human",
            when="The write failed three times in a row and will not succeed by retrying.",
            remedy="Stop calling this tool. Tell the user it must be done by hand and how.",
        ),
    ),
)
