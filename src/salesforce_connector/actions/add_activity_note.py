"""Logging an interaction as a completed Task.

Which field the record hangs from depends on what it is attached to: a contact
is a person, so it goes in WhoId, while an opportunity is a thing, so it goes
in WhatId. Salesforce silently ignores an id in the wrong one, which would
produce an activity attached to nothing, so the id prefix decides it here.

The task is written as already completed, because this action records
something that happened rather than scheduling something to do.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar, Final

from salesforce_connector.actions.action import Action
from salesforce_connector.actions.action import created_id as created_id_of
from salesforce_connector.errors.model import ErrorContext, InvalidInputError
from salesforce_connector.schemas.write import add_activity_note as schema
from salesforce_connector.transport.exchange import RequestSpec

_PATH: Final = "sobjects/Task"

# Salesforce record ids carry their object in the first three characters.
_CONTACT_PREFIX: Final = "003"
_OPPORTUNITY_PREFIX: Final = "006"

_COMPLETED: Final = "Completed"


class AddActivityNote(Action):
    """Put a call, email, meeting, or note on a record's timeline."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.AddActivityNoteInput
    output_model: ClassVar[type] = schema.AddActivityNoteOutput

    async def _execute(self, params: schema.AddActivityNoteInput) -> Mapping[str, Any]:
        response = await self._client.request(
            RequestSpec(
                method="POST",
                path=_PATH,
                json_body=_task_fields(params),
                is_write=True,
                idempotency_key=params.idempotency_key,
            )
        )
        created_id = created_id_of(response.body)
        return {
            "id": created_id,
            "subject": params.subject,
            "related_to_id": params.related_to_id,
            "created": True,
        }


def _task_fields(params: schema.AddActivityNoteInput) -> Mapping[str, Any]:
    """Build the task, attaching it to the right kind of record."""
    when = params.activity_date or datetime.now(UTC).date()
    fields: dict[str, Any] = {
        "Subject": params.subject,
        "Status": _COMPLETED,
        "ActivityDate": when.isoformat(),
        **_attachment(params.related_to_id),
    }
    # TaskSubtype is a restricted picklist every org configures for itself, and
    # this connector was sending its own default of "Other" whenever the caller
    # named no kind. An org that has not enabled that value rejects the whole
    # write -- which is what a real org did, on a note the caller never asked
    # to categorise. Omitted rather than invented, so Salesforce applies the
    # org's own default. ADR-008 made this argument about sales stages; the
    # same reasoning applies here and had not been carried across.
    if params.activity_kind is not None:
        fields["TaskSubtype"] = params.activity_kind.value
    if params.body is not None:
        fields["Description"] = params.body
    return fields


def _attachment(related_to_id: str) -> Mapping[str, str]:
    """Choose WhoId or WhatId from the record's own id prefix.

    Guessing wrong is worse than refusing: Salesforce accepts the record and
    quietly attaches the activity to nothing, so the note exists and nobody
    ever sees it.
    """
    if related_to_id.startswith(_CONTACT_PREFIX):
        return {"WhoId": related_to_id}
    if related_to_id.startswith(_OPPORTUNITY_PREFIX):
        return {"WhatId": related_to_id}
    raise InvalidInputError(
        f"{related_to_id!r} is not a contact or opportunity id.",
        ErrorContext(
            next_step=(
                "A note attaches to a contact, whose id starts 003, or an "
                "opportunity, whose id starts 006. Search for the record first to "
                "get its id."
            ),
            invalid_fields=("related_to_id",),
        ),
    )
