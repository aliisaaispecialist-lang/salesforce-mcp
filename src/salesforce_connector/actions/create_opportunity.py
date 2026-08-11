"""Creating an opportunity, and optionally linking a contact to it.

Two writes, and the second can fail after the first has taken effect. The
journal records the opportunity the moment it exists, so a failure while
linking reports a deal that was created and a link that was not, rather than
an outright failure that would tempt a caller into creating the deal twice.

The stage is validated against the org's own picklist before sending. Every
Salesforce org configures its own stages, so any list written here would be
wrong somewhere; asking the org costs one cached call and turns a rejected
write into a corrected argument.
"""

from collections.abc import Mapping
from typing import Any, ClassVar, Final

from salesforce_connector.actions import stages
from salesforce_connector.actions.action import Action
from salesforce_connector.actions.action import created_id as created_id_of
from salesforce_connector.replay.journal import Journal
from salesforce_connector.schemas.write import create_opportunity as schema
from salesforce_connector.transport.client import SalesforceClient
from salesforce_connector.transport.exchange import RequestSpec

_PATH: Final = "sobjects/Opportunity"
_DESCRIBE_PATH: Final = "sobjects/Opportunity/describe"

_CREATED = "opportunity_created"


class CreateOpportunity(Action):
    """Add a deal. Attaching a contact is a separate tool."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.CreateOpportunityInput
    output_model: ClassVar[type] = schema.CreateOpportunityOutput

    def __init__(self, client: SalesforceClient) -> None:
        super().__init__(client)
        self._journal = Journal()

    async def _execute(self, params: schema.CreateOpportunityInput) -> Mapping[str, Any]:
        await stages.reject_unknown(self._client, params.stage_name)
        opportunity_id = await self._create(params)

        return {
            "id": opportunity_id,
            "name": params.name,
            "stage_name": params.stage_name,
            "created": True,
            # The handover, in the result rather than only the description,
            # because this is the moment the next decision is due. It names
            # what is unfinished, the tool that finishes it, and the id to
            # carry across -- a model missing any of the three guesses at it.
            "next_action": (
                f"This deal has no contact attached. If it is for a specific person, "
                f"call salesforce_opportunity_link_contact_by_id with "
                f"opportunity_id={opportunity_id} and their contact id."
            ),
        }

    async def _create(self, params: schema.CreateOpportunityInput) -> str:
        """Create the deal, unless a resumed attempt already did."""
        done = self._journal.find(_CREATED)
        if done is not None:
            return str(done.data["id"])

        response = await self._client.request(
            RequestSpec(
                method="POST",
                path=_PATH,
                json_body=_fields(params),
                is_write=True,
                idempotency_key=params.idempotency_key,
            )
        )
        created_id = created_id_of(response.body)
        self._journal.record(_CREATED, {"id": created_id})
        return created_id


def _fields(params: schema.CreateOpportunityInput) -> Mapping[str, Any]:
    """Assemble the record, omitting anything the caller left unset."""
    fields: dict[str, Any] = {
        "Name": params.name,
        "StageName": params.stage_name,
        "CloseDate": params.close_date.isoformat(),
    }
    if params.account_id is not None:
        fields["AccountId"] = params.account_id
    if params.amount is not None:
        fields["Amount"] = params.amount
    if params.description is not None:
        fields["Description"] = params.description
    return fields
