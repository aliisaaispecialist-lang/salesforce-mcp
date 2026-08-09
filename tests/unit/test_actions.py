"""What each action sends to Salesforce, and what it does with the answer.

respx intercepts at the transport layer, so these exercise the real request
objects the connector would put on the wire, without a socket.
"""

import json
from typing import Any

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from salesforce_connector.actions import registry
from salesforce_connector.auth.jwt_bearer import JwtBearerAuth
from salesforce_connector.config import Settings
from salesforce_connector.contract import ActionRequest
from salesforce_connector.errors.model import InvalidInputError
from salesforce_connector.errors.retry import RetryPolicy
from salesforce_connector.transport.client import SalesforceClient

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
        assert len(registry.BY_ID) == 17

    def test_the_order_is_stable_rather_than_incidental(self) -> None:
        assert list(registry.BY_ID) == sorted(registry.BY_ID)

    def test_descriptors_carry_the_rendered_description(self) -> None:
        described = registry.descriptors()

        assert len(described) == 17
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


def describing_stages(stages: tuple[str, ...]) -> httpx.Response:
    """The describe response the stage check reads."""
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


@pytest.mark.asyncio
class TestCreateOpportunity:
    def describe(self, stages: tuple[str, ...]) -> httpx.Response:
        return describing_stages(stages)

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


@pytest.mark.asyncio
class TestCreateOpportunityWithContact:
    """The atomic pair, and the failure Salesforce hides inside a success."""

    async def test_both_records_come_back_from_one_call(self, client: SalesforceClient) -> None:
        async with client, respx.mock:
            token_route()
            respx.get(f"{DATA}/sobjects/Opportunity/describe").mock(
                return_value=describing_stages(("Qualify", "Negotiate"))
            )
            route = respx.post(f"{DATA}/composite").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "compositeResponse": [
                            {
                                "body": {"id": "006new", "success": True},
                                "httpStatusCode": 201,
                                "referenceId": "newOpportunity",
                            },
                            {
                                "body": {"id": "00Knew", "success": True},
                                "httpStatusCode": 201,
                                "referenceId": "contactRole",
                            },
                        ]
                    },
                )
            )

            result = await run(
                client,
                "salesforce.create_opportunity_with_contact",
                name="Example Corp - renewal",
                stage_name="Qualify",
                close_date="2026-12-01",
                contact_id="003xx000004TmiQAAS",
                idempotency_key=KEY,
                approved=True,
            )

            assert result.ok
            assert result.data["id"] == "006new"
            assert result.data["contact_role_id"] == "00Knew"
            sent = json.loads(route.calls.last.request.content)
            assert sent["allOrNone"] is True
            # The role names an opportunity that has no id yet.
            assert sent["compositeRequest"][1]["body"]["OpportunityId"] == "@{newOpportunity.id}"

    async def test_a_failure_inside_a_200_is_still_a_failure(
        self, client: SalesforceClient
    ) -> None:
        """The bug this tool would otherwise ship with.

        A composite that rolled everything back answers HTTP 200. Read by
        status alone, this is a success whose ids are empty strings, and the
        caller is told a deal exists that does not.
        """
        async with client, respx.mock:
            token_route()
            respx.get(f"{DATA}/sobjects/Opportunity/describe").mock(
                return_value=describing_stages(("Qualify", "Nonexistent"))
            )
            respx.post(f"{DATA}/composite").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "compositeResponse": [
                            {
                                "body": [
                                    {
                                        "errorCode": "FIELD_CUSTOM_VALIDATION_EXCEPTION",
                                        "message": "bad stage",
                                        "fields": ["StageName"],
                                    }
                                ],
                                "httpStatusCode": 400,
                                "referenceId": "newOpportunity",
                            },
                            {
                                "body": [
                                    {"errorCode": "PROCESSING_HALTED", "message": "rolled back"}
                                ],
                                "httpStatusCode": 400,
                                "referenceId": "contactRole",
                            },
                        ]
                    },
                )
            )

            result = await run(
                client,
                "salesforce.create_opportunity_with_contact",
                name="Example Corp - renewal",
                stage_name="Nonexistent",
                close_date="2026-12-01",
                contact_id="003xx000004TmiQAAS",
                idempotency_key=KEY,
                approved=True,
            )

            assert not result.ok
            assert result.error is not None
            # Blamed on the subrequest that failed, not the one it halted.
            assert "bad stage" in result.error.reason
            assert "PROCESSING_HALTED" not in result.error.reason


