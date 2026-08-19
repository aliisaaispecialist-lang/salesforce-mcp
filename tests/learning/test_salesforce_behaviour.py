"""What Salesforce actually does, pinned so a change is visible.

Different in purpose from `tests/integration/`. Those ask whether the connector
works. These ask whether the assumptions it was built on are true -- and every
one of them was made from documentation rather than observation, because no org
existed while it was written.

Each test names the assumption and the code that leans on it. A failure here
does not necessarily mean the connector is broken. It means something believed
about Salesforce is wrong, which is a different and more useful signal than a
red integration test.

Anything learned here belongs in `docs/research/03-salesforce-api-map.md`, and
in an ADR if it changes a decision.
"""

import pytest

from salesforce_connector.errors.model import ConnectorError
from salesforce_connector.transport.exchange import RequestSpec
from tests.live_org import Org, needs_an_org, unwrap

pytestmark = [pytest.mark.learning, needs_an_org]

MISSING_CONTACT = "003000000000000AAA"


class TestHowMuchOfAWordSearchNeeds:
    """Where a search term has to line up with the word it is meant to find.

    This was got wrong twice, in opposite directions, from documentation alone,
    and only a live org settled it.

    `record_search_by_text` originally promised that "a partial word finds
    records containing it". Reading the SOSL FIND documentation, which says an
    asterisk matches "at the middle or end of your search term" and offers no
    leading wildcard, that looked plainly false, and it was rewritten to say
    partial words may not match at all.

    That correction was worse than the thing it corrected. Against a real org,
    a prefix matches perfectly well: `Pager` finds `PagerDemo`, and so does
    `Pag`. What fails is a suffix or a fragment from the middle -- `Demo` and
    `agerDemo` both find nothing. The rule is not "whole words" and not
    "contains"; it is **matches from the start of a word**.

    The cost of getting it wrong runs in both directions, which is why it is
    pinned here. Promise too much and a model trusts a search that cannot work.
    Promise too little and a model skips a search that would have worked, finds
    nothing, and creates the duplicate the whole connector is arranged to
    prevent.
    """

    @pytest.mark.asyncio
    async def test_a_prefix_finds_the_word(self, org: Org) -> None:
        """Both search descriptions promise this, so it has to be true."""
        made = unwrap(
            await org.call(
                "salesforce.contact_create", last_name=org.marker, idempotency_key=org.key
            )
        )
        org.litter.track("Contact", made["id"])

        found = unwrap(await org.call("salesforce.contact_search_by_text", query=org.marker[:-3]))

        assert any(c["id"] == made["id"] for c in found["contacts"]), (
            f"A prefix of the name found nothing. Both search descriptions tell a "
            f"model that the start of a word matches, and searching "
            f"{org.marker[:-3]!r} for {org.marker!r} did not. They are now wrong in "
            f"the direction that makes a model skip a search that would have worked."
        )

    @pytest.mark.asyncio
    async def test_a_fragment_from_the_middle_does_not(self, org: Org) -> None:
        """The half that makes the rule a rule rather than a coincidence.

        Without this, "a prefix matches" cannot be told apart from "any
        substring matches", and the descriptions would be asking a model for
        more of the name than it actually needs to supply.
        """
        made = unwrap(
            await org.call(
                "salesforce.contact_create", last_name=org.marker, idempotency_key=org.key
            )
        )
        org.litter.track("Contact", made["id"])

        found = unwrap(await org.call("salesforce.contact_search_by_text", query=org.marker[4:]))

        assert not any(c["id"] == made["id"] for c in found["contacts"]), (
            f"Searching {org.marker[4:]!r} matched {org.marker!r}, so Salesforce now "
            f"finds fragments from the middle of a word. Both search descriptions say "
            f"it does not, and are understating what a model can do."
        )


class TestWhatTheSearchEndpointHonours:
    @pytest.mark.asyncio
    async def test_parameterized_search_accepts_an_offset(self, org: Org) -> None:
        """The assumption `actions/search_contact.py` is built on.

        Its cursor is an offset, sent to `parameterizedSearch`. SOSL results
        have not historically supported offset the way a SOQL query does. An
        outright rejection here would be far better than acceptance-and-
        ignoring: an error can be handled, a silently repeated page cannot.
        """
        response = await org.client.request(
            RequestSpec(
                method="POST",
                path="parameterizedSearch",
                json_body={
                    "q": "MCPTestNoSuchPerson",
                    "fields": ["Id", "Name"],
                    "sobjects": [{"name": "Contact"}],
                    "in": "ALL",
                    "overallLimit": 2,
                    "offset": 2,
                },
            )
        )

        assert response.status < 400, (
            f"parameterizedSearch rejected `offset` (HTTP {response.status}). "
            "The cursor in actions/search_contact.py cannot work as written; "
            "pagination needs a different mechanism."
        )

    @pytest.mark.asyncio
    async def test_search_finds_a_record_soon_after_it_is_written(self, org: Org) -> None:
        """How stale search can be, recorded rather than guessed at.

        Salesforce search is index-backed and eventually consistent. The
        connector's central advice -- search before creating, to avoid a
        duplicate -- is only sound if the index can see a recent write. If this
        fails, that advice needs a caveat and the tool description needs to
        carry it.
        """
        made = unwrap(
            await org.call(
                "salesforce.contact_create", last_name=org.marker, idempotency_key=org.key
            )
        )
        org.litter.track("Contact", made["id"])

        found = unwrap(await org.call("salesforce.contact_search_by_text", query=org.marker))

        assert any(c["id"] == made["id"] for c in found["contacts"]), (
            "a contact created moments ago is not searchable yet. Record the "
            "observed delay and put it in the search tool's description: a "
            "model told to search before creating will otherwise make "
            "duplicates during that window."
        )


