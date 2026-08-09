"""Two writes Salesforce applies as one, and the failure that hides inside a 200.

The composite endpoint takes several subrequests and, with `allOrNone` set,
either commits all of them or none. The second subrequest refers to the first
by reference id, so the contact role can name an opportunity that does not have
an id yet at the moment the request is written.

The part that matters, and the part that is easy to get wrong: **a composite
that failed still answers HTTP 200.** The real error sits inside the body, on
whichever subrequest was rejected, and the others report PROCESSING_HALTED to
say they were rolled back. Every error path in this connector keys on the HTTP
status, so without the check below a failed write would be reported as a
success carrying empty ids. That is the same class of bug as the four the first
live run found, and it is invisible to a mock that only ever returns the happy
shape.
"""

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, Final

from salesforce_connector.actions import stages
from salesforce_connector.actions.action import Action, created_id
from salesforce_connector.errors.mapping import to_connector_error
from salesforce_connector.errors.model import (
    ErrorContext,
    EscalationError,
    TransportError,
)
from salesforce_connector.schemas import create_opportunity_with_contact as schema
from salesforce_connector.transport.exchange import RequestSpec

_PATH: Final = "composite"
_OPPORTUNITY: Final = "newOpportunity"
_ROLE: Final = "contactRole"
_FAILED: Final = 400
# What Salesforce reports on the subrequests it rolled back. It is a
# consequence of some other subrequest failing, never the cause, so it is the
# last thing to blame for the failure.
_HALTED: Final = "PROCESSING_HALTED"
# How many subrequests are sent. A shorter answer than this means
# something was lost, not that something succeeded.
_SUBREQUESTS: Final = 2


