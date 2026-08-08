"""What each action sends to Salesforce, and what it does with the answer.

respx intercepts at the transport layer, so these exercise the real request
objects the connector would put on the wire, without a socket.
"""

from typing import Any

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from salesforce_connector.actions import registry
from salesforce_connector.auth.jwt_bearer import JwtBearerAuth
from salesforce_connector.client import SalesforceClient
from salesforce_connector.config import Settings
from salesforce_connector.contract import ActionRequest
from salesforce_connector.errors.model import InvalidInputError
from salesforce_connector.errors.retry import RetryPolicy

INSTANCE = "https://mycompany--dev.sandbox.my.salesforce.com"
DATA = f"{INSTANCE}/services/data/v67.0"
TOKEN_URL = "https://test.salesforce.com/services/oauth2/token"
KEY = "key-abcdefgh"

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
        "salesforce_connector.client.RetryPolicy",
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


async def run(client: SalesforceClient, action_id: str, **params: Any) -> Any:
    request = ActionRequest(
        action_id=action_id,
        params=params,
        idempotency_key=params.get("idempotency_key"),
        approved=True,
    )
    return await registry.build(action_id, client).run(request)


class TestTheRegistry:
    def test_it_offers_the_five_assigned_actions_plus_the_link_split_from_one(self) -> None:
        assert len(registry.BY_ID) == 11

    def test_the_order_is_stable_rather_than_incidental(self) -> None:
        assert list(registry.BY_ID) == sorted(registry.BY_ID)

    def test_descriptors_carry_the_rendered_description(self) -> None:
        described = registry.descriptors()

        assert len(described) == 11
        assert all("Do not use this when:" in item.description for item in described)

    def test_an_unknown_action_names_the_ones_that_exist(self, client: SalesforceClient) -> None:
        with pytest.raises(InvalidInputError) as raised:
            registry.build("salesforce.nonexistent", client)

        # The remedy lists the valid ids; the reason names only what was asked for.
        assert "salesforce.search_contact" in raised.value.to_action_error().next_step


@pytest.mark.asyncio
class TestSearchContact:
    async def test_the_query_is_sent_as_data_never_as_syntax(
        self, client: SalesforceClient
    ) -> None:
        async with client, respx.mock:
            token_route()
            route = respx.post(f"{DATA}/parameterizedSearch").mock(
                return_value=httpx.Response(200, json={"searchRecords": []})
            )

            await run(client, "salesforce.search_contact", query="Ada' OR Name LIKE '%")

            sent = route.calls.last.request.content.decode()
            assert "Ada' OR Name LIKE '%" in sent  # carried as a JSON value
            assert "SELECT" not in sent.upper()

    async def test_records_are_reduced_to_the_fields_a_caller_acts_on(
        self, client: SalesforceClient
    ) -> None:
        async with client, respx.mock:
            token_route()
            respx.post(f"{DATA}/parameterizedSearch").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "searchRecords": [
                            {
                                "attributes": {"type": "Contact", "url": "/noise"},
                                "Id": "003xx",
                                "Name": "Ada Lovelace",
                                "Email": "ada@example.com",
                            }
                        ]
                    },
                )
            )

            result = await run(client, "salesforce.search_contact", query="Ada")

            assert result.ok
            assert result.data["contacts"][0]["name"] == "Ada Lovelace"
            assert "attributes" not in result.data["contacts"][0]

    async def test_a_full_page_offers_a_cursor_and_a_short_one_does_not(
        self, client: SalesforceClient
    ) -> None:
        async with client, respx.mock:
            token_route()
            respx.post(f"{DATA}/parameterizedSearch").mock(
                return_value=httpx.Response(
                    200, json={"searchRecords": [{"Id": f"003{n}", "Name": "x"} for n in range(2)]}
                )
            )

            full = await run(client, "salesforce.search_contact", query="Ada", limit=2)
            short = await run(client, "salesforce.search_contact", query="Ada", limit=50)

            assert full.data["next_cursor"] == "2"
            assert short.data["next_cursor"] is None


