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

from salesforce_connector.actions.action import Action
from salesforce_connector.checkpoint import Journal
from salesforce_connector.client import SalesforceClient
from salesforce_connector.errors.model import ConnectorError, ErrorContext, InvalidInputError
from salesforce_connector.exchange import RequestSpec
from salesforce_connector.schemas import create_opportunity as schema

_PATH: Final = "sobjects/Opportunity"
_ROLE_PATH: Final = "sobjects/OpportunityContactRole"
_DESCRIBE_PATH: Final = "sobjects/Opportunity/describe"

_CREATED = "opportunity_created"
_LINKED = "contact_linked"


class CreateOpportunity(Action):
    """Add a deal, and attach a contact to it when asked."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.CreateOpportunityInput
    output_model: ClassVar[type] = schema.CreateOpportunityOutput

    def __init__(self, client: SalesforceClient) -> None:
        super().__init__(client)
        self._journal = Journal()

    async def _execute(self, params: schema.CreateOpportunityInput) -> Mapping[str, Any]:
        await self._reject_unknown_stage(params.stage_name)

        opportunity_id = await self._create(params)
        linked = await self._link_contact(opportunity_id, params.contact_id)

        return {
            "id": opportunity_id,
            "name": params.name,
            "stage_name": params.stage_name,
            "created": True,
            "contact_linked": linked,
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
        created_id = str(response.body.get("id", "")) if isinstance(response.body, Mapping) else ""
        self._journal.record(_CREATED, {"id": created_id})
        return created_id

    async def _link_contact(self, opportunity_id: str, contact_id: str | None) -> bool | None:
        """Attach the contact, reporting failure without losing the deal.

        The opportunity already exists by this point, so a failure here is a
        partial success. Raising would send the caller back to create a second
        deal.
        """
        if contact_id is None:
            return None
        if self._journal.is_done(_LINKED):
            return True
        try:
            await self._client.request(
                RequestSpec(
                    method="POST",
                    path=_ROLE_PATH,
                    json_body={"OpportunityId": opportunity_id, "ContactId": contact_id},
                    is_write=True,
                    idempotency_key=f"{opportunity_id}:role",
                )
            )
        except ConnectorError:
            self._log.warning("action.partial", step=_LINKED, opportunity_id=opportunity_id)
            return False
        self._journal.record(_LINKED)
        return True

    async def _reject_unknown_stage(self, stage: str) -> None:
        """Refuse a stage this org does not use, and say which it does."""
        allowed = await self._stages()
        if allowed and stage not in allowed:
            raise InvalidInputError(
                f"{stage!r} is not a sales stage in this Salesforce org.",
                ErrorContext(
                    next_step=(
                        f"Use one of these exact values: {', '.join(allowed)}. "
                        f"Ask the user which they meant if none is obviously right."
                    ),
                    invalid_fields=("stage_name",),
                ),
            )

    async def _stages(self) -> tuple[str, ...]:
        """Read the org's configured stages, tolerating a describe we cannot do.

        A profile may be allowed to create opportunities but not to describe
        them. Losing the check is better than losing the action, so an
        unreadable picklist simply skips validation and lets Salesforce judge.
        """
        try:
            response = await self._client.request(RequestSpec(method="GET", path=_DESCRIBE_PATH))
        except ConnectorError:
            return ()
        return _picklist_values(response.body, "StageName")


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


def _picklist_values(body: object, field_name: str) -> tuple[str, ...]:
    """Pull the active values of one picklist out of a describe response."""
    if not isinstance(body, Mapping):
        return ()
    fields = body.get("fields", ())
    if not isinstance(fields, (list, tuple)):
        return ()
    field = next(
        (item for item in fields if isinstance(item, Mapping) and item.get("name") == field_name),
        None,
    )
    if field is None:
        return ()
    values = field.get("picklistValues", ())
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(
        str(value["value"])
        for value in values
        if isinstance(value, Mapping) and value.get("active", True) and "value" in value
    )
