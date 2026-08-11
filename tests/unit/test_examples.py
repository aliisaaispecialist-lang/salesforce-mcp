"""Every published example is a call that would actually work.

An example that no longer validates is worse than no example at all: a reader
trusts it, copies it, and gets an error the documentation told them to expect
success from. So each one is run through the same model the action validates
with, which means a renamed field or a tightened constraint breaks this file
rather than shipping a lie.

The results are checked the same way, against the output model, because half an
example is not one -- a reader needs to know the shape of the answer as much as
the shape of the call.
"""

from typing import Any

import pytest
from pydantic import BaseModel

from salesforce_connector.actions import registry
from salesforce_connector.contract import ActionDescriptor, ActionKind
from salesforce_connector.protocol.translate import as_tool
from salesforce_connector.schemas.read import (
    count_records,
    describe_object,
    get_record,
    get_related,
    list_tools,
    search_contact,
    search_records,
    soql_query,
    tool_schema,
)
from salesforce_connector.schemas.write import (
    add_activity_note,
    create_contact,
    create_opportunity,
    create_opportunity_with_contact,
    link_contact_to_opportunity,
    update_contact,
    update_record,
    upsert_record,
)

MODELS: dict[str, tuple[type[BaseModel], type[BaseModel]]] = {
    "salesforce.record_count_by_object": (
        count_records.CountRecordsInput,
        count_records.CountRecordsOutput,
    ),
    "salesforce.opportunity_create_with_contact_by_id": (
        create_opportunity_with_contact.CreateOpportunityWithContactInput,
        create_opportunity_with_contact.CreateOpportunityWithContactOutput,
    ),
    "salesforce.record_search_by_text": (
        search_records.SearchRecordsInput,
        search_records.SearchRecordsOutput,
    ),
    "salesforce.record_update_by_id": (
        update_record.UpdateRecordInput,
        update_record.UpdateRecordOutput,
    ),
    "salesforce.record_upsert_by_external_id": (
        upsert_record.UpsertRecordInput,
        upsert_record.UpsertRecordOutput,
    ),
    "salesforce.tool_list_by_kind": (
        list_tools.ListToolsInput,
        list_tools.ListToolsOutput,
    ),
    "salesforce.tool_describe_by_name": (
        tool_schema.ToolSchemaInput,
        tool_schema.ToolSchemaOutput,
    ),
    "salesforce.object_describe_by_name": (
        describe_object.DescribeObjectInput,
        describe_object.DescribeObjectOutput,
    ),
    "salesforce.record_get_by_id": (
        get_record.GetRecordInput,
        get_record.GetRecordOutput,
    ),
    "salesforce.record_get_related_by_id": (
        get_related.GetRelatedInput,
        get_related.GetRelatedOutput,
    ),
    "salesforce.contact_search_by_text": (
        search_contact.SearchContactInput,
        search_contact.SearchContactOutput,
    ),
    "salesforce.record_query_by_soql": (
        soql_query.SoqlQueryInput,
        soql_query.SoqlQueryOutput,
    ),
    "salesforce.contact_create": (
        create_contact.CreateContactInput,
        create_contact.CreateContactOutput,
    ),
    "salesforce.contact_update_by_id": (
        update_contact.UpdateContactInput,
        update_contact.UpdateContactOutput,
    ),
    "salesforce.opportunity_create": (
        create_opportunity.CreateOpportunityInput,
        create_opportunity.CreateOpportunityOutput,
    ),
    "salesforce.opportunity_link_contact_by_id": (
        link_contact_to_opportunity.LinkContactToOpportunityInput,
        link_contact_to_opportunity.LinkContactToOpportunityOutput,
    ),
    "salesforce.activity_create_by_related_id": (
        add_activity_note.AddActivityNoteInput,
        add_activity_note.AddActivityNoteOutput,
    ),
}


def described() -> tuple[ActionDescriptor, ...]:
    return registry.descriptors()


def worked_calls() -> list[tuple[str, int]]:
    """Every example, identified by action and position."""
    return [
        (action.action_id, index) for action in described() for index in range(len(action.examples))
    ]


def example_at(action_id: str, index: int) -> tuple[dict[str, Any], dict[str, Any]]:
    action = next(d for d in described() if d.action_id == action_id)
    shown = action.examples[index]
    return dict(shown.arguments), dict(shown.result)


class TestEveryActionShowsItsWork:
    @pytest.mark.parametrize("action", described(), ids=lambda d: d.tool_name)
    def test_it_has_at_least_one_example(self, action: ActionDescriptor) -> None:
        # Definition of Done item 4: typed inputs, outputs, and examples. An
        # action without one meets two thirds of that.
        assert action.examples, f"{action.tool_name} publishes no example"

    @pytest.mark.parametrize("action", described(), ids=lambda d: d.tool_name)
    def test_each_example_says_what_it_demonstrates(self, action: ActionDescriptor) -> None:
        for shown in action.examples:
            assert shown.title.strip(), f"{action.tool_name} has an untitled example"


class TestTheExamplesWouldActuallyRun:
    @pytest.mark.parametrize(("action_id", "index"), worked_calls())
    def test_the_arguments_validate(self, action_id: str, index: int) -> None:
        arguments, _ = example_at(action_id, index)

        MODELS[action_id][0].model_validate(arguments)

    @pytest.mark.parametrize(("action_id", "index"), worked_calls())
    def test_the_result_validates(self, action_id: str, index: int) -> None:
        _, result = example_at(action_id, index)

        MODELS[action_id][1].model_validate(result)

    @pytest.mark.parametrize(("action_id", "index"), worked_calls())
    def test_a_write_example_carries_the_key_it_demands(self, action_id: str, index: int) -> None:
        action = next(d for d in described() if d.action_id == action_id)
        if action.kind is not ActionKind.WRITE:
            pytest.skip("reads have no idempotency key")
        arguments, _ = example_at(action_id, index)

        # An example that omitted it would teach the one habit that causes
        # duplicate records.
        assert arguments.get("idempotency_key")


class TestTheExamplesReachTheSurfaces:
    @pytest.mark.parametrize("action", described(), ids=lambda d: d.tool_name)
    def test_the_published_tool_schema_carries_them(self, action: ActionDescriptor) -> None:
        published = as_tool(action).input_schema

        assert published["examples"] == [dict(e.arguments) for e in action.examples]

    @pytest.mark.parametrize("action", described(), ids=lambda d: d.tool_name)
    def test_the_description_a_model_reads_shows_one(self, action: ActionDescriptor) -> None:
        # The schema is where a careful reader looks; the description is where
        # a model looks. Both, or the effort is half wasted.
        assert "Example -- " in action.description
        assert action.examples[0].title in action.description
