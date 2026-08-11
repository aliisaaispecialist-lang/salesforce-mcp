"""How many records an object holds, without querying them.

Overlaps `soql_query` deliberately and narrowly. `SELECT COUNT() FROM Contact`
answers the same question, and anything conditional -- how many closed this
month, how many at one account -- only `soql_query` can answer.

What this has instead is cost. It reads a counter Salesforce already maintains
rather than running a query, so it answers "how many contacts are there" for
several objects at once and without spending a query against the org's
allowance. That is the whole of its advantage, and the description says so, so
a model reaching for it on a conditional question is told where to go.
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

MAX_OBJECTS = 20


class CountRecordsInput(BaseModel):
    """Which objects to count."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    objects: Annotated[
        tuple[str, ...],
        Field(
            min_length=1,
            max_length=MAX_OBJECTS,
            description=(
                "Required. Salesforce object names to count, spelled as Salesforce "
                "spells them: Contact, Opportunity, Lead, Account, Task, or a "
                "custom object ending __c. Ask for several at once rather than "
                "calling repeatedly; one call answers for all of them.\n\n"
                "This counts every record of that type. It cannot count a subset. "
                "For 'how many contacts at Acme' or 'how many deals closed this "
                "month', use salesforce_record_query_by_soql with SELECT COUNT() and a "
                "WHERE clause instead."
            ),
            examples=[["Contact"], ["Contact", "Opportunity", "Lead"]],
        ),
    ]


class ObjectCount(BaseModel):
    """One object and how many records it holds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Annotated[str, Field(description="The object, as Salesforce names it.")]
    count: Annotated[int, Field(description="How many records of this type exist.")]


class CountRecordsOutput(BaseModel):
    """A count for each object that was asked about."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    counts: Annotated[
        tuple[ObjectCount, ...],
        Field(
            description=(
                "One entry per object Salesforce could count. These counts are "
                "cached and approximate, not live. An object asked for but absent "
                "here was not counted, which is not the same as having no records."
            )
        ),
    ]
    not_counted: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Present when Salesforce declined to count something that was "
                "asked for, naming which objects and the tool that can answer "
                "exactly. Absent when everything asked for came back."
            ),
        ),
    ] = None


SPEC = ActionSpec(
    action_id="salesforce.record_count_by_object",
    tool_name="salesforce_record_count_by_object",
    title="Count Salesforce records by object",
    summary=(
        "Report how many records exist for one or more Salesforce objects, without "
        "reading the records themselves."
    ),
    when_to_use=(
        "the user asked how much of something there is in total, across a whole "
        "object: how many contacts, how many opportunities, how big is the "
        "database. Several objects can be counted in one call."
    ),
    when_not_to_use=(
        "the question has any condition attached, such as how many were created "
        "this month or how many belong to one account. This counts everything and "
        "cannot filter; salesforce_record_query_by_soql with SELECT COUNT() and a WHERE "
        "clause is the tool for that. Also not for reading the records themselves."
    ),
    kind=ActionKind.READ,
    risk=RiskLevel.LOW,
    idempotent=True,
    requires_approval=False,
    input_schema=schema_of(CountRecordsInput),
    output_schema=schema_of(CountRecordsOutput),
    examples=(
        ActionExample(
            title="Count one object",
            arguments={"objects": ["Contact"]},
            result={"counts": [{"name": "Contact", "count": 7}], "not_counted": None},
        ),
        ActionExample(
            title="Count several at once",
            arguments={"objects": ["Contact", "Opportunity"]},
            result={
                "counts": [
                    {"name": "Contact", "count": 7},
                    {"name": "Opportunity", "count": 2},
                ],
                "not_counted": None,
            },
        ),
    ),
    missing_inputs=(
        MissingInput(
            field="objects",
            prompt="Which Salesforce objects should I count? For example Contact or Opportunity.",
        ),
    ),
    errors=(
        ErrorGuidance(
            code="connector.invalid_input",
            when="No object was named, or too many were asked for at once.",
            remedy="Name at least one object, and no more than twenty per call.",
        ),
        ErrorGuidance(
            code="salesforce.permission_denied",
            when="This user may not read one of the objects named.",
            remedy=(
                "Do not retry. The result lists the objects that were readable; "
                "report which was refused and that an administrator must grant "
                "read access."
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
            remedy="Wait briefly and repeat. Counting changes nothing, so retrying is always safe.",
        ),
    ),
)
