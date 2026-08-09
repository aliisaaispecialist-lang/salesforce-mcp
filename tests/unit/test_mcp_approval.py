"""Asking a person before a write, exercised through the fake client's answers.

The interesting cases are all the ways an answer is not a yes: a decline, a
cancel, an accepted form with the box left unchecked, and content the SDK
cannot validate. Each has to end with nothing written, because the alternative
-- a dialog dismissed and the record created anyway -- is the failure this
whole path exists to prevent.

A client that never declared the elicitation capability is the other half. It
is not asked at all, because the specification forbids sending a request whose
capability was not declared, and the write falls through to the action's own
refusal.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pytest
from mcp.types import CallToolRequestParams, CallToolResult, ElicitResult, TextContent

from salesforce_connector.actions import registry
from salesforce_connector.approval.elicit import (
    DECLINED,
    TAMPERED,
    UNREADABLE,
    ConfirmWrite,
    WriteApproval,
)
from salesforce_connector.approval.gate import ApprovalGate
from salesforce_connector.contract import ActionRequest, ActionResult
from salesforce_connector.protocol import server as mcp_server

CONTACT_ARGUMENTS: Mapping[str, Any] = {
    "last_name": "Lovelace",
    "first_name": "Ada",
    "idempotency_key": "key-12345678",
}


@dataclass
class Declared:
    """Only the one capability this code reads."""

    elicitation: object | None


class FakeSession:
    """Stands in for the client, answering however the test says."""

    def __init__(self, answer: ElicitResult | None, *, declares: bool = True) -> None:
        self._answer = answer
        self.client_capabilities = Declared(elicitation={} if declares else None)
        self.asked: list[str] = []

    async def elicit_form(
        self,
        message: str,
        requested_schema: Mapping[str, Any],
        related_request_id: object = None,
    ) -> ElicitResult:
        self.asked.append(message)
        assert self._answer is not None, "this client should never have been asked"
        return self._answer


@dataclass
class FakeContext:
    """The three fields these paths read off a live request."""

    session: FakeSession
    request_id: str | None = "req-1"
    lifespan_context: Any = None


def as_ctx(session: FakeSession) -> Any:
    """Hand the fake over as a request context.

    FakeContext carries the two fields the approval path reads and nothing
    else, which is the point: a stand-in for ServerRequestContext that
    satisfied it structurally would drag in a live session.
    """
    return FakeContext(session)


class SpyConnector:
    """Records what reached the connector, and answers with a bare success."""

    def __init__(self) -> None:
        self.executed: list[ActionRequest] = []

    def list_actions(self) -> tuple[Any, ...]:
        return registry.descriptors()

    async def execute(self, request: ActionRequest) -> ActionResult:
        self.executed.append(request)
        return ActionResult(ok=True, request_id="req-1", data={"id": "003xx"})


def server_context(session: FakeSession, connector: SpyConnector) -> Any:
    """Assemble what `call_tool` reads: a connector and an approval, no more."""
    return FakeContext(
        session,
        lifespan_context=mcp_server.AppContext(
            connector=connector,  # type: ignore[arg-type]
            approval=WriteApproval(ApprovalGate()),
            surface="full",
        ),
    )


def write_request(**overrides: Any) -> ActionRequest:
    params = {**CONTACT_ARGUMENTS, **overrides}
    return ActionRequest(
        action_id="salesforce.create_contact",
        params=params,
        idempotency_key="key-12345678",
        approved=False,
    )


def contact_action() -> Any:
    return next(d for d in registry.descriptors() if d.action_id == "salesforce.create_contact")


def read_action() -> Any:
    return next(d for d in registry.descriptors() if not d.requires_approval)


def approval() -> WriteApproval:
    return WriteApproval(ApprovalGate())


def refused_with(result: CallToolResult, code: str) -> bool:
    """The code travels at the front of the text, where a model will read it."""
    assert result.is_error
    return any(
        isinstance(part, TextContent) and part.text.startswith(f"[{code}] ")
        for part in result.content
    )


class TestAYesLetsTheWriteThrough:
    @pytest.mark.asyncio
    async def test_a_confirmed_form_marks_the_request_approved(self) -> None:
        session = FakeSession(ElicitResult(action="accept", content={"confirm": True}))

        settled = await approval().granted(as_ctx(session), contact_action(), write_request())

        assert isinstance(settled, ActionRequest)
        assert settled.approved is True

    @pytest.mark.asyncio
    async def test_the_question_names_the_action_and_shows_the_values(self) -> None:
        session = FakeSession(ElicitResult(action="accept", content={"confirm": True}))

        await approval().granted(as_ctx(session), contact_action(), write_request())

        asked = session.asked[0]
        assert "Lovelace" in asked
        # A person cannot approve what they were not shown, and the two fields
        # that are bookkeeping rather than the caller's intent stay out of it.
        assert "key-12345678" not in asked
        assert "approved" not in asked


class TestEverythingElseStopsTheWrite:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "answer",
        [
            ElicitResult(action="decline"),
            ElicitResult(action="cancel"),
            ElicitResult(action="accept", content={"confirm": False}),
        ],
        ids=["declined", "cancelled", "unchecked"],
    )
    async def test_no_answer_short_of_a_yes_approves(self, answer: ElicitResult) -> None:
        session = FakeSession(answer)

        settled = await approval().granted(as_ctx(session), contact_action(), write_request())

        assert isinstance(settled, CallToolResult)
        assert refused_with(settled, DECLINED)

    @pytest.mark.asyncio
    async def test_content_the_sdk_cannot_validate_is_not_consent(self) -> None:
        # The SDK raises rather than returning here. An exception escaping into
        # the tool result would say "something went wrong", which a model may
        # well retry; this says plainly that nothing was written.
        session = FakeSession(ElicitResult(action="accept", content={"confirm": "maybe"}))

        settled = await approval().granted(as_ctx(session), contact_action(), write_request())

        assert isinstance(settled, CallToolResult)
        assert refused_with(settled, UNREADABLE)


class TestWhoGetsAsked:
    @pytest.mark.asyncio
    async def test_a_client_without_the_capability_is_never_asked(self) -> None:
        session = FakeSession(answer=None, declares=False)

        settled = await approval().granted(as_ctx(session), contact_action(), write_request())

        assert session.asked == []
        # Untouched: still unapproved, so the action refuses and says how.
        assert isinstance(settled, ActionRequest)
        assert settled.approved is False

    @pytest.mark.asyncio
    async def test_a_read_is_never_asked_about(self) -> None:
        session = FakeSession(answer=None)
        request = ActionRequest(action_id="salesforce.search_contact", params={"query": "ada"})

        settled = await approval().granted(as_ctx(session), read_action(), request)

        assert session.asked == []
        assert settled is request

    @pytest.mark.asyncio
    async def test_a_client_that_cannot_be_asked_keeps_the_flag_it_sent(self) -> None:
        # The fallback path, and the whole of it: no question, and the caller's
        # own assertion is what the action will judge.
        session = FakeSession(answer=None, declares=False)

        settled = await approval().granted(
            as_ctx(session),
            contact_action(),
            write_request().model_copy(update={"approved": True}),
        )

        assert session.asked == []
        assert isinstance(settled, ActionRequest)
        assert settled.approved is True

    @pytest.mark.asyncio
    async def test_a_caller_that_asserts_approval_is_asked_anyway(self) -> None:
        # The flag is the one thing that cannot be trusted: a model sets it as
        # easily as a host does. A client that declared elicitation never needs
        # to send it, so its presence buys nothing and skips nothing.
        session = FakeSession(ElicitResult(action="decline"))

        settled = await approval().granted(
            as_ctx(session),
            contact_action(),
            write_request().model_copy(update={"approved": True}),
        )

        assert len(session.asked) == 1
        assert isinstance(settled, CallToolResult)
        assert refused_with(settled, DECLINED)


class TestTheApprovalIsBoundToTheCall:
    """What the ticket buys, given the answer arrives inside the same call.

    A ticket that never leaves the process cannot be swapped for another call's
    -- the gate's own tests in test_connector.py cover that, and it is what
    would matter if the answer ever came back over a second round trip. What it
    buys here and now is the clock: an approval dialog left open all afternoon
    stops being an approval, and the write is refused rather than made on the
    strength of a yes the person has long since walked away from.
    """

    @pytest.mark.asyncio
    async def test_a_yes_that_arrives_too_late_does_not_write(self) -> None:
        expiring = WriteApproval(ApprovalGate(ttl_seconds=-1))
        session = FakeSession(ElicitResult(action="accept", content={"confirm": True}))

        settled = await expiring.granted(as_ctx(session), contact_action(), write_request())

        assert session.asked, "the person was still asked"
        assert isinstance(settled, CallToolResult)
        assert refused_with(settled, TAMPERED)

    @pytest.mark.asyncio
    async def test_a_yes_in_time_writes(self) -> None:
        patient = WriteApproval(ApprovalGate(ttl_seconds=600))
        session = FakeSession(ElicitResult(action="accept", content={"confirm": True}))

        settled = await patient.granted(as_ctx(session), contact_action(), write_request())

        assert isinstance(settled, ActionRequest)
        assert settled.approved is True


class TestNothingReachesTheConnectorUnapproved:
    """The one arrangement that matters, assembled the way the server does.

    Each half is tested above on its own. This checks the wiring between them:
    that `call_tool` really does run the approval before `execute`, so a write
    a person turned down never becomes a request the connector sees.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("answer", "executed"),
        [
            (ElicitResult(action="decline"), []),
            (
                ElicitResult(action="accept", content={"confirm": True}),
                ["salesforce.create_contact"],
            ),
        ],
        ids=["declined-never-executes", "accepted-executes"],
    )
    async def test_the_connector_is_called_only_after_a_yes(
        self, answer: ElicitResult, executed: list[str]
    ) -> None:
        session = FakeSession(answer)
        spy = SpyConnector()

        await mcp_server.call_tool(
            server_context(session, spy),
            CallToolRequestParams(
                name="salesforce_create_contact",
                arguments={**CONTACT_ARGUMENTS, "approved": False},
            ),
        )

        assert [request.action_id for request in spy.executed] == executed

    @pytest.mark.asyncio
    async def test_an_approved_call_arrives_at_the_connector_marked_approved(self) -> None:
        session = FakeSession(ElicitResult(action="accept", content={"confirm": True}))
        spy = SpyConnector()

        await mcp_server.call_tool(
            server_context(session, spy),
            CallToolRequestParams(
                name="salesforce_create_contact", arguments=dict(CONTACT_ARGUMENTS)
            ),
        )

        assert spy.executed[0].approved is True


class TestTheFormItself:
    def test_the_form_asks_one_primitive_question_and_defaults_to_no(self) -> None:
        schema = ConfirmWrite.model_json_schema()

        assert list(schema["properties"]) == ["confirm"]
        assert schema["properties"]["confirm"]["type"] == "boolean"
        assert schema["properties"]["confirm"]["default"] is False
