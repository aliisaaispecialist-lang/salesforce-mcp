"""The org's own sales stages, and refusing one it does not have.

Written once and used by both tools that open a deal. `create_opportunity` had
this check and `create_opportunity_with_contact` did not, although its own
description tells a caller that a wrong stage "fails the whole write, including
the contact link". That was true of the promise and not of the code.

Worth checking rather than leaving to Salesforce, because StageName is often an
*unrestricted* picklist: a stage nobody configured is accepted silently and
lands in every forecast and report keyed on stage. A hard refusal is right here
precisely because the failure is quiet.
"""

from collections.abc import Mapping, Sequence
from typing import Final

from salesforce_connector.errors.model import ConnectorError, ErrorContext, InvalidInputError
from salesforce_connector.transport.client import SalesforceClient
from salesforce_connector.transport.exchange import RequestSpec

DESCRIBE_PATH: Final = "sobjects/Opportunity/describe"


async def reject_unknown(client: SalesforceClient, stage: str) -> None:
    """Refuse a stage this org does not use, and say which it does."""
    allowed = await _stages(client)
    if allowed and stage not in allowed:
        raise InvalidInputError(
            f"{stage!r} is not a sales stage in this Salesforce org.",
            ErrorContext(
                next_step=(
                    f"Use one of these exact values: {', '.join(allowed)}. "
                    f"Ask the user which they meant if none is obviously right."
                ),
                invalid_fields=("stage_name",),
            ),
        )


async def _stages(client: SalesforceClient) -> tuple[str, ...]:
    """Read the org's configured stages, tolerating a describe we cannot do.

    A profile may be allowed to create opportunities but not to describe them.
    Losing the check is better than losing the action, so an unreadable
    picklist skips validation and lets Salesforce judge.
    """
    try:
        response = await client.request(RequestSpec(method="GET", path=DESCRIBE_PATH))
    except ConnectorError:
        return ()
    return picklist_values(response.body, "StageName")


def picklist_values(body: object, field_name: str) -> tuple[str, ...]:
    """Pull one field's active picklist values out of a describe response."""
    if not isinstance(body, Mapping):
        return ()
    fields = body.get("fields", ())
    if not isinstance(fields, Sequence):
        return ()
    for field in fields:
        if isinstance(field, Mapping) and field.get("name") == field_name:
            return _active(field.get("picklistValues", ()))
    return ()


def _active(values: object) -> tuple[str, ...]:
    if not isinstance(values, Sequence):
        return ()
    return tuple(
        str(value.get("value", ""))
        for value in values
        if isinstance(value, Mapping) and value.get("active", True)
    )
