"""Structured logging and in-process counters.

Built on structlog rather than hand-rolled JSON, which brings three things the
hand-written version did not have:

- contextvars binding, so a request id set once is attached to every line for
  that call without being threaded through every function signature, and
  without leaking between concurrent calls;
- censoring as a processor in the chain, so it runs on the event dictionary
  before rendering rather than as a regex over an already-rendered string;
- cache_logger_on_first_use, which the structlog performance guide recommends
  for hot paths.

Everything is written to stderr. An MCP server speaking over stdio owns stdout
for JSON-RPC, so a single stray line there corrupts the stream and ends the
session. The T20 lint rule bans print for the same reason.

Record field values are never logged. Salesforce contacts carry names, emails,
and phone numbers, so identifiers are logged and payloads are not.
"""

import logging
import re
import sys
from collections import Counter, defaultdict
from collections.abc import MutableMapping
from statistics import median
from typing import Any, Final

import structlog

_REDACTED: Final = "[redacted]"

# Censored wherever they appear as keys, at any depth of the event dictionary.
_SECRET_KEYS: Final = frozenset(
    {
        "access_token",
        "assertion",
        "authorization",
        "client_id",
        "client_secret",
        "private_key",
        "refresh_token",
        "sf_client_secret",
        "sf_private_key",
        "token",
    }
)

# Censored inside string values, for secrets that arrive embedded in a message.
_SECRET_PATTERNS: Final = (
    re.compile(r"(?i)(bearer\s+)[\w.\-]+"),
    re.compile(r"-----BEGIN[^-]+PRIVATE KEY-----.*?-----END[^-]+PRIVATE KEY-----", re.DOTALL),
)

_PERCENTILE_95: Final = 0.95


def _censor_text(value: str) -> str:
    masked = value
    for pattern in _SECRET_PATTERNS:
        masked = pattern.sub(
            lambda match: f"{match.group(1)}{_REDACTED}" if match.groups() else _REDACTED,
            masked,
        )
    return masked


def _censor_value(key: str, value: object) -> object:
    if key.lower() in _SECRET_KEYS:
        return _REDACTED
    if isinstance(value, str):
        return _censor_text(value)
    if isinstance(value, dict):
        return {inner: _censor_value(str(inner), held) for inner, held in value.items()}
    return value


def censor_secrets(
    _logger: Any,
    _method: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Mask secrets before the event is rendered.

    A structlog processor, so it applies to every line regardless of which
    call site produced it. A forgotten log.debug(response) cannot leak.
    """
    return {key: _censor_value(key, value) for key, value in event_dict.items()}


def configure_logging(level: int = logging.INFO) -> None:
    """Send structured JSON to stderr, with secrets censored on the way out."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    structlog.configure(
        cache_logger_on_first_use=True,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            censor_secrets,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


def get_logger() -> structlog.stdlib.BoundLogger:
    """Return the connector's logger."""
    return structlog.get_logger("salesforce_connector")  # type: ignore[no-any-return]


def bind_request(request_id: str, action_id: str) -> None:
    """Attach a call's identity to every line it produces.

    Uses contextvars, so concurrent calls do not inherit each other's context
    and no function has to carry the request id through its signature.
    """
    structlog.contextvars.bind_contextvars(request_id=request_id, action_id=action_id)


def clear_request() -> None:
    """Drop the call's context once it has finished."""
    structlog.contextvars.clear_contextvars()


class Metrics:
    """Counts and timings for the life of the process.

    Calls and attempts are counted separately on purpose. One call that
    retried twice is one call and three attempts, and the ratio between them
    is what reveals a degrading provider. Counting only calls hides it.
    """

    def __init__(self) -> None:
        self._calls: Counter[str] = Counter()
        self._attempts: Counter[str] = Counter()
        self._successes: Counter[str] = Counter()
        self._failures: Counter[str] = Counter()
        self._retries: Counter[str] = Counter()
        self._exhausted: Counter[str] = Counter()
        self._latencies: dict[str, list[float]] = defaultdict(list)

    def record_call(self, action_id: str, *, ok: bool, duration_ms: float) -> None:
        """Record one completed call as the caller experienced it, retries included."""
        self._calls[action_id] += 1
        self._latencies[action_id].append(duration_ms)
        if ok:
            self._successes[action_id] += 1

    def record_attempt(self, action_id: str) -> None:
        """Record one HTTP request actually made."""
        self._attempts[action_id] += 1

    def record_failure(self, action_id: str, category: str) -> None:
        """Record a failed call against the category the caller must respond to."""
        self._failures[f"{action_id}:{category}"] += 1

    def record_retry(self, action_id: str, *, exhausted: bool = False) -> None:
        """Record a retry, and whether it was the last one allowed."""
        self._retries[action_id] += 1
        if exhausted:
            self._exhausted[action_id] += 1

    def summary(self) -> dict[str, Any]:
        """Report the counters without anyone having to parse the logs."""
        return {
            "calls": dict(self._calls),
            "attempts": dict(self._attempts),
            "successes": dict(self._successes),
            "failures": dict(self._failures),
            "retries": dict(self._retries),
            "retries_exhausted": dict(self._exhausted),
            "attempts_per_call": {
                action: round(self._attempts[action] / count, 2)
                for action, count in self._calls.items()
                if count
            },
            "latency_ms": {
                action: _describe(samples) for action, samples in self._latencies.items()
            },
        }


def _describe(samples: list[float]) -> dict[str, float]:
    """Summarise timings without keeping a histogram."""
    ordered = sorted(samples)
    index = min(int(len(ordered) * _PERCENTILE_95), len(ordered) - 1)
    return {
        "count": len(ordered),
        "p50": round(median(ordered), 1),
        "p95": round(ordered[index], 1),
        "max": round(ordered[-1], 1),
    }
