"""Following a relationship from one record to what it is attached to.

`search_contact` returns an `account_id` and no way to learn the account's
name. That was recorded as a real limitation rather than fixed, because
resolving it needed either a second read the caller had to know to make, or a
relationship field this project could not verify without an org.

This is the first of those, made explicit. One call, one hop, from a record to
the thing it points at.

The alternative is `soql_query` with `SELECT Account.Name FROM Contact WHERE
Id = '...'`, which is more powerful and requires composing SOQL. This is the
short way when the question is simply "and what is that attached to".
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


class GetRelatedInput(BaseModel):
    """Which record, and which relationship to follow."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    object_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=80,
            description=(
                "Required. The object you are starting from, spelled as Salesforce "
                "spells it: Contact, Opportunity, Account, or a custom object "
                "ending __c."
            ),
        ),
    ]
    record_id: Annotated[
        str,
        Field(
            min_length=_ID_LENGTH[0],
            max_length=_ID_LENGTH[1],
            description=(
                "Required. The record to start from. Search for it first if you do "
                "not have the id; never guess one, because a valid-looking id may "
                "belong to a different record entirely."
            ),
        ),
    ]
    relationship: Annotated[
        str,
        Field(
            min_length=1,
            max_length=80,
            description=(
                "Required. The relationship to follow, named as Salesforce names "
                "it. Following a lookup field drops the Id: a Contact's AccountId "
                "is followed as 'Account'. Child collections keep their plural "
                "name, such as 'Contacts' on an Account or "
                "'OpportunityContactRoles' on an Opportunity.\n\n"
                "If you are unsure what a relationship is called, call "
                "salesforce_describe_object on the starting object and read its "
                "relationshipName values rather than guessing."
            ),
            examples=["Account", "Contacts", "OpportunityContactRoles"],
        ),
    ]


class GetRelatedOutput(BaseModel):
    """What the relationship led to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    records: Annotated[
        tuple[dict[str, Any], ...],
        Field(
            description=(
                "What was found. A lookup returns exactly one record; a child "
                "collection returns many, or none. Empty means the relationship "
                "exists but nothing is attached, which is different from the "
                "relationship not existing at all."
            )
        ),
    ]
    returned: Annotated[int, Field(description="How many records are in this response.")]


SPEC = ActionSpec(
    action_id="salesforce.get_related",
    tool_name="salesforce_get_related",
    title="Follow a Salesforce relationship",
    summary=(
        "Read the records a Salesforce record is attached to, such as a contact's "
        "account or an opportunity's contact roles."
    ),
    when_to_use=(
        "you hold a record and need what it points at: the account behind a "
        "contact's account id, the contacts under an account, the roles on a deal. "
        "One call rather than reading an id and then reading the record it names."
    ),
    when_not_to_use=(
        "you want the record itself rather than what it is attached to; or you "
        "need fields from both sides at once, or any filtering or sorting, which "
        "salesforce_soql_query does with a relationship field such as "
        "Account.Name. This follows exactly one hop and applies no conditions."
    ),
    kind=ActionKind.READ,
    risk=RiskLevel.LOW,
    idempotent=True,
    requires_approval=False,
    input_schema=schema_of(GetRelatedInput),
    output_schema=schema_of(GetRelatedOutput),
    examples=(
        ActionExample(
            title="The account a contact belongs to",
            arguments={
                "object_name": "Contact",
                "record_id": "003xx000004TmiQAAS",
                "relationship": "Account",
            },
            result={
                "records": [{"Id": "001xx000003DGb2AAG", "Name": "Example Corp"}],
                "returned": 1,
            },
        ),
        ActionExample(
            title="The contacts under an account",
            arguments={
                "object_name": "Account",
                "record_id": "001xx000003DGb2AAG",
                "relationship": "Contacts",
            },
            result={
                "records": [
                    {"Id": "003xx000004TmiQAAS", "Name": "Ada Lovelace"},
                    {"Id": "003xx000004TmiRAAS", "Name": "Grace Hopper"},
                ],
                "returned": 2,
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
                "Which record should I start from? A name or email is enough and I "
                "will search for its id."
            ),
        ),
        MissingInput(
            field="relationship",
            prompt=(
                "What should I follow to? For example Account from a contact, or "
                "Contacts from an account."
            ),
        ),
    ),
    errors=(
        ErrorGuidance(
            code="salesforce.record_not_found",
            when="No record has that id, or the relationship name does not exist.",
            remedy=(
                "Check the id first by searching for the record. If the id is "
                "right, the relationship name is wrong: call "
                "salesforce_describe_object on the starting object and use a "
                "relationshipName it actually lists."
            ),
        ),
        ErrorGuidance(
            code="connector.invalid_input",
            when="The id is malformed, or the object name is empty.",
            remedy="Correct the named field and call again.",
        ),
        ErrorGuidance(
            code="salesforce.permission_denied",
            when="This user may not read the object on the other side.",
            remedy=(
                "Do not retry. Reading a contact does not imply permission to read "
                "its account. Report which object was refused."
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
