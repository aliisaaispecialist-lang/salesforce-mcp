"""The four members every consumer goes through.

Three properties matter beyond wiring: a connection test must change nothing,
the budget must refuse rather than queue, and an approval must be useless for
any call other than the one it was issued for.
"""

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from salesforce_connector.approval import ApprovalGate, PendingWrite, digest_of
from salesforce_connector.auth.jwt_bearer import JwtBearerAuth
from salesforce_connector.client import SalesforceClient
from salesforce_connector.config import Settings
from salesforce_connector.connector import SalesforceConnector, load_manifest
from salesforce_connector.contract import ActionRequest
from salesforce_connector.errors.model import RateLimitError
from salesforce_connector.errors.retry import RetryPolicy
from salesforce_connector.ratelimit import CallBudget

INSTANCE = "https://mycompany--dev.sandbox.my.salesforce.com"
DATA = f"{INSTANCE}/services/data/v67.0"
TOKEN_URL = "https://test.salesforce.com/services/oauth2/token"

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
def connector(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> SalesforceConnector:
    monkeypatch.setattr(
        "salesforce_connector.client.RetryPolicy",
        # The waits are made tiny; whatever the caller passes for attempts and
        # budget is honoured, so a test of exhaustion still sees the real count.
        lambda **passed: RetryPolicy(**passed, initial_wait_seconds=0.001, max_wait_seconds=0.002),
    )
    client = SalesforceClient.open(settings, JwtBearerAuth())
    return SalesforceConnector(client, load_manifest(settings))


def token_route() -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "00Dxx!AQEAQ", "instance_url": INSTANCE}
        )
    )


class TestTheManifest:
    def test_it_declares_exactly_the_actions_that_exist(self, settings: Settings) -> None:
        manifest = load_manifest(settings)

        assert set(manifest.actions) == {
            "salesforce.search_contact",
            "salesforce.create_contact",
            "salesforce.update_contact",
            "salesforce.create_opportunity",
            "salesforce.add_activity_note",
        }

    def test_it_states_its_risks_rather_than_leaving_them_to_be_found(
        self, settings: Settings
    ) -> None:
        assert len(load_manifest(settings).risks) >= 3

    def test_it_asks_for_no_more_scope_than_the_actions_need(self, settings: Settings) -> None:
        assert set(load_manifest(settings).scopes) == {"api", "refresh_token"}

    def test_it_carries_no_secret(self, settings: Settings) -> None:
        rendered = str(load_manifest(settings).model_dump())

        assert "PRIVATE KEY" not in rendered
        assert "3MVG9key" not in rendered


class TestListActions:
    def test_all_five_are_described_in_a_stable_order(self, connector: SalesforceConnector) -> None:
        first = connector.list_actions()
        second = connector.list_actions()

        assert len(first) == 5
        assert [a.action_id for a in first] == [a.action_id for a in second]


@pytest.mark.asyncio
class TestTestConnection:
    async def test_it_reads_limits_and_writes_nothing(
        self, connector: SalesforceConnector, settings: Settings
    ) -> None:
        with respx.mock:
            token_route()
            limits = respx.get(f"{DATA}/limits").mock(
                return_value=httpx.Response(200, json={"DailyApiRequests": {"Max": 5000}})
            )

            result = await connector.test_connection(settings)

            assert result.ok
            assert limits.calls.last.request.method == "GET"
            assert result.instance_url == INSTANCE

    async def test_a_failure_explains_itself_instead_of_raising(
        self, connector: SalesforceConnector, settings: Settings
    ) -> None:
        with respx.mock:
            token_route()
            respx.get(f"{DATA}/limits").mock(
                return_value=httpx.Response(
                    401, json=[{"errorCode": "INVALID_SESSION_ID", "message": "expired"}]
                )
            )

            result = await connector.test_connection(settings)

            assert not result.ok
            assert "Re-authenticate" in result.message


