"""Translate Salesforce error responses into the connector's failure types.

The only module that speaks Salesforce's error vocabulary. Actions and the
client never contain a provider error code, so wrapping a different CRM would
mean replacing this module and its rules file, and nothing else.

Salesforce publishes no machine-readable catalogue of error codes, so the
rules cannot be fetched at runtime. They are matched by the shape of the code
instead, which classifies codes nobody has seen yet, and they live in
salesforce_codes.yaml so changing them is editing data rather than shipping
code.
"""

from collections.abc import Mapping, Sequence
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import Final

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

from salesforce_connector.errors.model import (
    AuthenticationError,
    ConfigurationError,
    ConflictError,
    ConnectorError,
    ErrorContext,
    InvalidInputError,
    PermissionDeniedError,
    RateLimitError,
    RecordNotFoundError,
    TransportError,
)

# Provider messages can echo submitted values, so they are capped rather than
# passed through whole.
_MAX_REASON_LENGTH: Final = 300

_SERVER_ERROR_FLOOR: Final = 500

_RULES_PATH: Final = Path(__file__).with_name("salesforce_codes.yaml")

# Our vocabulary, not Salesforce's. The rules file may only name these.
_OUTCOMES: Final[Mapping[str, type[ConnectorError]]] = {
    "auth": AuthenticationError,
    "permission": PermissionDeniedError,
    "rate_limit": RateLimitError,
    "input": InvalidInputError,
    "not_found": RecordNotFoundError,
    "conflict": ConflictError,
    "transient": TransportError,
}


def _known_outcome(name: str) -> str:
    if name not in _OUTCOMES:
        raise ConfigurationError(
            f"{_RULES_PATH.name} names the unknown outcome {name!r}. "
            f"Known outcomes: {', '.join(sorted(_OUTCOMES))}."
        )
    return name


class _PatternRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: str
    match: tuple[str, ...]

    @field_validator("outcome")
    @classmethod
    def _outcome_is_known(cls, value: str) -> str:
        return _known_outcome(value)


class _Rules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    overrides: Mapping[str, str]
    patterns: tuple[_PatternRule, ...]
    status: Mapping[int, str]

    @field_validator("overrides", "status")
    @classmethod
    def _outcomes_are_known(cls, value: Mapping[object, str]) -> Mapping[object, str]:
        for outcome in value.values():
            _known_outcome(outcome)
        return value


@lru_cache(maxsize=1)
def _rules() -> _Rules:
    """Load and validate the rules once, failing loudly if they are unusable."""
    try:
        document = yaml.safe_load(_RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"{_RULES_PATH.name} could not be read: {exc}") from exc
    return _Rules.model_validate(document)


@lru_cache(maxsize=512)
def _outcome_for_code(code: str) -> str | None:
    """Classify one error code by override, then by pattern shape."""
    rules = _rules()
    override = rules.overrides.get(code)
    if override is not None:
        return override
    return next(
        (
            rule.outcome
            for rule in rules.patterns
            if any(fnmatchcase(code, pattern) for pattern in rule.match)
        ),
        None,
    )


def _failure_for(status: int, code: str) -> type[ConnectorError]:
    """Choose the failure type: code shape first, HTTP status second."""
    outcome = _outcome_for_code(code) if code else None
    if outcome is None:
        outcome = _rules().status.get(status)
    if outcome is not None:
        return _OUTCOMES[outcome]
    return TransportError if status >= _SERVER_ERROR_FLOOR else ConnectorError


def _faults(body: object) -> tuple[Mapping[str, object], ...]:
    """Normalise the two shapes Salesforce uses into one list of faults."""
    if isinstance(body, Mapping):
        return (body,)
    if isinstance(body, Sequence) and not isinstance(body, str):
        return tuple(item for item in body if isinstance(item, Mapping))
    return ()


def _code_of(fault: Mapping[str, object]) -> str:
    """Read the fault code from either the REST or the OAuth shape."""
    return str(fault.get("errorCode") or fault.get("error") or "").upper()


def _message_of(fault: Mapping[str, object]) -> str:
    """Read the human message from either the REST or the OAuth shape."""
    return str(fault.get("message") or fault.get("error_description") or "").strip()


def _fields_of(fault: Mapping[str, object]) -> tuple[str, ...]:
    """Read one fault's field list, tolerating a missing or malformed value.

    A bare string is rejected explicitly: it satisfies Sequence and would
    otherwise be iterated one character at a time.
    """
    fields = fault.get("fields")
    if isinstance(fields, Sequence) and not isinstance(fields, str):
        return tuple(str(field) for field in fields)
    return ()


def _invalid_fields(faults: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    """Collect every field Salesforce named, in order, without duplicates."""
    named = (name for fault in faults for name in _fields_of(fault))
    return tuple(dict.fromkeys(named))


def _reason(
    status: int, code: str, faults: Sequence[Mapping[str, object]]
) -> tuple[str, str | None]:
    """State what Salesforce reported, traceably and without dumping the body.

    Returns:
        The reason, and the substring of it that is Salesforce's own words, or
        None when the message is ours because the provider sent no detail. The
        second value exists so the rendering layer can mark provider text as
        data: a duplicate rule quotes the record it matched, and a validation
        rule quotes whatever an administrator typed into it, so an error is
        another way for record content to reach a model.
    """
    message = _message_of(faults[0]) if faults else ""
    trace = f" (Salesforce code {code}, HTTP {status})" if code else f" (HTTP {status})"
    if not message:
        return f"Salesforce returned HTTP {status} with no error detail." + trace, None
    quoted = message[:_MAX_REASON_LENGTH]
    return quoted + trace, quoted


def to_connector_error(
    status: int,
    body: object,
    retry_after: float | None = None,
) -> ConnectorError:
    """Convert one Salesforce error response into the failure it represents.

    Args:
        status: HTTP status code of the response.
        body: Already-parsed JSON body, in either the REST list shape or the
            OAuth object shape. Anything unrecognised is tolerated.
        retry_after: Seconds to wait, taken from the response headers when the
            provider supplied one.

    Returns:
        The failure type whose remedy matches what actually went wrong.
    """
    faults = _faults(body)
    code = _code_of(faults[0]) if faults else ""
    reason, quoted = _reason(status, code, faults)
    return _failure_for(status, code)(
        reason,
        ErrorContext(
            invalid_fields=_invalid_fields(faults),
            retry_after_seconds=retry_after,
            quoted=quoted,
        ),
    )
