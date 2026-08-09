"""Changing an existing contact, then reading back what it now says.

Salesforce answers a successful PATCH with 204 and no body. Returning that
alone would tell a caller only that nothing went wrong, which is not the same
as knowing what the record holds. So the update is followed by a read, at the
cost of one extra API call and in exchange for an answer that means something.
"""

from collections.abc import Mapping
from typing import Any, ClassVar, Final

from salesforce_connector.actions.action import Action
from salesforce_connector.schemas import update_contact as schema
from salesforce_connector.transport.exchange import RequestSpec

_FIELD_NAMES: Final = {
    "first_name": "FirstName",
    "last_name": "LastName",
    "email": "Email",
    "phone": "Phone",
    "title": "Title",
    "account_id": "AccountId",
}

_READ_BACK: Final = ("Id", "Name", "Email", "Phone", "Title")


class UpdateContact(Action):
    """Set fields on a contact and report the record afterwards."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.UpdateContactInput
    output_model: ClassVar[type] = schema.UpdateContactOutput

    async def _execute(self, params: schema.UpdateContactInput) -> Mapping[str, Any]:
        changes = _changes(params)
        await self._client.request(
            RequestSpec(
                method="PATCH",
                path=f"sobjects/Contact/{params.contact_id}",
                json_body=changes,
                is_write=True,
                idempotency_key=params.idempotency_key,
            )
        )
        current = await self._read_back(params.contact_id)
        return {
            "id": current.get("Id", params.contact_id),
            "name": current.get("Name", ""),
            "email": current.get("Email"),
            "phone": current.get("Phone"),
            "title": current.get("Title"),
            # Reported in the caller's own vocabulary, not Salesforce's. A
            # caller who sent `title` was getting back `Title`, which is the
            # provider's field name leaking through an interface that is
            # snake_case everywhere else -- and unusable for the obvious thing
            # a caller does with this list, which is compare it to what they
            # asked for. Found by running against a real org.
            "changed_fields": tuple(_asked_for(params)),
        }

    async def _read_back(self, contact_id: str) -> Mapping[str, Any]:
        """Fetch only the fields we report, rather than the whole record.

        A contact carries dozens of fields, most of them empty and none of them
        asked for. Naming the few we return keeps the answer small.
        """
        response = await self._client.request(
            RequestSpec(
                method="GET",
                path=f"sobjects/Contact/{contact_id}",
                params={"fields": ",".join(_READ_BACK)},
            )
        )
        return response.body if isinstance(response.body, Mapping) else {}


def _changes(params: schema.UpdateContactInput) -> Mapping[str, Any]:
    """Send only the fields the caller named.

    An unset field is left as it is. Sending a null would clear it, which is a
    different instruction from the one the caller gave.
    """
    given = params.model_dump(exclude_none=True)
    return {
        _FIELD_NAMES[name]: str(value)
        for name, value in given.items()
        if name in _FIELD_NAMES and value is not None
    }


def _asked_for(params: schema.UpdateContactInput) -> tuple[str, ...]:
    """Name the changed fields the way the caller named them.

    Derived from the same source as `_changes` so the two cannot disagree
    about what was sent: one renders the caller's names into Salesforce's,
    this one keeps them.
    """
    given = params.model_dump(exclude_none=True)
    return tuple(name for name in given if name in _FIELD_NAMES and given[name] is not None)