@pytest.mark.asyncio
class TestCreateContact:
    async def test_only_the_fields_given_are_sent(self, client: SalesforceClient) -> None:
        async with client, respx.mock:
            token_route()
            route = respx.post(f"{DATA}/sobjects/Contact").mock(
                return_value=httpx.Response(201, json={"id": "003new", "success": True})
            )

            await run(
                client,
                "salesforce.create_contact",
                last_name="Lovelace",
                idempotency_key=KEY,
            )

            sent = route.calls.last.request.content.decode()
            assert '"LastName":"Lovelace"' in sent.replace(" ", "")
            assert "Email" not in sent  # absent means absent, not null

    async def test_duplicate_rules_are_only_bypassed_when_asked(
        self, client: SalesforceClient
    ) -> None:
        async with client, respx.mock:
            token_route()
            route = respx.post(f"{DATA}/sobjects/Contact").mock(
                return_value=httpx.Response(201, json={"id": "003new"})
            )

            await run(client, "salesforce.create_contact", last_name="A", idempotency_key=KEY)
            guarded = route.calls.last.request.headers

            await run(
                client,
                "salesforce.create_contact",
                last_name="B",
                idempotency_key="key-second1",
                allow_duplicate=True,
            )
            permitted = route.calls.last.request.headers

            assert "Sforce-Duplicate-Rule-Header" not in guarded
            assert permitted["Sforce-Duplicate-Rule-Header"] == "allowSave=true"

    async def test_a_repeated_key_returns_the_first_outcome_without_writing_again(
        self, client: SalesforceClient
    ) -> None:
        async with client, respx.mock:
            token_route()
            route = respx.post(f"{DATA}/sobjects/Contact").mock(
                return_value=httpx.Response(201, json={"id": "003new"})
            )

            first = await run(
                client, "salesforce.create_contact", last_name="A", idempotency_key=KEY
            )
            second = await run(
                client, "salesforce.create_contact", last_name="A", idempotency_key=KEY
            )

            assert route.call_count == 1
            assert first.data["id"] == second.data["id"] == "003new"
            assert second.warnings


@pytest.mark.asyncio
class TestUpdateContact:
    async def test_the_record_is_read_back_because_a_patch_answers_with_nothing(
        self, client: SalesforceClient
    ) -> None:
        async with client, respx.mock:
            token_route()
            respx.patch(f"{DATA}/sobjects/Contact/003xx000004TmiQ").mock(
                return_value=httpx.Response(204)
            )
            read = respx.get(f"{DATA}/sobjects/Contact/003xx000004TmiQ").mock(
                return_value=httpx.Response(
                    200, json={"Id": "003xx000004TmiQ", "Name": "Ada L", "Title": "CTO"}
                )
            )

            result = await run(
                client,
                "salesforce.update_contact",
                contact_id="003xx000004TmiQ",
                idempotency_key=KEY,
                title="CTO",
            )

            assert read.called
            assert result.data["title"] == "CTO"
            # The caller's own name for the field, not Salesforce's. This test
            # asserted `Title` until a live org showed the provider's casing
            # leaking through an interface that is snake_case everywhere else.
            assert result.data["changed_fields"] == ["title"]


@pytest.mark.asyncio
class TestAddActivityNote:
    async def test_a_contact_hangs_from_whoid_and_an_opportunity_from_whatid(
        self, client: SalesforceClient
    ) -> None:
        async with client, respx.mock:
            token_route()
            route = respx.post(f"{DATA}/sobjects/Task").mock(
                return_value=httpx.Response(201, json={"id": "00Txx"})
            )

            await run(
                client,
                "salesforce.add_activity_note",
                related_to_id="003xx000004TmiQ",
                subject="Called",
                idempotency_key=KEY,
            )
            on_contact = route.calls.last.request.content.decode()

            await run(
                client,
                "salesforce.add_activity_note",
                related_to_id="006xx000004TmiQ",
                subject="Called",
                idempotency_key="key-second1",
            )
            on_deal = route.calls.last.request.content.decode()

            assert "WhoId" in on_contact
            assert "WhatId" not in on_contact
            assert "WhatId" in on_deal
            assert "WhoId" not in on_deal

    async def test_an_id_belonging_to_neither_is_refused_with_the_prefixes(
        self, client: SalesforceClient
    ) -> None:
        async with client, respx.mock:
            token_route()

            result = await run(
                client,
                "salesforce.add_activity_note",
                related_to_id="001xx000004TmiQ",
                subject="Called",
                idempotency_key=KEY,
            )

            assert not result.ok
            assert result.error is not None
            assert "003" in result.error.next_step


