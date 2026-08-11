"""What a client is shown, and what it is refused.

This file used to test a router of this connector's own: two doors, a surface
switch, and the rule that a door decided visibility and never permission. That
router is gone. Executor sits in front now and does the routing for every
integration on the machine at once, so a second one here would only mean
generated code opening a door for no reason.

What remains is the half a gateway cannot do for us. Executor can decide which
of our tools an agent may reach; it cannot answer for a tool that does not
exist anywhere, because it does not know what this connector is for. That
answer is here.
"""

from salesforce_connector.actions import registry
from salesforce_connector.contract import ActionDescriptor, ActionKind
from salesforce_connector.protocol import surface


def described() -> tuple[ActionDescriptor, ...]:
    return registry.descriptors()


class TestWhatIsPublished:
    def test_every_tool_is_published_to_every_client(self) -> None:
        published = surface.published(described())

        assert len(published) == len(described())
        assert [tool.name for tool in published] == [one.tool_name for one in described()]

    def test_each_one_carries_both_schemas(self) -> None:
        for tool in surface.published(described()):
            assert tool.input_schema["type"] == "object"
            assert tool.output_schema is not None

    def test_the_annotations_say_honestly_what_each_one_does(self) -> None:
        by_name = {tool.name: tool for tool in surface.published(described())}

        for one in described():
            hints = by_name[one.tool_name].annotations
            assert hints is not None
            assert hints.read_only_hint is (one.kind is ActionKind.READ)
            assert hints.destructive_hint is (one.kind is ActionKind.WRITE)


class TestSomethingTheConnectorCannotDo:
    """The case that actually happens: a user asks for what is not here."""

    def test_the_refusal_says_it_is_outside_this_connector(self) -> None:
        said = surface.unavailable("salesforce_send_email", described())

        assert "is not something this connector can do" in said

    def test_it_lists_what_does_exist_split_by_kind(self) -> None:
        said = surface.unavailable("salesforce_send_email", described())

        assert "Reads:" in said
        assert "Writes:" in said
        assert "salesforce_search_contact" in said
        assert "salesforce_create_contact" in said

    def test_it_forbids_reaching_for_the_nearest_tool_instead(self) -> None:
        """Refused a delete, a model will otherwise blank fields with an update."""
        said = surface.unavailable("salesforce_delete_contact", described())

        assert "Do not substitute a different tool" in said
        assert "tell the user this connector cannot do it" in said

    def test_a_near_miss_is_named_because_it_usually_is_one(self) -> None:
        said = surface.unavailable("salesforce_create_contacts", described())

        assert "Did you mean salesforce_create_contact?" in said

    def test_a_wholly_invented_name_gets_no_guess(self) -> None:
        said = surface.unavailable("salesforce_send_email", described())

        assert "Did you mean" not in said

    def test_a_delete_is_never_answered_with_the_update_that_looks_like_it(self) -> None:
        """One word apart in text, and opposite in consequence.

        A plain closest match answers "delete this contact" by proposing the
        tool that overwrites one, in the same message that forbids exactly
        that substitution.
        """
        said = surface.unavailable("salesforce_delete_contact", described())

        assert "Did you mean" not in said
        assert "salesforce_update_contact" in said  # listed, not recommended

    def test_a_call_to_a_name_that_does_not_exist_resolves_to_nothing(self) -> None:
        opened = surface.resolved("salesforce_drop_database", {}, described())

        assert opened.described is None
        assert opened.refusal is not None
        assert "is not something this connector can do" in opened.refusal
        assert opened.code == "connector.unknown_tool"

    def test_a_real_name_resolves_with_its_arguments_untouched(self) -> None:
        opened = surface.resolved("salesforce_get_record", {"object_name": "Contact"}, described())

        assert opened.described is not None
        assert opened.described.tool_name == "salesforce_get_record"
        assert opened.arguments == {"object_name": "Contact"}
        assert opened.refusal is None


class TestNamesAreAClosedSetInTheSchema:
    """A string field invites invention; an enum states the whole set."""

    def test_the_schema_guide_can_only_name_a_tool_that_exists(self) -> None:
        guide = next(
            tool
            for tool in surface.published(described())
            if tool.name == surface.TOOL_SCHEMA_GUIDE
        )

        assert set(guide.input_schema["properties"]["tool_name"]["enum"]) == {
            one.tool_name for one in described()
        }

    def test_the_kind_argument_is_an_enum_rather_than_a_regex(self) -> None:
        guide = next(
            tool for tool in surface.published(described()) if tool.name == "salesforce_list_tools"
        )

        assert guide.input_schema["properties"]["kind"]["enum"] == ["read", "write", "all"]

    def test_no_other_tool_is_rewritten_on_the_way_out(self) -> None:
        """Only the guide's name field is closed; every other schema is as authored."""
        published = {tool.name: tool for tool in surface.published(described())}

        for one in described():
            if one.tool_name == surface.TOOL_SCHEMA_GUIDE:
                continue
            assert published[one.tool_name].input_schema == dict(one.input_schema) | {
                key: value
                for key, value in published[one.tool_name].input_schema.items()
                if key == "examples"
            }
