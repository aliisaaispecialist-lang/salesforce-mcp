"""Changing a record of any object, then reading back what it now says.

Same shape as `update_contact` and for the same reason: Salesforce answers a
successful PATCH with 204 and no body, so the write alone reports only that
nothing went wrong. The read that follows costs one call and turns that into an
answer.

The read asks for exactly the fields that were written, plus the id. Reading
the whole record would return dozens of empty fields nobody asked about, and on
an unknown object there is no shorter list that can be known in advance.
"""

from collections.abc import Mapping
from typing import Any, ClassVar

from salesforce_connector.actions.action import Action
from salesforce_connector.errors.model import ConnectorError
from salesforce_connector.schemas.write import update_record as schema
from salesforce_connector.transport.exchange import RequestSpec


class UpdateRecord(Action):
    """Set named fields on a record and report them afterwards."""

    spec = schema.SPEC
    input_model: ClassVar[type] = schema.UpdateRecordInput
    output_model: ClassVar[type] = schema.UpdateRecordOutput

    async def _execute(self, params: schema.UpdateRecordInput) -> Mapping[str, Any]:
        path = f"sobjects/{params.object_name}/{params.record_id}"
        await self._client.request(
            RequestSpec(
                method="PATCH",
                path=path,
                json_body=dict(params.fields),
                is_write=True,
                idempotency_key=params.idempotency_key,
            )
        )
        return {
            "id": params.record_id,
            "object_name": params.object_name,
            "record": await self._confirmed(path, tuple(params.fields)),
            "changed_fields": tuple(params.fields),
        }

    async def _confirmed(self, path: str, written: tuple[str, ...]) -> dict[str, Any]:
        """Read the record back, without letting that read undo the write.

        The write has already happened by this point. A failure in the read
        that follows used to escape and fail the whole action, so a caller was
        told the update did not happen when it had -- and a retry on that
        advice would apply it a second time.

        So the read is allowed to fail on its own. The write is still reported,
        and the caller is told plainly that the confirmation is missing rather
        than being shown an empty record and left to guess.
        """
        try:
            return await self._read_back(path, written)
        except ConnectorError as unconfirmed:
            self.warn(
                f"The change was applied, but reading the record back afterwards "
                f"failed: {unconfirmed.to_action_error().reason} Do not repeat this "
                f"call; read the record separately to confirm what it now holds."
            )
            return {}

    async def _read_back(self, path: str, written: tuple[str, ...]) -> dict[str, Any]:
        """Fetch the fields that were just set, and nothing else."""
        response = await self._client.request(
            RequestSpec(
                method="GET",
                path=path,
                params={"fields": ",".join(("Id", *written))},
            )
        )
        body = response.body if isinstance(response.body, Mapping) else {}
        return {name: value for name, value in body.items() if name != "attributes"}
