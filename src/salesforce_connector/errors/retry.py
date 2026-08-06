"""Whether and when to retry a failed call.

Nothing here sleeps or performs I/O. The decision is a pure function of the
failure, the attempts already made, and the policy, so the maths is tested in
microseconds instead of in real elapsed seconds. The waiting itself belongs to
the client, which owns I/O.

Timing is deliberately not the model's decision either: a model has no clock,
so it chooses whether to call again while this module chooses when.
"""

from random import Random
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from salesforce_connector.errors.model import ConnectorError

_HALF: Final = 2.0


class RetryPolicy(BaseModel):
    """Limits on how hard and how long a failed call is retried."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = Field(default=3, ge=1)
    base_delay_seconds: float = Field(default=1.0, gt=0)
    max_delay_seconds: float = Field(default=60.0, gt=0)
    total_budget_seconds: float = Field(default=120.0, gt=0)


class RetryContext(BaseModel):
    """What has happened so far, and what kind of call this is.

    Grouped into one object so the decision stays within the argument limit
    and so a caller cannot pass the write flags in the wrong order.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt: int = Field(ge=1)
    elapsed_seconds: float = Field(default=0.0, ge=0)
    is_write: bool = False
    has_idempotency_key: bool = False


class RetryDecision(BaseModel):
    """The verdict, and why.

    `base_delay_seconds` is named for what it is: the wait before jitter is
    applied. Nothing should sleep on it directly - pass this decision through
    `jittered` instead, or simultaneous callers retry in lockstep.

    `reason` is recorded whether or not a retry happens: during an incident the
    first question is why something stopped retrying, and an unexplained halt
    is indistinguishable from a bug.

    `min_delay_seconds` is the provider's own instruction. Jitter may extend a
    wait but must never shorten it below this, or the retry lands inside the
    window the provider already refused.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    should_retry: bool
    base_delay_seconds: float = 0.0
    min_delay_seconds: float = 0.0
    reason: str


DEFAULT_POLICY: Final = RetryPolicy()


def _backoff_seconds(attempt: int, policy: RetryPolicy) -> float:
    """Double the wait per attempt, up to the policy ceiling."""
    unbounded = policy.base_delay_seconds * _HALF ** (attempt - 1)
    return min(unbounded, policy.max_delay_seconds)


def decide(
    error: ConnectorError,
    context: RetryContext,
    policy: RetryPolicy = DEFAULT_POLICY,
) -> RetryDecision:
    """Judge whether this failure should be tried again, and after how long.

    Args:
        error: The failure that just occurred.
        context: Attempts made, time spent, and whether this call writes.
        policy: Limits to apply. The defaults follow the backoff schedule in
            the tool-use literature: one second, doubling, capped at sixty.

    Returns:
        The verdict, the wait before the next attempt, and the reasoning.
    """
    if not error.retryable:
        return RetryDecision(
            should_retry=False,
            reason=f"{type(error).__name__} is not transient; a retry fails identically",
        )

    if context.is_write and not context.has_idempotency_key:
        return RetryDecision(
            should_retry=False,
            reason="a write without an idempotency key must not be repeated; "
            "the first attempt may already have succeeded",
        )

    if context.attempt >= policy.max_attempts:
        return RetryDecision(
            should_retry=False,
            reason=f"attempt limit reached ({context.attempt}/{policy.max_attempts})",
        )

    provider_wait = error.context.retry_after_seconds or 0.0
    delay = max(_backoff_seconds(context.attempt, policy), provider_wait)

    if context.elapsed_seconds + delay > policy.total_budget_seconds:
        return RetryDecision(
            should_retry=False,
            reason=f"waiting {delay:.1f}s would exceed the "
            f"{policy.total_budget_seconds:.0f}s budget for this call",
        )

    return RetryDecision(
        should_retry=True,
        base_delay_seconds=delay,
        min_delay_seconds=provider_wait,
        reason=f"attempt {context.attempt} of {policy.max_attempts}, waiting about {delay:.1f}s",
    )


def jittered(decision: RetryDecision, rng: Random) -> float:
    """Spread the wait so simultaneous callers do not retry in lockstep.

    Equal jitter rather than the full jitter the literature describes: full
    jitter can return a value near zero, which would contradict the "do not
    retry immediately" instruction the same failure gives the model. The wait
    never falls below whatever the provider asked for.
    """
    half = decision.base_delay_seconds / _HALF
    spread = half + rng.uniform(0, half)
    return max(decision.min_delay_seconds, spread)
