"""Running a SOQL query, with the two guards the endpoint does not provide.

Salesforce enforces what this user may read, and `/query` cannot write at all,
so neither permission nor destruction is this action's problem. Two things are:

**It must be a SELECT.** Not because something worse would succeed -- nothing
else is expressible -- but because a caller sending anything else has
misunderstood the tool, and saying so plainly is more useful than forwarding it
to be rejected by a stranger.

**It must be bounded.** `SELECT Id FROM Contact` is a valid query that pages an
entire object and spends an org's daily allowance answering a question nobody
asked precisely. An absent LIMIT is added; an excessive one is lowered and the
caller is told.
"""

import re
from collections.abc import Mapping
from typing import Any, ClassVar, Final

from salesforce_connector.actions.action import Action
from salesforce_connector.errors.model import ErrorContext, InvalidInputError
from salesforce_connector.exchange import RequestSpec
from salesforce_connector.schemas import soql_query as schema

_PATH: Final = "query"
_SELECT: Final = re.compile(r"^\s*SELECT\s", re.IGNORECASE)
_LIMIT: Final = re.compile(r"\bLIMIT\s+(\d+)\s*$", re.IGNORECASE)
# COUNT() returns a number rather than rows, so a LIMIT would be meaningless
# and Salesforce rejects the combination outright.
_COUNT: Final = re.compile(r"\bCOUNT\s*\(\s*\)", re.IGNORECASE)


class SoqlQuery(Action):
    """Answer a question about records, without changing any of them."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.SoqlQueryInput
    output_model: ClassVar[type] = schema.SoqlQueryOutput

    async def _execute(self, params: schema.SoqlQueryInput) -> Mapping[str, Any]:
        if params.cursor is not None:
            # The cursor is a path Salesforce gave us. It is used verbatim,
            # never rebuilt, because its contents are Salesforce's business.
            body = await self._fetch(RequestSpec(method="GET", absolute_url=params.cursor))
        else:
            bounded = _bounded(_must_be_a_select(params.soql), self._client.settings.max_query_rows)
            body = await self._fetch(RequestSpec(method="GET", path=_PATH, params={"q": bounded}))

        records = tuple(_row(record) for record in body.get("records", ()))
        return {
            "records": records,
            "returned": len(records),
            "total_size": int(body.get("totalSize", len(records))),
            # `done` is Salesforce's own word for "there is no more". Deriving
            # the cursor from it rather than from the row count keeps the two
            # from ever disagreeing.
            "next_cursor": None if body.get("done", True) else body.get("nextRecordsUrl"),
        }

    async def _fetch(self, spec: RequestSpec) -> Mapping[str, Any]:
        response = await self._client.request(spec)
        return response.body if isinstance(response.body, Mapping) else {}


def _must_be_a_select(soql: str) -> str:
    """Refuse anything that is not a read, and say why rather than how."""
    if _SELECT.match(soql):
        return soql.strip()
    raise InvalidInputError(
        f"{soql.strip().split()[0]!r} is not a SELECT, and this tool only reads.",
        ErrorContext(
            next_step=(
                "Rewrite it as a SELECT. This endpoint cannot create, change, or "
                "delete anything; use one of the write tools for that."
            ),
            invalid_fields=("soql",),
        ),
    )


def _bounded(soql: str, ceiling: int) -> str:
    """Give an unbounded query a limit, and lower one that is too large.

    A count is left alone. It returns a single number, so there is nothing to
    limit, and Salesforce rejects COUNT() combined with LIMIT.
    """
    if _COUNT.search(soql):
        return soql

    asked = _LIMIT.search(soql)
    if asked is None:
        return f"{soql} LIMIT {ceiling}"
    if int(asked.group(1)) <= ceiling:
        return soql
    return _LIMIT.sub(f"LIMIT {ceiling}", soql)


def _row(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return one row as a plain dict, without Salesforce's own bookkeeping.

    Two reasons, and neither is cosmetic. Responses arrive frozen, and a
    read-only mapping cannot be serialised back out, so the copy is required
    rather than tidy. And every record carries an `attributes` block naming its
    type and REST path, which the caller did not ask for and which costs
    context on every row of every page.
    """
    return {name: value for name, value in record.items() if name != "attributes"}
