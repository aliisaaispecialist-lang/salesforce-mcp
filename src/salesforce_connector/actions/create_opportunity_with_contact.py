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

from salesforce_connector.actions.action import Action
from salesforce_connector.errors.mapping import to_connector_error
from salesforce_connector.exchange import RequestSpec
from salesforce_connector.schemas import create_opportunity_with_contact as schema

_PATH: Final = "composite"
_OPPORTUNITY: Final = "newOpportunity"
_ROLE: Final = "contactRole"
_FAILED: Final = 400
# What Salesforce reports on the subrequests it rolled back. It is a
# consequence of some other subrequest failing, never the cause, so it is the
# last thing to blame for the failure.
_HALTED: Final = "PROCESSING_HALTED"


class CreateOpportunityWithContact(Action):
    """Open a deal and attach its contact, atomically."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.CreateOpportunityWithContactInput
    output_model: ClassVar[type] = schema.CreateOpportunityWithContactOutput

    async def _execute(self, params: schema.CreateOpportunityWithContactInput) -> Mapping[str, Any]:
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
    failures = [part for part in parts if int(part.get("httpStatusCode", 200)) >= _FAILED]
    if not failures:
        return
    blamed = next((part for part in failures if not _is_halted(part)), failures[0])
    raise to_connector_error(int(blamed.get("httpStatusCode", _FAILED)), blamed.get("body"))


def _is_halted(part: Mapping[str, Any]) -> bool:
    """Say whether this subrequest was rolled back rather than rejected."""
    body = part.get("body")
    faults = body if isinstance(body, (list, tuple)) else ()
    return any(isinstance(fault, Mapping) and fault.get("errorCode") == _HALTED for fault in faults)


def _id_from(parts: Sequence[Mapping[str, Any]], reference: str) -> str:
    """Read the record id one subrequest created."""
    for part in parts:
        if part.get("referenceId") != reference:
            continue
        body = part.get("body")
        if isinstance(body, Mapping):
            return str(body.get("id", ""))
    return ""
