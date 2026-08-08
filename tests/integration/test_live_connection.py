"""The first thing to run against a real org, and the only one that must pass.

If these fail, nothing else in this directory is worth reading: the credential,
the Connected App, and the pre-authorisation are the three things that go wrong
during setup, and all three surface here.

Definition of Done item 9 asks for one real sandbox test. This is it, and it is
deliberately the one that changes nothing.
"""

import pytest

from tests.live_org import Org, needs_an_org

pytestmark = [pytest.mark.integration, needs_an_org]

SETUP_ADVICE = (
    "Check, in this order: the Connected App has finished propagating (2-10 "
    "minutes after saving), Permitted Users is set to 'Admin approved users "
    "are pre-authorized' with this user's profile added, and SF_USERNAME is "
    "the Salesforce username rather than an email that resembles it."
)


class TestTheOrgAnswers:
    @pytest.mark.asyncio
    async def test_the_credentials_work(self, org: Org) -> None:
        result = await org.connector.test_connection(org.settings)

        assert result.ok, f"could not reach the org: {result.message}\n\n{SETUP_ADVICE}"

    @pytest.mark.asyncio
    async def test_it_reports_which_org_answered(self, org: Org) -> None:
        result = await org.connector.test_connection(org.settings)

        assert result.instance_url.startswith("https://")
        assert result.api_version == org.settings.api_version

    @pytest.mark.asyncio
    async def test_it_changes_nothing(self, org: Org) -> None:
        # Checked rather than restated: nothing is registered for cleanup here,
        # and the fixture fails the test if the org is left holding anything.
        await org.connector.test_connection(org.settings)

        assert org.litter.tracked == ()


class TestWhatTheOrgOffers:
    @pytest.mark.asyncio
    async def test_all_five_actions_are_available(self, org: Org) -> None:
        assert len(org.connector.list_actions()) == 9

    @pytest.mark.asyncio
    async def test_the_quota_is_reported(self, org: Org) -> None:
        # Not an assertion about a number -- a Developer Edition org and a
        # sandbox have very different allowances. Only that the org told us,
        # because a caller deciding whether to keep going needs it.
        result = await org.call("salesforce.search_contact", query="MCPTestNoSuchPerson")

        assert result.rate_limit is not None, (
            "Salesforce did not return Sforce-Limit-Info. If this fails, the "
            "header name or format has changed and client.py needs a look."
        )
        assert result.rate_limit.limit > 0
