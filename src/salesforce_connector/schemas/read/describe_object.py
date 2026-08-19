"""What an object's fields are called, and which values they accept.

Already used privately: `create_opportunity` calls describe to read this org's
sales stages, which is why it can say `Qualify, Meet & Present, Propose` rather
than assuming the `Prospecting` most Salesforce documentation uses as its
example. Every other tool that needs a field name has to be told one.

The raw response is enormous, around ninety-six thousand characters for
Opportunity on a plain org, because it describes layouts, permissions, child
relationships and a great deal nobody asked for. Returning it would spend more
context than the question is worth, so this returns the part a caller needs to
write a correct call: what the fields are called, what type they are, which are
required, and which picklist values this org actually accepts.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from salesforce_connector.contract import ActionExample, ActionKind, RiskLevel
from salesforce_connector.schemas.envelope import (
    ActionSpec,
    ErrorGuidance,
    MissingInput,
    schema_of,
)


class DescribeObjectInput(BaseModel):
    """Which object to describe."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    object_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=80,
            pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
            description=(
                "Required. The object, spelled as Salesforce spells it: Contact, "
                "Opportunity, Account, Lead, Task, or a custom object ending __c. "
                "Translate the user's word first: a company is Account, a deal is "
                "Opportunity, a person is Contact, a prospect is Lead. If you still "
                "cannot tell which object they mean, ask them rather than guessing. A "
                "name this org does not have comes back as not-found, not as a "
                "correction, so a guess costs a call and teaches you nothing."
            ),
            examples=["Contact", "Opportunity"],
        ),
    ]
    only_writable: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "Optional, defaults to false. When true, returns only the fields "
                "that can be set, which is what you want before creating or "
                "updating a record. Formula fields, rollups and system fields such "
                "as CreatedDate are dropped, because writing to one fails."
            ),
        ),
    ] = False


class FieldDescription(BaseModel):
    """One field, reduced to what a caller needs to use it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Annotated[str, Field(description="The API name, which is what a call must use.")]
    label: Annotated[str, Field(description="What a person sees in the Salesforce UI.")]
    type: Annotated[
        str, Field(description="string, picklist, date, currency, reference, and so on.")
    ]
    required: Annotated[
        bool,
        Field(
            description=("True when a create fails without it and Salesforce supplies no default.")
        ),
    ]
    updateable: Annotated[bool, Field(description="False for a field that cannot be written to.")]
    picklist_values: Annotated[
        tuple[str, ...],
        Field(
            default=(),
            description=(
                "The active values this org accepts, for a picklist field. Empty "
                "for every other type. These are configured per org: never assume "
                "a value that is not listed here."
            ),
        ),
    ] = ()
    relationship_name: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "For a lookup field, the name to follow with "
                "salesforce_record_get_related_by_id. A Contact's AccountId is followed as "
                "the relationship named Account."
            ),
        ),
    ] = None


class DescribeObjectOutput(BaseModel):
    """The object's fields, and how many there were."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    object_name: Annotated[str, Field(description="The object described.")]
    label: Annotated[str, Field(description="What a person calls it in the UI.")]
    fields: Annotated[
        tuple[FieldDescription, ...],
        Field(description="Its fields, reduced to what is needed to read or write one."),
    ]
    returned: Annotated[int, Field(description="How many fields are in this response.")]


SPEC = ActionSpec(
    action_id="salesforce.object_describe_by_name",
    tool_name="salesforce_object_describe_by_name",
    title="Describe a Salesforce object's fields",
    summary=(
        "List an object's field names, types, and the picklist values this org "
        "accepts, so a call can be written correctly the first time."
    ),
    when_to_use=(
        "before writing to an object you have not written to before; when a call "
        "failed because a field name or picklist value was not recognised; or when "
        "the user asks what can be stored about something. Picklists are "
        "configured per org, so this is the only reliable way to learn a stage or "
        "a status."
    ),
    when_not_to_use=(
        "you already know the field names, since this returns a lot and costs "
        "context; or you want the records themselves rather than the shape of "
        "them, which is salesforce_record_get_by_id or salesforce_record_query_by_soql."
    ),
    kind=ActionKind.READ,
    risk=RiskLevel.LOW,
    idempotent=True,
    requires_approval=False,
    input_schema=schema_of(DescribeObjectInput),
    output_schema=schema_of(DescribeObjectOutput),
    examples=(
        ActionExample(
            title="Learn which sales stages this org accepts",
            arguments={"object_name": "Opportunity", "only_writable": True},
            result={
                "object_name": "Opportunity",
                "label": "Opportunity",
                "fields": [
                    {
                        "name": "StageName",
                        "label": "Stage",
                        "type": "picklist",
                        "required": True,
                        "updateable": True,
                        "picklist_values": ["Qualify", "Propose", "Closed Won"],
                        "relationship_name": None,
                    }
                ],
                "returned": 1,
            },
        ),
    ),
    missing_inputs=(
        MissingInput(
            field="object_name",
            prompt=(
                "Which Salesforce object should I describe? For example Contact or Opportunity."
            ),
        ),
    ),
    errors=(
        ErrorGuidance(
            code="salesforce.record_not_found",
            when="No object has that name in this org.",
            remedy=(
                "Check the spelling: Salesforce object names are capitalised and "
                "custom ones end __c. Do not retry the same name."
            ),
        ),
        ErrorGuidance(
            code="salesforce.permission_denied",
            when="This user may not see that object's definition.",
            remedy="Do not retry. Report that an administrator must grant access to the object.",
        ),
        ErrorGuidance(
            code="salesforce.rate_limited",
            when="The org has spent its API allowance for now.",
            remedy="Wait the stated number of seconds, then repeat the same call.",
        ),
        ErrorGuidance(
            code="salesforce.transport_failed",
            when="Salesforce did not answer in time.",
            remedy=(
                "Wait briefly and repeat. A describe is a large response, so a "
                "timeout here is more likely than on other reads."
            ),
        ),
    ),
)
