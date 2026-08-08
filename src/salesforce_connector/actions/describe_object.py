"""Describing an object, reduced to the part a caller can act on.

Salesforce answers a describe with everything it knows: layouts, permissions,
child relationships, per-field metadata dozens of keys deep. Ninety-six
thousand characters for Opportunity on a plain org, and almost none of it helps
somebody write a correct call.

So this keeps five things per field and drops the rest. What it is called, what
a person calls it, its type, whether a create fails without it, and the values
this org accepts if it is a picklist. Plus the relationship name, because that
is the argument `get_related` needs and nothing else reports it.
"""

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from salesforce_connector.actions.action import Action
from salesforce_connector.exchange import RequestSpec
from salesforce_connector.schemas import describe_object as schema


class DescribeObject(Action):
    """Report an object's fields, without the ninety-six thousand characters."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.DescribeObjectInput
    output_model: ClassVar[type] = schema.DescribeObjectOutput

    async def _execute(self, params: schema.DescribeObjectInput) -> Mapping[str, Any]:
        response = await self._client.request(
            RequestSpec(method="GET", path=f"sobjects/{params.object_name}/describe")
        )
        body = response.body if isinstance(response.body, Mapping) else {}

        described = [
            _field(field)
            for field in body.get("fields", ())
            if not params.only_writable or _is_writable(field)
        ]
        return {
            "object_name": str(body.get("name", params.object_name)),
            "label": str(body.get("label", "")),
            "fields": tuple(described),
            "returned": len(described),
        }


def _is_writable(field: Mapping[str, Any]) -> bool:
    """Say whether a create or update could set this field.

    A formula, a rollup, an autonumber and CreatedDate are all readable and all
    reject a write. Offering them to a caller composing a create is offering a
    failure.
    """
    return bool(field.get("createable")) or bool(field.get("updateable"))


def _field(field: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the five things that decide how a field is used."""
    return {
        "name": str(field.get("name", "")),
        "label": str(field.get("label", "")),
        "type": str(field.get("type", "")),
        # Salesforce states this as two negatives: a field is required when it
        # cannot be null and has no default the platform supplies. Saying it
        # positively here saves every caller working it out.
        "required": not field.get("nillable", True) and not field.get("defaultedOnCreate", False),
        "updateable": bool(field.get("updateable")),
        "picklist_values": _active(field.get("picklistValues", ())),
        "relationship_name": field.get("relationshipName") or None,
    }


def _active(values: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Return the picklist values this org currently accepts.

    Inactive values stay in the describe response so historical records still
    render, but sending one to a write is rejected. A caller offered an
    inactive value would be offered a failure.
    """
    return tuple(str(value.get("value", "")) for value in values if value.get("active", True))
