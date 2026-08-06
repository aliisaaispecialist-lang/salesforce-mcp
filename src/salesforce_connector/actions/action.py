"""The shape every action shares.

Each of the five does the same four things: validate what it was given, ask
the client for something, shape the answer, and turn any failure into the same
envelope. Writing that four times would be four chances to get the error
handling subtly different, so it is written once here and each action supplies
only what makes it different.

No exception leaves `run`. A failed action is a result the caller reads, not a
crash it must catch: one action failing must never end the session or affect
the other four.
"""

import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, ClassVar, Final

from pydantic import BaseModel, ValidationError

from salesforce_connector.client import SalesforceClient
from salesforce_connector.contract import ActionRequest, ActionResult
from salesforce_connector.errors.model import ConnectorError, ErrorContext, InvalidInputError
from salesforce_connector.observability import bind_request, clear_request, get_logger
from salesforce_connector.schemas.envelope import ActionSpec

_MILLISECONDS: Final = 1000.0


class Action(ABC):
    """One Salesforce operation, wrapped so that it always answers.

    Subclasses declare their specification and input model, then implement
    `_execute`, which may assume its argument is already valid.
    """

    spec: ClassVar[ActionSpec]
    input_model: ClassVar[type[BaseModel]]
    output_model: ClassVar[type[BaseModel]]

    def __init__(self, client: SalesforceClient) -> None:
        self._client = client
        self._log = get_logger()

    async def run(self, request: ActionRequest) -> ActionResult:
        """Perform this action, returning the outcome either way.

        Args:
            request: The action id, its arguments, and the caller's key.

        Returns:
            The uniform envelope, successful or not. Never raises.
        """
        started = time.monotonic()
        bind_request(request.request_id, self.spec.action_id)
        try:
            return await self._attempt(request, started)
        except ConnectorError as failure:
            return self._failed(request, failure, started)
        finally:
            clear_request()

    async def _attempt(self, request: ActionRequest, started: float) -> ActionResult:
        params = self._validated(request.params)
        settled = self._already_done(request)
        if settled is not None:
            return settled
        self._require_approval(request)

        data = await self._execute(params)
        checked = self.output_model.model_validate(data).model_dump(mode="json")
        if request.idempotency_key is not None:
            self._client.ledger.complete(request.idempotency_key, checked)
        return self._succeeded(request, checked, started)

    def _validated(self, params: Mapping[str, Any]) -> BaseModel:
        """Reject bad arguments here, so no action sends one to Salesforce."""
        try:
            return self.input_model.model_validate(dict(params))
        except ValidationError as exc:
            raise InvalidInputError(
                self._explain(exc), ErrorContext(invalid_fields=_fields_of(exc))
            ) from exc

    def _explain(self, exc: ValidationError) -> str:
        faults = "; ".join(
            f"{_name_of(problem['loc'])}: {problem['msg']}" for problem in exc.errors()
        )
        return f"{self.spec.tool_name} rejected its arguments. {faults}."

    def _already_done(self, request: ActionRequest) -> ActionResult | None:
        """Answer from the ledger when this key has already succeeded."""
        if request.idempotency_key is None:
            return None
        entry = self._client.ledger.find(request.idempotency_key)
        if entry is None or entry.result is None:
            return None
        return ActionResult(
            ok=True,
            request_id=request.request_id,
            data=entry.result,
            warnings=(
                "This idempotency key had already completed; the original result is returned.",
            ),
        )

    def _require_approval(self, request: ActionRequest) -> None:
        """Refuse a consequential write nobody approved."""
        if self.spec.requires_approval and not request.approved:
            raise InvalidInputError(
                f"{self.spec.tool_name} changes data in Salesforce and needs approval "
                f"before it runs.",
                ErrorContext(
                    next_step=(
                        "Ask the user to confirm this write, then call again with "
                        "approved set to true and the same idempotency_key."
                    ),
                    invalid_fields=("approved",),
                ),
            )

    def _succeeded(
        self, request: ActionRequest, data: Mapping[str, Any], started: float
    ) -> ActionResult:
        elapsed = (time.monotonic() - started) * _MILLISECONDS
        self._client.metrics.record_call(self.spec.action_id, ok=True, duration_ms=elapsed)
        self._log.info("action.completed", duration_ms=round(elapsed, 1))
        return ActionResult(ok=True, request_id=request.request_id, data=data)

    def _failed(
        self, request: ActionRequest, failure: ConnectorError, started: float
    ) -> ActionResult:
        elapsed = (time.monotonic() - started) * _MILLISECONDS
        error = failure.to_action_error()
        self._client.metrics.record_call(self.spec.action_id, ok=False, duration_ms=elapsed)
        self._client.metrics.record_failure(self.spec.action_id, error.category.value)
        if request.idempotency_key is not None and not failure.retryable:
            self._client.ledger.fail(request.idempotency_key)
        self._log.warning("action.failed", code=error.code, category=error.category.value)
        return ActionResult(ok=False, request_id=request.request_id, error=error)

    @abstractmethod
    async def _execute(self, params: Any) -> Mapping[str, Any]:
        """Do the work, given arguments already known to be valid."""


def _name_of(location: tuple[object, ...]) -> str:
    return str(location[0]) if location else "arguments"


def _fields_of(exc: ValidationError) -> tuple[str, ...]:
    named = (_name_of(problem["loc"]) for problem in exc.errors())
    return tuple(dict.fromkeys(named))
