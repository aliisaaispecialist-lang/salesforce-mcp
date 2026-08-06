"""When a failed call earns another attempt, and how long it waits first.

The rule that matters most is the last one: a write with no idempotency key is
never retried, because the first attempt may already have created the record.
"""

from random import Random

import pytest

from salesforce_connector.errors.model import (
    ConnectorError,
    ErrorContext,
    InvalidInputError,
    PermissionDeniedError,
    RateLimitError,
    TransportError,
)
from salesforce_connector.errors.retry import (
    DEFAULT_POLICY,
    RetryContext,
    RetryDecision,
    RetryPolicy,
    decide,
    jittered,
)


def read_attempt(number: int = 1, elapsed: float = 0.0) -> RetryContext:
    return RetryContext(attempt=number, elapsed_seconds=elapsed)


def write_attempt(*, keyed: bool, number: int = 1) -> RetryContext:
    return RetryContext(attempt=number, is_write=True, has_idempotency_key=keyed)


class TestOnlyTransientFailuresAreRetried:
    @pytest.mark.parametrize(
        "error",
        [
            InvalidInputError("the email address is malformed"),
            PermissionDeniedError("the profile lacks Create on Contact"),
        ],
    )
    def test_a_failure_that_would_repeat_identically_is_not_retried(
        self, error: ConnectorError
    ) -> None:
        decision = decide(error, read_attempt())

        assert decision.should_retry is False
        assert "not transient" in decision.reason

    def test_a_transient_failure_is_retried(self) -> None:
        assert decide(TransportError("connection reset"), read_attempt()).should_retry is True


class TestWritesWithoutAKeyAreNeverRetried:
    def test_an_unkeyed_write_is_refused_even_though_the_failure_is_transient(self) -> None:
        decision = decide(TransportError("timed out"), write_attempt(keyed=False))

        assert decision.should_retry is False
        assert "idempotency key" in decision.reason

    def test_a_keyed_write_is_retried(self) -> None:
        assert decide(TransportError("timed out"), write_attempt(keyed=True)).should_retry is True

    def test_the_refusal_outranks_the_attempt_count(self) -> None:
        decision = decide(TransportError("timed out"), write_attempt(keyed=False, number=1))

        assert "idempotency key" in decision.reason


class TestBackoff:
    @pytest.mark.parametrize(("attempt", "expected"), [(1, 1.0), (2, 2.0), (3, 4.0), (4, 8.0)])
    def test_the_wait_doubles_each_attempt(self, attempt: int, expected: float) -> None:
        policy = RetryPolicy(max_attempts=99)

        assert decide(TransportError("x"), read_attempt(attempt), policy).delay_seconds == expected

    def test_the_wait_stops_growing_at_the_ceiling(self) -> None:
        policy = RetryPolicy(max_attempts=99, max_delay_seconds=10.0)

        decision = decide(TransportError("x"), read_attempt(20), policy)

        assert decision.delay_seconds == 10.0

    def test_the_provider_instruction_wins_when_it_asks_for_longer(self) -> None:
        error = RateLimitError("quota spent", ErrorContext(retry_after_seconds=30.0))

        decision = decide(error, read_attempt(1))

        assert decision.delay_seconds == 30.0
        assert decision.min_delay_seconds == 30.0

    def test_our_backoff_wins_when_the_provider_asks_for_less(self) -> None:
        error = RateLimitError("quota spent", ErrorContext(retry_after_seconds=0.5))

        assert decide(error, read_attempt(2)).delay_seconds == 2.0


class TestLimits:
    def test_retrying_stops_at_the_attempt_limit(self) -> None:
        decision = decide(TransportError("x"), read_attempt(DEFAULT_POLICY.max_attempts))

        assert decision.should_retry is False
        assert "attempt limit" in decision.reason

    def test_a_wait_that_would_overrun_the_budget_is_refused(self) -> None:
        policy = RetryPolicy(max_attempts=99, total_budget_seconds=10.0)

        decision = decide(TransportError("x"), read_attempt(3, elapsed=9.0), policy)

        assert decision.should_retry is False
        assert "budget" in decision.reason

    def test_every_decision_explains_itself(self) -> None:
        decisions = [
            decide(InvalidInputError("x"), read_attempt()),
            decide(TransportError("x"), write_attempt(keyed=False)),
            decide(TransportError("x"), read_attempt(3)),
            decide(TransportError("x"), read_attempt(1)),
        ]

        assert all(d.reason.strip() for d in decisions)


class TestJitter:
    def test_the_wait_is_spread_but_never_reaches_zero(self) -> None:
        decision = RetryDecision(should_retry=True, delay_seconds=8.0, reason="x")
        rng = Random(1234)

        waits = [jittered(decision, rng) for _ in range(200)]

        assert min(waits) >= 4.0
        assert max(waits) <= 8.0
        assert len(set(waits)) > 1

    def test_jitter_never_undercuts_what_the_provider_demanded(self) -> None:
        decision = RetryDecision(
            should_retry=True, delay_seconds=30.0, min_delay_seconds=30.0, reason="x"
        )
        rng = Random(99)

        assert all(jittered(decision, rng) >= 30.0 for _ in range(200))
