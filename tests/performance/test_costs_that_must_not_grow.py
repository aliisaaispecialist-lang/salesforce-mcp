"""Costs a caller pays whether or not Salesforce is slow, and how they scale.

None of this measures Salesforce. A connector cannot make a remote API faster
and should not pretend to. What it can do is add nothing measurable of its own,
and this tier exists to notice when it stops doing that.

Two kinds of assertion, and the difference matters more than the numbers.

**Shape**, wherever it is available: that a lookup does not get slower as the
ledger fills, that the budget admits the number of calls it was configured for
and not one more. These are the assertions worth having. They are exact, they
hold on any machine, and they fail for one reason only -- the behaviour changed.

**Size and time**, where nothing else will do. The connect cost is the clearest
example: it is a real number a user pays, in tokens, before saying anything, and
it can only be measured by measuring it. Its ceiling is deliberately loose. A
tight bound on a shared machine reports a regression that is not there, and a
tier that cries wolf gets deselected and then deleted.

This tier is excluded from the default run for that reason -- `pytest -m
performance`, on a machine that is not busy. A timing test that runs beside a
build is not a measurement, it is a coin toss with extra steps.
"""

import json
import time
from typing import Any

import pytest

from salesforce_connector.actions import registry
from salesforce_connector.errors.model import RateLimitError
from salesforce_connector.protocol import surface
from salesforce_connector.replay.ledger import IdempotencyLedger
from salesforce_connector.transport.ratelimit import CallBudget

pytestmark = pytest.mark.performance

DESCRIBED = registry.descriptors()

# The published catalogue, in tokens, is the number a user pays at connect
# before saying anything, so it is the one figure here with a business meaning.
# Roughly four characters to a token for English prose, which is close enough
# for a ceiling and needs no tokenizer dependency to compute.
CHARACTERS_PER_TOKEN = 4
CONNECT_CEILING_TOKENS = 40_000

# Loose on purpose. Observed is far below each of these; they are set to catch a
# change of order, not a change of weather.
RESOLVE_CEILING_MICROSECONDS = 200.0
LEDGER_CEILING_MICROSECONDS = 20.0

# Dispatch measured the way the server performs it, list fetch included. The
# observed figure is about 1us; the ceiling is set two orders of magnitude above
# that, because the failure worth catching is not drift but the return of the
# six-hundred-microsecond rebuild, and a tight bound here would only flake.
DISPATCH_CEILING_MICROSECONDS = 100.0


def _published_bytes() -> int:
    """The tool list serialised the way it travels to a client."""
    tools = [
        tool.model_dump(by_alias=True, exclude_none=True) for tool in surface.published(DESCRIBED)
    ]
    return len(json.dumps({"tools": tools}, separators=(",", ":")))


def _microseconds(call: Any, repeats: int) -> float:
    """Mean duration of one call, in microseconds.

    The best of three rounds rather than a single timing. A slower round means
    something else on the machine got the CPU, which is information about the
    machine and not about this code.
    """
    rounds = []
    for _ in range(3):
        started = time.perf_counter()
        for _ in range(repeats):
            call()
        rounds.append((time.perf_counter() - started) / repeats * 1_000_000)
    return min(rounds)


class TestWhatAConnectionCosts:
    """The tool list is read once per session and paid for in full.

    This is the cost the gateway exists to avoid, so it is worth watching from
    both ends: the number is what a direct client pays, and the reason Executor
    reduces it by two orders of magnitude is that it never sends this at all.
    """

    def test_the_catalogue_stays_within_its_token_budget(self) -> None:
        estimate = _published_bytes() // CHARACTERS_PER_TOKEN
        assert estimate < CONNECT_CEILING_TOKENS, (
            f"The published catalogue is about {estimate:,} tokens, past the "
            f"{CONNECT_CEILING_TOKENS:,} ceiling. Every client pays this at connect, "
            f"before the user has said anything."
        )

    def test_no_single_tool_dominates_the_catalogue(self) -> None:
        """One runaway description is the way this grows without anyone noticing.

        A total creeping up is visible. A total that is fine while one tool
        holds a third of it is not, and it is the more likely failure: a tool
        gains a paragraph each time it confuses somebody.
        """
        sizes = {
            tool.name: len(json.dumps(tool.model_dump(by_alias=True, exclude_none=True)))
            for tool in surface.published(DESCRIBED)
        }
        total = sum(sizes.values())
        worst, largest = max(sizes.items(), key=lambda pair: pair[1])
        assert largest / total < 0.25, (
            f"{worst} is {largest / total:.0%} of the whole catalogue on its own. "
            f"Either it is doing too much, or its description has grown past its usefulness."
        )


