"""Paging position and quota, reported where a caller can use them.

Definition of Done item 6 asks for pagination and rate-limit metadata to be
returned where relevant. Both are read from Salesforce already; these assert
they reach the caller rather than stopping inside the client.
"""

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from salesforce_connector.actions import registry
from salesforce_connector.auth.jwt_bearer import JwtBearerAuth
from salesforce_connector.config import Settings
from salesforce_connector.contract import (
    ActionError,
    ActionRequest,
    ActionResult,
    Pagination,
    RateLimit,
)
from salesforce_connector.errors.model import RateLimitError
from salesforce_connector.errors.retry import RetryPolicy
from salesforce_connector.protocol import translate as mcp_translate
from salesforce_connector.transport.client import SalesforceClient

INSTANCE = "https://mycompany--dev.sandbox.my.salesforce.com"
DATA = f"{INSTANCE}/services/data/v67.0"
TOKEN_URL = "https://test.salesforce.com/services/oauth2/token"
QUOTA = {"Sforce-Limit-Info": "api-usage=42/5000"}

PRIVATE_KEY = (
    rsa.generate_private_key(public_exponent=65537, key_size=2048)
    .private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    .decode()
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> SalesforceClient:
    monkeypatch.setattr(
        "salesforce_connector.transport.client.RetryPolicy",
        # The waits are made tiny; whatever the caller passes for attempts and
        # budget is honoured, so a test of exhaustion still sees the real count.
        lambda **passed: RetryPolicy(**passed, initial_wait_seconds=0.001, max_wait_seconds=0.002),
    )
    settings = Settings(
        client_id="3MVG9key",  # type: ignore[arg-type]
        username="integration@example.com.sandbox",
        private_key=PRIVATE_KEY,  # type: ignore[arg-type]
    )
    return SalesforceClient.open(settings, JwtBearerAuth())


def token_route() -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "00Dxx!AQEAQ", "instance_url": INSTANCE}
        )
    )


async def search(client: SalesforceClient, **params: object) -> ActionResult:
    request = ActionRequest(action_id="salesforce.contact_search_by_text", params=params)
    return await registry.build("salesforce.contact_search_by_text", client).run(request)


@pytest.mark.asyncio
class TestPaginationReachesTheEnvelope:
    async def test_a_paged_read_reports_where_it_stopped(self, client: SalesforceClient) -> None:
        async with client, respx.mock:
            token_route()
            respx.post(f"{DATA}/parameterizedSearch").mock(
                return_value=httpx.Response(
                    200, json={"searchRecords": [{"Id": f"003{n}", "Name": "x"} for n in range(2)]}
                )
            )

            result = await search(client, query="Ada", limit=2)

            assert result.pagination is not None
            assert result.pagination.returned == 2
            assert result.pagination.next_cursor == "2"
            assert result.pagination.has_more is True

    async def test_the_last_page_offers_no_cursor_and_says_so(
        self, client: SalesforceClient
    ) -> None:
        async with client, respx.mock:
            token_route()
            respx.post(f"{DATA}/parameterizedSearch").mock(
                return_value=httpx.Response(200, json={"searchRecords": []})
            )

            result = await search(client, query="Ada", limit=20)

            assert result.pagination is not None
            assert result.pagination.next_cursor is None
            assert result.pagination.has_more is False

    async def test_a_write_reports_no_pagination_at_all(self, client: SalesforceClient) -> None:
        async with client, respx.mock:
            token_route()
            respx.post(f"{DATA}/sobjects/Contact").mock(
                return_value=httpx.Response(201, json={"id": "003new"})
            )

            request = ActionRequest(
                action_id="salesforce.contact_create",
                params={"last_name": "Lovelace", "idempotency_key": "key-1234"},
                idempotency_key="key-1234",
                approved=True,
            )
            result = await registry.build("salesforce.contact_create", client).run(request)

            assert result.ok
            assert result.pagination is None


