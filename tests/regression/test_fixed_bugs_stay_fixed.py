"""One test per bug that was found the expensive way, so it cannot return quietly.

A regression test is not a second unit test. A unit test states what a function
is for; the tests here state what a particular mistake looked like, so that if
somebody makes it again the failure names the original incident instead of
leaving them to rediscover it.

Everything in this file was a real fault, and each one shared the property that
made it costly: **the suite stayed green while it was present.** That is the
admission criterion. A bug that broke a test when it was introduced needs no
pin here, because the test that broke is already the pin.

The last section is different and is marked as expected to fail. Those are
faults that have been found and not yet fixed, because the fix is a wording
change awaiting a decision. Writing them now means the decision is recorded as
an executable statement rather than a note, and the marker is strict on
purpose: the moment the wording is corrected these tests pass unexpectedly and
pytest complains until the marker is deleted. A pin for a fixed bug and a pin
for an open one should not be able to look alike.
"""

import importlib.util
import sys
from inspect import signature
from pathlib import Path
from types import ModuleType

import jsonschema
import pytest

from salesforce_connector.actions.registry import BY_ID
from tests.contract.test_schemas_are_truthful import _validator

pytestmark = pytest.mark.regression

ROOT = Path(__file__).resolve().parents[2]
BY_NAME = {action.spec.tool_name: action.spec for action in BY_ID.values()}


def _eval_module(name: str) -> ModuleType:
    """Import a module from `evals/`, which is scripts rather than a package.

    They are deliberately not importable as a package: they are run, not
    depended on. That is fine for their purpose and inconvenient here, so they
    are loaded by path rather than by making the eval directory into something
    it is not.
    """
    path = ROOT / "evals" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"evals_{name}", path)
    assert spec is not None, f"{path} is not importable"
    assert spec.loader is not None, f"{path} has no loader"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestTheEvalHarnessDoesNotMeasureItself:
    """The scoring run once reported 37.7%, and the connector was not at fault.

    Two settings did it, and each hid the other. `plan` mode forbids a write
    tool call outright, so nine tools could not be chosen however well they
    were described. And the scorer read the *first* tool call rather than the
    chosen one, which punished the model for searching before creating -- the
    exact behaviour this connector's instructions demand.

    With recon happening, both modes produced identical numbers, so the mode
    looked irrelevant and was cleared of suspicion. It was not irrelevant. Only
    after the recon was suppressed did the difference appear, and the score
    went to 69.6% without a line of the connector changing.

    A wrong measurement is worse than no measurement: it was believed for a
    whole session and sent the search for the fault into the wrong repository.
    """

    def test_the_default_mode_permits_a_write_to_be_chosen(self) -> None:
        """Nothing may default to a mode that can only ever score reads."""
        default = signature(_eval_module("via_cli").chosen).parameters["mode"].default
        assert default != "plan", (
            "The harness is back in plan mode, where a write tool cannot be called "
            "at all. Every write will score zero and the connector will be blamed."
        )

    def test_the_model_is_told_to_answer_in_one_call(self) -> None:
        """The instruction that suppresses recon is still sent.

        Without it the model reads or searches first, entirely correctly, and
        the scorer records that read as its answer.
        """
        one_shot = _eval_module("via_cli").ONE_SHOT
        assert "exactly one tool" in one_shot
        assert "search" in one_shot, (
            "The instruction no longer names the recon behaviour it exists to "
            "suppress, which is the whole reason the first scores were wrong."
        )


class TestTheCaseSetStaysAnswerable:
    """Eleven 'wrong tool' misses were prompts that could not be answered at all.

    They omitted a value the schema requires. The model declined to invent one,
    which is correct, and the eval counted the refusal as a bad choice. Nothing
    detected it, because a prompt is data: it is never validated against the
    tool it names.

    The generator now checks itself, and this pins that the check is still
    honest -- a required field added to any action makes the affected prompts
    fail here rather than silently depress the next score.
    """

    def test_every_prompt_carries_what_its_tool_requires(self) -> None:
        complaints = _eval_module("build_happy_path").verify()
        assert not complaints, (
            "The happy-path set no longer matches the schemas:\n  " + "\n  ".join(complaints)
        )


