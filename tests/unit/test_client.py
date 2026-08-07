"""What the client does with what Salesforce sends back.

No socket is opened: respx intercepts at the transport layer, so these are the
real httpx request and response objects with the network removed.
"""

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from salesforce_connector.auth.jwt_bearer import JwtBearerAuth
from salesforce_connector.client import SalesforceClient
from salesforce_connector.config import Settings
from salesforce_connector.errors.model import (
    AuthenticationError,
    ConflictError,
    PermissionDeniedError,
    RateLimitError,
    TransportError,
)
from salesforce_connector.errors.retry import RetryPolicy
from salesforce_connector.exchange import RequestSpec, parse_rate_limit

INSTANCE = "https://mycompany--dev.sandbox.my.salesforce.com"
TOKEN_URL = "https://test.salesforce.com/services/oauth2/token"
CONTACT_URL = f"{INSTANCE}/services/data/v67.0/sobjects/Contact"

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
def settings() -> Settings:
    return Settings(
        client_id="3MVG9key",  # type: ignore[arg-type]
        username="integration@example.com.sandbox",
        private_key=PRIVATE_KEY,  # type: ignore[arg-type]
    )


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> SalesforceClient:
    """A client whose retries are instant, so tests do not wait."""
    monkeypatch.setattr(
        "salesforce_connector.client.RetryPolicy",
        lambda: RetryPolicy(initial_wait_seconds=0.001, max_wait_seconds=0.002),
    )
    return SalesforceClient.open(settings, JwtBearerAuth())


def token_route() -> respx.Route:
    return respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "00Dxx!AQEAQ", "instance_url": INSTANCE}
        )
    )


class TestRateLimitHeader:
    def test_quota_is_read_from_the_header(self) -> None:
        limit = parse_rate_limit("api-usage=18/5000")

        assert limit is not None
        assert (limit.used, limit.limit) == (18, 5000)

    def test_extra_fields_in_the_header_are_tolerated(self) -> None:
        limit = parse_rate_limit("api-usage=100/15000, per-app-api-usage=25/5000")

        assert limit is not None
        assert (limit.used, limit.limit) == (100, 15000)

    @pytest.mark.parametrize("header", [None, "", "nonsense", "api-usage=many/lots"])
    def test_an_unusable_header_is_ignored_rather_than_fatal(self, header: str | None) -> None:
        assert parse_rate_limit(header) is None


@pytest.mark.asyncio
class TestSuccessfulCalls:
    async def test_a_token_is_obtained_and_the_instance_host_is_used(
        self, client: SalesforceClient
    ) -> None:
        async with client:
            with respx.mock:
                token_route()
                route = respx.get(CONTACT_URL).mock(return_value=httpx.Response(200, json={}))

                await client.request(RequestSpec(method="GET", path="sobjects/Contact"))

                assert route.called

    async def test_the_response_body_cannot_be_modified(self, client: SalesforceClient) -> None:
        async with client:
            with respx.mock:
                token_route()
                respx.get(CONTACT_URL).mock(
                    return_value=httpx.Response(200, json={"records": [{"Id": "003xx"}]})
                )

                response = await client.request(RequestSpec(method="GET", path="sobjects/Contact"))

                with pytest.raises(TypeError):
                    response.body["records"] = []

    async def test_quota_is_returned_alongside_the_body(self, client: SalesforceClient) -> None:
        async with client:
            with respx.mock:
                token_route()
                respx.get(CONTACT_URL).mock(
                    return_value=httpx.Response(
                        200, json={}, headers={"Sforce-Limit-Info": "api-usage=7/5000"}
                    )
                )

                response = await client.request(RequestSpec(method="GET", path="sobjects/Contact"))

                assert response.rate_limit is not None
                assert response.rate_limit.used == 7

    async def test_an_empty_body_from_a_patch_is_not_an_error(
        self, client: SalesforceClient
    ) -> None:
        async with client:
            with respx.mock:
                token_route()
                respx.patch(f"{CONTACT_URL}/003xx").mock(return_value=httpx.Response(204))

                response = await client.request(
                    RequestSpec(
                        method="PATCH",
                        path="sobjects/Contact/003xx",
                        is_write=True,
                        idempotency_key="key-1",
                    )
                )

                assert response.status == 204
                assert response.body is None

    async def test_an_opaque_cursor_is_used_exactly_as_given(
        self, client: SalesforceClient
    ) -> None:
        cursor = f"{INSTANCE}/services/data/v67.0/query/01gxx-2000"
        async with client:
            with respx.mock:
                token_route()
                route = respx.get(cursor).mock(return_value=httpx.Response(200, json={}))

                await client.request(RequestSpec(method="GET", absolute_url=cursor))

                assert route.called


