"""Structured logging and in-process counters.

Everything is written to stderr. An MCP server speaking over stdio owns stdout
for JSON-RPC, so a single stray line there corrupts the stream and ends the
session. The T20 lint rule bans print for the same reason.

Redaction is a filter on the logger rather than a rule at call sites: a
forgotten logger.debug(response) still cannot leak a token, because the mask is
applied on the way out.

Record field values are never logged. Salesforce contacts carry names, emails,
and phone numbers, so identifiers are logged and payloads are not.
"""

import json
import logging
import re
import sys
from collections import Counter, defaultdict
from statistics import median
from typing import Any, Final

_REDACTED: Final = "[redacted]"

# Matched against the rendered line, so a secret is masked no matter which
# field or nested structure carried it.
_SECRET_PATTERNS: Final = (
    re.compile(r"(?i)(bearer\s+)[\w.\-]+"),
    re.compile(
        r"(?i)(\"?(?:access_token|refresh_token|client_secret|assertion)\"?\s*[:=]\s*\"?)[^\"\s,}]+"
    ),
    re.compile(r"-----BEGIN[^-]+PRIVATE KEY-----.*?-----END[^-]+PRIVATE KEY-----", re.DOTALL),
    re.compile(r"(?i)(\"?authorization\"?\s*[:=]\s*\"?)[^\"\s,}]+"),
)

_PERCENTILE_95: Final = 0.95


def redact(text: str) -> str:
    """Mask anything token-shaped in an already-rendered line."""
    masked = text
    for pattern in _SECRET_PATTERNS:
        masked = pattern.sub(
            lambda match: f"{match.group(1)}{_REDACTED}" if match.groups() else _REDACTED,
            masked,
        )
    return masked


class RedactingFormatter(logging.Formatter):
    """Render each record as one JSON object, with secrets masked."""

    def format(self, record: logging.LogRecord) -> str:
        """Flatten the record and its extra fields into one masked JSON line."""
        payload: dict[str, Any] = {
            "level": record.levelname.lower(),
            "event": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return redact(json.dumps(payload, default=str))


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Send this package's logs to stderr as redacted JSON lines."""
    logger = logging.getLogger("salesforce_connector")
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(RedactingFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def log_event(logger: logging.Logger, event: str, **fields: object) -> None:
    """Record one structured event.

    Args:
        logger: The package logger.
        event: Short, stable name for what happened.
        fields: Identifiers and outcomes only. Never record payloads, field
            values, or credentials.
    """
    logger.info(event, extra={"fields": fields})


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