class TestWhatWritesReturn:
    @pytest.mark.asyncio
    async def test_a_patch_answers_204_with_no_body(self, org: Org) -> None:
        """Why `update_contact` re-reads the record.

        An empty success tells a caller nothing about what the record now
        holds. If Salesforce ever starts returning a body, the re-read becomes
        a wasted call worth removing.
        """
        made = unwrap(
            await org.call(
                "salesforce.contact_create", last_name=org.marker, idempotency_key=org.key
            )
        )
        org.litter.track("Contact", made["id"])

        response = await org.client.request(
            RequestSpec(
                method="PATCH",
                path=f"sobjects/Contact/{made['id']}",
                json_body={"Title": "Analyst"},
            )
        )

        assert response.status == 204
        assert not response.body

    @pytest.mark.asyncio
    async def test_a_create_returns_the_id_under_a_lowercase_key(self, org: Org) -> None:
        # The actions read `id` from the response. Salesforce is inconsistent
        # about casing across its APIs, and this is the one that matters.
        response = await org.client.request(
            RequestSpec(method="POST", path="sobjects/Contact", json_body={"LastName": org.marker})
        )
        org.litter.track("Contact", str(response.body["id"]))

        assert "id" in response.body
        assert response.body.get("success") is True


class TestWhatTheOrgTellsUsAboutItself:
    @pytest.mark.asyncio
    async def test_the_limit_header_is_present_and_still_parses(self, org: Org) -> None:
        """`Sforce-Limit-Info`, which the rate-limit metadata depends on.

        Asked through the parsed result rather than the raw header, because
        `Response` deliberately does not carry headers -- the client reads what
        it needs and drops the rest. That makes this the right question anyway:
        a `None` here means the header was absent *or* its documented
        `api-usage=used/limit` format changed, and both have the same
        consequence. The connector then reports no quota rather than a wrong
        one, which is safe but leaves a caller without the one number that
        tells it whether to keep going.
        """
        response = await org.client.request(RequestSpec(method="GET", path="limits"))

        assert response.rate_limit is not None, (
            "no quota parsed from Sforce-Limit-Info. Either Salesforce stopped "
            "sending the header or its format changed; see parse_rate_limit "
            "in exchange.py."
        )
        assert response.rate_limit.limit > 0
        assert response.rate_limit.used >= 0

    @pytest.mark.asyncio
    async def test_the_opportunity_stage_picklist_can_be_read(self, org: Org) -> None:
        """Why no list of stages is hard-coded anywhere.

        `create_opportunity` reads the org's own values to validate a stage and
        to tell a caller what is allowed. That depends on describe being
        readable by this user.
        """
        response = await org.client.request(
            RequestSpec(method="GET", path="sobjects/Opportunity/describe")
        )

        stage = next(f for f in response.body["fields"] if f["name"] == "StageName")

        assert stage["type"] == "picklist"
        assert stage["picklistValues"], "no stage values readable; validation cannot work"


class TestWhatFailureLooksLike:
    @pytest.mark.asyncio
    async def test_a_missing_record_is_a_404_with_a_coded_body(self, org: Org) -> None:
        """The shape `errors/mapping.py` classifies against.

        A list of objects carrying `errorCode` and `message`. The mapping
        classifies by the code's shape rather than a fixed table, so a new code
        is handled -- but a change to this *structure* would not be.
        """
        with pytest.raises(ConnectorError) as raised:
            await org.client.request(
                RequestSpec(method="GET", path=f"sobjects/Contact/{MISSING_CONTACT}")
            )

        failure = raised.value.to_action_error()
        assert failure.code == "salesforce.record_not_found"
        assert failure.next_step, "every failure must say what to do next"

    @pytest.mark.asyncio
    async def test_a_required_field_omission_names_the_field(self, org: Org) -> None:
        with pytest.raises(ConnectorError) as raised:
            await org.client.request(
                RequestSpec(method="POST", path="sobjects/Contact", json_body={})
            )

        failure = raised.value.to_action_error()
        assert failure.category == "input"
        # The connector forwards which field was wrong so a caller can fix it
        # rather than guess. If Salesforce stops naming it, that guidance is
        # empty and the tool descriptions should stop promising it.
        assert failure.invalid_fields or "LastName" in failure.reason
