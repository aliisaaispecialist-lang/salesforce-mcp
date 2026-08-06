"""Retry policy, built on tenacity.

The rules are ours; the mechanics are not. Tenacity supplies the attempt loop,
the exponential backoff with jitter, the stop conditions, and the sleeping, all
of which are easy to write badly by hand and have been correct in that library
for years.

Three rules are enforced on top of it:

- only transient failures are retried, because everything else fails
  identically on a second attempt and merely spends the org's API quota;
- a write with no idempotency key is never retried, because the first attempt
  may already have created the record;
- a wait the provider asked for is never undercut, or the retry lands inside
  the window it already refused.

Timing is deliberately not the model's decision: a model has no clock, so it
chooses whether to call again while this module chooses when.
"""

from collections.abc import Callable
from typing import Final

from pydantic import BaseModel, ConfigDict, Field
from tenacity import AsyncRetrying, RetryCallState, stop_after_attempt, stop_after_delay
from tenacity.wait import wait_exponential_jitter

from salesforce_connector.errors.model import ConnectorError

_INITIAL_WAIT_SECONDS: Final = 1.0
_MAX_WAIT_SECONDS: Final = 60.0
_JITTER_SECONDS: Final = 1.0


class RetryPolicy(BaseModel):
    """Limits on how hard and how long a failed call is retried."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = Field(default=3, ge=1)
    total_budget_seconds: float = Field(default=120.0, gt=0)
    initial_wait_seconds: float = Field(default=_INITIAL_WAIT_SECONDS, gt=0)
    max_wait_seconds: float = Field(default=_MAX_WAIT_SECONDS, gt=0)


class CallShape(BaseModel):
    """What kind of call is being retried.

    An argument object rather than two booleans, so a caller cannot silently
    swap them and turn an unkeyed write into a retryable one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_write: bool = False
    has_idempotency_key: bool = False


DEFAULT_POLICY: Final = RetryPolicy()
READ_CALL: Final = CallShape()


def is_worth_retrying(exc: BaseException, *, is_write: bool, has_idempotency_key: bool) -> bool:
    """Judge one failure against the three rules.

    Args:
        exc: The failure that just occurred.
        is_write: Whether the call changes state in Salesforce.
        has_idempotency_key: Whether a repeat of this call would be deduplicated.

    Returns:
        True only when another attempt is both useful and safe.
    """
    if not isinstance(exc, ConnectorError) or not exc.retryable:
        return False
    return not (is_write and not has_idempotency_key)


def provider_wait_of(state: RetryCallState) -> float:
    """Read the wait the provider itself asked for, if it asked for one."""
    outcome = state.outcome
    if outcome is None or not outcome.failed:
        return 0.0
    failure = outcome.exception()
    if not isinstance(failure, ConnectorError):
        return 0.0
    return failure.context.retry_after_seconds or 0.0


def build_wait(policy: RetryPolicy = DEFAULT_POLICY) -> Callable[[RetryCallState], float]:
    """Wait for whichever is longer: our backoff, or what the provider demanded.

    Tenacity treats a wait strategy as any callable taking the retry state, so
    combining the two is composition rather than a reimplementation of either.
    """
    backoff = wait_exponential_jitter(
        initial=policy.initial_wait_seconds,
        max=policy.max_wait_seconds,
        jitter=_JITTER_SECONDS,
    )

    def wait(state: RetryCallState) -> float:
        return max(backoff(state), provider_wait_of(state))

    return wait


def build_retrying(
    policy: RetryPolicy = DEFAULT_POLICY,
    shape: CallShape = READ_CALL,
    before_sleep: Callable[[RetryCallState], None] | None = None,
) -> AsyncRetrying:
    """Assemble the retry loop for one call.

    Stops when either limit is reached, rather than both: an attempt ceiling
    alone would let three sixty-second waits hold a call for minutes, and a
    time budget alone would allow an unbounded number of fast failures.

    Args:
        policy: Limits to apply.
        shape: Whether this call writes, and whether a repeat is safe.
        before_sleep: Called with the retry state before each wait, for logging.

    Returns:
        A configured AsyncRetrying, ready to drive an `async for` attempt loop.
    """
    return AsyncRetrying(
        retry=lambda state: _should_retry(state, shape),
        wait=build_wait(policy),
        stop=stop_after_attempt(policy.max_attempts)
        | stop_after_delay(policy.total_budget_seconds),
        before_sleep=before_sleep,
        reraise=True,  # the caller sees the Salesforce failure, not a RetryError
    )


def _should_retry(state: RetryCallState, shape: CallShape) -> bool:
    outcome = state.outcome
    if outcome is None or not outcome.failed:
        return False
    failure = outcome.exception()
    if failure is None:
        return False
    return is_worth_retrying(
        failure,
        is_write=shape.is_write,
        has_idempotency_key=shape.has_idempotency_key,
    )
