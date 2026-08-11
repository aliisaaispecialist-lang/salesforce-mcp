"""Check that every description tells the truth about its own schema.

The other tests here ask whether an action behaves correctly. This one asks a
different and narrower question: does what we *say* about an action match what
we would actually accept and return?

It matters because a model reads nothing but the description. A worked example
is the strongest signal in it -- stronger than the schema, because it is
concrete -- so an example that would be rejected by its own validator is worse
than no example at all. It does not merely fail to help; it teaches a wrong
call, confidently, to every model that reads it. And nothing else in this
repository would notice, because an example is data: it is never executed, so
no unit test exercises it and no type checker looks inside it.

Deterministic and free. Every check here is a validator run against a literal,
which is why this is a test rather than part of the eval suite: an LLM is not
needed to find out whether a document contradicts itself.
"""

from typing import Any

import jsonschema
import pytest
from jsonschema.protocols import Validator

from salesforce_connector.actions.registry import BY_ID
from salesforce_connector.contract import ActionKind
from salesforce_connector.schemas.envelope import ActionSpec

SPECS: list[ActionSpec] = [action.spec for action in BY_ID.values()]
NAMES: list[str] = [spec.tool_name for spec in SPECS]


def _validator(schema: Any) -> Validator:
    """Build a validator for one of our schemas, in the dialect MCP assumes.

    MCP takes an absent `$schema` to mean 2020-12, which is the dialect pydantic
    emits, so the validator is chosen explicitly here rather than inferred. A
    validator picked by inference would silently fall back to an older draft and
    stop enforcing the keywords the schemas actually use.

    The format checker is switched on deliberately. `format` is annotation-only
    by default, so a validator without it reads `"format": "date"` and then
    accepts `30/09/2026` -- which was exactly the hole a mutation run found in
    the first version of this file: an example with a European-style date
    passed, while the connector itself would have rejected it. A check that
    only catches the errors nobody makes is not a check.
    """
    return jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    )


@pytest.mark.parametrize("spec", SPECS, ids=NAMES)
def test_schemas_are_valid_json_schema(spec: ActionSpec) -> None:
    """Both schemas are themselves well formed, before anything is checked against them.

    A malformed schema does not fail loudly. It is published to the client,
    which either ignores the parts it cannot parse or rejects the tool outright,
    and either way the connector looks like it works right up until it does not.
    """
    jsonschema.Draft202012Validator.check_schema(spec.input_schema)
    jsonschema.Draft202012Validator.check_schema(spec.output_schema)


@pytest.mark.parametrize("spec", SPECS, ids=NAMES)
def test_example_arguments_would_be_accepted(spec: ActionSpec) -> None:
    """The call shown in the description is a call this action would accept.

    This is the check with the most to catch. The arguments are hand written,
    they sit in the most-read line of the description, and a rename or a new
    required field leaves them stale without breaking anything that runs.
    """
    validate = _validator(spec.input_schema)
    for example in spec.examples:
        errors = sorted(validate.iter_errors(dict(example.arguments)), key=str)
        assert not errors, (
            f"{spec.tool_name} shows an example call its own input schema rejects.\n"
            f"  example: {example.title}\n"
            f"  problem: {errors[0].message}\n"
            f"  at:      {'/'.join(str(part) for part in errors[0].absolute_path) or '(top level)'}"
        )


@pytest.mark.parametrize("spec", SPECS, ids=NAMES)
def test_example_results_match_the_output_schema(spec: ActionSpec) -> None:
    """The answer shown in the description is an answer this action could return.

    A wrong result shape is quieter than a wrong argument list and lasts longer.
    The call succeeds, so nothing errors; the model simply reads a field that
    was never going to be there, and plans its next step around it.
    """
    validate = _validator(spec.output_schema)
    for example in spec.examples:
        errors = sorted(validate.iter_errors(dict(example.result)), key=str)
        assert not errors, (
            f"{spec.tool_name} shows a result its own output schema rejects.\n"
            f"  example: {example.title}\n"
            f"  problem: {errors[0].message}\n"
            f"  at:      {'/'.join(str(part) for part in errors[0].absolute_path) or '(top level)'}"
        )


@pytest.mark.parametrize("spec", SPECS, ids=NAMES)
def test_every_action_shows_a_worked_call(spec: ActionSpec) -> None:
    """No action is published without one example.

    A schema states what is permitted; an example states what is meant. For the
    mistakes a schema cannot prevent -- a date in the wrong shape, an id from
    the wrong object, an amount sent as a word -- the example is the only
    correction available, and it costs a handful of tokens in the one place a
    model is certain to look.
    """
    assert spec.examples, f"{spec.tool_name} publishes no worked example."


@pytest.mark.parametrize("spec", SPECS, ids=NAMES)
def test_references_stay_inside_the_document(spec: ActionSpec) -> None:
    """No `$ref` points anywhere a client would have to fetch.

    The specification forbids resolving a reference over the network, so a
    schema that needs one is a schema no conforming client can fully read.
    """
    for schema, which in ((spec.input_schema, "input"), (spec.output_schema, "output")):
        for reference in _references(schema):
            assert reference.startswith("#/"), (
                f"{spec.tool_name}'s {which} schema refers to {reference!r}, which is "
                f"outside the document. A client is not permitted to fetch it."
            )


@pytest.mark.parametrize("spec", SPECS, ids=NAMES)
def test_stated_needs_match_the_validator(spec: ActionSpec) -> None:
    """The "You need:" line agrees with what the schema actually requires.

    That line is what a model reads while *choosing*, before it reads the
    schema: do I have what this needs, or must I find something first? If it
    understates the requirement the call is attempted and fails; if it
    overstates it, a usable tool is passed over.
    """
    required = tuple(spec.input_schema.get("required", ()))
    stated = spec.description().split("You need: ", 1)[1].split("\n", 1)[0]
    for field in required:
        assert field in stated, (
            f"{spec.tool_name} requires {field!r} but does not say so in 'You need:'."
        )


@pytest.mark.parametrize("spec", SPECS, ids=NAMES)
def test_every_write_says_how_to_undo_it_by_hand(spec: ActionSpec) -> None:
    """A write that changes state carries a manual recovery procedure.

    This connector has no rollback tools and should not pretend otherwise: it
    cannot un-create a contact. What it can do is say, at the moment a write
    has failed beyond retrying, what a person now has to go and do. Reads carry
    nothing, because there is nothing to recover from a failed search.
    """
    if spec.kind is ActionKind.READ:
        return
    assert spec.manual_recovery, (
        f"{spec.tool_name} changes state but documents no manual recovery. "
        f"There are no rollback tools here, so this is the only recourse a "
        f"person has when it fails."
    )


def _references(node: Any) -> list[str]:
    """Every `$ref` anywhere in a schema, however deeply nested."""
    if isinstance(node, dict):
        found = [node["$ref"]] if isinstance(node.get("$ref"), str) else []
        return found + [one for value in node.values() for one in _references(value)]
    if isinstance(node, list):
        return [one for value in node for one in _references(value)]
    return []
