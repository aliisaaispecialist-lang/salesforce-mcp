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
from salesforce_connector.mcp_translate import as_tool
from salesforce_connector.schemas import (
    add_activity_note,
    count_records,
    create_contact,
    create_opportunity,
    create_opportunity_with_contact,
    describe_object,
    get_record,
    get_related,
    link_contact_to_opportunity,
    list_tools,
    search_contact,
    search_records,
    soql_query,
    tool_schema,
    update_contact,
    update_record,
    upsert_record,
)

MODELS: dict[str, tuple[type[BaseModel], type[BaseModel]]] = {
    "salesforce.count_records": (
        count_records.CountRecordsInput,
        count_records.CountRecordsOutput,
    ),
    "salesforce.create_opportunity_with_contact": (
        create_opportunity_with_contact.CreateOpportunityWithContactInput,
        create_opportunity_with_contact.CreateOpportunityWithContactOutput,
    ),
    "salesforce.search_records": (
        search_records.SearchRecordsInput,
        search_records.SearchRecordsOutput,
    ),
    "salesforce.update_record": (
        update_record.UpdateRecordInput,
        update_record.UpdateRecordOutput,
    ),
    "salesforce.upsert_record": (
        upsert_record.UpsertRecordInput,
        upsert_record.UpsertRecordOutput,
    ),
    "salesforce.list_tools": (
        list_tools.ListToolsInput,
        list_tools.ListToolsOutput,
    ),
    "salesforce.tool_schema": (
        tool_schema.ToolSchemaInput,
        tool_schema.ToolSchemaOutput,
    ),
    "salesforce.describe_object": (
        describe_object.DescribeObjectInput,
        describe_object.DescribeObjectOutput,
    ),
    "salesforce.get_record": (
        get_record.GetRecordInput,
        get_record.GetRecordOutput,
    ),
    "salesforce.get_related": (
        get_related.GetRelatedInput,
        get_related.GetRelatedOutput,
    ),
    "salesforce.search_contact": (
        search_contact.SearchContactInput,
        search_contact.SearchContactOutput,
    ),
    "salesforce.soql_query": (
        soql_query.SoqlQueryInput,
        soql_query.SoqlQueryOutput,
    ),
    "salesforce.create_contact": (
        create_contact.CreateContactInput,
        create_contact.CreateContactOutput,
    ),
    "salesforce.update_contact": (
        update_contact.UpdateContactInput,
        update_contact.UpdateContactOutput,
    ),
    "salesforce.create_opportunity": (
        create_opportunity.CreateOpportunityInput,
        create_opportunity.CreateOpportunityOutput,
    ),
    "salesforce.link_contact_to_opportunity": (
        link_contact_to_opportunity.LinkContactToOpportunityInput,
        link_contact_to_opportunity.LinkContactToOpportunityOutput,
    ),
    "salesforce.add_activity_note": (
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
