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
# A trailing OFFSET belongs to the same clause and must survive a clamp,
# otherwise lowering the ceiling would silently return the caller to page one.
_LIMIT: Final = re.compile(r"\bLIMIT\s+(\d+)(\s+OFFSET\s+\d+)?\s*$", re.IGNORECASE)
# COUNT() returns a number rather than rows, so a LIMIT would be meaningless
# and Salesforce rejects the combination outright.
#
# Anchored to the select list, which it was not. Searched anywhere in the text,
# it matched the literal characters inside `WHERE Name LIKE '%COUNT()%'`, took
# the count branch, and returned that query with no LIMIT at all -- the row
# ceiling, which is the only cost control this tool has, simply did not apply.
_COUNT: Final = re.compile(r"^\s*SELECT\s+COUNT\s*\(\s*\)", re.IGNORECASE)
# SOQL is not purely a read. FOR UPDATE takes row locks until the transaction
# ends; FOR VIEW and FOR REFERENCE write LastViewedDate and LastReferencedDate
# on every row matched, which is what "recently viewed" lists are built from.
# All three were rejected only as a side effect of appending LIMIT after them,
# which is not a guard, and stopped happening for any query the count check
# mis-matched above.
_FOR_CLAUSE: Final = re.compile(r"\bFOR\s+(UPDATE|VIEW|REFERENCE)\b", re.IGNORECASE)
# The shape of Salesforce's own nextRecordsUrl, and the only thing accepted as
# a cursor. A path, never a full address: see _paged_at.
_CURSOR: Final = re.compile(r"^/services/data/v\d+\.\d+/query/[A-Za-z0-9_-]+/?$")
# A quoted value in a WHERE clause is data, not syntax. Searching the raw text
# for a keyword finds it inside `WHERE Name = 'For view'` too, which is how the
# count check came to skip the row ceiling on an ordinary query.
_LITERAL: Final = re.compile(r"'(?:[^'\\]|\\.)*'")


class SoqlQuery(Action):
    """Answer a question about records, without changing any of them."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.SoqlQueryInput
    output_model: ClassVar[type] = schema.SoqlQueryOutput

    async def _execute(self, params: schema.SoqlQueryInput) -> Mapping[str, Any]:
        if params.cursor is not None:
            body = await self._fetch(RequestSpec(method="GET", path=_paged_at(params.cursor)))
        else:
            checked = _reads_only(_must_be_a_select(params.soql))
            bounded = _bounded(checked, self._client.settings.max_query_rows)
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


def _paged_at(cursor: str) -> str:
    """Turn a cursor into a path this connector will resolve against its own org.

    It used to be sent as an absolute URL, verbatim, on the reasoning that its
    contents were Salesforce's business. Two things were wrong with that. The
    client attaches the org's bearer token to whatever URL it is given, so a
    cursor naming another host would have posted the token to that host -- and
    the records this connector reads contain text other people wrote, which is
    the whole reason responses are fenced. Second, it never worked: Salesforce
    returns nextRecordsUrl as a path, and a path with no scheme is not a URL
    httpx will send, so every genuine attempt to read a second page raised.

    Returning a path fixes both. The client builds the URL from the token's own
    instance, so a cursor cannot name a host at all.
    """
    if _CURSOR.match(cursor):
        return cursor
    raise InvalidInputError(
        "That cursor is not one Salesforce issued.",
        ErrorContext(
            next_step=(
                "Send back the next_cursor from the previous result exactly as it "
                "was given, or omit it to start again from the first page. A "
                "cursor is a path, never a full web address."
            ),
            invalid_fields=("cursor",),
        ),
    )


def _without_literals(soql: str) -> str:
    """Blank out quoted values, so a keyword search cannot match one."""
    return _LITERAL.sub("''", soql)


def _reads_only(soql: str) -> str:
    """Refuse the three SOQL clauses that are not reads.

    FOR UPDATE locks the rows it selects until the transaction ends. FOR VIEW
    and FOR REFERENCE update LastViewedDate and LastReferencedDate, which is a
    write to every row matched, and is what "most recently viewed" is built on.
    """
    found = _FOR_CLAUSE.search(_without_literals(soql))
    if found is None:
        return soql
    raise InvalidInputError(
        f"{found.group(0).upper()!r} is not a read: it locks rows or updates "
        f"when they were last viewed.",
        ErrorContext(
            next_step=(
                "Remove the FOR clause and run the query again. This tool only "
                "reads; nothing here can mark a record as viewed or lock it."
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
    # Keep any OFFSET: lowering the ceiling must not move the caller's page.
    return _LIMIT.sub(lambda kept: f"LIMIT {ceiling}{kept.group(2) or ''}", soql)


def _row(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return one row as a plain dict, without Salesforce's own bookkeeping.

    Two reasons, and neither is cosmetic. Responses arrive frozen, and a
    read-only mapping cannot be serialised back out, so the copy is required
    rather than tidy. And every record carries an `attributes` block naming its
    type and REST path, which the caller did not ask for and which costs
    context on every row of every page.
    """
    return {name: value for name, value in record.items() if name != "attributes"}