class TestTheCatalogueIsNotRebuiltPerCall:
    """Describing every action is expensive, and dispatch needs the list.

    `descriptors()` renders each action's whole description from scratch: both
    schemas in words, the worked example, every failure and its remedy. About
    seventy-one thousand characters across seventeen actions.

    Dispatch calls it, because resolving a name means finding that name in the
    list. So for a while every single tool call rebuilt all seventeen
    descriptions in order to look one of them up, at six hundred microseconds
    against the one microsecond the lookup itself costs. Nothing was wrong,
    nothing failed, and the connector did six hundred times more work than the
    task required.

    It is a pure function of things fixed at import time, so the fix is one
    `@cache`. These tests exist because removing that decorator breaks nothing
    visible: every test still passes, and the cost quietly comes back.
    """

    def test_describing_every_action_is_free_after_the_first_time(self) -> None:
        registry.descriptors()  # pay for it once, outside the measurement
        spent = _microseconds(registry.descriptors, repeats=20_000)
        assert spent < 5.0, (
            f"descriptors() costs {spent:.1f}us, so it is being rebuilt rather than "
            f"cached. Dispatch calls it on every tool call, which puts the whole cost "
            f"of rendering seventeen descriptions on the path of every request."
        )

    def test_the_same_tuple_comes_back_every_time(self) -> None:
        """Identity, not equality: equality would pass on a fresh rebuild.

        Everything in it is frozen, so sharing one tuple is safe, and sharing
        is the whole point. A test for equality would be satisfied by code that
        rebuilds an identical tuple every call, which is exactly the behaviour
        this is here to prevent.
        """
        assert registry.descriptors() is registry.descriptors()

    def test_dispatch_costs_about_what_the_lookup_costs(self) -> None:
        """The end to end check, and the one that would have caught the original.

        Measured the way the server does it, fetching the list and then
        resolving against it, rather than against a list a test kindly hoisted
        out of the loop.
        """
        spent = _microseconds(
            lambda: surface.resolved("salesforce_contact_create", {}, registry.descriptors()),
            repeats=20_000,
        )
        assert spent < DISPATCH_CEILING_MICROSECONDS, (
            f"A tool call spends {spent:.1f}us before reaching Salesforce. The lookup "
            f"itself is about a microsecond, so anything much above that is work being "
            f"redone on every request."
        )


class TestDispatchAddsNothingMeasurable:
    """Resolving a name happens on every call and must stay far below the network.

    A tool call spends hundreds of milliseconds waiting for Salesforce. Anything
    this connector adds is invisible until it is not, and the way it stops being
    invisible is somebody making the lookup linear in the number of tools.
    """

    def test_a_known_name_resolves_in_microseconds(self) -> None:
        spent = _microseconds(
            lambda: surface.resolved("salesforce_contact_create", {}, DESCRIBED), repeats=2_000
        )
        assert spent < RESOLVE_CEILING_MICROSECONDS, f"{spent:.1f}us to resolve a known tool name"

    def test_an_unknown_name_is_refused_without_costing_more_than_a_known_one(self) -> None:
        """The refusal path searches for a near miss, and that search is bounded.

        It compares the name against every published tool, so it is the one
        place where the cost genuinely does grow with the catalogue. Worth
        pinning: a model that has just mistyped a name is often about to mistype
        several, and a slow refusal is a slow loop.
        """
        spent = _microseconds(
            lambda: surface.resolved("salesforce_contact_delete", {}, DESCRIBED), repeats=1_000
        )
        assert spent < RESOLVE_CEILING_MICROSECONDS * 10, f"{spent:.1f}us to refuse an unknown name"


class TestTheLedgerDoesNotSlowDownAsItFills:
    """Every write consults the ledger, and a long session fills it.

    This is the assertion this tier is really for. A dict lookup is constant
    time and a list scan is not, and the change from one to the other is a small
    edit that no other test would notice -- it would still be correct, just
    quadratic over a session, and only in production.
    """

    def test_a_lookup_costs_the_same_at_ten_thousand_keys_as_at_ten(self) -> None:
        ledger = IdempotencyLedger()
        for index in range(10):
            ledger.complete(f"key-{index}", {"id": "003xx000004TmiQAAS"})
        when_small = _microseconds(lambda: ledger.find("key-5"), repeats=20_000)

        for index in range(10, 10_000):
            ledger.complete(f"key-{index}", {"id": "003xx000004TmiQAAS"})
        when_large = _microseconds(lambda: ledger.find("key-5"), repeats=20_000)

        assert when_large < when_small * 3 + 1, (
            f"A ledger lookup went from {when_small:.2f}us at 10 keys to "
            f"{when_large:.2f}us at 10,000. That is a scan, not a lookup, and a "
            f"long session will feel it on every single write."
        )

    def test_recording_a_result_stays_cheap(self) -> None:
        ledger = IdempotencyLedger()
        counter = iter(range(200_000))
        spent = _microseconds(
            lambda: ledger.complete(f"key-{next(counter)}", {"id": "003xx000004TmiQAAS"}),
            repeats=5_000,
        )
        assert spent < LEDGER_CEILING_MICROSECONDS * 20, f"{spent:.1f}us to record one outcome"


class TestTheBudgetSpendsExactlyWhatItWasGiven:
    """The rate limit is a promise to the org, and an exact one.

    Counted rather than timed. How long the calls take is the machine's
    business; how many are admitted is the connector's, and that number is
    checkable to the call.
    """

    @pytest.mark.asyncio
    async def test_it_admits_the_configured_number_and_refuses_the_next(self) -> None:
        allowed = 20
        budget = CallBudget(calls_per_minute=allowed)
        for _ in range(allowed):
            await budget.claim("salesforce_contact_search_by_text")
        with pytest.raises(RateLimitError):
            await budget.claim("salesforce_contact_search_by_text")

    @pytest.mark.asyncio
    async def test_the_refusal_says_how_long_to_wait(self) -> None:
        """A refusal without a wait is a dead end, and a retry loop follows it.

        Checked here rather than only in the error tests because the number
        comes from the configured rate: it is the one part of the refusal that
        goes wrong when somebody changes the limit.
        """
        budget = CallBudget(calls_per_minute=30)
        for _ in range(30):
            await budget.claim("salesforce_contact_create")
        with pytest.raises(RateLimitError) as refused:
            await budget.claim("salesforce_contact_create")
        assert refused.value.context.retry_after_seconds == pytest.approx(2.0)
