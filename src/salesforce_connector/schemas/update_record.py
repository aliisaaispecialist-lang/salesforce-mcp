"""Changing a field on any record, not only a contact.

`update_contact` names its fields in the caller's vocabulary: `first_name`,
`phone`, `title`. That is only possible because the object is known in advance
and its fields could be mapped one by one. For an arbitrary object there is no
such map, so this takes Salesforce's own field names and says so plainly.

That is the cost of being general, and the description carries the remedy: call
`describe_object` first if the names are not already known. Guessing one fails
the write, and a failed write on an unknown object is exactly the case where a
caller has least idea what to do next.
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

MIN_KEY_LENGTH = 8
_ID_LENGTH = (15, 18)


class UpdateRecordInput(BaseModel):
    """Which record to change, and to what."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    object_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=80,
            pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
            description=(
                "Required. The object the record belongs to, spelled as Salesforce "
                "spells it: Account, Lead, Opportunity, Case, or a custom object "
                "ending __c. For Contact use salesforce_update_contact, which takes "
                "plain field names and needs no lookup first."
            ),
            examples=["Account", "Opportunity"],
        ),
    ]
    record_id: Annotated[
        str,
        Field(
            min_length=_ID_LENGTH[0],
            max_length=_ID_LENGTH[1],
            pattern=r"^[a-zA-Z0-9]{15,18}$",
            description=(
                "Required. The record to change. Find it first with "
                "salesforce_search_records if you do not have the id. Never guess "
                "one: a valid-looking id belongs to some other record, and this "
                "tool would change it."
            ),
        ),
    ]
    fields: Annotated[
        dict[str, Any],
        Field(
            min_length=1,
            description=(
                "Required. The fields to set, keyed by Salesforce's own API names, "
                "not plain English: Industry, StageName, CloseDate, Description. "
                "Call salesforce_describe_object on this object first if you are "
                "not certain of a name or of the values a picklist accepts.\n\n"
                "Only the fields named here are touched; everything else on the "
                "record is left alone. Do not send a field to clear it unless the "
                "user asked for it to be cleared."
            ),
            examples=[{"Industry": "Technology"}, {"StageName": "Closed Won"}],
        ),
    ]
    idempotency_key: Annotated[
        str,
        Field(
            min_length=MIN_KEY_LENGTH,
            max_length=128,
            description=(
                "Required. A unique string for this specific change. Reuse the same "
                "one when retrying so the same edit is not applied twice; generate "
                "a new one for a genuinely different change."
            ),
        ),
    ]
    approved: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "Optional, defaults to false, but the call is refused without it. "
                "Confirmation that the user asked for this change. This writes to a "
                "record that already exists and there is no undo."
            ),
        ),
    ] = False


class UpdateRecordOutput(BaseModel):
    """What the record holds now."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Annotated[str, Field(description="Record id of the record that was changed.")]
    object_name: Annotated[str, Field(description="The object it belongs to.")]
    record: Annotated[
        dict[str, Any],
        Field(
            description=(
                "The changed fields as they now read, fetched back after the write. "
                "Salesforce answers an update with an empty response, so this is a "
                "second read and is what makes the result mean something."
            )
        ),
    ]
    changed_fields: Annotated[
        tuple[str, ...],
        Field(description="The field names that were sent, in the order they were given."),
    ]


SPEC = ActionSpec(
    action_id="salesforce.update_record",
    tool_name="salesforce_update_record",
    title="Update a Salesforce record",
    summary=(
        "Change named fields on an existing record of any object, then read back "
        "what they now hold."
    ),
    when_to_use=(
        "the user wants to correct or move on something that already exists: an "
        "account's industry, a deal's stage, a case's status. You must already know "
        "the record id and the Salesforce field names."
    ),
    when_not_to_use=(
        "the record is a Contact, which is salesforce_update_contact and takes "
        "plain field names; the record does not exist yet, which is a create tool; "
        "or you are not certain the field name is right, in which case call "
        "salesforce_describe_object first rather than trying a name to see."
    ),
    kind=ActionKind.WRITE,
    risk=RiskLevel.MEDIUM,
    idempotent=False,
    requires_approval=True,
    input_schema=schema_of(UpdateRecordInput),
    output_schema=schema_of(UpdateRecordOutput),
    examples=(
        ActionExample(
            title="Move a deal to a new stage",
            arguments={
                "object_name": "Opportunity",
                "record_id": "006xx000004TmiQAAS",
                "fields": {"StageName": "Negotiate"},
                "idempotency_key": "f1e2d3c4-b5a6-4978-8a9b-0c1d2e3f4a5b",
                "approved": True,
            },
            result={
                "id": "006xx000004TmiQAAS",
                "object_name": "Opportunity",
                "record": {"Id": "006xx000004TmiQAAS", "StageName": "Negotiate"},
                "changed_fields": ["StageName"],
            },
        ),
    ),
    manual_recovery=(
        "Open Salesforce, find the record by its id in the address bar of a record "
        "page, and set the field there. Check what it currently holds before "
        "changing it, because an earlier attempt may already have applied part of "
        "the change. "
    ),
    missing_inputs=(
        MissingInput(
            field="fields",
            prompt="Which fields should I set, and to what?",
        ),
        MissingInput(
            field="record_id",
            prompt=("Which record should I change? A name is enough and I will search for its id."),
        ),
        MissingInput(
            field="object_name",
            prompt="Which Salesforce object is it? For example Account or Opportunity.",
        ),
    ),
    errors=(
        ErrorGuidance(
            code="salesforce.record_not_found",
            when="No record of that object has that id.",
            remedy=(
                "Search for the record again rather than retrying. An id from a "
                "different object gives this same error."
            ),
        ),
        ErrorGuidance(
            code="connector.invalid_input",
            when="A field name does not exist, or a value is not one this org accepts.",
            remedy=(
                "Call salesforce_describe_object on this object, use a field name it "
                "lists, and for a picklist use one of the values it reports. Then "
                "call again with the same idempotency key."
            ),
        ),
        ErrorGuidance(
            code="salesforce.permission_denied",
            when="This user may not edit that object, or that field on it.",
            remedy=(
                "Do not retry. Report which field was refused and that an "
                "administrator must grant edit access."
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
                "Repeat with the identical idempotency key. The change may already have "
                "been applied, and the key is what stops it being applied twice."
            ),
        ),
        ErrorGuidance(
            code="connector.escalate_to_human",
            when="The update failed three times in a row and will not succeed by retrying.",
            remedy="Stop calling this tool. Tell the user it must be done by hand and how.",
        ),
    ),
)
