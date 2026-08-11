"""Exception types, classified by how a caller must respond.

One class per distinct required response, not one per Salesforce error code:
callers catch by remedy, so hundreds of provider codes collapse into eight
outcomes. Translation from provider codes happens in errors/mapping.py.

Every message is written for a language model to act on, so each one states
what happened and what to do next. A category alone is not enough - the model
sees only text.
"""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from salesforce_connector.contract import ActionError, ErrorCategory


class ErrorContext(BaseModel):
    """Optional detail attached to a failure.

    Grouped into one object because four separate keyword arguments on every
    raise exceeds the argument limit and obscures which ones matter.

    `resume_cursor` is deliberately not exposed to the model: it is operational
    state for the retry path, letting an interrupted read continue from where
    it stopped instead of starting over.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    next_step: str | None = None
    retry_after_seconds: float | None = None
    invalid_fields: tuple[str, ...] = ()
    resume_cursor: str | None = None
    quoted: str | None = None
    """Set only when the reason repeats Salesforce's own words verbatim."""


class ConnectorError(Exception):
    """Base for every failure this connector raises.

    A caller wanting to catch everything we raise catches this and nothing
    else. Subclasses declare their category and their default remedy.
    """

    category: ClassVar[ErrorCategory] = ErrorCategory.FATAL
    code: ClassVar[str] = "connector.unexpected"
    retryable: ClassVar[bool] = False
    default_next_step: ClassVar[str] = (
        "Stop and report this failure to a human. Retrying will not help."
    )

    def __init__(self, reason: str, context: ErrorContext | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.context = context or ErrorContext()

    def to_action_error(self) -> ActionError:
        """Render this failure as the envelope's error payload."""
        return ActionError(
            code=self.code,
            category=self.category,
            reason=self.reason,
            next_step=self.context.next_step or self.default_next_step,
            retryable=self.retryable,
            retry_after_seconds=self.context.retry_after_seconds,
            invalid_fields=self.context.invalid_fields,
            quoted=self.context.quoted,
        )


class ConfigurationError(ConnectorError):
    """A required setting is missing or malformed.

    Raised at startup, before any tool is exposed. This is the one failure that
    is not degraded gracefully: a misconfigured server should refuse to start
    rather than accept calls that can only fail.
    """

    category = ErrorCategory.FATAL
    code = "connector.configuration_invalid"
    default_next_step = (
        "Set the missing environment variable and restart the server. "
        "This cannot be fixed by retrying."
    )


class AuthenticationError(ConnectorError):
    """Salesforce did not accept the credentials, or the session expired.

    Categorised FATAL rather than TRANSIENT on purpose: an expired token looks
    retryable, but retrying with it fails identically. The remedy is to
    re-authenticate, not to wait.
    """

    category = ErrorCategory.FATAL
    code = "salesforce.authentication_failed"
    default_next_step = (
        "Re-authenticate before calling again. Do not retry with the same token, "
        "it will fail identically. If this repeats, the connected app credentials "
        "are wrong or have expired."
    )


class PermissionDeniedError(ConnectorError):
    """Authenticated, but this user may not perform this operation."""

    category = ErrorCategory.RESOURCE
    code = "salesforce.permission_denied"
    default_next_step = (
        "You are authenticated but not authorised for this object or field. "
        "Do not retry. Ask a Salesforce administrator to grant the permission, "
        "or use an action the current profile allows."
    )


class InvalidInputError(ConnectorError):
    """An argument was missing, malformed, or out of range."""

    category = ErrorCategory.INPUT
    code = "connector.invalid_input"
    default_next_step = (
        "Correct the named field and call this action again. The same input will fail identically."
    )


class RecordNotFoundError(ConnectorError):
    """The requested record does not exist, or has been deleted."""

    category = ErrorCategory.RESOURCE
    code = "salesforce.record_not_found"
    default_next_step = (
        "Verify the record id, or search for the record first. Do not retry, "
        "the record will not appear on its own."
    )


class ConflictError(ConnectorError):
    """The write was refused because it conflicts with existing state."""

    category = ErrorCategory.RESOURCE
    code = "salesforce.conflict"
    default_next_step = (
        "Do not retry unchanged. Either update the existing record, or repeat "
        "the call with the flag that permits the conflict."
    )


class RateLimitError(ConnectorError):
    """The org's API quota is exhausted for now."""

    category = ErrorCategory.TRANSIENT
    code = "salesforce.rate_limited"
    retryable = True
    default_next_step = (
        "Wait for the stated number of seconds, then retry the identical call. "
        "Do not retry immediately, it will be refused again."
    )


class TransportError(ConnectorError):
    """The request did not complete: timeout, connection failure, or 5xx."""

    category = ErrorCategory.TRANSIENT
    code = "salesforce.transport_failed"
    retryable = True
    default_next_step = (
        "Wait for the stated number of seconds, then retry with the same "
        "idempotency_key, so a write that already succeeded is not repeated. "
        "If a cursor was returned, resume from it rather than starting over."
    )


class EscalationError(ConnectorError):
    """A retryable failure that has stopped being retryable.

    The retry loop tried this the full number of times allowed and got the same
    error each time. The underlying failure may still be categorised as
    transient -- a timeout, a 503 -- but after exhaustion that classification
    is misleading. A model reading "wait and retry" for the fourth time will
    wait and retry.

    So exhaustion changes the category to FATAL, which means stop, report, and
    escalate to a person. It is the one place in this taxonomy where the same
    provider error maps to two different categories depending on history rather
    than on the error itself.
    """

    category = ErrorCategory.FATAL
    code = "connector.escalate_to_human"
