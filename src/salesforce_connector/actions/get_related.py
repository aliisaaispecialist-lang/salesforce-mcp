"""Following one relationship, from a record to what it is attached to."""

from collections.abc import Mapping
from typing import Any, ClassVar

from salesforce_connector.actions.action import Action
from salesforce_connector.exchange import RequestSpec
from salesforce_connector.schemas import get_related as schema


class GetRelated(Action):
    """Read whatever sits on the other side of a relationship."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.GetRelatedInput
    output_model: ClassVar[type] = schema.GetRelatedOutput

    async def _execute(self, params: schema.GetRelatedInput) -> Mapping[str, Any]:
        response = await self._client.request(
            RequestSpec(
                method="GET",
                path=(f"sobjects/{params.object_name}/{params.record_id}/{params.relationship}"),
            )
        )
        return {"records": tuple(_records(response.body)), "returned": len(_records(response.body))}


def _records(body: Any) -> list[dict[str, Any]]:
    """Return a list either way, since Salesforce answers in two shapes.

    A lookup returns the related record on its own. A child collection returns
    an envelope with `records` inside it. A caller should not have to know
    which kind of relationship it followed to read the answer, so both become
    a list here.

    `attributes` is dropped for the same reasons as everywhere else: the
    response arrives frozen and cannot be serialised back out, and the block
    names a type and a REST path nobody asked for.
    """
    if not isinstance(body, Mapping):
        return []
    if "records" in body:
        return [_row(record) for record in body["records"]]
    return [_row(body)]


def _row(record: Mapping[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in record.items() if name != "attributes"}
