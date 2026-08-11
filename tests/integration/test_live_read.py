"""Searching a real org, including the one thing that might not work.

`search_contact` sends an `offset` to `parameterizedSearch` and builds its
pagination cursor from it. SOSL-backed search has not historically supported
offset the way a SOQL query does, and this project refused to claim it worked
without checking. `test_the_second_page_is_not_the_first_page_again` is that
check, and it is by far the most likely test here to fail.

If it does, it is a connector bug rather than a test bug: page two silently
repeating page one is worse than any error, because a caller walking the cursor
would loop forever believing it was making progress.
"""

import pytest

from tests.live_org import Org, needs_an_org, unwrap

pytestmark = [pytest.mark.integration, needs_an_org]

PAGE = 3
ENOUGH_TO_PAGE = PAGE + 2


class TestSearchingForNothing:
    @pytest.mark.asyncio
    async def test_a_search_matching_nobody_succeeds_with_an_empty_list(self, org: Org) -> None:
        # Empty is not an error. A model told "no such contact" creates one; a
        # model told "that search failed" asks the user.
        found = unwrap(
            await org.call("salesforce.contact_search_by_text", query="MCPTestNoSuchPerson")
        )

        assert found["contacts"] == []
        assert found["returned"] == 0
        assert found.get("next_cursor") is None

    @pytest.mark.asyncio
    async def test_a_query_that_is_too_short_never_reaches_the_network(self, org: Org) -> None:
        result = await org.call("salesforce.contact_search_by_text", query="a")

        assert not result.ok
        assert result.error is not None
        assert result.error.code == "connector.invalid_input"


class TestFindingWhatWeJustCreated:
    @pytest.mark.asyncio
    async def test_a_created_contact_can_be_found_by_name(self, org: Org) -> None:
        made = unwrap(
            await org.call(
                "salesforce.contact_create",
                last_name=org.marker,
                first_name="Ada",
                idempotency_key=org.key,
            )
        )
        org.litter.track("Contact", made["id"])

        found = unwrap(await org.call("salesforce.contact_search_by_text", query=org.marker))

        # Salesforce search is index-backed and eventually consistent. If this
        # is flaky rather than failing, that delay is why -- and it is the
        # org's behaviour, so record it in tests/learning/ rather than papering
        # over it with a sleep here.
        assert any(contact["id"] == made["id"] for contact in found["contacts"]), (
            f"created {made['id']} but searching {org.marker!r} did not return it; "
            "search indexing may lag a write"
        )

    @pytest.mark.asyncio
    async def test_every_field_the_schema_promises_is_populated(self, org: Org) -> None:
        made = unwrap(
            await org.call(
                "salesforce.contact_create",
                last_name=org.marker,
                first_name="Grace",
                email=f"{org.marker.lower()}@example.com",
                title="Chief Analyst",
                idempotency_key=org.key,
            )
        )
        org.litter.track("Contact", made["id"])

        found = unwrap(await org.call("salesforce.contact_search_by_text", query=org.marker))
        contact = next(c for c in found["contacts"] if c["id"] == made["id"])

        assert contact["name"]
        assert contact["email"] == f"{org.marker.lower()}@example.com"
        assert contact["title"] == "Chief Analyst"
        # ADR-023: the account is an id, and account_name is deliberately gone.
        assert "account_name" not in contact


class TestPagination:
    @pytest.mark.asyncio
    async def test_the_second_page_is_not_the_first_page_again(self, org: Org) -> None:
        """The open question this whole suite exists to settle.

        Five contacts sharing a searchable word, read three at a time. If
        `offset` is honoured, page two holds the rest and no id repeats. If
        Salesforce ignores it, page two is page one.
        """
        for index in range(ENOUGH_TO_PAGE):
            made = unwrap(
                await org.call(
                    "salesforce.contact_create",
                    last_name=org.marker,
                    first_name=f"Pager{index}",
                    idempotency_key=f"{org.key}-{index}",
                )
            )
            org.litter.track("Contact", made["id"])

        first = unwrap(
            await org.call("salesforce.contact_search_by_text", query=org.marker, limit=PAGE)
        )
        assert first["returned"] == PAGE, "not enough matches to page; indexing may lag"
        assert first["next_cursor"] is not None, "a full page must offer a cursor"

        second = unwrap(
            await org.call(
                "salesforce.contact_search_by_text",
                query=org.marker,
                limit=PAGE,
                cursor=first["next_cursor"],
            )
        )

        seen = {c["id"] for c in first["contacts"]}
        again = {c["id"] for c in second["contacts"]}
        assert not (seen & again), (
            "page two repeated records from page one. parameterizedSearch is "
            "ignoring the offset that actions/search_contact.py sends, so the "
            "cursor never advances and a caller walking it would loop. This is "
            f"a connector bug: pagination needs another mechanism. Repeated: "
            f"{sorted(seen & again)}"
        )

    @pytest.mark.asyncio
    async def test_the_last_page_offers_no_cursor(self, org: Org) -> None:
        made = unwrap(
            await org.call(
                "salesforce.contact_create", last_name=org.marker, idempotency_key=org.key
            )
        )
        org.litter.track("Contact", made["id"])

        page = unwrap(
            await org.call("salesforce.contact_search_by_text", query=org.marker, limit=50)
        )

        # Fewer results than asked for means there is nothing more to ask for.
        assert page["next_cursor"] is None

    @pytest.mark.asyncio
    async def test_paging_position_reaches_the_envelope(self, org: Org) -> None:
        made = unwrap(
            await org.call(
                "salesforce.contact_create", last_name=org.marker, idempotency_key=org.key
            )
        )
        org.litter.track("Contact", made["id"])

        result = await org.call("salesforce.contact_search_by_text", query=org.marker)

        assert result.pagination is not None
        assert result.pagination.returned >= 1
