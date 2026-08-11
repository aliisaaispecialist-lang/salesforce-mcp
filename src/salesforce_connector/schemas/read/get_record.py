"""Reading one record whose id you already hold.

The narrowest read there is, and the one the other two cannot do cheaply.
`search_contact` matches words, `soql_query` needs a query composed; this takes
an id and returns the record.

The code has existed since the beginning, privately, inside `update_contact`:
Salesforce answers a PATCH with an empty 204, so that action re-reads the
record to have something to report. Only the caller could never ask for the
same thing on its own.
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

_ID_LENGTH = (15, 18)


class GetRecordInput(BaseModel):
    """Which record, and how much of it."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    object_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=80,
            pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
            description=(
                "Required. The object, spelled as Salesforce spells it: Contact, "
                "Opportunity, Account, Lead, Task, or a custom object ending __c."
            ),
        ),
    ]
    record_id: Annotated[
        str,
        Field(
            min_length=_ID_LENGTH[0],
            max_length=_ID_LENGTH[1],
            pattern=r"^[a-zA-Z0-9]{15,18}$",
            description=(
                "Required. The record's Salesforce id. Search for it first if you "
                "do not have it. Never guess: a well-formed id that belongs to "
                "something else returns that something else, quietly."
            ),
        ),
    ]
    fields: Annotated[
        tuple[str, ...],
        Field(
            default=(),
            description=(
                "Optional. Which fields to return, named as Salesforce names them: "
                "Name, Email, Title. Omit to get every field the object has, which "
                "on a real org is dozens of them and mostly empty. Naming the three "
                "or four you need keeps the answer readable and cheap.\n\n"
                "If you do not know what a field is called, call "
                "salesforce_object_describe_by_name first rather than guessing."
            ),
            examples=[["Name", "Email"], ["Name", "StageName", "Amount"]],
        ),
    ] = ()


class GetRecordOutput(BaseModel):
    """The record as Salesforce holds it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record: Annotated[
        dict[str, Any],
        Field(
            description=(
                "The record's fields. Exactly the ones asked for, or all of them "
                "if none were named. A field present with a null value is set to "
                "nothing; a field absent was not requested."
            )
        ),
    ]


SPEC = ActionSpec(
    action_id="salesforce.record_get_by_id",
    tool_name="salesforce_record_get_by_id",
    title="Read one Salesforce record by id",
    summary=(
        "Read one Salesforce record directly by its id, returning either every "
        "field or only the ones asked for."
    ),
    when_to_use=(
        "you hold a record id, from a search, from a record you just created, or "
        "from a relationship, and want the record itself."
    ),
    when_not_to_use=(
        "you do not have the id, in which case search for it by name or query for "
        "it by condition; or you want several records at once, which is "
        "salesforce_record_query_by_soql. This reads exactly one."
    ),
    kind=ActionKind.READ,
    risk=RiskLevel.LOW,
    idempotent=True,
    requires_approval=False,
    input_schema=schema_of(GetRecordInput),
    output_schema=schema_of(GetRecordOutput),
    examples=(
        ActionExample(
            title="Read the fields you care about",
            arguments={
                "object_name": "Contact",
                "record_id": "003xx000004TmiQAAS",
                "fields": ["Name", "Email", "Title"],
            },
            result={
                "record": {
                    "Id": "003xx000004TmiQAAS",
                    "Name": "Ada Lovelace",
                    "Email": "ada@example.com",
                    "Title": "Chief Analyst",
                }
            },
        ),
    ),
    missing_inputs=(
        MissingInput(
            field="object_name",
            prompt="Which Salesforce object is it? For example Contact or Opportunity.",
        ),
        MissingInput(
            field="record_id",
            prompt=(
                "Which record should I read? A name or email is enough and I will "
                "search for its id."
            ),
        ),
    ),
    errors=(
        ErrorGuidance(
            code="salesforce.record_not_found",
            when="No record has that id, or it has been deleted.",
            remedy=(
                "Do not retry with the same id. Search for the record by name or "
                "email, and tell the user if it no longer exists."
            ),
        ),
        ErrorGuidance(
            code="connector.invalid_input",
            when="The id is malformed, or a named field does not exist.",
            remedy=(
                "Salesforce names the field it did not recognise. Call "
                "salesforce_object_describe_by_name to see the real field names, then call "
                "again."
            ),
        ),
        ErrorGuidance(
            code="salesforce.permission_denied",
            when="This user may not read that object, or one of the fields named.",
            remedy=(
                "Do not retry. Try again naming fewer fields if only one was "
                "refused, and report that an administrator must grant access."
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
            remedy="Wait briefly and repeat. Reading again is always safe.",
        ),
    ),
)