class TestFormatIsActuallyChecked:
    """A published example showed `30/09/2026` for a `format: date` field, and passed.

    JSON Schema treats `format` as an annotation unless a checker is switched
    on, so the validator read the keyword and enforced nothing. The example was
    wrong in the most-read line of the description, the connector itself would
    have rejected it, and the test written specifically to catch that could not
    see it.

    It was found by mutation rather than by reading, which is why it is pinned:
    the fix is one argument, and removing that argument breaks nothing visible.
    """

    def test_a_date_in_the_wrong_shape_is_rejected(self) -> None:
        validate = jsonschema.Draft202012Validator(
            {"type": "string", "format": "date"},
            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
        )
        assert list(validate.iter_errors("30/09/2026")), (
            "A European-style date passed a `format: date` check, which means "
            "the format checker is off and every date example is unverified."
        )

    def test_the_truthfulness_suite_builds_validators_that_check_format(self) -> None:
        """The suite's own validator, not a fresh one, is the thing that matters."""
        assert list(_validator({"type": "string", "format": "date"}).iter_errors("30/09/2026")), (
            "The contract suite builds validators without a format checker again."
        )


class TestDescriptionsMatchTheEndpointTheyCall:
    """Two descriptions contradict Salesforce's own documentation.

    Found by reading each tool against the endpoint it calls, which is the only
    way either could have been found: both descriptions are internally
    consistent, pass every schema check, and are wrong about Salesforce.

    Both are now fixed, and these tests were written before the fix rather than
    after it. They spent a while marked expected-to-fail, strictly, so that
    correcting the wording made pytest refuse the marker and demand it be
    deleted. That is the useful shape for a defect found before it can be
    fixed: an executable statement of what "fixed" means, which turns red the
    moment somebody words it back the old way.

    A third suspect was dropped after being written. `record_count_by_object`
    looked as though it presented a cached figure as fact, because the summary
    line says only that it reports how many records exist -- but its `counts`
    field already says "these counts are cached and approximate, not live",
    which is in the same description and which a model reads. The test passed,
    which is the answer. It is recorded here rather than deleted silently,
    because an audit finding that turns out to be wrong is worth exactly as
    much as one that turns out to be right, and only if it is written down.
    """

    def test_the_two_search_tools_agree_about_partial_words(self) -> None:
        """One says a partial word matches. Salesforce says it does not.

        `salesforce_record_search_by_text` promises "a partial word finds
        records containing it". SOSL tokenises, and the FIND documentation is
        explicit that an asterisk matches "at the middle or end" of a term --
        there is no leading wildcard. Our own contact search gets this right
        and says a partial word may not match.

        The cost is not a confusing sentence. A model that believes it searches
        "Contos", finds nothing, concludes the account does not exist, and
        creates a duplicate. Creating a duplicate is the single most expensive
        thing this connector can do, and its instructions say so.
        """
        query = BY_NAME["salesforce_record_search_by_text"].input_schema["properties"]["query"]
        assert "a partial word finds records containing it" not in query["description"]

    def test_the_missing_record_remedy_allows_for_an_unset_lookup(self) -> None:
        """A contact with no account produces the same 404 as a bad id.

        Salesforce: "If there's no record associated with a relationship field,
        a 404 error response is returned." So an id that is right and a
        relationship name that is right can still answer 404, whenever the
        lookup field is simply not set.

        The remedy does not allow for it. It says: "If the id is right, the
        relationship name is wrong." A model following that calls describe,
        finds the relationship listed exactly as it sent it, and has been left
        with no next step and no way to report what actually happened.

        The tool is not wrong everywhere about this -- its `records` field
        explains that an empty collection means the relationship exists with
        nothing attached. That covers a child collection. This is the other
        case, an unset lookup, which does not return empty; it returns 404.
        """
        described = BY_NAME["salesforce_record_get_related_by_id"].description()
        remedy = described.split("salesforce.record_not_found", 1)[1].split("  - ", 1)[0]
        assert "If the id is right, the relationship name is wrong" not in remedy, (
            "The 404 remedy still offers only two causes, so an unset lookup field "
            "sends the model to describe the object and leaves it stuck there."
        )
