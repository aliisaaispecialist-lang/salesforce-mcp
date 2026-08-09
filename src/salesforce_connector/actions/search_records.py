"""Searching an arbitrary object through the parameterized search endpoint.

Same endpoint and same security argument as `search_contact`: the term travels
as a JSON value, never as query text, so nothing the caller supplies is parsed
as syntax and there is no escaping to get wrong.

What differs is that neither the object nor the field list can be decided here.
`search_contact` knows it is looking at contacts and knows which six fields a
contact tool needs. This one is told both, and passes the records through as
Salesforce returns them, because a shape chosen for an unknown object would be
a guess.
"""

from collections.abc import Mapping
from typing import Any, ClassVar, Final

from salesforce_connector.actions.action import Action
from salesforce_connector.schemas import search_records as schema
from salesforce_connector.transport.exchange import RequestSpec

_PATH: Final = "parameterizedSearch"


class SearchRecords(Action):
    """Find records of any object matching free text."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.SearchRecordsInput
    output_model: ClassVar[type] = schema.SearchRecordsOutput

    async def _execute(self, params: schema.SearchRecordsInput) -> Mapping[str, Any]:
        offset = _offset_from(params.cursor)
        response = await self._client.request(
            RequestSpec(
                method="POST",
                path=_PATH,
                json_body={
                    "q": params.query,
                    "fields": list(params.fields),
                    "sobjects": [{"name": params.object_name}],
                    "in": "ALL",
                    "overallLimit": params.limit,
                    "offset": offset,
                },
            )
        )
        found = _records_of(response.body)
        return {
            "records": tuple(_without_attributes(record) for record in found),
            "returned": len(found),
            "next_cursor": _next_cursor(offset, len(found), params.limit),
        }


def _offset_from(cursor: str | None) -> int:
    """Read the position a cursor represents, tolerating a malformed one.

    An unreadable cursor restarts at the beginning rather than failing. A
    caller that mangled one gets the first page, not an error it cannot act on.
    """
    if cursor is None:
        return 0
    try:
        return max(0, int(cursor))
    except ValueError:
        return 0


def _next_cursor(offset: int, returned: int, limit: int) -> str | None:
    """Offer a next page only when this one filled up."""
    return str(offset + returned) if returned == limit else None


def _records_of(body: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(body, Mapping):
        return ()
    records = body.get("searchRecords", ())
    if not isinstance(records, (list, tuple)):
        return ()
    return tuple(record for record in records if isinstance(record, Mapping))


def _without_attributes(record: Mapping[str, Any]) -> dict[str, Any]:
    """Drop the block Salesforce adds to every record and nobody asked for.

    `attributes` carries the object's type and a URL to itself. Both are
    already known to whoever made the call, so passing them through spends the
    caller's context on what it already has.
    """
    return {name: value for name, value in record.items() if name != "attributes"}
