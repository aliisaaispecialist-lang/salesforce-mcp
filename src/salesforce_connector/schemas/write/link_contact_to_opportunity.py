"""Attaching a contact to an opportunity that already exists.

This was a `contact_id` parameter on `create_opportunity`: optional, and
supplying it silently caused a second write to a second object. That is the
pitfall Chapter 6 names directly, and the cost showed up in the result as
`contact_linked: false` -- a successful response carrying a failure inside it.

Now it is its own tool, and what was optional and hidden is required and
named. Two writes, two tools, two approval prompts, each describing one change.

The contact role is what Salesforce calls the join: it records that a person
plays a part in a deal, and it is a record in its own right rather than a field
on either side.
"""

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

_ID_LENGTH = (15, 18)


class LinkContactToOpportunityInput(BaseModel):
    """Which contact, and which deal."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    opportunity_id: Annotated[
        str,
        Field(
            min_length=_ID_LENGTH[0],
            max_length=_ID_LENGTH[1],
            pattern=r"^[a-zA-Z0-9]{15,18}$",
            description=(
                "Required. The deal to attach someone to, id starting 006. If you "
                "have just created the opportunity, this is the id it returned. If "
                "you do not have it, do not guess: create the opportunity first, or "
                "search for it if it already exists."
            ),
        ),
    ]
    contact_id: Annotated[
        str,
        Field(
            min_length=_ID_LENGTH[0],
            max_length=_ID_LENGTH[1],
            pattern=r"^[a-zA-Z0-9]{15,18}$",
            description=(
                "Required. The person to attach, id starting 003. Search for the "
                "contact by name or email if you do not have their id. Never guess "
                "an id: a valid-looking one may belong to somebody else, and this "
                "would attach the wrong person to the deal."
            ),
        ),
    ]
    idempotency_key: Annotated[str, Field(min_length=8, description=IDEMPOTENCY_KEY_DESCRIPTION)]
    approved: Annotated[bool, Field(default=False, description=APPROVED_DESCRIPTION)] = False
    role: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional. What part this person plays, for example 'Decision Maker' "
                "or 'Economic Buyer'. Roles are a picklist configured per org, so "
                "omit this unless the user named one: Salesforce then applies the "
                "org's own default rather than rejecting a value invented here."
            ),
        ),
    ] = None


class LinkContactToOpportunityOutput(BaseModel):
    """The link that now exists."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Annotated[str, Field(description="Record id of the contact role, starting 00K.")]
    opportunity_id: Annotated[str, Field(description="The deal the contact is now attached to.")]
    contact_id: Annotated[str, Field(description="The person attached.")]
    linked: Annotated[
        bool,
        Field(
            description=(
                "True if this call created the link. False means the identical "
                "idempotency key had already created it and this is the original "
                "outcome, not a second role."
            )
        ),
    ]


SPEC = ActionSpec(
    action_id="salesforce.opportunity_link_contact_by_id",
    tool_name="salesforce_opportunity_link_contact_by_id",
    title="Attach a contact to a Salesforce opportunity",
    summary=(
        "Attach an existing contact to an existing opportunity, so the deal records who it is for."
    ),
    when_to_use=(
        "you have just created an opportunity for a particular person and hold both "
        "ids; or an existing deal is missing the contact it belongs to."
    ),
    when_not_to_use=(
        "the opportunity does not exist yet, in which case create it first and use "
        "the id it returns; or you do not have the contact's id, in which case "
        "search for them rather than guessing. This tool only links two records "
        "that already exist, and creates neither."
    ),
    kind=ActionKind.WRITE,
    risk=RiskLevel.LOW,
    idempotent=False,
    requires_approval=True,
    input_schema=schema_of(LinkContactToOpportunityInput),
    output_schema=schema_of(LinkContactToOpportunityOutput),
    examples=(
        ActionExample(
            title="Attach the contact to a deal just created",
            arguments={
                "opportunity_id": "006xx000004TmiQAAS",
                "contact_id": "003xx000004TmiQAAS",
                "idempotency_key": "f6a7b8c9-d0e1-4f2a-9b3c-5d6e7f8a9b0c",
                "approved": True,
            },
            result={
                "id": "00Kxx0000012345AAA",
                "opportunity_id": "006xx000004TmiQAAS",
                "contact_id": "003xx000004TmiQAAS",
                "linked": True,
            },
        ),
    ),
    manual_recovery=(
        "Open the opportunity in Salesforce and add the person under Related > "
        "Contact Roles. Check what is already listed first, in case the link was "
        "made before the failure was reported."
    ),
    missing_inputs=(
        MissingInput(
            field="opportunity_id",
            prompt=(
                "Which opportunity should this contact be attached to? If it was "
                "just created, use the id that came back from creating it."
            ),
        ),
        MissingInput(
            field="contact_id",
            prompt=(
                "Which contact should be attached? A name or email is enough and I "
                "will search for their id."
            ),
        ),
    ),
    errors=(
        ErrorGuidance(
            code="salesforce.record_not_found",
            when="Either the opportunity or the contact does not exist.",
            remedy=(
                "Do not retry with the same ids. Search for whichever record is "
                "missing, and tell the user if it has been deleted. The error names "
                "which id failed."
            ),
        ),
        ErrorGuidance(
            code="connector.invalid_input",
            when="An id is malformed, or the two ids are the wrong way round.",
            remedy=(
                "Check that opportunity_id starts 006 and contact_id starts 003. "
                "Correct them and call again with the same idempotency key."
            ),
        ),
        ErrorGuidance(
            code="salesforce.conflict",
            when="This contact already has a role on this opportunity.",
            remedy=(
                "Do not retry. The link you wanted already exists, so report that "
                "the contact is already attached rather than treating it as a "
                "failure."
            ),
        ),
        ErrorGuidance(
            code="salesforce.permission_denied",
            when="This Salesforce user may not create contact roles.",
            remedy=(
                "Do not retry. Report that the profile lacks Create on "
                "OpportunityContactRole and an administrator must grant it."
            ),
        ),
        ErrorGuidance(
            code="salesforce.rate_limited",
            when="The org has spent its API allowance for now.",
            remedy="Wait the stated number of seconds, then repeat with the same key.",
        ),
        ErrorGuidance(
            code="salesforce.transport_failed",
            when="The request did not complete, so the link may or may not exist.",
            remedy=(
                "Repeat with the identical idempotency key. Attaching the same "
                "person twice would put them on the deal twice, and the key is what "
                "prevents it."
            ),
        ),
    ),
)
