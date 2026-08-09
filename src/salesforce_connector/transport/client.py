"""The only module that opens a socket.

Everything network-shaped lives here: the token, the connection pool, the
timeouts, the retry loop, and the translation of any non-2xx into a typed
failure. Actions above this line describe what they want; none of them knows
that HTTP exists, and an import contract enforces that rather than trusting it.

The shape of a request and its answer lives next door in `exchange`, so this
file is about sending and that one is about form.

One client is created when the server starts and closed when it stops. A single
connection pool is reused for the life of the process, because opening a fresh
TLS connection per call is the largest avoidable cost against a remote API.
"""

import uuid
from datetime import UTC, datetime
from types import TracebackType
from typing import Final, Self

import httpx
from tenacity import RetryCallState

from salesforce_connector.auth.strategy import AuthStrategy, Token
from salesforce_connector.config import Settings
from salesforce_connector.contract import RateLimit
from salesforce_connector.errors.mapping import to_connector_error
from salesforce_connector.errors.model import (
    AuthenticationError,
    ConnectorError,
    ErrorContext,
    EscalationError,
    InvalidInputError,
    TransportError,
)
from salesforce_connector.errors.retry import RetryPolicy, build_retrying
from salesforce_connector.immutable import freeze
from salesforce_connector.observability import Metrics, get_logger
from salesforce_connector.replay.ledger import IdempotencyLedger
from salesforce_connector.transport.exchange import (
    LIMIT_HEADER,
    NO_CONTENT,
    RequestSpec,
    Response,
    parse_rate_limit,
    retry_after_of,
)

_MAX_KEEPALIVE: Final = 5
_MAX_CONNECTIONS: Final = 10


