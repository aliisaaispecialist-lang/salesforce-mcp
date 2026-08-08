"""Creating a record if the external id is new, updating it if it exists.

This is the one tool that deliberately does two things, and the reason is worth
stating because the plan for this connector says the opposite everywhere else:
a tool that can create or update lets a model that meant to create silently
overwrite somebody's record instead.

What makes it defensible here is the external id. The decision is not the
model's; it is made by whether a record already carries that identifier, which
is a fact about the org rather than a guess about intent. A caller holding an
external id is saying "this thing, the one our other system calls ORD-4471",
and the correct answer to that is the same record every time.

That is also what it is for. Retrying a create makes a duplicate; retrying an
upsert with the same external id does not, no matter how many times it runs or
whether the previous answer was lost. It is idempotency enforced by Salesforce
rather than by this connector remembering.

The field must be marked External Id on the object. Nothing else works, and
Salesforce rejects the call rather than falling back.
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


class UpsertRecordInput(BaseModel):
    """Which record the external id names, and what it should hold."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    object_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=80,
            description=(
                "Required. The object, spelled as Salesforce spells it: Contact, "
                "Opportunity, Account, or a custom object ending __c."
            ),
            examples=["Contact", "Opportunity"],
        ),
    ]
    external_id_field: Annotated[
        str,
        Field(
            min_length=1,
            max_length=80,
            description=(
                "Required. The field that carries the outside system's identifier. "
                "It must be marked External Id on the object; an ordinary text "
                "field is refused. Custom fields end __c, as in External_Id__c. "
                "Call salesforce_describe_object if you do not know which field "
                "this org uses."
            ),
            examples=["External_Id__c"],
        ),
    ]
    external_id_value: Annotated[
        str,
        Field(
            min_length=1,
            max_length=255,
            description=(
                "Required. The identifier itself, as the other system knows it. "
                "This decides everything: a value already on a record updates that "
                "record, and a value not on any record creates a new one. Never "
                "invent one, because inventing a value that happens to exist "
                "overwrites somebody else's record."
            ),
            examples=["CRM-4471"],
        ),
    ]
    fields: Annotated[
        dict[str, Any],
        Field(
            min_length=1,
            description=(
                "Required. The fields to set, keyed by Salesforce's own API names: "
                "LastName, Email, StageName, CloseDate. On a create these must "
                "include everything the object requires, or the write fails. On an "
                "update only what is named here changes.\n\n"
                "Call salesforce_describe_object first to see which fields are "
                "required and which values a picklist accepts."
            ),
            examples=[{"LastName": "Lovelace", "Email": "ada@example.com"}],
        ),
    ]
    idempotency_key: Annotated[
        str,
        Field(
            min_length=MIN_KEY_LENGTH,
            max_length=128,
            description=(
                "Required. A unique string for this specific write. The external id "
                "already prevents duplicate records; this prevents a retry being "
                "counted as a second change."
            ),
        ),
    ]
    approved: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "Confirmation that the user asked for this. This can overwrite an "
                "existing record and there is no undo."
            ),
        ),
    ] = False


class UpsertRecordOutput(BaseModel):
    """The record the external id now names."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Annotated[str, Field(description="Salesforce record id of the record written.")]
    object_name: Annotated[str, Field(description="The object it belongs to.")]
    external_id_value: Annotated[
        str, Field(description="The identifier that decided which record.")
    ]
    created: Annotated[
        bool,
        Field(
            description=(
                "True when no record carried that external id and one was created. "
                "False when a record already carried it and was updated instead. "
                "Salesforce decides this, not the caller."
            )
        ),
    ]


SPEC = ActionSpec(
    action_id="salesforce.upsert_record",
    tool_name="salesforce_upsert_record",
    title="Create or update a Salesforce record by external id",
    summary=(
        "Write a record identified by an outside system's id: creates it if that id "
        "is new to Salesforce, updates it if a record already carries it."
    ),
    when_to_use=(
        "you are syncing records from another system that has its own identifiers, "
        "and you cannot tell whether Salesforce already holds this one. Also when a "
        "write must be safe to repeat: the same external id always lands on the "
        "same record, however many times it is sent."
    ),
    when_not_to_use=(
        "the user asked to add somebody new, which is salesforce_create_contact and "
        "will not silently overwrite; the user asked to change a record you already "
        "hold the id of, which is salesforce_update_record; or you do not have an "
        "external id from a real system. Do not invent an external id to use this "
        "tool: a value that happens to exist overwrites that record."
    ),
    kind=ActionKind.WRITE,
    risk=RiskLevel.HIGH,
    idempotent=True,
    requires_approval=True,
    input_schema=schema_of(UpsertRecordInput),
    output_schema=schema_of(UpsertRecordOutput),
    examples=(
        ActionExample(
            title="Sync a contact from another system",
            arguments={
                "object_name": "Contact",
                "external_id_field": "External_Id__c",
                "external_id_value": "CRM-4471",
                "fields": {"LastName": "Lovelace", "Email": "ada@example.com"},
                "idempotency_key": "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e",
                "approved": True,
            },
            result={
                "id": "003xx000004TmiQAAS",
                "object_name": "Contact",
                "external_id_value": "CRM-4471",
                "created": True,
            },
        ),
    ),
    manual_recovery=(
        "Open Salesforce and search the object for the external id value before "
        "doing anything, because the record may already exist under it. If it does, "
        "edit that record rather than creating another; if it does not, create one "
        "and set the external id field to that value by hand. "
    ),
    missing_inputs=(
        MissingInput(
            field="external_id_value",
            prompt=(
                "What is the record's id in the other system? I need the real "
                "value, because inventing one could overwrite an existing record."
            ),
        ),
        MissingInput(
            field="external_id_field",
            prompt="Which field on this object holds that outside id? For example External_Id__c.",
        ),
    ),
    errors=(
        ErrorGuidance(
            code="connector.invalid_input",
            when=(
                "The field is not marked External Id on this object, or a field name "
                "or picklist value in the write is not one this org accepts."
            ),
            remedy=(
                "Call salesforce_describe_object and use a field it lists. Only a "
                "field configured as an External Id can be used here; if none "
                "exists, an administrator must create one, and until then use "
                "salesforce_update_record with the Salesforce id instead."
            ),
        ),
        ErrorGuidance(
            code="salesforce.conflict",
            when="More than one record already carries that external id.",
            remedy=(
                "Do not retry. The org has duplicate data that only a person can "
                "resolve. Report the external id and that it matches several records."
            ),
        ),
        ErrorGuidance(
            code="salesforce.permission_denied",
            when="This user may not create or edit that object, or see the external id field.",
            remedy=(
                "Do not retry. Field-level security hides the external id field even "
                "when the object is writable. Report which was refused."
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
            remedy=(
                "Repeat the same call. The external id makes this safe: whether or "
                "not the first attempt landed, the second one writes the same record."
            ),
        ),
        ErrorGuidance(
            code="connector.escalate_to_human",
            when="The write failed three times in a row and will not succeed by retrying.",
            remedy="Stop calling this tool. Tell the user it must be done by hand and how.",
        ),
    ),
)
