"""Changing fields on an existing contact.

Naturally idempotent, since setting a field to the same value twice leaves the
same record. It still takes an idempotency key, so a caller never has to
remember which writes are safe to repeat and which are not.

Salesforce answers a successful update with an empty body, so the action
re-reads the record: an empty success tells a caller nothing about what the
record now contains.
"""

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from salesforce_connector.contract import ActionExample, ActionKind, RiskLevel
from salesforce_connector.schemas.envelope import (
    APPROVED_DESCRIPTION,
    IDEMPOTENCY_KEY_DESCRIPTION,
    ActionSpec,
    ErrorGuidance,
    MissingInput,
    schema_of,
)

_CHANGEABLE = ("first_name", "last_name", "email", "phone", "title", "account_id")


class UpdateContactInput(BaseModel):
    """Which contact to change, and what to change on it."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    contact_id: Annotated[
        str,
        Field(
            min_length=15,
            max_length=18,
            description=(
                "Required. Salesforce record id of the contact to change, starting "
                "003, for example 003xx000004TmiQAAS. Find it with the search action "
                "if you do not have it. Never guess an id: a wrong one either fails or "
                "edits somebody else's record."
            ),
        ),
    ]
    idempotency_key: Annotated[str, Field(min_length=8, description=IDEMPOTENCY_KEY_DESCRIPTION)]
    approved: Annotated[bool, Field(default=False, description=APPROVED_DESCRIPTION)] = False
    first_name: Annotated[
        str | None, Field(default=None, max_length=40, description="Optional. New given name.")
    ] = None
    last_name: Annotated[
        str | None, Field(default=None, max_length=80, description="Optional. New family name.")
    ] = None
    email: Annotated[
        EmailStr | None,
        Field(
            default=None,
            description="Optional. The new email address.",
            examples=["ada@example.com"],
        ),
    ] = None
    phone: Annotated[
        str | None, Field(default=None, max_length=40, description="Optional. New phone number.")
    ] = None
    title: Annotated[
        str | None, Field(default=None, max_length=128, description="Optional. New job title.")
    ] = None
    account_id: Annotated[
        str | None,
        Field(default=None, description="Optional. Move the contact to this account, id 001..."),
    ] = None

    @model_validator(mode="after")
    def _something_must_change(self) -> Self:
        """Refuse a call that would send no change at all.

        An update naming no fields is always a mistake, and sending it spends an
        API call to accomplish nothing.
        """
        if not any(getattr(self, field) is not None for field in _CHANGEABLE):
            raise ValueError(
                "Give at least one field to change besides contact_id. "
                f"Changeable fields: {', '.join(_CHANGEABLE)}."
            )
        return self


class UpdateContactOutput(BaseModel):
    """The contact as it stands after the change."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Annotated[str, Field(description="Record id of the contact.")]
    name: Annotated[str, Field(description="Full name after the change.")]
    changed_fields: Annotated[
        tuple[str, ...], Field(description="The fields this call actually set.")
    ]
    email: Annotated[str | None, Field(default=None, description="Email after the change.")] = None
    phone: Annotated[str | None, Field(default=None, description="Phone after the change.")] = None
    title: Annotated[str | None, Field(default=None, description="Title after the change.")] = None


SPEC = ActionSpec(
    action_id="salesforce.update_contact",
    tool_name="salesforce_update_contact",
    title="Update a Salesforce contact",
    summary=(
        "Change one or more fields on an existing Salesforce contact and return the "
        "record as it stands afterwards."
    ),
    when_to_use=(
        "you hold the contact's record id and the user has asked for a detail to be "
        "corrected or added, such as a new email, phone, title, or account."
    ),
    when_not_to_use=(
        "the person does not exist yet, which is the create action; you do not have "
        "the record id, in which case search first; or you want to record something "
        "that happened rather than change the person, which is the activity note."
    ),
    kind=ActionKind.WRITE,
    risk=RiskLevel.MEDIUM,
    idempotent=True,
    requires_approval=True,
    input_schema=schema_of(UpdateContactInput),
    output_schema=schema_of(UpdateContactOutput),
    examples=(
        ActionExample(
            title="Change one field, leaving the rest of the record alone",
            arguments={
                "contact_id": "003xx000004TmiQAAS",
                "title": "Chief Analyst",
                "idempotency_key": "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e",
                "approved": True,
            },
            result={
                "id": "003xx000004TmiQAAS",
                "name": "Ada Lovelace",
                "changed_fields": ["title"],
                "title": "Chief Analyst",
            },
        ),
    ),
    manual_recovery=(
        "Open the contact in Salesforce and set the fields by hand. Check "
        "the current values first: an update can apply and still report "
        "failure, so some of the change may already be saved. "
    ),
    missing_inputs=(
        MissingInput(
            field="contact_id",
            prompt=(
                "Which contact should I update? Give the Salesforce record id, or a "
                "name or email so I can search for it."
            ),
        ),
    ),
    errors=(
        ErrorGuidance(
            code="salesforce.record_not_found",
            when="No contact has that id, or it has been deleted.",
            remedy=(
                "Do not retry with the same id. Search for the contact by name or "
                "email to find the right one, and tell the user if it no longer exists."
            ),
        ),
        ErrorGuidance(
            code="connector.invalid_input",
            when="No changeable field was given, or a value was malformed.",
            remedy=(
                "Name at least one field to change and correct any malformed value, "
                "then call again with the same idempotency key."
            ),
        ),
        ErrorGuidance(
            code="salesforce.permission_denied",
            when="This Salesforce user may not edit this contact or one of these fields.",
            remedy=(
                "Do not retry. Some fields are read-only for some profiles. Report "
                "which field was refused and that an administrator must grant access."
            ),
        ),
        ErrorGuidance(
            code="salesforce.conflict",
            when="The record is locked, in an approval process, or was changed concurrently.",
            remedy=(
                "Do not retry immediately. Read the contact again to see its current "
                "state, and tell the user it is locked if it still is."
            ),
        ),
        ErrorGuidance(
            code="salesforce.rate_limited",
            when="The org has spent its API allowance for now.",
            remedy="Wait the stated number of seconds, then repeat the call with the same key.",
        ),
        ErrorGuidance(
            code="salesforce.transport_failed",
            when="The request did not complete, so the change may or may not have applied.",
            remedy=(
                "Repeat the call with the identical idempotency key. Setting the same "
                "fields twice is harmless, and the key prevents any doubt."
            ),
        ),
    ),
)
