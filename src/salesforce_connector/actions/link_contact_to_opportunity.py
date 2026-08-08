"""Attaching a contact to an opportunity, as one write and nothing else.

Extracted from `create_opportunity`, where it ran silently whenever an optional
`contact_id` was supplied. There it could fail after the deal already existed,
which is why that action had to report `contact_linked: false` -- a success
carrying a failure inside it.

Here a failure is simply a failed call. The caller sees it, the error says what
to do, and no other record was created on the way.
"""

from collections.abc import Mapping
from typing import Any, ClassVar, Final

from salesforce_connector.actions.action import Action
from salesforce_connector.errors.model import ErrorContext, InvalidInputError
from salesforce_connector.exchange import RequestSpec
from salesforce_connector.schemas import link_contact_to_opportunity as schema

_PATH: Final = "sobjects/OpportunityContactRole"
_OPPORTUNITY_PREFIX: Final = "006"
_CONTACT_PREFIX: Final = "003"


class LinkContactToOpportunity(Action):
    """Create the contact role joining a person to a deal."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.LinkContactToOpportunityInput
    output_model: ClassVar[type] = schema.LinkContactToOpportunityOutput

    async def _execute(self, params: schema.LinkContactToOpportunityInput) -> Mapping[str, Any]:
        _reject_swapped_ids(params)

        response = await self._client.request(
            RequestSpec(
                method="POST",
                path=_PATH,
                json_body=_fields(params),
                is_write=True,
                idempotency_key=params.idempotency_key,
            )
        )
        created = response.body.get("id", "") if isinstance(response.body, Mapping) else ""
        return {
            "id": str(created),
            "opportunity_id": params.opportunity_id,
            "contact_id": params.contact_id,
            "linked": True,
        }


def _reject_swapped_ids(params: schema.LinkContactToOpportunityInput) -> None:
    """Catch the two ids the wrong way round before Salesforce does.

    Both are eighteen characters of base62 and look identical to a model that
    is guessing. Salesforce rejects the swap with a cross-reference error that
    names neither field, so the check is worth doing here where it can.
    """
    wrong = [
        f"opportunity_id should start {_OPPORTUNITY_PREFIX} but starts {params.opportunity_id[:3]}"
        if not params.opportunity_id.startswith(_OPPORTUNITY_PREFIX)
        else "",
        f"contact_id should start {_CONTACT_PREFIX} but starts {params.contact_id[:3]}"
        if not params.contact_id.startswith(_CONTACT_PREFIX)
        else "",
    ]
    faults = [fault for fault in wrong if fault]
    if not faults:
        return
    raise InvalidInputError(
        f"The ids do not look right. {'; '.join(faults)}.",
        ErrorContext(
            next_step=(
                "An opportunity id starts 006 and a contact id starts 003. If they "
                "are the wrong way round, swap them and call again with the same "
                "idempotency key."
            ),
            invalid_fields=tuple(
                field
                for field, fault in zip(("opportunity_id", "contact_id"), wrong, strict=True)
                if fault
            ),
        ),
    )


def _fields(params: schema.LinkContactToOpportunityInput) -> Mapping[str, Any]:
    """Build the contact role, omitting a role nobody asked for.

    An omitted role lets Salesforce apply the org's own default. Sending one
    invented here risks a restricted picklist rejecting the whole write, which
    is the mistake `add_activity_note` made with TaskSubtype.
    """
    fields: dict[str, Any] = {
        "OpportunityId": params.opportunity_id,
        "ContactId": params.contact_id,
    }
    if params.role is not None:
        fields["Role"] = params.role
    return fields
