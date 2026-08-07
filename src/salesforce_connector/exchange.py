"""One request and its answer, described without performing either.

Split out of the client so that the client is about *sending* and this is about
*shape*. An action builds a RequestSpec and reads a Response; neither needs the
connection pool, the token, or the retry loop to be in the same file, and the
header parsing here is worth testing on its own.
"""

from collections.abc import Mapping
from typing import Any, Final

import httpx
from pydantic import BaseModel, ConfigDict

from salesforce_connector.contract import RateLimit
from salesforce_connector.errors.retry import CallShape

LIMIT_HEADER: Final = "Sforce-Limit-Info"
RETRY_AFTER_HEADER: Final = "Retry-After"
NO_CONTENT: Final = 204


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
    Format is `api-usage=18/5000`, sometimes followed by per-application
    counters we do not use.
    """
    if not header or "api-usage=" not in header:
        return None
    used, _, allowed = header.split("api-usage=", 1)[1].partition("/")
    try:
        return RateLimit(used=int(used.strip()), limit=int(allowed.split(",")[0].strip()))
    except ValueError:
        return None


def retry_after_of(headers: httpx.Headers) -> float | None:
    """Read the wait the provider asked for, if it asked in a form we can use."""
    raw = headers.get(RETRY_AFTER_HEADER)
    try:
        return float(raw) if raw else None
    except ValueError:
        return None
