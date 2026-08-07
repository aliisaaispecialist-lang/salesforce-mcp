"""Creating an opportunity, and optionally linking a contact to it.

Two fields here are traps. StageName is a picklist every org configures
differently, so no fixed list of stages is correct and the action reads the
org's own values rather than assuming; the error returns the permitted values
so a caller can correct itself in one step.

Linking a contact is a second write. It can fail after the opportunity exists,
which is why this action reports partial success rather than pretending the
whole thing either happened or did not.
"""

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from salesforce_connector.contract import ActionExample, ActionKind, RiskLevel
from salesforce_connector.schemas.envelope import (
    APPROVED_DESCRIPTION,
    IDEMPOTENCY_KEY_DESCRIPTION,
    ActionSpec,
    ErrorGuidance,
    MissingInput,
    schema_of,
)


class CreateOpportunityInput(BaseModel):
    """The deal to create."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=120,
            description=(
                "Required. What the deal is called, for example "
                "'Acme Corp - annual renewal'. Salesforce does not require this to be "
                "unique, so make it recognisable to a person."
            ),
        ),
    ]
    stage_name: Annotated[
        str,
        Field(
            description=(
                "Required. The sales stage, for example 'Prospecting' or "
                "'Closed Won'. Every Salesforce org configures its own stages, so "
                "there is no universal list. If you are not certain which stages this "
                "org uses, send your best guess: an invalid value is rejected and the "
                "error lists the exact values this org accepts."
            ),
        ),
    ]
    close_date: Annotated[
        date,
        Field(
            description=(
                "Required. Expected close date, as YYYY-MM-DD. Salesforce accepts a "
                "date in the past, so use the date the user actually meant rather "
                "than today's."
            )
        ),
    ]
    idempotency_key: Annotated[str, Field(min_length=8, description=IDEMPOTENCY_KEY_DESCRIPTION)]
    approved: Annotated[bool, Field(default=False, description=APPROVED_DESCRIPTION)] = False
    account_id: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional. Account the deal belongs to, id starting 001. Do not guess.",
        ),
    ] = None
    amount: Annotated[
        float | None,
        Field(default=None, ge=0, description="Optional. Value of the deal in the org's currency."),
    ] = None
    contact_id: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional. Contact to associate with the deal, id starting 003. This "
                "is a second write after the opportunity is created, so it can succeed "
                "or fail independently; the result says which happened."
            ),
        ),
    ] = None
    description: Annotated[
        str | None, Field(default=None, max_length=32000, description="Optional. Free-text notes.")
    ] = None


class CreateOpportunityOutput(BaseModel):
    """The deal that now exists, and whether the contact link took."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Annotated[str, Field(description="Record id of the created opportunity.")]
    name: Annotated[str, Field(description="Name as stored.")]
    stage_name: Annotated[str, Field(description="Stage as stored.")]
    created: Annotated[
        bool,
        Field(
            description=(
                "True if this call created the record. False means the identical key "
                "had already created it and this is the original outcome."
            )
        ),
    ]
    contact_linked: Annotated[
        bool | None,
        Field(
            default=None,
            description=(
                "True if the contact was linked, false if that step failed while the "
                "opportunity still exists, absent if no contact was requested. A false "
                "here is a partial success: do not create the opportunity again."
            ),
        ),
    ] = None


SPEC = ActionSpec(
    action_id="salesforce.create_opportunity",
    tool_name="salesforce_create_opportunity",
    title="Create a Salesforce opportunity",
    summary=(
        "Create a sales opportunity in Salesforce, optionally linked to an account "
        "and a contact, and return its record id."
    ),
    when_to_use=(
        "the user wants to record a new deal, renewal, or piece of pipeline, and you "
        "have a name, a stage, and an expected close date."
    ),
    when_not_to_use=(
        "the deal already exists and needs changing; you only want to log a "
        "conversation, which is the activity note; or you are missing the stage or "
        "close date, in which case ask the user rather than inventing them."
    ),
    kind=ActionKind.WRITE,
    risk=RiskLevel.MEDIUM,
    idempotent=False,
    requires_approval=True,
    input_schema=schema_of(CreateOpportunityInput),
    output_schema=schema_of(CreateOpportunityOutput),
    examples=(
        ActionExample(
            title="Open a deal and link the contact it came from",
            arguments={
                "name": "Example Corp - annual renewal",
                "stage_name": "Prospecting",
                "close_date": "2026-12-01",
                "amount": 45000,
                "account_id": "001xx000003DGb2AAG",
                "contact_id": "003xx000004TmiQAAS",
                "idempotency_key": "c3d4e5f6-a7b8-4c9d-8e0f-2a3b4c5d6e7f",
                "approved": True,
            },
            result={
                "id": "006xx000004TmiQAAS",
                "name": "Example Corp - annual renewal",
                "stage_name": "Prospecting",
                "created": True,
                "contact_linked": True,
            },
        ),
        ActionExample(
            title="The opportunity was created but the contact link failed",
            arguments={
                "name": "Example Corp - annual renewal",
                "stage_name": "Prospecting",
                "close_date": "2026-12-01",
                "contact_id": "003xx000004TmiQAAS",
                "idempotency_key": "c3d4e5f6-a7b8-4c9d-8e0f-2a3b4c5d6e7f",
                "approved": True,
            },
            result={
                "id": "006xx000004TmiQAAS",
                "name": "Example Corp - annual renewal",
                "stage_name": "Prospecting",
                "created": True,
                "contact_linked": False,
            },
        ),
    ),
    missing_inputs=(
        MissingInput(field="name", prompt="What should the opportunity be called?"),
        MissingInput(
            field="stage_name",
            prompt="Which sales stage is this opportunity at?",
        ),
        MissingInput(
            field="close_date",
            prompt="What is the expected close date? Use YYYY-MM-DD.",
        ),
    ),
    errors=(
        ErrorGuidance(
            code="connector.invalid_input",
            when="A required field was missing, or stage_name is not a stage this org uses.",
            remedy=(
                "The error lists the exact stages this org accepts. Choose one of them, "
                "or ask the user which they meant, then call again with the same "
                "idempotency key. Do not invent a stage name."
            ),
        ),
        ErrorGuidance(
            code="salesforce.record_not_found",
            when="The account_id or contact_id does not exist.",
            remedy=(
                "Search for the right record, or omit the optional id. Never guess an "
                "id: a valid-looking one may belong to something else."
            ),
        ),
        ErrorGuidance(
            code="salesforce.permission_denied",
            when="This Salesforce user may not create opportunities.",
            remedy=(
                "Do not retry. Report that the profile lacks Create on Opportunity and "
                "an administrator must grant it."
            ),
        ),
        ErrorGuidance(
            code="salesforce.conflict",
            when="Duplicate rules matched an existing opportunity.",
            remedy=(
                "Do not repeat unchanged. Show the user the matching deal and ask "
                "whether they meant that one."
            ),
        ),
        ErrorGuidance(
            code="salesforce.rate_limited",
            when="The org has spent its API allowance for now.",
            remedy="Wait the stated number of seconds, then repeat with the same key.",
        ),
        ErrorGuidance(
            code="salesforce.transport_failed",
            when="The request did not complete, so the opportunity may or may not exist.",
            remedy=(
                "Repeat with the identical idempotency key, which returns the original "
                "result if it was already created. If the result shows contact_linked "
                "false, the deal exists and only the link is missing: do not create it "
                "again."
            ),
        ),
    ),
)
