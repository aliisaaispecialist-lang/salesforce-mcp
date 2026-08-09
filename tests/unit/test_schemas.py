"""The contract each action offers a model.

Names must not be confusable, every write must demand an idempotency key, every
required field must have a question to ask when its value is unknown, and every
failure must carry a remedy. These are the properties that decide whether a
model uses the tools correctly, so they are asserted rather than reviewed.
"""

import re

import pytest
from pydantic import ValidationError

from salesforce_connector.actions import registry
from salesforce_connector.contract import ActionKind
from salesforce_connector.errors import model
from salesforce_connector.schemas import (
    add_activity_note,
    create_contact,
    create_opportunity,
    search_contact,
    update_contact,
)
from salesforce_connector.schemas.envelope import ActionSpec

ALL_SPECS: tuple[ActionSpec, ...] = tuple(action.spec for action in registry.BY_ID.values())
"""Every spec, derived rather than listed.

It used to be a hand-written tuple of the original five, which meant every
rule in this file was checked against five tools out of seventeen and passed
by not looking. Two specs documenting an error code nothing raises sat in the
repository under a test written to catch exactly that."""

WRITES = tuple(spec for spec in ALL_SPECS if spec.kind is ActionKind.WRITE)


def _raiseable_codes() -> frozenset[str]:
    """Every code an error class in this connector can actually carry."""
    return frozenset(
        found.code
        for found in vars(model).values()
        if isinstance(found, type) and issubclass(found, model.ConnectorError)
    )


RAISEABLE = _raiseable_codes()


class TestNamesCannotBeConfused:
    def test_the_five_assigned_actions_are_all_still_published(self) -> None:
        """The competition named five. Everything since is in addition to them."""
        assert {spec.action_id for spec in ALL_SPECS} >= {
            "salesforce.search_contact",
            "salesforce.create_contact",
            "salesforce.update_contact",
            "salesforce.create_opportunity",
            "salesforce.add_activity_note",
        }

    def test_every_tool_name_is_unique(self) -> None:
        names = [spec.tool_name for spec in ALL_SPECS]

        assert len(set(names)) == len(names)

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.tool_name)
    def test_every_tool_name_survives_the_provider_constraint(self, spec: ActionSpec) -> None:
        # MCP would permit the dot; Anthropic and OpenAI function names do not.
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", spec.tool_name)

    def test_every_tool_name_is_prefixed_so_it_cannot_clash_with_another_server(self) -> None:
        assert all(spec.tool_name.startswith("salesforce_") for spec in ALL_SPECS)


class TestDescriptionsHelpAModelChoose:
    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.tool_name)
    def test_a_description_says_when_to_use_and_when_not_to(self, spec: ActionSpec) -> None:
        rendered = spec.description()

        assert "Use this when:" in rendered
        assert "Do not use this when:" in rendered

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.tool_name)
    def test_a_description_does_not_merely_restate_the_name(self, spec: ActionSpec) -> None:
        assert len(spec.summary.split()) >= 12

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.tool_name)
    def test_every_failure_is_listed_with_its_remedy(self, spec: ActionSpec) -> None:
        rendered = spec.description()

        assert spec.errors
        for error in spec.errors:
            assert error.code in rendered
            assert error.remedy.strip()


class TestWritesCannotBeRepeatedByAccident:
    @pytest.mark.parametrize("spec", WRITES, ids=lambda s: s.tool_name)
    def test_a_write_requires_an_idempotency_key(self, spec: ActionSpec) -> None:
        assert "idempotency_key" in spec.input_schema["required"]

    @pytest.mark.parametrize("spec", WRITES, ids=lambda s: s.tool_name)
    def test_a_write_asks_for_approval(self, spec: ActionSpec) -> None:
        assert spec.requires_approval is True

    def test_the_only_read_needs_no_key_and_no_approval(self) -> None:
        assert "idempotency_key" not in search_contact.SPEC.input_schema.get("required", [])
        assert search_contact.SPEC.requires_approval is False

    @pytest.mark.parametrize("spec", WRITES, ids=lambda s: s.tool_name)
    def test_every_write_tells_the_model_to_reuse_the_key_on_retry(self, spec: ActionSpec) -> None:
        transport = next(e for e in spec.errors if e.code == "salesforce.transport_failed")

        assert "identical idempotency key" in transport.remedy


