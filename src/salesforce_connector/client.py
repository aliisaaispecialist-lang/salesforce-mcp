"""The only module that reaches Salesforce.

Everything network-shaped lives here: the token, the connection pool, timeouts,
the retry loop, the quota header, and the translation of any non-2xx into a
typed failure. Actions above this line describe what they want; none of them
knows that HTTP exists.

The client is created once, when the MCP server starts, and closed when it
stops. One connection pool is reused for the life of the process, because
opening a fresh TLS connection per call is the single largest avoidable cost
against a remote API.
"""

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Final, Self

import httpx
from pydantic import BaseModel, ConfigDict
from tenacity import RetryCallState

from salesforce_connector.auth.strategy import AuthStrategy, Token
from salesforce_connector.config import Settings
from salesforce_connector.contract import RateLimit
from salesforce_connector.errors.mapping import to_connector_error
from salesforce_connector.errors.model import AuthenticationError, ConnectorError, TransportError
from salesforce_connector.errors.retry import CallShape, RetryPolicy, build_retrying
from salesforce_connector.idempotency import IdempotencyLedger
from salesforce_connector.immutable import freeze
from salesforce_connector.observability import Metrics, get_logger

_LIMIT_HEADER: Final = "Sforce-Limit-Info"
_RETRY_AFTER_HEADER: Final = "Retry-After"
_NO_CONTENT: Final = 204
_MAX_KEEPALIVE: Final = 5
_MAX_CONNECTIONS: Final = 10


class RequestSpec(BaseModel):
    """One call an action wants made.

    An argument object rather than six parameters, so a caller cannot pass the
    write flag in the wrong position and quietly make a create retryable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: str
    path: str = ""  # relative to /services/data/<version>
    absolute_url: str | None = None  # for an opaque cursor, used verbatim
    params: Mapping[str, str] = {}
    json_body: Mapping[str, Any] | None = None
    # Salesforce turns a few behaviours on through headers rather than fields,
    # such as permitting a save that duplicate rules would otherwise refuse.
    headers: Mapping[str, str] = {}
    is_write: bool = False
    idempotency_key: str | None = None

    @property
    def shape(self) -> CallShape:
        """Describe this call to the retry policy."""
        return CallShape(
            is_write=self.is_write,
            has_idempotency_key=self.idempotency_key is not None,
        )


class Response(BaseModel):
    """What came back, in a form nobody can alter afterwards."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: int
    body: Any = None
    rate_limit: RateLimit | None = None
    request_id: str


def parse_rate_limit(header: str | None) -> RateLimit | None:
    """Read quota from the header Salesforce attaches to every response.

    Free telemetry: knowing the org's remaining quota costs nothing here, where
    polling the limits endpoint would spend a call to learn the same thing.
    Format is `api-usage=18/5000`.
    """
    if not header or "api-usage=" not in header:
        return None
    used, _, allowed = header.split("api-usage=", 1)[1].partition("/")
    try:
        return RateLimit(used=int(used.strip()), limit=int(allowed.split(",")[0].strip()))
    except ValueError:
        return None


def _retry_after(headers: httpx.Headers) -> float | None:
    raw = headers.get(_RETRY_AFTER_HEADER)
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


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
            timeout=httpx.Timeout(settings.read_timeout_seconds, connect=5.0),
            follow_redirects=False,
        )
        return cls(settings, strategy, http)

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
        async for attempt in build_retrying(RetryPolicy(), spec.shape, self._log_before_sleep):
            with attempt:
                return await self._attempt(spec)
        raise TransportError("the retry loop ended without a result")  # pragma: no cover

    async def _attempt(self, spec: RequestSpec) -> Response:
        token = await self.token()
        request_id = str(uuid.uuid4())
        try:
            raw = await self._http.request(
                spec.method,
                spec.absolute_url or self._url(token, spec.path),
                params=dict(spec.params) or None,
                json=dict(spec.json_body) if spec.json_body is not None else None,
                headers={**self._headers(token, request_id), **spec.headers},
                timeout=self._timeout(spec),
            )
        except httpx.HTTPError as exc:
            raise TransportError(f"the request to Salesforce did not complete: {exc}") from exc

        return self._interpret(raw, request_id)

    def _interpret(self, raw: httpx.Response, request_id: str) -> Response:
        rate_limit = parse_rate_limit(raw.headers.get(_LIMIT_HEADER))
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
        failure = to_connector_error(raw.status_code, body, _retry_after(raw.headers))
        if isinstance(failure, AuthenticationError):
            self._token = None  # the next attempt authenticates again
        raise failure

    def _body_of(self, raw: httpx.Response) -> object:
        """Parse the body, tolerating the empty one a PATCH returns."""
        if raw.status_code == _NO_CONTENT or not raw.content:
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
            raise to_connector_error(raw.status_code, body, _retry_after(raw.headers))
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
