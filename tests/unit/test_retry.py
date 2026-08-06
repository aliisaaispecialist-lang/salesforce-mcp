"""The three rules layered on top of tenacity's attempt loop.

The rule that matters most is the last one: a write with no idempotency key is
never retried, because the first attempt may already have created the record.
"""

import time

import pytest

from salesforce_connector.errors.model import (
    ErrorContext,
    InvalidInputError,
    PermissionDeniedError,
    RateLimitError,
    RecordNotFoundError,
    TransportError,
)
from salesforce_connector.errors.retry import (
    DEFAULT_POLICY,
    READ_CALL,
    CallShape,
    RetryPolicy,
    build_retrying,
    is_worth_retrying,
)

# Waits are kept tiny so the suite stays fast; the schedule itself is
# tenacity's and is not re-tested here.
BRISK = RetryPolicy(initial_wait_seconds=0.001, max_wait_seconds=0.002, max_attempts=3)


class Failing:
    """An operation that fails a fixed number of times, then succeeds."""

    def __init__(self, failures: int, error: Exception) -> None:
        self._remaining = failures
        self._error = error
        self.attempts = 0

    async def __call__(self) -> str:
        self.attempts += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise self._error
        return "done"


async def run(operation: Failing, shape: CallShape = READ_CALL) -> str:
    result = ""
    async for attempt in build_retrying(BRISK, shape):
        with attempt:
            result = await operation()
    return result


class TestOnlyTransientFailuresAreWorthRetrying:
    @pytest.mark.parametrize(
        "error",
        [
            InvalidInputError("the email address is malformed"),
            PermissionDeniedError("the profile lacks Create on Contact"),
            RecordNotFoundError("no such contact"),
        ],
    )
    def test_a_failure_that_would_repeat_identically_is_refused(self, error: Exception) -> None:
        assert not is_worth_retrying(error, is_write=False, has_idempotency_key=False)

    @pytest.mark.parametrize(
        "error",
        [TransportError("connection reset"), RateLimitError("quota spent")],
    )
    def test_a_transient_failure_is_accepted(self, error: Exception) -> None:
        assert is_worth_retrying(error, is_write=False, has_idempotency_key=False)

    def test_something_that_is_not_our_error_is_never_retried(self) -> None:
        assert not is_worth_retrying(
            RuntimeError("unexpected"), is_write=False, has_idempotency_key=False
        )


class TestWritesWithoutAKeyAreNeverRetried:
    def test_an_unkeyed_write_is_refused_even_though_the_failure_is_transient(self) -> None:
        assert not is_worth_retrying(
            TransportError("timed out"), is_write=True, has_idempotency_key=False
        )

    def test_a_keyed_write_is_accepted(self) -> None:
        assert is_worth_retrying(
            TransportError("timed out"), is_write=True, has_idempotency_key=True
        )

    @pytest.mark.asyncio
    async def test_an_unkeyed_write_is_attempted_exactly_once(self) -> None:
        operation = Failing(failures=1, error=TransportError("timed out"))

        with pytest.raises(TransportError):
            await run(operation, CallShape(is_write=True))

        assert operation.attempts == 1

    @pytest.mark.asyncio
    async def test_a_keyed_write_is_attempted_again(self) -> None:
        operation = Failing(failures=1, error=TransportError("timed out"))

        assert await run(operation, CallShape(is_write=True, has_idempotency_key=True)) == "done"
        assert operation.attempts == 2


class TestTheAttemptLoop:
    @pytest.mark.asyncio
    async def test_a_transient_failure_is_recovered_from(self) -> None:
        operation = Failing(failures=2, error=TransportError("connection reset"))

        assert await run(operation) == "done"
        assert operation.attempts == 3

    @pytest.mark.asyncio
    async def test_attempts_stop_at_the_limit(self) -> None:
        operation = Failing(failures=99, error=TransportError("connection reset"))

        with pytest.raises(TransportError):
            await run(operation)

        assert operation.attempts == BRISK.max_attempts

    @pytest.mark.asyncio
    async def test_the_caller_sees_the_salesforce_failure_not_a_retry_error(self) -> None:
        operation = Failing(failures=99, error=RateLimitError("quota spent"))

        with pytest.raises(RateLimitError, match="quota spent"):
            await run(operation)

    @pytest.mark.asyncio
    async def test_a_failure_that_is_not_transient_is_raised_at_once(self) -> None:
        operation = Failing(failures=99, error=InvalidInputError("bad email"))

        with pytest.raises(InvalidInputError):
            await run(operation)

        assert operation.attempts == 1

    @pytest.mark.asyncio
    async def test_a_call_that_succeeds_first_time_is_not_repeated(self) -> None:
        operation = Failing(failures=0, error=TransportError("unused"))

        assert await run(operation) == "done"
        assert operation.attempts == 1


class TestProviderWait:
    @pytest.mark.asyncio
    async def test_a_provider_wait_is_honoured_rather_than_undercut(self) -> None:
        demanded = 0.25
        error = RateLimitError("quota spent", ErrorContext(retry_after_seconds=demanded))
        operation = Failing(failures=1, error=error)
        started = time.monotonic()
        await run(operation)
        elapsed = time.monotonic() - started

        assert elapsed >= demanded


class TestDefaults:
    def test_the_shipped_policy_is_conservative(self) -> None:
        assert DEFAULT_POLICY.max_attempts == 3
        assert DEFAULT_POLICY.total_budget_seconds == 120.0
