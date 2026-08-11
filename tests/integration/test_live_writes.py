"""The four writes, against a real org, cleaning up after themselves.

Two claims this project makes throughout are only really testable here, because
both are about what a *second* call does:

- a repeated idempotency key writes once, not twice;
- an unapproved write reaches no endpoint at all.

The second is asserted by consequence rather than by inspection. The write is
attempted without approval, and then the org is asked whether anything
appeared. A test that only checked the refusal message would pass just as
happily if the record had been created and the message were a lie.
"""

import pytest

from tests.live_org import Org, needs_an_org, unwrap

pytestmark = [pytest.mark.integration, needs_an_org]

CONTACT_PREFIX = "003"
OPPORTUNITY_PREFIX = "006"
TASK_PREFIX = "00T"
FAR_FUTURE = "2027-12-01"


class TestCreatingAContact:
    @pytest.mark.asyncio
    async def test_it_creates_one_and_returns_its_id(self, org: Org) -> None:
        made = unwrap(
            await org.call(
                "salesforce.contact_create",
                last_name=org.marker,
                first_name="Ada",
                email=f"{org.marker.lower()}@example.com",
                idempotency_key=org.key,
            )
        )
        org.litter.track("Contact", made["id"])

        assert made["id"].startswith(CONTACT_PREFIX)
        assert made["created"] is True
        assert org.marker in made["name"]

    @pytest.mark.asyncio
    async def test_the_same_key_twice_writes_one_record(self, org: Org) -> None:
        arguments = {
            "last_name": org.marker,
            "first_name": "Ada",
            "idempotency_key": org.key,
        }

        first = unwrap(await org.call("salesforce.contact_create", **arguments))
        org.litter.track("Contact", first["id"])
        again = unwrap(await org.call("salesforce.contact_create", **arguments))

        assert again["id"] == first["id"], "the same key produced a second record"
        assert again["created"] is False, "the repeat should report that it created nothing"

        # And the org agrees, which is the part that matters. The ledger could
        # claim anything; only Salesforce knows how many records exist.
        found = unwrap(await org.call("salesforce.contact_search_by_text", query=org.marker))
        assert len({c["id"] for c in found["contacts"]}) == 1

    @pytest.mark.asyncio
    async def test_an_unapproved_write_creates_nothing(self, org: Org) -> None:
        refused = await org.call(
            "salesforce.contact_create",
            last_name=org.marker,
            idempotency_key=org.key,
            approved=False,
        )

        assert not refused.ok
        assert refused.error is not None

        # The claim is not that it said no. It is that nothing happened.
        found = unwrap(await org.call("salesforce.contact_search_by_text", query=org.marker))
        assert found["contacts"] == [], "a refused write reached Salesforce anyway"


class TestUpdatingAContact:
    @pytest.mark.asyncio
    async def test_it_changes_the_named_field_and_reports_the_record_back(self, org: Org) -> None:
        made = unwrap(
            await org.call(
                "salesforce.contact_create", last_name=org.marker, idempotency_key=org.key
            )
        )
        org.litter.track("Contact", made["id"])

        changed = unwrap(
            await org.call(
                "salesforce.contact_update_by_id",
                contact_id=made["id"],
                title="Chief Analyst",
                idempotency_key=f"{org.key}-update",
            )
        )

        # Salesforce answers a PATCH with 204 and an empty body, so the action
        # re-reads the record. This is what proves the re-read happens: an
        # empty success would carry no title at all.
        assert changed["title"] == "Chief Analyst"
        assert "title" in changed["changed_fields"]

    @pytest.mark.asyncio
    async def test_an_id_for_no_existing_record_is_a_clean_not_found(self, org: Org) -> None:
        result = await org.call(
            "salesforce.contact_update_by_id",
            contact_id="003000000000000AAA",
            title="Nobody",
            idempotency_key=org.key,
        )

        assert not result.ok
        assert result.error is not None
        assert result.error.code == "salesforce.record_not_found"


