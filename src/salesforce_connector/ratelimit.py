"""Capping how often this connector may be asked to act.

The protocol requires it: servers MUST rate limit tool invocations. The reason
is concrete rather than theoretical. A model in a loop can spend a Salesforce
org's entire daily API allowance in a few minutes, and every other integration
in that org stops working until the window resets. The damage lands on people
who never saw this connector.

Calls are refused rather than queued. Waiting would hide the problem inside a
call that appears merely slow, and would let a runaway loop build a backlog
nobody asked for. A refusal that says how long to wait is something the caller
can act on, which is the whole point of the error taxonomy.

The bucket is aiolimiter's, which implements the leaky bucket properly,
including the partial refill between calls that a naive counter gets wrong.
"""

from typing import Final

from aiolimiter import AsyncLimiter

from salesforce_connector.errors.model import ErrorContext, RateLimitError

DEFAULT_CALLS_PER_MINUTE: Final = 60.0
_ONE_MINUTE: Final = 60.0


class CallBudget:
    """How many actions this process may run in a rolling window."""

    def __init__(self, calls_per_minute: float = DEFAULT_CALLS_PER_MINUTE) -> None:
        self._calls_per_minute = calls_per_minute
        self._bucket = AsyncLimiter(calls_per_minute, _ONE_MINUTE)

    async def claim(self, action_id: str) -> None:
        """Take one call from the budget, or refuse this one.

        Capacity is checked before it is taken, so the acquire that follows
        never waits: this refuses rather than queues, and the await is a
        formality the library's interface requires.

        Args:
            action_id: The action being attempted, named in the refusal.

        Raises:
            RateLimitError: The budget is spent. The message says how long to
                wait, so the caller retries rather than gives up.
        """
        if not self._bucket.has_capacity():
            raise RateLimitError(
                f"This connector has already run {self._calls_per_minute:.0f} actions in the "
                f"last minute, which is its own limit, separate from the org's API quota.",
                ErrorContext(
                    next_step=(
                        f"Wait {self._wait_seconds():.0f} seconds and call {action_id} again. "
                        f"If you are working through a list, slow down rather than retrying "
                        f"immediately."
                    ),
                    retry_after_seconds=self._wait_seconds(),
                ),
            )
        await self._bucket.acquire()

    def _wait_seconds(self) -> float:
        """How long until one call frees up, at the configured rate."""
        return _ONE_MINUTE / self._calls_per_minute
