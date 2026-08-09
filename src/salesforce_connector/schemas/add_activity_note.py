"""Logging something that happened against a contact or an opportunity.

The programme names this action but not the object behind it, and Salesforce
offers three candidates. It is implemented as a completed Task, because in
Salesforce an activity is a Task or an Event, a Task appears on the record's
activity timeline where a person expects to find it, and it works in every org.
The alternatives were rejected: classic Notes are disabled in many modern orgs,
and ContentNote needs a base64 body plus a second linking call for no gain
here.

Changing that decision means changing this file and the action that reads it,
and nothing else.
"""

from datetime import date
from enum import StrEnum
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


class ActivityKind(StrEnum):
    """How the interaction happened."""

    CALL = "Call"
    EMAIL = "Email"
    MEETING = "Meeting"
    NOTE = "Other"


class AddActivityNoteInput(BaseModel):
    """The interaction to record."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    related_to_id: Annotated[
        str,
        Field(
            min_length=15,
            max_length=18,
            description=(
                "Required. Record the note belongs to: a contact id starting 003, or "
                "an opportunity id starting 006. Search for it first if you do not "
                "have it. A note on the wrong record is worse than no note."
            ),
        ),
    ]
    subject: Annotated[
        str,
        Field(
            min_length=1,
            max_length=255,
            description=(
                "Required. One line summarising what happened, for example "
                "'Renewal call - agreed to 12 month extension'. This is what a person "
                "sees in the activity timeline, so make it readable on its own."
            ),
        ),
    ]
    idempotency_key: Annotated[str, Field(min_length=8, description=IDEMPOTENCY_KEY_DESCRIPTION)]
    approved: Annotated[bool, Field(default=False, description=APPROVED_DESCRIPTION)] = False
    body: Annotated[
        str | None,
        Field(
            default=None,
            max_length=32000,
            description=(
                "Optional. The detail behind the subject. Write what was said or "
                "agreed, not a restatement of the subject line."
            ),
        ),
    ] = None
    activity_kind: Annotated[
        ActivityKind | None,
        Field(
            default=None,
            description=(
                "Optional. How the interaction happened. Omit it for a plain note "
                "and Salesforce applies this org's own default: the underlying "
                "field is a restricted picklist configured per org, so a value "
                "invented here can be rejected outright. Send one only when the "
                "user actually said how the interaction happened."
            ),
        ),
    ] = None
    activity_date: Annotated[
        date | None,
        Field(
            default=None,
            description=(
                "Optional. When it happened, written as YYYY-MM-DD. Defaults to "
                "today. Use the date the user described, not today's, when logging "
                "something past."
            ),
            examples=["2026-08-09"],
        ),
    ] = None


class AddActivityNoteOutput(BaseModel):
    """The activity now on the record's timeline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Annotated[str, Field(description="Record id of the created activity, starting 00T.")]
    subject: Annotated[str, Field(description="Subject as stored.")]
    related_to_id: Annotated[str, Field(description="Record the activity is attached to.")]
    created: Annotated[
        bool,
        Field(
            description=(
                "True if this call created it. False means the identical key had "
                "already created it and this is the original outcome."
            )
        ),
    ]


SPEC = ActionSpec(
    action_id="salesforce.add_activity_note",
    tool_name="salesforce_add_activity_note",
    title="Log an activity note in Salesforce",
    summary=(
        "Record a call, email, meeting, or note against a Salesforce contact or "
        "opportunity, so it appears on that record's activity timeline."
    ),
    when_to_use=(
        "the user wants to capture what happened with someone, such as a call "
        "summary, a meeting outcome, or a note to the account team, and you have the "
        "record it belongs to."
    ),
    when_not_to_use=(
        "the information belongs on the record itself, such as a corrected phone "
        "number, which is the update action; or you do not know which record it "
        "attaches to, in which case search first rather than guessing."
    ),
    kind=ActionKind.WRITE,
    risk=RiskLevel.LOW,
    idempotent=False,
    requires_approval=True,
    input_schema=schema_of(AddActivityNoteInput),
    output_schema=schema_of(AddActivityNoteOutput),
    examples=(
        ActionExample(
            title="Log a call against a contact",
            arguments={
                "related_to_id": "003xx000004TmiQAAS",
                "subject": "Intro call",
                "body": "Walked through pricing. Wants a quote by Friday.",
                "activity_kind": "Call",
                "idempotency_key": "d4e5f6a7-b8c9-4d0e-9f1a-3b4c5d6e7f8a",
                "approved": True,
            },
            result={
                "id": "00Txx0000012345AAA",
                "subject": "Intro call",
                "related_to_id": "003xx000004TmiQAAS",
                "created": True,
            },
        ),
        ActionExample(
            title="Log the same note against an opportunity instead",
            arguments={
                "related_to_id": "006xx000004TmiQAAS",
                "subject": "Quote sent",
                "idempotency_key": "e5f6a7b8-c9d0-4e1f-8a2b-4c5d6e7f8a9b",
                "approved": True,
            },
            result={
                "id": "00Txx0000012346AAA",
                "subject": "Quote sent",
                "related_to_id": "006xx000004TmiQAAS",
                "created": True,
            },
        ),
    ),
    manual_recovery=(
        "Open the contact or opportunity in Salesforce and add the activity "
        "by hand from the Activity tab. Check the timeline first in case "
        "the note was already logged before the failure. "
    ),
    missing_inputs=(
        MissingInput(
            field="related_to_id",
            prompt=(
                "Which contact or opportunity should this note be attached to? A name "
                "or email is enough and I will search."
            ),
        ),
        MissingInput(
            field="subject",
            prompt="What should the note say in one line?",
        ),
        MissingInput(
            field="activity_kind",
            prompt="Was this a call, an email, a meeting, or a plain note?",
            choices=("Call", "Email", "Meeting", "Other"),
        ),
    ),
    errors=(
        ErrorGuidance(
            code="salesforce.record_not_found",
            when="No record has that id, or it has been deleted.",
            remedy=(
                "Do not retry with the same id. Search for the contact or opportunity "
                "by name, and confirm with the user which record they meant."
            ),
        ),
        ErrorGuidance(
            code="connector.invalid_input",
            when="A required field was missing, or the subject exceeded 255 characters.",
            remedy=(
                "Shorten the subject and move the detail into body, or ask the user "
                "for the missing value, then call again with the same idempotency key."
            ),
        ),
        ErrorGuidance(
            code="salesforce.permission_denied",
            when="This Salesforce user may not create activities on that record.",
            remedy=(
                "Do not retry. Report that the profile lacks the permission and an "
                "administrator must grant it."
            ),
        ),
        ErrorGuidance(
            code="salesforce.rate_limited",
            when="The org has spent its API allowance for now.",
            remedy="Wait the stated number of seconds, then repeat with the same key.",
        ),
        ErrorGuidance(
            code="salesforce.transport_failed",
            when="The request did not complete, so the note may or may not have been saved.",
            remedy=(
                "Repeat with the identical idempotency key. Retrying with a new key "
                "would put the same note on the timeline twice."
            ),
        ),
    ),
)