@pytest.mark.asyncio
class TestTheRouter:
    """Choosing a tool without reading all seventeen, and calling it correctly."""

    async def test_asking_for_writes_lists_only_what_changes_data(
        self, client: SalesforceClient
    ) -> None:
        async with client:
            result = await run(client, "salesforce.list_tools", kind="write")

            assert result.ok
            assert result.data["tools"]
            assert all(one["changes_data"] for one in result.data["tools"])
            assert all(one["needs_approval"] for one in result.data["tools"])
            assert "salesforce_tool_schema" in result.data["next_action"]

    async def test_asking_for_reads_lists_nothing_that_changes_data(
        self, client: SalesforceClient
    ) -> None:
        async with client:
            result = await run(client, "salesforce.list_tools", kind="read")

            assert result.ok
            assert not any(one["changes_data"] for one in result.data["tools"])

    async def test_every_registered_tool_can_be_found_through_the_router(
        self, client: SalesforceClient
    ) -> None:
        """The one way this pair can quietly go wrong.

        A tool added to the registry and missing from here would be invisible
        to anything that routes, while still being published. Derived from the
        registry rather than listed, so this holds by construction -- and fails
        loudly if that ever stops being true.
        """
        async with client:
            result = await run(client, "salesforce.list_tools", kind="all")

            listed = {one["name"] for one in result.data["tools"]}
            assert listed == {action.spec.tool_name for action in registry.BY_ID.values()}

    async def test_a_field_expecting_a_number_says_so_in_words(
        self, client: SalesforceClient
    ) -> None:
        async with client:
            result = await run(
                client, "salesforce.tool_schema", tool_name="salesforce_create_opportunity"
            )

            assert result.ok
            amount = next(one for one in result.data["fields"] if one["name"] == "amount")
            assert amount["type"] == "a number, written in digits"
            assert amount["example"] == "45000"

    async def test_a_field_with_fixed_values_lists_them_rather_than_naming_the_enum(
        self, client: SalesforceClient
    ) -> None:
        async with client:
            result = await run(
                client, "salesforce.tool_schema", tool_name="salesforce_add_activity_note"
            )

            kind = next(one for one in result.data["fields"] if one["name"] == "activity_kind")
            assert kind["type"] == "exactly one of: Call, Email, Meeting, Other"

    async def test_required_fields_are_reported_first(self, client: SalesforceClient) -> None:
        async with client:
            result = await run(
                client, "salesforce.tool_schema", tool_name="salesforce_create_contact"
            )

            required = [one["required"] for one in result.data["fields"]]
            assert required == sorted(required, reverse=True)

    async def test_an_unknown_tool_name_is_answered_with_the_real_ones(
        self, client: SalesforceClient
    ) -> None:
        async with client:
            result = await run(client, "salesforce.tool_schema", tool_name="salesforce_delete_all")

            assert not result.ok
            assert result.error is not None
            assert "salesforce_search_contact" in result.error.next_step


@pytest.mark.asyncio
class TestWrongTypesAreExplainedNotJustRejected:
    """The failure the router exists to prevent, checked where it lands."""

    async def test_a_number_written_as_a_word_is_told_to_use_digits(
        self, client: SalesforceClient
    ) -> None:
        async with client:
            result = await run(
                client,
                "salesforce.create_opportunity",
                name="Renewal",
                stage_name="Qualify",
                close_date="2026-12-01",
                amount="one",
                idempotency_key=KEY,
            )

            assert not result.ok
            assert result.error is not None
            assert "a number, written in digits" in result.error.reason
            assert "45000" in result.error.reason

    async def test_a_date_in_words_is_told_the_format(self, client: SalesforceClient) -> None:
        async with client:
            result = await run(
                client,
                "salesforce.create_opportunity",
                name="Renewal",
                stage_name="Qualify",
                close_date="next Tuesday",
                idempotency_key=KEY,
            )

            assert not result.ok
            assert result.error is not None
            assert "YYYY-MM-DD" in result.error.reason

    async def test_a_value_outside_a_fixed_set_is_told_the_whole_set(
        self, client: SalesforceClient
    ) -> None:
        async with client:
            result = await run(
                client,
                "salesforce.add_activity_note",
                related_to_id="003xx000004TmiQAAS",
                subject="Called them",
                activity_kind="phone call",
                idempotency_key=KEY,
            )

            assert not result.ok
            assert result.error is not None
            assert "Call, Email, Meeting, Other" in result.error.reason


@pytest.mark.asyncio
class TestASuccessMustCarryAnId:
    """A 2xx with no record id is not a success anybody can use."""

    async def test_a_create_with_no_id_is_a_failure_not_an_empty_success(
        self, client: SalesforceClient
    ) -> None:
        """Nothing declared `id` non-empty, so `""` validated and came back ok.

        Reported as retryable, because the write may have landed and the
        caller's idempotency key is what makes asking again safe.
        """
        async with client, respx.mock:
            token_route()
            respx.post(f"{DATA}/sobjects/Contact").mock(
                return_value=httpx.Response(201, json={"success": True})
            )

            result = await run(
                client,
                "salesforce.create_contact",
                last_name="Lovelace",
                idempotency_key=KEY,
                approved=True,
            )

            assert not result.ok
            assert result.error is not None
            assert "no record id" in result.error.reason

    async def test_an_upsert_that_updated_may_answer_without_a_body(
        self, client: SalesforceClient
    ) -> None:
        """An update answers 204 and nothing, which is ordinary, not a fault."""
        async with client, respx.mock:
            token_route()
            respx.patch(f"{DATA}/sobjects/Contact/External_Id__c/CRM-4471").mock(
                return_value=httpx.Response(204)
            )

            result = await run(
                client,
                "salesforce.upsert_record",
                object_name="Contact",
                external_id_field="External_Id__c",
                external_id_value="CRM-4471",
                fields={"LastName": "Lovelace"},
                idempotency_key=KEY,
                approved=True,
            )

            assert result.ok
            assert result.data["created"] is False