class SalesforceClient:
    """Sends requests to one Salesforce org, and normalises what comes back."""

    def __init__(self, settings: Settings, strategy: AuthStrategy, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._strategy = strategy
        self._http = http
        self._token: Token | None = None
        self.ledger = IdempotencyLedger()
        self.metrics = Metrics()
        # Quota as of the most recent response, so a caller can report it
        # without spending a request to ask. Salesforce attaches it to every
        # reply, including the ones that failed.
        self.last_rate_limit: RateLimit | None = None
        self._log = get_logger()

    @classmethod
    def open(cls, settings: Settings, strategy: AuthStrategy) -> Self:
        """Create a client with a pooled connection, ready for a lifespan.

        No network call happens here. The token is fetched on first use, so a
        server can start and report its tools even while the org is briefly
        unreachable.
        """
        http = httpx.AsyncClient(
            limits=httpx.Limits(
                max_keepalive_connections=_MAX_KEEPALIVE,
                max_connections=_MAX_CONNECTIONS,
            ),
            timeout=httpx.Timeout(
                settings.read_timeout_seconds, connect=settings.connect_timeout_seconds
            ),
            follow_redirects=False,
        )
        return cls(settings, strategy, http)

    @property
    def settings(self) -> Settings:
        """The configuration this client was opened with.

        Exposed because the connector above needs the same tunables -- the call
        budget, chiefly -- and passing them twice invites the two copies to
        disagree.
        """
        return self._settings

    async def aclose(self) -> None:
        """Close the pool and forget the token."""
        self._token = None
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        """Enter a scope that closes the pool on the way out."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the pool however the scope ended."""
        await self.aclose()

    async def token(self) -> Token:
        """Return the current access token, obtaining one if there is none."""
        if self._token is None:
            self._token = await self._authenticate()
        return self._token

    async def request(self, spec: RequestSpec) -> Response:
        """Send one call, retrying only where that is useful and safe.

        Args:
            spec: What to send.

        Returns:
            The response, with its body frozen against modification.

        Raises:
            ConnectorError: The call failed in a way no further attempt fixes.
        """
        policy = RetryPolicy(
            max_attempts=self._settings.max_attempts,
            total_budget_seconds=self._settings.retry_budget_seconds,
        )
        attempted = 0
        try:
            async for attempt in build_retrying(policy, spec.shape, self._log_before_sleep):
                with attempt:
                    attempted += 1
                    return await self._attempt(spec)
        except ConnectorError as exhausted:
            raise _escalated(exhausted, attempted, policy.max_attempts) from exhausted
        raise TransportError("the retry loop ended without a result")  # pragma: no cover

    async def _attempt(self, spec: RequestSpec) -> Response:
        token = await self.token()
        request_id = str(uuid.uuid4())
        try:
            raw = await self._http.request(
                spec.method,
                _within_the_org(spec.absolute_url, token) or self._url(token, spec.path),
                params=dict(spec.params) or None,
                json=dict(spec.json_body) if spec.json_body is not None else None,
                headers={**self._headers(token, request_id), **spec.headers},
                timeout=self._timeout(spec),
            )
        except httpx.HTTPError as exc:
            raise TransportError(_transport_reason(spec, exc, self._timeout(spec))) from exc

        return self._interpret(raw, request_id)

    def _interpret(self, raw: httpx.Response, request_id: str) -> Response:
        rate_limit = parse_rate_limit(raw.headers.get(LIMIT_HEADER))
        if rate_limit is not None:
            self.last_rate_limit = rate_limit
        body = self._body_of(raw)
        if raw.is_success:
            return Response(
                status=raw.status_code,
                body=freeze(body),
                rate_limit=rate_limit,
                request_id=request_id,
            )
        failure = to_connector_error(raw.status_code, body, retry_after_of(raw.headers))
        if isinstance(failure, AuthenticationError):
            self._token = None  # the next attempt authenticates again
        raise failure

    def _body_of(self, raw: httpx.Response) -> object:
        """Parse the body, tolerating the empty one a PATCH returns."""
        if raw.status_code == NO_CONTENT or not raw.content:
            return None
        try:
            return raw.json()
        except ValueError:
            return raw.text

    def _url(self, token: Token, path: str) -> str:
        base = token.instance_url.rstrip("/")
        return f"{base}/services/data/{self._settings.api_version}/{path.lstrip('/')}"

    def _headers(self, token: Token, request_id: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token.access_token.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Request-Id": request_id,
        }

    def _timeout(self, spec: RequestSpec) -> float:
        """Give writes longer, since one that times out may already have landed."""
        return (
            self._settings.write_timeout_seconds
            if spec.is_write
            else self._settings.read_timeout_seconds
        )

    async def _authenticate(self) -> Token:
        exchange = self._strategy.build_request(self._settings, datetime.now(UTC))
        try:
            raw = await self._http.post(
                exchange.url,
                data=dict(exchange.form),
                timeout=self._settings.read_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise TransportError(f"the token endpoint was unreachable: {exc}") from exc

        body = self._body_of(raw)
        if not raw.is_success:
            raise to_connector_error(raw.status_code, body, retry_after_of(raw.headers))
        token = self._strategy.parse_token(body, datetime.now(UTC))
        self._log.info("auth.token_issued", flow=self._strategy.name, host=token.instance_url)
        return token

    def _log_before_sleep(self, state: RetryCallState) -> None:
        outcome = state.outcome
        failure = outcome.exception() if outcome is not None else None
        self._log.warning(
            "client.retrying",
            attempt=state.attempt_number,
            waiting_seconds=round(state.next_action.sleep, 2) if state.next_action else None,
            because=type(failure).__name__ if failure else None,
            detail=failure.reason if isinstance(failure, ConnectorError) else None,
        )


def _escalated(failure: ConnectorError, attempted: int, allowed: int) -> ConnectorError:
    """Say plainly when something failed every time it was tried.

    The retry loop reraises the original Salesforce error, which is right: the
    caller should see what actually went wrong. But it leaves out the fact that
    it went wrong three times, and that changes what a caller should do. An
    error a model reads as "retry this" after it has already been retried to
    exhaustion produces a fourth attempt, then a fifth.

    So a call that used every attempt stops being a retry suggestion and
    becomes an escalation: tell the user, by name, that it failed N times and
    needs doing by hand. Chapter 6's fatal category -- stop, report, escalate.

    A failure on the first attempt is left exactly as it was. Only exhaustion
    changes the advice.
    """
    if attempted < allowed:
        return failure

    original = failure.to_action_error()
    return EscalationError(
        f"{original.reason} This failed {attempted} times in a row.",
        ErrorContext(
            next_step=(
                f"Stop retrying. This has now failed {attempted} times with the same "
                f"internal error, so another attempt will fail too. Tell the user "
                f"plainly that the operation could not be completed automatically and "
                f"that they need to do it manually in Salesforce. Give them the error "
                f"({original.code}) so they can pass it on if they need support."
            ),
            invalid_fields=original.invalid_fields,
        ),
    )


def _within_the_org(url: str | None, token: Token) -> str | None:
    """Refuse an absolute URL that does not belong to this org.

    The last line of defence, and the only one that covers every action at
    once. Every request made here carries the org's bearer token, and the
    token is attached without looking at where the request is going -- so a URL
    that came from anywhere other than Salesforce would post that token to
    whoever supplied it.

    That is not hypothetical. The SOQL cursor was passed through verbatim on
    the reasoning that its contents were Salesforce's business, and the records
    this connector reads contain text written by other people, which is the
    whole reason responses are fenced. Guarding it in the action closed that
    one path; guarding it here means the next action cannot reopen it.
    """
    if url is None:
        return None
    within = f"{token.instance_url.rstrip('/')}/services/data/"
    if url.startswith(within):
        return url
    raise InvalidInputError(
        "That address does not belong to this Salesforce org, so it will not be called.",
        ErrorContext(
            next_step=(
                "Only addresses Salesforce itself issued can be followed. Start "
                "the request again rather than supplying one."
            ),
        ),
    )


def _transport_reason(spec: RequestSpec, failure: Exception, waited: float) -> str:
    """Say what a failed call means, and a timeout differently from the rest.

    Every other transport failure is unambiguous: the request did not arrive.
    A timeout is the one case where nobody knows. Salesforce may have applied
    the write and been slow to answer, or never received it at all, and the
    difference matters enormously to whoever reads this next.

    So the message says which of those two situations it is in, rather than
    reporting the exception and leaving the reader to work it out.
    """
    if not isinstance(failure, httpx.TimeoutException):
        return f"the request to Salesforce did not complete: {failure}"
    if spec.is_write:
        return (
            f"Salesforce did not answer within {waited:.0f} seconds. This was a write, "
            f"so it may already have been applied and the answer lost, or it may never "
            f"have arrived. Nobody knows which from here."
        )
    return (
        f"Salesforce did not answer within {waited:.0f} seconds. This was a read, "
        f"so nothing was changed and asking again is safe."
    )
