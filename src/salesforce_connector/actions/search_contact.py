"""Searching contacts through the parameterized search endpoint.

The endpoint choice is a security decision, not a convenience one. SOQL and
SOSL are assembled as text, so building either from a user's words invites the
same class of bug as string-built SQL. `parameterizedSearch` takes the search
term as a JSON value, so nothing the caller supplies is ever parsed as query
syntax and there is no escaping to get wrong.
"""

from collections.abc import Mapping
from typing import Any, ClassVar, Final

from salesforce_connector.actions.action import Action
from salesforce_connector.schemas.read import search_contact as schema
from salesforce_connector.transport.exchange import RequestSpec

_PATH: Final = "parameterizedSearch"
_FIELDS: Final = ("Id", "Name", "Email", "Phone", "Title", "AccountId")


class SearchContact(Action):
    """Find contacts matching free text."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.SearchContactInput
    output_model: ClassVar[type] = schema.SearchContactOutput

    async def _execute(self, params: schema.SearchContactInput) -> Mapping[str, Any]:
        offset = _offset_from(params.cursor)
        response = await self._client.request(
            RequestSpec(
                method="POST",
                path=_PATH,
                json_body={
                    "q": params.query,
                    "fields": list(_FIELDS),
                    "sobjects": [{"name": "Contact"}],
                    "in": "ALL",
                    "overallLimit": params.limit,
                    "offset": offset,
                },
            )
        )
        found = _records_of(response.body)
        return {
            "contacts": [_as_summary(record) for record in found],
            "returned": len(found),
            "next_cursor": _next_cursor(offset, len(found), params.limit),
        }


def _offset_from(cursor: str | None) -> int:
    """Read the position a cursor represents, tolerating a malformed one.

    A cursor is opaque to its holder but ours to interpret. An unreadable one
    restarts at the beginning rather than failing: a caller that mangled a
    cursor gets the first page, not an error it cannot act on.
    """
    if cursor is None:
        return 0
    try:
        return max(0, int(cursor))
    except ValueError:
        return 0


def _next_cursor(offset: int, returned: int, limit: int) -> str | None:
    """Offer a next page only when this one filled up.

    A short page means the results ran out, and returning a cursor there would
    send the caller to fetch nothing.
    """
    return str(offset + returned) if returned == limit else None


def _records_of(body: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(body, Mapping):
        return ()
    records = body.get("searchRecords", ())
    if not isinstance(records, (list, tuple)):
        return ()
    return tuple(record for record in records if isinstance(record, Mapping))


def _as_summary(record: Mapping[str, Any]) -> Mapping[str, Any]:
    """Keep the fields a caller acts on and drop the rest.

    Salesforce returns an `attributes` block and nulls for every unset field on
    every record. Passing that through would spend the caller's context on
    nothing.
    """
    return {
        "id": record.get("Id", ""),
        "name": record.get("Name", ""),
        "email": record.get("Email"),
        "phone": record.get("Phone"),
        "title": record.get("Title"),
        "account_id": record.get("AccountId"),
    }