@pytest.mark.asyncio
class TestCreateOpportunity:
    def describe(self, stages: tuple[str, ...]) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "fields": [
                    {
                        "name": "StageName",
                        "picklistValues": [{"value": s, "active": True} for s in stages],
                    }
                ]
            },
        )

    async def test_a_stage_this_org_does_not_use_is_refused_with_the_ones_it_does(
        self, client: SalesforceClient
    ) -> None:
        async with client, respx.mock:
            token_route()
            respx.get(f"{DATA}/sobjects/Opportunity/describe").mock(
                return_value=self.describe(("Prospecting", "Closed Won"))
            )

            result = await run(
                client,
                "salesforce.create_opportunity",
                name="Renewal",
                stage_name="Nonsense",
                close_date="2026-12-01",
                idempotency_key=KEY,
            )

            assert not result.ok
            assert result.error is not None
            assert "Prospecting" in result.error.next_step
            assert result.error.invalid_fields == ("stage_name",)

    async def test_it_hands_over_rather_than_linking_a_contact_itself(
        self, client: SalesforceClient
    ) -> None:
        """The split, asserted from the outside.

        Linking used to happen inside this action whenever an optional
        contact_id was supplied, and could fail after the deal existed. Now the
        deal is all this tool makes, and the result names the tool that
        finishes the job and the id to give it.
        """
        async with client, respx.mock:
            token_route()
            respx.get(f"{DATA}/sobjects/Opportunity/describe").mock(
                return_value=self.describe(("Qualify",))
            )
            role = respx.post(f"{DATA}/sobjects/OpportunityContactRole").mock(
                return_value=httpx.Response(201, json={"id": "00Krole"})
            )
            respx.post(f"{DATA}/sobjects/Opportunity").mock(
                return_value=httpx.Response(201, json={"id": "006new"})
            )

            result = await run(
                client,
                "salesforce.create_opportunity",
                name="Deal",
                stage_name="Qualify",
                close_date="2030-01-01",
                idempotency_key=KEY,
            )

            assert result.ok
            assert role.call_count == 0, "this action must not write a contact role"
            assert "salesforce_link_contact_to_opportunity" in result.data["next_action"]
            assert "006new" in result.data["next_action"]

    async def test_bad_arguments_come_back_as_a_result_naming_the_field(
        self, client: SalesforceClient
    ) -> None:
        async with client, respx.mock:
            token_route()

            result = await run(client, "salesforce.search_contact", query="a")

            assert not result.ok
            assert result.error is not None
            assert result.error.invalid_fields == ("query",)

    async def test_a_write_without_approval_is_refused_before_anything_is_sent(
        self, client: SalesforceClient
    ) -> None:
        async with client, respx.mock:
            token_route()
            route = respx.post(f"{DATA}/sobjects/Contact").mock(
                return_value=httpx.Response(201, json={"id": "003new"})
            )

            action = registry.build("salesforce.create_contact", client)
            result = await action.run(
                ActionRequest(
                    action_id="salesforce.create_contact",
                    params={"last_name": "Lovelace", "idempotency_key": KEY},
                    idempotency_key=KEY,
                )
            )

            assert not result.ok
            assert not route.called
            assert result.error is not None
            assert "approved" in result.error.next_step

    async def test_a_salesforce_failure_is_a_result_with_a_remedy(
        self, client: SalesforceClient
    ) -> None:
        async with client, respx.mock:
            token_route()
            respx.post(f"{DATA}/parameterizedSearch").mock(
                return_value=httpx.Response(
                    403, json=[{"errorCode": "INSUFFICIENT_ACCESS", "message": "denied"}]
                )
            )

            result = await run(client, "salesforce.search_contact", query="Ada")

            assert not result.ok
            assert result.error is not None
            assert result.error.category.value == "resource"
            assert result.error.next_step
