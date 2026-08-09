"""Creating a contact.

Duplicate rules are left switched on. Salesforce refuses a create that matches
an existing person unless a header explicitly permits it, and that refusal is
useful: it is the org telling us the person is already there. The header is
sent only when the caller has said so, so overriding a duplicate rule is always
a deliberate act.
"""

from collections.abc import Mapping
from typing import Any, ClassVar, Final

from salesforce_connector.actions.action import Action
from salesforce_connector.actions.action import created_id as created_id_of
from salesforce_connector.schemas import create_contact as schema
from salesforce_connector.transport.exchange import RequestSpec

_PATH: Final = "sobjects/Contact"

# Salesforce only bypasses duplicate rules when asked in this header.
_ALLOW_DUPLICATE_HEADER: Final = {"Sforce-Duplicate-Rule-Header": "allowSave=true"}

_FIELD_NAMES: Final = {
    "first_name": "FirstName",
    "last_name": "LastName",
    "email": "Email",
    "phone": "Phone",
    "title": "Title",
    "account_id": "AccountId",
}


class CreateContact(Action):
    """Add a person to Salesforce."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.CreateContactInput
    output_model: ClassVar[type] = schema.CreateContactOutput

    async def _execute(self, params: schema.CreateContactInput) -> Mapping[str, Any]:
        response = await self._client.request(
            RequestSpec(
                method="POST",
                path=_PATH,
                json_body=salesforce_fields(params),
                headers=_ALLOW_DUPLICATE_HEADER if params.allow_duplicate else {},
                is_write=True,
                idempotency_key=params.idempotency_key,
            )
        )
        return {
            "id": _created_id(response.body),
            "name": " ".join(part for part in (params.first_name, params.last_name) if part),
            "created": True,
        }


def salesforce_fields(params: schema.CreateContactInput) -> Mapping[str, Any]:
    """Translate our field names into the org's, omitting anything unset.

    Sending a null would clear a field rather than leave it alone, so absent
    means absent.
    """
    given = params.model_dump(exclude_none=True)
    return {
        _FIELD_NAMES[name]: str(value)
        for name, value in given.items()
        if name in _FIELD_NAMES and value is not None
    }


def _created_id(body: object) -> str:
    """Read the id Salesforce assigned."""
    return created_id_of(body)
