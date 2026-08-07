"""What a live test needs, and what it refuses to do without.

Everything here exists to make one guarantee: these tests either run against a
real org with real credentials, or they skip. They never quietly fall back to a
mock, because a green integration suite that never left the machine is worse
than a red one -- it reports a connection that was never made.

Three safety rules, in the order they matter:

1. **Skip, never fail, when there are no credentials.** A contributor without
   an org runs the whole suite and sees skips, not errors.
2. **Refuse production outright.** `Settings` already guards the login host;
   this adds a second check, because these tests create and delete records.
3. **Every write is registered for deletion as it is created.** Not at the end
   of the test, where a failed assertion would skip the cleanup -- at the
   moment the id comes back.

The pieces arrive as one `Org` argument rather than five separate fixtures.
That is this repository's three-argument limit doing its job: a test signature
listing five fixtures says nothing about what the test does, and `org.marker`
reads better at the point of use than a bare `marker` anyway.
"""

import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio

from salesforce_connector.auth.jwt_bearer import JwtBearerAuth
from salesforce_connector.client import SalesforceClient
from salesforce_connector.config import PRODUCTION_LOGIN_URL, Settings, load_settings
from salesforce_connector.connector import SalesforceConnector, load_manifest
from salesforce_connector.contract import ActionRequest, ActionResult
from salesforce_connector.exchange import RequestSpec

REQUIRED = ("SF_CLIENT_ID", "SF_USERNAME", "SF_PRIVATE_KEY")

Call = Callable[..., Awaitable[ActionResult]]


def credentials_present() -> bool:
    """True when every variable a live run needs is set to something."""
    return all(os.environ.get(name) for name in REQUIRED)


needs_an_org = pytest.mark.skipif(
    not credentials_present(),
    reason=f"live org required; set {', '.join(REQUIRED)} (see QUICKSTART.md)",
)


class Litter:
    """Records what a test created, so it can be removed afterwards.

    Registration happens when the id arrives, not when the test ends. A failed
    assertion must not be the reason a record survives in someone's org.
    """

    def __init__(self) -> None:
        self._created: list[tuple[str, str]] = []

    def track(self, sobject: str, record_id: str) -> str:
        """Remember one record, and hand its id straight back."""
        self._created.append((sobject, record_id))
        return record_id

    @property
    def tracked(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._created)

    async def sweep(self, client: SalesforceClient) -> list[str]:
        """Delete everything recorded, newest first, reporting what would not go.

        Newest first because a note attached to a contact must go before the
        contact does. Failures are collected rather than raised: one record
        that will not delete should not hide the rest.
        """
        failures = []
        for sobject, record_id in reversed(self._created):
            try:
                await client.request(
                    RequestSpec(method="DELETE", path=f"sobjects/{sobject}/{record_id}")
                )
            except Exception as failure:
                failures.append(f"{sobject} {record_id}: {failure}")
        self._created.clear()
        return failures


@dataclass(frozen=True)
class Org:
    """One live org, and everything a test needs to work against it."""

    call: Call
    """Run an action the way the MCP server runs it, minus the protocol."""

    litter: Litter
    """Register every record created, for deletion when the test ends."""

    marker: str
    """A string unique to this test, for finding what this test created.

    Search is eventually consistent and an org may hold other people's data.
    Tagging every record makes an assertion about "the contact we just made"
    answerable without assuming the org is empty.
    """

    key: str
    """A fresh idempotency key.

    Real and unique, because these tests exercise the deduplication that
    depends on it. A fixed key would let the second test in a session see the
    first one's result and pass for the wrong reason.
    """

    connector: SalesforceConnector
    """The core itself, for the members `call` does not cover."""

    client: SalesforceClient
    """For the learning tier, which asks Salesforce things directly."""

    settings: Settings
    """The credentials, in the form `test_connection` asks for them."""


@pytest.fixture(scope="session")
def live_settings() -> Settings:
    """Read the real credentials, and refuse a production org."""
    settings = load_settings()
    if settings.login_url.rstrip("/") == PRODUCTION_LOGIN_URL:
        pytest.exit(
            "Integration tests refuse to run against login.salesforce.com. "
            "These tests create and delete records. Point SF_LOGIN_URL at a "
            "sandbox or a Developer Edition org.",
            returncode=2,
        )
    return settings


@pytest_asyncio.fixture
async def live_client(live_settings: Settings) -> AsyncIterator[SalesforceClient]:
    """One authenticated client per test, closed however the test ends."""
    client = SalesforceClient.open(live_settings, JwtBearerAuth())
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def org(live_client: SalesforceClient, live_settings: Settings) -> AsyncIterator[Org]:
    """The live org, with cleanup guaranteed however the test ends."""
    connector = SalesforceConnector(live_client, load_manifest(live_settings))
    bin_bag = Litter()

    async def _call(action_id: str, *, approved: bool = True, **params: Any) -> ActionResult:
        # `approved` defaults to true: there is no client here to put a
        # confirmation to a person, and the caller-asserted flag is exactly
        # the documented fallback for that case.
        return await connector.execute(
            ActionRequest(
                action_id=action_id,
                params=params,
                idempotency_key=_string_or_none(params.get("idempotency_key")),
                approved=approved,
            )
        )

    unique = uuid.uuid4()
    try:
        yield Org(
            call=_call,
            litter=bin_bag,
            marker=f"MCPTest{unique.hex[:10]}",
            key=f"itest-{unique}",
            connector=connector,
            client=live_client,
            settings=live_settings,
        )
    finally:
        leftovers = await bin_bag.sweep(live_client)
        if leftovers:
            pytest.fail("records left behind in the org:\n  " + "\n  ".join(leftovers))


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def unwrap(result: ActionResult) -> Mapping[str, Any]:
    """Return the payload, or fail with what the connector actually said.

    A bare `assert result.ok` reports False and nothing else, which is useless
    against a live org where the interesting information is always in the
    error.
    """
    if not result.ok:
        error = result.error
        raise AssertionError(
            f"{error.code if error else 'unknown'}: {error.reason if error else result}\n"
            f"next step: {error.next_step if error else 'none given'}"
        )
    return result.data
