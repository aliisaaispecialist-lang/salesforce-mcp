"""What a client is shown, and what a door may be used for.

The surface decides visibility. It must not decide permission: a write called
through a door is the same write, gated the same way, or the door is a hole.
"""

import json

import pytest
from mcp.types import Tool

from salesforce_connector.actions import registry
from salesforce_connector.contract import ActionDescriptor, ActionKind
from salesforce_connector.protocol import surface


def described() -> tuple[ActionDescriptor, ...]:
    return registry.descriptors()


class TestWhatIsPublished:
    def test_the_full_surface_publishes_every_tool(self) -> None:
        published = surface.published(described(), surface.FULL)

        assert len(published) == len(described())

    def test_the_router_surface_publishes_four(self) -> None:
        published = surface.published(described(), surface.ROUTER)

        assert [tool.name for tool in published] == [
            "salesforce_list_tools",
            "salesforce_tool_schema",
            surface.READ_DOOR,
            surface.WRITE_DOOR,
        ]

    def test_the_router_surface_costs_far_less_to_publish(self) -> None:
        """The whole reason it exists, asserted rather than assumed."""

        def size(tools: list[Tool]) -> int:
            return sum(
                len(tool.description or "") + len(json.dumps(tool.input_schema)) for tool in tools
            )

        assert size(surface.published(described(), surface.ROUTER)) * 4 < size(
            surface.published(described(), surface.FULL)
        )

    def test_each_door_declares_honestly_what_it_does(self) -> None:
        doors = {
            tool.name: tool
            for tool in surface.published(described(), surface.ROUTER)
            if tool.name in (surface.READ_DOOR, surface.WRITE_DOOR)
        }

        reading = doors[surface.READ_DOOR].annotations
        writing = doors[surface.WRITE_DOOR].annotations
        assert reading is not None
        assert writing is not None

        assert reading.read_only_hint is True
        assert reading.destructive_hint is False
        assert writing.read_only_hint is False
        assert writing.destructive_hint is True

    def test_a_door_tells_the_model_the_order_to_work_in(self) -> None:
        door = next(
            tool
            for tool in surface.published(described(), surface.ROUTER)
            if tool.name == surface.WRITE_DOOR
        )

        assert door.description is not None
        assert "salesforce_list_tools" in door.description
        assert "salesforce_tool_schema" in door.description


class TestWhatADoorResolvesTo:
    def test_a_tool_called_directly_resolves_to_itself(self) -> None:
        opened = surface.resolved(
            "salesforce_soql_query", {"soql": "SELECT Id FROM C"}, described()
        )

        assert opened.described is not None
        assert opened.described.tool_name == "salesforce_soql_query"
        assert opened.arguments == {"soql": "SELECT Id FROM C"}

    def test_a_door_hands_back_the_inner_tool_and_its_own_arguments(self) -> None:
        opened = surface.resolved(
            surface.READ_DOOR,
            {"tool_name": "salesforce_count_records", "arguments": {"objects": ["Contact"]}},
            described(),
        )

        assert opened.described is not None
        assert opened.described.tool_name == "salesforce_count_records"
        assert opened.arguments == {"objects": ["Contact"]}
        assert opened.refusal is None

    def test_the_read_door_refuses_a_write(self) -> None:
        """Otherwise read_only_hint would be a lie to a host that gates on it."""
        opened = surface.resolved(
            surface.READ_DOOR,
            {"tool_name": "salesforce_create_contact", "arguments": {"last_name": "X"}},
            described(),
        )

        assert opened.described is None
        assert opened.refusal is not None
        assert surface.WRITE_DOOR in opened.refusal

    def test_the_write_door_refuses_a_read(self) -> None:
        opened = surface.resolved(
            surface.WRITE_DOOR,
            {"tool_name": "salesforce_soql_query", "arguments": {}},
            described(),
        )

        assert opened.refusal is not None
        assert surface.READ_DOOR in opened.refusal

    def test_an_unknown_inner_tool_is_named_as_the_problem(self) -> None:
        opened = surface.resolved(
            surface.WRITE_DOOR, {"tool_name": "salesforce_delete_all", "arguments": {}}, described()
        )

        assert opened.refusal is not None
        assert "salesforce_delete_all" in opened.refusal

    def test_a_door_with_no_tool_name_says_where_to_find_one(self) -> None:
        opened = surface.resolved(surface.READ_DOOR, {"arguments": {}}, described())

        assert opened.refusal is not None
        assert "salesforce_list_tools" in opened.refusal

    def test_missing_arguments_become_an_empty_mapping_not_a_crash(self) -> None:
        """The inner model then reports what is missing, which is its job."""
        opened = surface.resolved(
            surface.READ_DOOR, {"tool_name": "salesforce_count_records"}, described()
        )

        assert opened.described is not None
        assert opened.arguments == {}


class TestTheDoorDecidesVisibilityNotPermission:
    @pytest.mark.parametrize(
        "tool_name",
        sorted(d.tool_name for d in registry.descriptors() if d.kind is ActionKind.WRITE),
    )
    def test_every_write_still_requires_approval_through_the_door(self, tool_name: str) -> None:
        opened = surface.resolved(
            surface.WRITE_DOOR, {"tool_name": tool_name, "arguments": {}}, described()
        )

        assert opened.described is not None
        assert opened.described.requires_approval is True

    def test_every_tool_remains_reachable_through_one_door_or_the_other(self) -> None:
        """A tool nothing can reach is a tool that has been removed by accident."""
        for one in described():
            door = surface.READ_DOOR if one.kind is ActionKind.READ else surface.WRITE_DOOR
            opened = surface.resolved(
                door, {"tool_name": one.tool_name, "arguments": {}}, described()
            )

            assert opened.refusal is None, f"{one.tool_name} unreachable"
            assert opened.described is not None
