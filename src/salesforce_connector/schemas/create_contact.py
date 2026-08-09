"""Creating a contact.

Salesforce requires exactly one field, a last name, which makes it easy to
create a near-empty duplicate by accident. The description therefore pushes a
search first, and duplicate rules are surfaced rather than silently overridden.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from salesforce_connector.contract import ActionExample, ActionKind, RiskLevel
from salesforce_connector.schemas.envelope import (
    APPROVED_DESCRIPTION,
    IDEMPOTENCY_KEY_DESCRIPTION,
    ActionSpec,
    ErrorGuidance,
    MissingInput,
    schema_of,
)


class CreateContactInput(BaseModel):
    """The contact to create."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    last_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=80,
            description=(
                "Required. Family name. This is the only field Salesforce insists on. "
                "If you do not know it, ask the user rather than inventing one or "
                "putting the full name here."
            ),
        ),
    ]
    idempotency_key: Annotated[str, Field(min_length=8, description=IDEMPOTENCY_KEY_DESCRIPTION)]
    approved: Annotated[bool, Field(default=False, description=APPROVED_DESCRIPTION)] = False
    first_name: Annotated[
        str | None, Field(default=None, max_length=40, description="Optional. Given name.")
    ] = None
    email: Annotated[
        EmailStr | None,
        Field(
            default=None,
            description="Optional. An email address, rejected before sending if malformed.",
            examples=["ada@example.com"],
        ),
    ] = None
    phone: Annotated[
        str | None,
        Field(default=None, max_length=40, description="Optional. Any format Salesforce accepts."),
    ] = None
    title: Annotated[
        str | None, Field(default=None, max_length=128, description="Optional. Job title.")
    ] = None
    account_id: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional. Id of the account this person belongs to, starting 001. "
                "Omit it if you do not have one; do not guess."
            ),
        ),
    ] = None
    allow_duplicate: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "Optional, defaults to false. When false, a contact matching the org's "
                "duplicate rules is refused and the matches are returned so you can use "
                "an existing record instead. Set true only after the user has confirmed "
                "they want a second record."
            ),
        ),
    ] = False


class CreateContactOutput(BaseModel):
    """The contact that now exists."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Annotated[str, Field(description="Record id of the created contact.")]
    name: Annotated[str, Field(description="Full name as Salesforce assembled it.")]
    created: Annotated[
        bool,
        Field(
            description=(
                "True if this call created the record. False means the identical "
                "idempotency key had already created it and this is the original "
                "outcome, not a second record."
            )
        ),
    ]


SPEC = ActionSpec(
    action_id="salesforce.create_contact",
    tool_name="salesforce_create_contact",
    title="Create a Salesforce contact",
    summary="Create a new person record in Salesforce and return its record id.",
    when_to_use=(
        "the user has asked for a new contact to be added and you have at least a "
        "family name, and a search has shown the person is not already there."
    ),
    when_not_to_use=(
        "you have not searched first, since a duplicate person is the most common "
        "damage this connector can do; or the person already exists and you mean to "
        "change them, which is the update action; or you want to record an "
        "interaction, which is the activity note action."
    ),
    kind=ActionKind.WRITE,
    risk=RiskLevel.MEDIUM,
    idempotent=False,
    requires_approval=True,
    input_schema=schema_of(CreateContactInput),
    output_schema=schema_of(CreateContactOutput),
    examples=(
        ActionExample(
            title="Create a contact after searching and finding nobody",
            arguments={
                "last_name": "Lovelace",
                "first_name": "Ada",
                "email": "ada@example.com",
                "idempotency_key": "8f14e45f-ea11-4b52-9f1a-0c2d3e4f5a6b",
                "approved": True,
            },
            result={"id": "003xx000004TmiQAAS", "name": "Ada Lovelace", "created": True},
        ),
        ActionExample(
            title="The same key sent again after a timeout: no second record",
            arguments={
                "last_name": "Lovelace",
                "first_name": "Ada",
                "email": "ada@example.com",
                "idempotency_key": "8f14e45f-ea11-4b52-9f1a-0c2d3e4f5a6b",
                "approved": True,
            },
            result={"id": "003xx000004TmiQAAS", "name": "Ada Lovelace", "created": False},
        ),
    ),
    manual_recovery=(
        "Open Salesforce, search Contacts for the name to confirm it was "
        "not partly created, then create it by hand from Contacts > New. If "
        "a half-created record is there, correct that one rather than "
        "adding a second. "
    ),
    missing_inputs=(
        MissingInput(
            field="last_name",
            prompt="What is the family name of the contact to create?",
        ),
        MissingInput(
            field="email",
            prompt="What email address should the new contact have? Leave blank to skip.",
        ),
    ),
    errors=(
        ErrorGuidance(
            code="salesforce.conflict",
            when="Salesforce duplicate rules matched an existing contact.",
            remedy=(
                "Do not repeat this call unchanged. The matched record ids are in the "
                "error. Use the existing contact, or ask the user whether they really "
                "want a second record and only then call again with "
                "allow_duplicate=true."
            ),
        ),
        ErrorGuidance(
            code="connector.invalid_input",
            when="A field was missing or malformed; the error names which.",
            remedy=(
                "Correct the named field and call again with the same idempotency key. "
                "If the value is genuinely unknown, ask the user for it."
            ),
        ),
        ErrorGuidance(
            code="salesforce.record_not_found",
            when="The account_id you supplied does not exist.",
            remedy="Omit account_id, or find the correct account first. Do not guess an id.",
        ),
        ErrorGuidance(
            code="salesforce.permission_denied",
            when="This Salesforce user may not create contacts.",
            remedy=(
                "Do not retry. Tell the user their profile lacks Create on Contact and "
                "an administrator must grant it."
            ),
        ),
        ErrorGuidance(
            code="salesforce.rate_limited",
            when="The org has spent its API allowance for now.",
            remedy="Wait the stated number of seconds, then repeat the call with the same key.",
        ),
        ErrorGuidance(
            code="salesforce.transport_failed",
            when="The request did not complete, so the contact may or may not exist.",
            remedy=(
                "Repeat the call with the identical idempotency key. If the record was "
                "already created, you will get that original result rather than a "
                "second contact. Never retry with a new key."
            ),
        ),
    ),
)