@pytest.mark.asyncio
class TestTheCallBudget:
    async def test_calls_within_the_budget_pass(self) -> None:
        budget = CallBudget(calls_per_minute=5)

        for _ in range(5):
            await budget.claim("salesforce.search_contact")

    async def test_a_call_beyond_the_budget_is_refused_not_queued(self) -> None:
        budget = CallBudget(calls_per_minute=2)
        await budget.claim("salesforce.search_contact")
        await budget.claim("salesforce.search_contact")

        with pytest.raises(RateLimitError) as raised:
            await budget.claim("salesforce.search_contact")

        error = raised.value.to_action_error()
        assert error.retryable is True
        assert error.retry_after_seconds is not None

    async def test_the_refusal_names_the_action_and_says_how_long_to_wait(self) -> None:
        budget = CallBudget(calls_per_minute=1)
        await budget.claim("salesforce.create_contact")

        with pytest.raises(RateLimitError) as raised:
            await budget.claim("salesforce.create_contact")

        assert "salesforce.create_contact" in raised.value.to_action_error().next_step

    async def test_an_exhausted_budget_comes_back_as_a_result_not_a_crash(
        self, connector: SalesforceConnector, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(connector, "_budget", CallBudget(calls_per_minute=1))
        request = ActionRequest(action_id="salesforce.search_contact", params={"query": "Ada"})

        with respx.mock:
            token_route()
            respx.post(f"{DATA}/parameterizedSearch").mock(
                return_value=httpx.Response(200, json={"searchRecords": []})
            )

            first = await connector.execute(request)
            second = await connector.execute(request)

        assert first.ok
        assert not second.ok
        assert second.error is not None
        assert second.error.code == "salesforce.rate_limited"


class TestApproval:
    def create_request(self, **params: str) -> ActionRequest:
        return ActionRequest(
            action_id="salesforce.create_contact",
            params={"last_name": "Lovelace", "idempotency_key": "key-1234", **params},
        )

    def test_a_token_approves_the_call_it_was_issued_for(
        self, connector: SalesforceConnector
    ) -> None:
        request = self.create_request()

        assert connector.approves(request, connector.approval_for(request))

    def test_it_does_not_approve_the_same_action_with_different_arguments(
        self, connector: SalesforceConnector
    ) -> None:
        issued_for = self.create_request()
        state = connector.approval_for(issued_for)

        assert not connector.approves(self.create_request(last_name="Someone"), state)

    def test_it_does_not_approve_a_different_action(self, connector: SalesforceConnector) -> None:
        state = connector.approval_for(self.create_request())
        other = ActionRequest(
            action_id="salesforce.update_contact",
            params={"last_name": "Lovelace", "idempotency_key": "key-1234"},
        )

        assert not connector.approves(other, state)

    def test_a_tampered_token_is_refused(self, connector: SalesforceConnector) -> None:
        request = self.create_request()
        state = connector.approval_for(request)

        assert not connector.approves(request, state[:-4] + "AAAA")

    def test_an_expired_token_is_refused(self) -> None:
        gate = ApprovalGate(ttl_seconds=-1)
        pending = PendingWrite.of("salesforce.create_contact", {"last_name": "Lovelace"})

        assert not gate.accepts(gate.issue(pending), pending)

    def test_a_token_from_another_process_is_refused(self) -> None:
        pending = PendingWrite.of("salesforce.create_contact", {"last_name": "Lovelace"})
        issued_elsewhere = ApprovalGate().issue(pending)

        assert not ApprovalGate().accepts(issued_elsewhere, pending)

    def test_argument_order_does_not_change_the_fingerprint(self) -> None:
        assert digest_of({"a": 1, "b": 2}) == digest_of({"b": 2, "a": 1})

    def test_a_changed_value_changes_the_fingerprint(self) -> None:
        assert digest_of({"a": 1}) != digest_of({"a": 2})