@pytest.mark.asyncio
class TestFailuresBecomeTypedErrors:
    async def test_a_rate_limit_arriving_as_403_is_recognised(
        self, client: SalesforceClient
    ) -> None:
        async with client:
            with respx.mock:
                token_route()
                respx.get(CONTACT_URL).mock(
                    return_value=httpx.Response(
                        403,
                        json=[{"message": "limit", "errorCode": "REQUEST_LIMIT_EXCEEDED"}],
                        headers={"Retry-After": "0.01"},
                    )
                )

                with pytest.raises(RateLimitError):
                    await client.request(RequestSpec(method="GET", path="sobjects/Contact"))

    async def test_a_permission_failure_is_not_retried(self, client: SalesforceClient) -> None:
        async with client:
            with respx.mock:
                token_route()
                route = respx.get(CONTACT_URL).mock(
                    return_value=httpx.Response(
                        403, json=[{"message": "no", "errorCode": "INSUFFICIENT_ACCESS"}]
                    )
                )

                with pytest.raises(PermissionDeniedError):
                    await client.request(RequestSpec(method="GET", path="sobjects/Contact"))

                assert route.call_count == 1

    async def test_a_duplicate_becomes_a_conflict(self, client: SalesforceClient) -> None:
        async with client:
            with respx.mock:
                token_route()
                respx.post(CONTACT_URL).mock(
                    return_value=httpx.Response(
                        400,
                        json=[{"errorCode": "DUPLICATES_DETECTED", "fields": ["Email"]}],
                    )
                )

                with pytest.raises(ConflictError):
                    await client.request(
                        RequestSpec(
                            method="POST",
                            path="sobjects/Contact",
                            is_write=True,
                            idempotency_key="key-1",
                        )
                    )

    async def test_a_network_failure_becomes_a_transport_error(
        self, client: SalesforceClient
    ) -> None:
        async with client:
            with respx.mock:
                token_route()
                respx.get(CONTACT_URL).mock(side_effect=httpx.ConnectError("refused"))

                with pytest.raises(TransportError):
                    await client.request(RequestSpec(method="GET", path="sobjects/Contact"))

    async def test_a_rejected_token_is_discarded_so_the_next_call_reauthenticates(
        self, client: SalesforceClient
    ) -> None:
        async with client:
            with respx.mock:
                token = token_route()
                respx.get(CONTACT_URL).mock(
                    return_value=httpx.Response(
                        401, json=[{"errorCode": "INVALID_SESSION_ID", "message": "expired"}]
                    )
                )

                with pytest.raises(AuthenticationError):
                    await client.request(RequestSpec(method="GET", path="sobjects/Contact"))

                assert token.call_count == 1
                assert client._token is None


@pytest.mark.asyncio
class TestRetryBehaviour:
    async def test_a_transient_read_failure_is_retried_and_recovers(
        self, client: SalesforceClient
    ) -> None:
        async with client:
            with respx.mock:
                token_route()
                route = respx.get(CONTACT_URL).mock(
                    side_effect=[
                        httpx.Response(503, json=[]),
                        httpx.Response(200, json={"ok": True}),
                    ]
                )

                response = await client.request(RequestSpec(method="GET", path="sobjects/Contact"))

                assert response.status == 200
                assert route.call_count == 2

    async def test_a_write_without_a_key_is_attempted_exactly_once(
        self, client: SalesforceClient
    ) -> None:
        async with client:
            with respx.mock:
                token_route()
                route = respx.post(CONTACT_URL).mock(return_value=httpx.Response(503, json=[]))

                with pytest.raises(TransportError):
                    await client.request(
                        RequestSpec(method="POST", path="sobjects/Contact", is_write=True)
                    )

                assert route.call_count == 1

    async def test_a_write_with_a_key_is_retried(self, client: SalesforceClient) -> None:
        async with client:
            with respx.mock:
                token_route()
                route = respx.post(CONTACT_URL).mock(
                    side_effect=[
                        httpx.Response(503, json=[]),
                        httpx.Response(201, json={"id": "003xx"}),
                    ]
                )

                response = await client.request(
                    RequestSpec(
                        method="POST",
                        path="sobjects/Contact",
                        is_write=True,
                        idempotency_key="key-1",
                    )
                )

                assert response.status == 201
                assert route.call_count == 2
