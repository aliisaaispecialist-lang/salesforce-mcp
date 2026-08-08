"""Reading Salesforce's own record counters, rather than counting rows."""

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, Final

from salesforce_connector.actions.action import Action
from salesforce_connector.exchange import RequestSpec
from salesforce_connector.schemas import count_records as schema

_PATH: Final = "limits/recordCount"

# Kept out of an f-string on purpose. It names a SOQL statement as advice, and
# inside an f-string a linter reads that as query construction -- correctly, in
# general; wrongly here, where nothing is being built and nothing is sent.
_ADVICE: Final = (
    "Salesforce returned no count for: {absent}. These counts are cached and "
    "refreshed on Salesforce's own schedule, so an object it has not computed "
    "yet is missing rather than zero -- this does not mean there are no "
    "records. For an exact count, call salesforce_soql_query and ask it to "
    "select a count from that object."
)


class CountRecords(Action):
    """Report how many records each named object holds."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.CountRecordsInput
    output_model: ClassVar[type] = schema.CountRecordsOutput

    async def _execute(self, params: schema.CountRecordsInput) -> Mapping[str, Any]:
        response = await self._client.request(
            RequestSpec(
                method="GET",
                path=_PATH,
                params={"sObjects": ",".join(params.objects)},
            )
        )
        body = response.body if isinstance(response.body, Mapping) else {}
        counted = _counted(body.get("sObjects", ()))
        return {
            "counts": tuple(counted),
            "not_counted": _missing(params.objects, counted),
        }


def _counted(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep the name and the number, and drop the rest.

    Salesforce omits an object the user may not read rather than reporting it
    as zero, which is why the output documents that a missing name means
    unreadable-or-absent rather than empty.
    """
    return [{"name": str(row.get("name", "")), "count": int(row.get("count", 0))} for row in rows]


def _missing(asked: tuple[str, ...], counted: list[dict[str, Any]]) -> str | None:
    """Say which objects Salesforce declined to count, and what to do instead.

    This endpoint reports a cached, approximate count that Salesforce refreshes
    on its own schedule, and an object it has not yet computed is simply absent
    from the response rather than reported as zero. A young org can return
    nothing at all -- which is exactly what the org this was first run against
    did, for objects that demonstrably held records.

    Returning an empty list and leaving the caller to conclude "no records"
    would be the worst outcome available, so absence is named and the tool that
    can answer properly is named with it.
    """
    answered = {row["name"].lower() for row in counted}
    absent = [name for name in asked if name.lower() not in answered]
    if not absent:
        return None
    return _ADVICE.format(absent=", ".join(absent))