class CreateOpportunityWithContact(Action):
    """Open a deal and attach its contact, atomically."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.CreateOpportunityWithContactInput
    output_model: ClassVar[type] = schema.CreateOpportunityWithContactOutput

    async def _execute(self, params: schema.CreateOpportunityWithContactInput) -> Mapping[str, Any]:
        # The same check create_opportunity makes. This tool's own description
        # tells the caller a wrong stage "fails the whole write, including the
        # contact link", which was a promise nothing here kept.
        await stages.reject_unknown(self._client, params.stage_name)
        response = await self._client.request(
            RequestSpec(
                method="POST",
                path=_PATH,
                json_body={
                    "allOrNone": True,
                    "compositeRequest": self._subrequests(params),
                },
                is_write=True,
                idempotency_key=params.idempotency_key,
            )
        )
        parts = _subresponses(response.body)
        _raise_if_any_failed(parts)
        return {
            "id": _id_from(parts, _OPPORTUNITY),
            "name": params.name,
            "stage_name": params.stage_name,
            "contact_id": params.contact_id,
            "contact_role_id": _id_from(parts, _ROLE),
            "created": True,
        }

    def _subrequests(
        self, params: schema.CreateOpportunityWithContactInput
    ) -> list[Mapping[str, Any]]:
        """Write the two calls, the second pointing at the first.

        The urls are absolute paths including the API version, which composite
        requires and which is read from settings rather than written here: a
        version in the code would drift from the one every other call uses.
        """
        base = f"/services/data/{self._client.settings.api_version}/sobjects"
        return [
            {
                "method": "POST",
                "url": f"{base}/Opportunity",
                "referenceId": _OPPORTUNITY,
                "body": _deal(params),
            },
            {
                "method": "POST",
                "url": f"{base}/OpportunityContactRole",
                "referenceId": _ROLE,
                # Resolved by Salesforce once the opportunity above has an id.
                "body": _role(params, opportunity=f"@{{{_OPPORTUNITY}.id}}"),
            },
        ]


def _deal(params: schema.CreateOpportunityWithContactInput) -> Mapping[str, Any]:
    """Build the opportunity, omitting what was not given."""
    fields: dict[str, Any] = {
        "Name": params.name,
        "StageName": params.stage_name,
        "CloseDate": params.close_date.isoformat(),
    }
    if params.amount is not None:
        fields["Amount"] = params.amount
    if params.account_id is not None:
        fields["AccountId"] = params.account_id
    return fields


def _role(params: schema.CreateOpportunityWithContactInput, opportunity: str) -> Mapping[str, Any]:
    """Build the contact role, leaving out a role nobody asked for.

    An omitted role lets the org apply its own default. Inventing one risks a
    restricted picklist rejecting it, and here that would roll back the deal as
    well.
    """
    fields: dict[str, Any] = {"OpportunityId": opportunity, "ContactId": params.contact_id}
    if params.role is not None:
        fields["Role"] = params.role
    return fields


def _subresponses(body: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(body, Mapping):
        return ()
    parts = body.get("compositeResponse", ())
    if not isinstance(parts, (list, tuple)):
        return ()
    return tuple(part for part in parts if isinstance(part, Mapping))


def _raise_if_any_failed(parts: Sequence[Mapping[str, Any]]) -> None:
    """Turn a failure buried in a 200 into the error it actually is.

    The subrequest that caused the rollback is preferred over the ones merely
    halted by it, so the caller is told the real reason rather than told that
    something else went wrong.
    """
    if len(parts) != _SUBREQUESTS:
        raise TransportError(
            f"Salesforce answered with {len(parts)} results for {_SUBREQUESTS} "
            f"requests, so what was written cannot be established from here."
        )
    failures = [part for part in parts if int(part.get("httpStatusCode", 200)) >= _FAILED]
    if not failures:
        return
    _raise_if_partly_applied(parts, failures)
    blamed = next((part for part in failures if not _is_halted(part)), failures[0])
    raise to_connector_error(int(blamed.get("httpStatusCode", _FAILED)), blamed.get("body"))


def _raise_if_partly_applied(
    parts: Sequence[Mapping[str, Any]], failures: Sequence[Mapping[str, Any]]
) -> None:
    """Check the all-or-nothing promise instead of assuming it.

    This tool tells a person, in its own recovery instructions, that nothing
    was left half-done and there is no orphaned deal to clean up. That is a
    claim about Salesforce's behaviour, and it was never verified: the code
    raised the first failure it found and stopped, so a subrequest reporting
    success beside a failure would have gone unmentioned while the caller was
    told to expect nothing.

    If that ever happens the right answer is a person, not a retry, because a
    record exists that nobody is expecting.
    """
    applied = [
        part
        for part in parts
        if part not in failures and int(part.get("httpStatusCode", 200)) < _FAILED
    ]
    if not applied:
        return
    left = ", ".join(_id_of(part) or part.get("referenceId", "?") for part in applied)
    raise EscalationError(
        f"Salesforce rolled back part of this write but not all of it. "
        f"These records still exist: {left}.",
        ErrorContext(
            next_step=(
                "Do not retry. Open Salesforce and delete the records named "
                "above, which were created without the rest of the write they "
                "belonged to."
            ),
        ),
    )


def _is_halted(part: Mapping[str, Any]) -> bool:
    """Say whether this subrequest was rolled back rather than rejected."""
    body = part.get("body")
    faults = body if isinstance(body, (list, tuple)) else ()
    return any(isinstance(fault, Mapping) and fault.get("errorCode") == _HALTED for fault in faults)


def _id_from(parts: Sequence[Mapping[str, Any]], reference: str) -> str:
    """Read the record id one subrequest created, insisting there is one.

    An empty string here used to be returned as a success: `created: true`
    beside an id nobody can look up. Both records are reported, so both must
    have arrived.
    """
    for part in parts:
        if part.get("referenceId") == reference:
            return created_id(part.get("body"))
    raise TransportError(
        f"Salesforce did not answer the {reference!r} part of this write, so "
        f"what it wrote cannot be established from here."
    )


def _id_of(part: Mapping[str, Any]) -> str:
    """Read a subrequest's record id without insisting on one."""
    body = part.get("body")
    return str(body.get("id", "")) if isinstance(body, Mapping) else ""