@pytest.mark.asyncio
class TestQuotaReachesTheEnvelope:
    async def test_quota_is_reported_on_a_successful_call(self, client: SalesforceClient) -> None:
        async with client, respx.mock:
            token_route()
            respx.post(f"{DATA}/parameterizedSearch").mock(
                return_value=httpx.Response(200, json={"searchRecords": []}, headers=QUOTA)
            )

            result = await search(client, query="Ada")

            assert result.rate_limit is not None
            assert result.rate_limit.used == 42
            assert result.rate_limit.limit == 5000

    async def test_quota_is_reported_on_a_failure_too(self, client: SalesforceClient) -> None:
        async with client, respx.mock:
            token_route()
            respx.post(f"{DATA}/parameterizedSearch").mock(
                return_value=httpx.Response(
                    403,
                    json=[{"errorCode": "INSUFFICIENT_ACCESS", "message": "no"}],
                    headers=QUOTA,
                )
            )

            result = await search(client, query="Ada")

            assert not result.ok
            assert result.rate_limit is not None
            assert result.rate_limit.used == 42

    async def test_a_response_without_the_header_reports_nothing_rather_than_zero(
        self, client: SalesforceClient
    ) -> None:
        async with client, respx.mock:
            token_route()
            respx.post(f"{DATA}/parameterizedSearch").mock(
                return_value=httpx.Response(200, json={"searchRecords": []})
            )

            assert (await search(client, query="Ada")).rate_limit is None


class TestTheAdapterCarriesItBesideThePayload:
    def test_both_travel_in_metadata_not_in_the_declared_output(self) -> None:
        outcome = ActionResult(
            ok=True,
            request_id="req-1",
            data={"contacts": [], "returned": 0},
            pagination=Pagination(returned=0, next_cursor="20"),
            rate_limit=RateLimit(used=42, limit=5000),
        )

        result = mcp_translate.as_result(outcome)

        assert result.meta is not None
        assert result.meta["salesforce-connector/pagination"]["next_cursor"] == "20"
        assert result.meta["salesforce-connector/rate_limit"]["used"] == 42
        assert result.structured_content == {"contacts": [], "returned": 0}

    def test_a_result_with_neither_carries_no_paging_or_quota(self) -> None:
        """Bookkeeping appears only when there is bookkeeping to report.

        A successful result always carries one other key, the notice that says
        what the structured half of the answer is, because that is true of
        every result rather than only of paged ones.
        """
        outcome = ActionResult(ok=True, request_id="req-1", data={"id": "003xx"})

        carried = mcp_translate.as_result(outcome).meta or {}

        assert "salesforce-connector/pagination" not in carried
        assert "salesforce-connector/rate_limit" not in carried
        assert list(carried) == ["salesforce-connector/content_is_data"]

    def test_a_failure_carries_no_data_notice_because_it_carries_no_structured_data(self) -> None:
        """The notice describes `structured_content`, and a failure has none.

        What a failure quotes from Salesforce is fenced in the text itself,
        which is where a reader will actually meet it.
        """
        failure = ActionError(
            code="salesforce.conflict",
            category="resource",  # type: ignore[arg-type]
            reason="duplicate",
            next_step="use the existing record",
        )
        outcome = ActionResult(ok=False, request_id="r", error=failure)

        carried = mcp_translate.as_result(outcome).meta or {}

        assert "salesforce-connector/content_is_data" not in carried

    def test_the_metadata_keys_carry_a_vendor_prefix(self) -> None:
        outcome = ActionResult(
            ok=True, request_id="r", data={}, rate_limit=RateLimit(used=1, limit=2)
        )

        keys = (mcp_translate.as_result(outcome).meta or {}).keys()

        # Anything whose second label is mcp or modelcontextprotocol is reserved.
        assert all("/" in key for key in keys)
        assert not any(key.startswith(("mcp/", "io.modelcontextprotocol/")) for key in keys)

    def test_a_failure_still_reports_the_quota_that_was_left(self) -> None:
        failure = RateLimitError("quota spent").to_action_error()
        outcome = ActionResult(
            ok=False, request_id="r", error=failure, rate_limit=RateLimit(used=5000, limit=5000)
        )

        result = mcp_translate.as_result(outcome)

        assert result.is_error is True
        assert result.meta is not None
        assert result.meta["salesforce-connector/rate_limit"]["used"] == 5000
