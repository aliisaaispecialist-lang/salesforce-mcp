"""Every required field says what to do when its value is not available.

This is one specific failure, and it is worth its own file because it is
invisible from inside the connector. The canonical case: a `send_email` tool
with a required `recipient` field whose description says only what the field
is. Asked to fill it with no address in context, a model does not refuse. It
supplies the most semantically related string in scope, which is often the tool
description itself, and the mail bounces because "Required field: recipient
email address" is not an address.

Nothing catches that. The schema is satisfied -- a string was supplied. The
tool runs. The unit tests pass, because they call the function with a real
address. It surfaces as an occasional production oddity that looks like a model
failure and is a description failure.

So the rule enforced here is: for every required field, if the value cannot be
determined at call time, the description must say what to do instead. Four
answers are accepted, and the fourth is the interesting one:

  * ask the user,
  * call a named tool first,
  * do not call this tool at all,
  * send a best guess, *where the connector itself validates the value and
    returns the acceptable ones*.

The fourth is only honest when the validation actually exists. `stage_name` may
be guessed because `stages.py` reads the org's own picklist, refuses a value it
does not have, and puts the real list in the error. That is a better answer
than "call describe first", because it costs no round trip and cannot go stale.
It would be the worst answer of the four if the check were ever removed, which
is why the check has its own tests.

Two exemptions, both named rather than inferred. `idempotency_key` and
`approved` are supplied by the caller rather than found in a conversation, so
"what if it is unavailable" does not arise. And a field with an `enum` needs no
sentence, because the schema itself refuses an invented value before the call
is ever dispatched -- which is the stronger form of the same protection, and
the reason to prefer an enum wherever the value space is genuinely bounded.
"""

import re

import pytest

from salesforce_connector.actions.registry import BY_ID
from salesforce_connector.schemas.envelope import ActionSpec

SPECS: list[ActionSpec] = [action.spec for action in BY_ID.values()]

# Not found in a conversation, so the question does not apply to them.
SUPPLIED_BY_THE_CALLER = frozenset({"idempotency_key", "approved"})

# The four shapes an answer can take. Matching on phrasing is loose by nature,
# and loose is the right direction here: a false pass needs a sentence that
# already reads like guidance, and writing one of those by accident is hard.
ANSWERS_THE_QUESTION = re.compile(
    r"do not call|call salesforce_\w+|use salesforce_\w+|\bask\b|"  # ask, or call something first
    r"find (it|them) with|if you do not (know|have)|read it off|"  # where to get it
    r"never (guess|invent)|do not (guess|assume|invent)|"  # forbidden outright
    r"best guess|the error lists",  # guess, and be corrected
    re.IGNORECASE,
)

CASES = [
    (spec, field)
    for spec in SPECS
    for field in spec.input_schema.get("required", ())
    if field not in SUPPLIED_BY_THE_CALLER
]
NAMES = [f"{spec.tool_name}.{field}" for spec, field in CASES]


@pytest.mark.parametrize(("spec", "field"), CASES, ids=NAMES)
def test_it_says_what_to_do_when_the_value_is_unavailable(spec: ActionSpec, field: str) -> None:
    described = spec.input_schema.get("properties", {}).get(field, {})
    if "enum" in described:
        return  # the schema refuses an invented value; no sentence needed
    text = described.get("description", "")
    assert ANSWERS_THE_QUESTION.search(text), (
        f"{spec.tool_name}.{field} is required and does not say what to do when the "
        f"value cannot be determined. A model that must fill it and cannot will supply "
        f"the nearest string in context rather than refusing. Add one sentence: name a "
        f"tool to call first, tell it to ask the user, or forbid the call.\n"
        f"  current: {text[:200]}"
    )


@pytest.mark.parametrize("spec", SPECS, ids=[spec.tool_name for spec in SPECS])
def test_optional_fields_state_what_happens_when_they_are_absent(spec: ActionSpec) -> None:
    """The other half of the same rule, and the cheaper half to get right.

    An optional field is a promise that there is sensible behaviour without it.
    A model reading one that does not say what that behaviour is has to choose
    between supplying a value it invented and omitting it blindly, and it will
    sometimes choose the first.
    """
    properties = spec.input_schema.get("properties", {})
    required = set(spec.input_schema.get("required", ()))
    for field, described in properties.items():
        if field in required or field in SUPPLIED_BY_THE_CALLER:
            continue
        text = described.get("description", "")
        assert "optional" in text.lower(), (
            f"{spec.tool_name}.{field} is optional and its description never says so, "
            f"nor what happens when it is left out."
        )
