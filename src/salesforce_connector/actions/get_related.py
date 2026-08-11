"""Following one relationship, from a record to what it is attached to.

Bounded, like every other read here. A lookup returns one record and needs no
ceiling, but a child collection does not: `Contacts` on a large account returns
whatever Salesforce chose to put on the first page, and the caller had no way
to ask for less and no way to learn there was more. `soql_query` has been held
to `max_query_rows` from the start; this is the same ceiling, applied to the
one read that escaped it.
"""

from collections.abc import Mapping
from typing import Any, ClassVar

from salesforce_connector.actions.action import Action
from salesforce_connector.schemas.read import get_related as schema
from salesforce_connector.transport.exchange import RequestSpec


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
        found = _records(response.body)
        total = _total_size(response.body, len(found))
        kept = self._bounded(found, total)
        return {"records": tuple(kept), "returned": len(kept), "total_size": total}

    def _bounded(self, found: list[dict[str, Any]], total: int) -> list[dict[str, Any]]:
        """Hold the answer to the configured ceiling, and say so when it bites.

        Silently returning fewer records than exist is the failure mode worth
        avoiding: a model that asked for an account's contacts and got the
        first two hundred would reasonably conclude that is all of them.
        """
        ceiling = self._client.settings.max_query_rows
        if len(found) <= ceiling:
            return found
        self.warn(
            f"This relationship holds {total} records and only the first "
            f"{ceiling} are below. Do not treat them as the whole set. Use "
            f"salesforce_soql_query if you need the rest, or a filter to "
            f"narrow it."
        )
        return found[:ceiling]


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


def _total_size(body: Any, found: int) -> int:
    """How many records exist, when Salesforce says so.

    A child collection answers with a query result envelope and reports
    `totalSize`. A lookup answers with the record itself and reports nothing,
    in which case what was found is all there is.
    """
    if isinstance(body, Mapping) and isinstance(body.get("totalSize"), int):
        return int(body["totalSize"])
    return found


def _row(record: Mapping[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in record.items() if name != "attributes"}