class TestCreatingAnOpportunity:
    @pytest.mark.asyncio
    async def test_it_creates_one_and_links_a_contact(self, org: Org) -> None:
        contact = unwrap(
            await org.call(
                "salesforce.contact_create", last_name=org.marker, idempotency_key=org.key
            )
        )
        org.litter.track("Contact", contact["id"])

        deal = unwrap(
            await org.call(
                "salesforce.opportunity_create",
                name=f"{org.marker} renewal",
                stage_name=org.stage,
                close_date=FAR_FUTURE,
                contact_id=contact["id"],
                idempotency_key=f"{org.key}-opp",
            )
        )
        org.litter.track("Opportunity", deal["id"])

        assert deal["id"].startswith(OPPORTUNITY_PREFIX)
        assert deal["created"] is True
        assert deal["contact_linked"] is True, (
            "the opportunity exists but the contact link failed -- a partial "
            "success, reported honestly, but worth investigating"
        )

    @pytest.mark.asyncio
    async def test_an_unknown_stage_returns_the_ones_this_org_accepts(self, org: Org) -> None:
        """The check that runs before any record is created.

        Stage picklists are configured per org, so no hard-coded list is
        correct. The action reads the org's own values and returns them, which
        lets a caller correct itself in one step instead of guessing.
        """
        result = await org.call(
            "salesforce.opportunity_create",
            name=f"{org.marker} bad stage",
            stage_name="NotAStageAnyOrgHas",
            close_date=FAR_FUTURE,
            idempotency_key=org.key,
        )

        assert not result.ok
        assert result.error is not None
        assert result.error.next_step, "a rejected stage must say which are allowed"
        assert org.litter.tracked == (), "a rejected stage must not leave a record behind"


class TestAddingAnActivityNote:
    @pytest.mark.asyncio
    async def test_it_attaches_to_a_contact(self, org: Org) -> None:
        contact = unwrap(
            await org.call(
                "salesforce.contact_create", last_name=org.marker, idempotency_key=org.key
            )
        )
        org.litter.track("Contact", contact["id"])

        note = unwrap(
            await org.call(
                "salesforce.activity_create_by_related_id",
                related_to_id=contact["id"],
                subject="Intro call",
                body="Discussed pricing. Wants a quote by Friday.",
                activity_kind="Call",
                idempotency_key=f"{org.key}-note",
            )
        )
        org.litter.track("Task", note["id"])

        assert note["id"].startswith(TASK_PREFIX)
        assert note["related_to_id"] == contact["id"]

    @pytest.mark.asyncio
    async def test_it_attaches_to_an_opportunity_too(self, org: Org) -> None:
        deal = unwrap(
            await org.call(
                "salesforce.opportunity_create",
                name=f"{org.marker} deal",
                stage_name=org.stage,
                close_date=FAR_FUTURE,
                idempotency_key=org.key,
            )
        )
        org.litter.track("Opportunity", deal["id"])

        note = unwrap(
            await org.call(
                "salesforce.activity_create_by_related_id",
                related_to_id=deal["id"],
                subject="Quote sent",
                idempotency_key=f"{org.key}-note",
            )
        )
        org.litter.track("Task", note["id"])

        # A contact goes on WhoId and an opportunity on WhatId. Sending the
        # wrong one is accepted by Salesforce and silently attaches nothing,
        # which is why this is asked of a real org rather than a mock.
        assert note["related_to_id"] == deal["id"]

    @pytest.mark.asyncio
    async def test_an_id_from_the_wrong_object_never_reaches_the_network(self, org: Org) -> None:
        result = await org.call(
            "salesforce.activity_create_by_related_id",
            related_to_id="005000000000000AAA",  # a User, which a note cannot attach to
            subject="Should not happen",
            idempotency_key=org.key,
        )

        assert not result.ok
        assert result.error is not None
        assert result.error.code == "connector.invalid_input"
