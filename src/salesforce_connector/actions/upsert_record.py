"""Writing a record by an outside system's identifier.

Salesforce decides here, not this connector. The PATCH goes to a path built
from the external id field and its value, and whether that becomes an insert or
an update depends on whether any record already carries that value. There is no
lookup first, and deliberately so: a read followed by a write is two calls with
a gap between them, and the gap is where two callers create the same record
twice.

Whether it created or updated is reported, because the caller cannot tell
otherwise and it changes what they say to the user. Salesforce states it twice,
once in the body and once in the status, and both are read here because the
body is absent on some updates.
"""

from collections.abc import Mapping
from typing import Any, ClassVar, Final
from urllib.parse import quote

from salesforce_connector.actions.action import Action
from salesforce_connector.actions.action import created_id as created_id_of
from salesforce_connector.schemas import upsert_record as schema
from salesforce_connector.transport.exchange import RequestSpec

_CREATED_STATUS: Final = 201


class UpsertRecord(Action):
    """Create the record if its external id is new, update it if it is not."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.UpsertRecordInput
    output_model: ClassVar[type] = schema.UpsertRecordOutput

    async def _execute(self, params: schema.UpsertRecordInput) -> Mapping[str, Any]:
        response = await self._client.request(
            RequestSpec(
                method="PATCH",
                # The value is somebody else's identifier and may contain a
                # slash -- ORD/2024/441 is an ordinary order number. Encoded
                # rather than refused, so it stays one path segment and cannot
                # steer the call at a different endpoint.
                path=(
                    f"sobjects/{params.object_name}/"
                    f"{params.external_id_field}/{quote(params.external_id_value, safe='')}"
                ),
                json_body=dict(params.fields),
                is_write=True,
                idempotency_key=params.idempotency_key,
            )
        )
        body = response.body if isinstance(response.body, Mapping) else {}
        return {
            "id": _written_id(response.status, body),
            "object_name": params.object_name,
            "external_id_value": params.external_id_value,
            "created": _was_created(response.status, body),
        }


def _was_created(status: int, body: Mapping[str, Any]) -> bool:
    """Say whether a record was inserted rather than updated.

    Salesforce answers an insert with 201 and an update with 200, and since
    v46 also states it as `created` in the body. The body is preferred because
    it is explicit, but an update can answer 204 with nothing at all, so the
    status is the fallback rather than the other way round.
    """
    stated = body.get("created")
    if isinstance(stated, bool):
        return stated
    return status == _CREATED_STATUS


def _written_id(status: int, body: Mapping[str, Any]) -> str:
    """Return the record id, insisting on one only where Salesforce promises it.

    A create answers 201 carrying the new id. An update frequently answers 204
    with no body at all, so an absent id there is ordinary and the caller still
    has the external id, which is what named the record in the first place.
    """
    if _was_created(status, body):
        return created_id_of(body)
    return str(body.get("id", ""))