class TestMissingValuesHaveAQuestion:
    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.tool_name)
    def test_every_required_field_except_the_key_can_be_asked_for(self, spec: ActionSpec) -> None:
        required = set(spec.input_schema["required"]) - {"idempotency_key"}

        askable = {entry.field for entry in spec.missing_inputs}

        assert required <= askable, f"{spec.tool_name} cannot ask for {required - askable}"

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.tool_name)
    def test_each_question_actually_asks_something(self, spec: ActionSpec) -> None:
        assert all("?" in entry.prompt for entry in spec.missing_inputs)

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.tool_name)
    def test_a_question_uses_only_types_elicitation_permits(self, spec: ActionSpec) -> None:
        assert all(
            entry.json_type in {"string", "number", "integer", "boolean"}
            for entry in spec.missing_inputs
        )

    def test_a_field_with_a_fixed_set_of_answers_offers_them(self) -> None:
        kind = add_activity_note.SPEC.find_missing_input("activity_kind")

        assert kind is not None
        assert kind.choices == ("Call", "Email", "Meeting", "Other")

    def test_a_field_nobody_knows_how_to_ask_for_returns_nothing(self) -> None:
        assert search_contact.SPEC.find_missing_input("nonexistent") is None


class TestInputValidation:
    def test_a_search_shorter_than_two_characters_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            search_contact.SearchContactInput(query="a")

    def test_an_unknown_field_is_refused_rather_than_ignored(self) -> None:
        with pytest.raises(ValidationError):
            search_contact.SearchContactInput(query="Ada", nonsense=1)  # type: ignore[call-arg]

    def test_a_malformed_email_never_reaches_salesforce(self) -> None:
        with pytest.raises(ValidationError):
            create_contact.CreateContactInput(
                last_name="Lovelace", idempotency_key="key-12345", email="not-an-email"
            )

    def test_an_update_that_changes_nothing_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="at least one field"):
            update_contact.UpdateContactInput(
                contact_id="003xx000004TmiQ", idempotency_key="key-12345"
            )

    def test_an_update_naming_one_field_is_accepted(self) -> None:
        parsed = update_contact.UpdateContactInput(
            contact_id="003xx000004TmiQ", idempotency_key="key-12345", title="CTO"
        )

        assert parsed.title == "CTO"

    def test_a_page_larger_than_the_ceiling_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            search_contact.SearchContactInput(query="Ada", limit=5000)

    def test_a_negative_deal_amount_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            create_opportunity.CreateOpportunityInput(
                name="Renewal",
                stage_name="Prospecting",
                close_date="2026-12-01",  # type: ignore[arg-type]
                idempotency_key="key-12345",
                amount=-1,
            )


class TestSchemasAreUsableByTheProtocol:
    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.tool_name)
    def test_the_input_schema_is_an_object_schema(self, spec: ActionSpec) -> None:
        assert spec.input_schema["type"] == "object"
        assert "properties" in spec.input_schema

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.tool_name)
    def test_an_output_schema_is_declared(self, spec: ActionSpec) -> None:
        assert spec.output_schema["type"] == "object"

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.tool_name)
    def test_no_schema_points_at_a_network_reference(self, spec: ActionSpec) -> None:
        rendered = str(spec.input_schema) + str(spec.output_schema)

        assert "http://" not in rendered
        assert "https://" not in rendered

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.tool_name)
    def test_every_property_explains_itself(self, spec: ActionSpec) -> None:
        properties = spec.input_schema["properties"]

        undocumented = [name for name, field in properties.items() if not field.get("description")]

        assert not undocumented, f"{spec.tool_name}: {undocumented} have no description"

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.tool_name)
    def test_every_optional_field_says_it_is_optional(self, spec: ActionSpec) -> None:
        required = set(spec.input_schema.get("required", []))
        properties = spec.input_schema["properties"]

        silent = [
            name
            for name, field in properties.items()
            if name not in required and "ptional" not in field.get("description", "")
        ]

        assert not silent, f"{spec.tool_name}: {silent} do not say they are optional"

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.tool_name)
    def test_every_documented_error_is_one_the_connector_can_raise(self, spec: ActionSpec) -> None:
        """A remedy for a code nothing emits is a remedy nobody ever reads.

        Four specs documented `salesforce.invalid_input`, which no error class
        carries; the real code for a rejected field is `connector.invalid_input`.
        A model matching on the code would have found no guidance at exactly the
        moment the guidance existed for.
        """
        invented = [error.code for error in spec.errors if error.code not in RAISEABLE]

        assert not invented, f"{spec.tool_name} documents codes nothing raises: {invented}"
