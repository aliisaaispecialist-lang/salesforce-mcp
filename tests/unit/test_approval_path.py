"""The approval round trip, exercised the way a client actually performs it.

These exist because a bug got past every other test in this repository. The
tools tell a caller, in their own error text, to "call again with approved set
to true". Every other test built an ActionRequest directly, setting `approved`
as a field, which is not the path a client takes: a client sends `approved`
inside the tool call's arguments. Those arguments are validated against the
action's input model, which forbids unknown fields, and `approved` was not
declared in any of them. So a caller doing exactly what it was told was
rejected, and nothing noticed.

The fix was to declare `approved` where it is asked for. These tests walk the
client's path, from raw tool arguments through to the action, so the two cannot
drift apart again.
"""

import pytest
from mcp.types import CallToolRequestParams
from pydantic import BaseModel

from salesforce_connector.actions import registry
from salesforce_connector.contract import ActionDescriptor, ActionKind
from salesforce_connector.protocol.server import _as_request, _descriptor
from salesforce_connector.schemas import (
    add_activity_note,
    create_contact,
    create_opportunity,
    search_contact,
    update_contact,
)

WRITE_ARGUMENTS = {
    "salesforce_create_contact": {"last_name": "Lovelace", "idempotency_key": "key-12345678"},
    "salesforce_update_contact": {
        "contact_id": "003xx000004TmiQ",
        "idempotency_key": "key-12345678",
        "title": "CTO",
    },
    "salesforce_create_opportunity": {
        "name": "Renewal",
        "stage_name": "Prospecting",
        "close_date": "2026-12-01",
        "idempotency_key": "key-12345678",
    },
    "salesforce_add_activity_note": {
        "related_to_id": "003xx000004TmiQ",
        "subject": "Called",
        "idempotency_key": "key-12345678",
    },
}

WRITE_MODELS: dict[str, type[BaseModel]] = {
    "salesforce_create_contact": create_contact.CreateContactInput,
    "salesforce_update_contact": update_contact.UpdateContactInput,
    "salesforce_create_opportunity": create_opportunity.CreateOpportunityInput,
    "salesforce_add_activity_note": add_activity_note.AddActivityNoteInput,
}


def described() -> tuple[ActionDescriptor, ...]:
    return registry.descriptors()


def for_tool(tool_name: str) -> ActionDescriptor:
    found = _descriptor(tool_name, described())
    assert found is not None
    return found


class TestApprovalIsDeclaredWhereItIsAskedFor:
    @pytest.mark.parametrize("tool_name", sorted(WRITE_ARGUMENTS))
    def test_the_schema_offers_the_field_the_error_text_demands(self, tool_name: str) -> None:
        # A tool must not ask for an argument its own schema does not offer: a
        # caller working from the schema alone would have no way to supply it.
        properties = WRITE_MODELS[tool_name].model_json_schema()["properties"]

        assert "approved" in properties
        assert properties["approved"]["description"]

    @pytest.mark.parametrize("tool_name", sorted(WRITE_ARGUMENTS))
    def test_approval_is_optional_so_the_default_is_refusal(self, tool_name: str) -> None:
        schema = WRITE_MODELS[tool_name].model_json_schema()

        assert "approved" not in schema.get("required", [])
        assert schema["properties"]["approved"]["default"] is False

    def test_the_read_action_offers_no_approval_field(self) -> None:
        assert "approved" not in search_contact.SearchContactInput.model_json_schema()["properties"]


class TestTheClientsPath:
    @pytest.mark.parametrize("tool_name", sorted(WRITE_ARGUMENTS))
    def test_arguments_carrying_approval_survive_validation(self, tool_name: str) -> None:
        arguments = {**WRITE_ARGUMENTS[tool_name], "approved": True}

        request = _as_request(
            CallToolRequestParams(name=tool_name, arguments=arguments), for_tool(tool_name)
        )

        assert request.approved is True
        # The step that used to fail: the action validates what the client sent.
        WRITE_MODELS[tool_name].model_validate(dict(request.params))

    @pytest.mark.parametrize("tool_name", sorted(WRITE_ARGUMENTS))
    def test_arguments_without_approval_still_validate_and_are_refused_later(
        self, tool_name: str
    ) -> None:
        request = _as_request(
            CallToolRequestParams(name=tool_name, arguments=WRITE_ARGUMENTS[tool_name]),
            for_tool(tool_name),
        )

        assert request.approved is False
        WRITE_MODELS[tool_name].model_validate(dict(request.params))

    def test_the_key_is_lifted_onto_the_request_as_well_as_left_in_the_payload(self) -> None:
        arguments = {**WRITE_ARGUMENTS["salesforce_create_contact"], "approved": True}

        request = _as_request(
            CallToolRequestParams(name="salesforce_create_contact", arguments=arguments),
            for_tool("salesforce_create_contact"),
        )

        assert request.idempotency_key == "key-12345678"

    def test_an_unknown_tool_is_recognised_before_a_request_is_built(self) -> None:
        assert _descriptor("nonsense", described()) is None


class TestEveryWriteAgrees:
    def test_every_write_declares_approval_and_the_read_does_not(self) -> None:
        writes = [d for d in described() if d.kind is ActionKind.WRITE]
        reads = [d for d in described() if d.kind is ActionKind.READ]

        assert len(writes) == 8
        assert len(reads) == 9
        for action in writes:
            assert "approved" in action.input_schema["properties"]
        for action in reads:
            assert "approved" not in action.input_schema["properties"]
