"""Reading one record, optionally narrowed to the fields worth having."""

from collections.abc import Mapping
from typing import Any, ClassVar

from salesforce_connector.actions.action import Action
from salesforce_connector.exchange import RequestSpec
from salesforce_connector.schemas import get_record as schema


class GetRecord(Action):
    """Fetch a single record by id."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.GetRecordInput
    output_model: ClassVar[type] = schema.GetRecordOutput

    async def _execute(self, params: schema.GetRecordInput) -> Mapping[str, Any]:
        response = await self._client.request(
            RequestSpec(
                method="GET",
                path=f"sobjects/{params.object_name}/{params.record_id}",
                # Salesforce returns every field when none are named, which on a
                # real object is dozens of mostly-empty columns spent on a
                # question about three of them.
                params={"fields": ",".join(params.fields)} if params.fields else {},
            )
        )
        body = response.body if isinstance(response.body, Mapping) else {}
        return {"record": {name: value for name, value in body.items() if name != "attributes"}}