@pytest.mark.asyncio
class TestAWriteIsNotUndoneByTheReadAfterIt:
    async def test_a_failed_read_back_still_reports_the_write(
        self, client: SalesforceClient
    ) -> None:
        """The PATCH landed. Only the confirmation read failed.

        This used to fail the whole action, telling the caller the update had
        not happened when it had -- and a retry on that advice would apply it
        twice.
        """
        async with client, respx.mock:
            token_route()
            respx.patch(f"{DATA}/sobjects/Account/001xx000003DGb2AAG").mock(
                return_value=httpx.Response(204)
            )
            respx.get(f"{DATA}/sobjects/Account/001xx000003DGb2AAG").mock(
                side_effect=httpx.ReadTimeout("too slow")
            )

            result = await run(
                client,
                "salesforce.update_record",
                object_name="Account",
                record_id="001xx000003DGb2AAG",
                fields={"Industry": "Technology"},
                idempotency_key=KEY,
                approved=True,
            )

            assert result.ok
            assert result.data["changed_fields"] == ["Industry"]
            assert result.warnings
            assert "was applied" in result.warnings[0]
            assert "Do not repeat" in result.warnings[0]


@pytest.mark.asyncio
class TestTheAtomicityClaimIsChecked:
    """The tool tells a person nothing was left half-done. Now it verifies it."""

    async def test_a_success_beside_a_failure_goes_to_a_human(
        self, client: SalesforceClient
    ) -> None:
        async with client, respx.mock:
            token_route()
            respx.get(f"{DATA}/sobjects/Opportunity/describe").mock(
                return_value=describing_stages(("Qualify",))
            )
            respx.post(f"{DATA}/composite").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "compositeResponse": [
                            {
                                "body": {"id": "006orphan", "success": True},
                                "httpStatusCode": 201,
                                "referenceId": "newOpportunity",
                            },
                            {
                                "body": [{"errorCode": "INVALID_CROSS_REFERENCE_KEY"}],
                                "httpStatusCode": 400,
                                "referenceId": "contactRole",
                            },
                        ]
                    },
                )
            )

            result = await run(
                client,
                "salesforce.create_opportunity_with_contact",
                name="Renewal",
                stage_name="Qualify",
                close_date="2026-12-01",
                contact_id="003xx000004TmiQAAS",
                idempotency_key=KEY,
                approved=True,
            )

            assert not result.ok
            assert result.error is not None
            assert result.error.code == "connector.escalate_to_human"
            # Names the record nobody is expecting.
            assert "006orphan" in result.error.reason

    async def test_a_short_response_is_not_read_as_success(self, client: SalesforceClient) -> None:
        async with client, respx.mock:
            token_route()
            respx.get(f"{DATA}/sobjects/Opportunity/describe").mock(
                return_value=describing_stages(("Qualify",))
            )
            respx.post(f"{DATA}/composite").mock(
                return_value=httpx.Response(200, json={"compositeResponse": []})
            )

            result = await run(
                client,
                "salesforce.create_opportunity_with_contact",
                name="Renewal",
                stage_name="Qualify",
                close_date="2026-12-01",
                contact_id="003xx000004TmiQAAS",
                idempotency_key=KEY,
                approved=True,
            )

            assert not result.ok
            assert result.error is not None
            assert "0 results for 2" in result.error.reason

    async def test_the_stage_is_checked_here_too(self, client: SalesforceClient) -> None:
        """The description promised this. Only the other tool delivered it."""
        async with client, respx.mock:
            token_route()
            respx.get(f"{DATA}/sobjects/Opportunity/describe").mock(
                return_value=describing_stages(("Qualify", "Closed Won"))
            )
            composite = respx.post(f"{DATA}/composite").mock(
                return_value=httpx.Response(200, json={"compositeResponse": []})
            )

            result = await run(
                client,
                "salesforce.create_opportunity_with_contact",
                name="Renewal",
                stage_name="Prospecting",
                close_date="2026-12-01",
                contact_id="003xx000004TmiQAAS",
                idempotency_key=KEY,
                approved=True,
            )

            assert not result.ok
            assert not composite.called
            assert result.error is not None
            assert "Qualify, Closed Won" in result.error.next_step
