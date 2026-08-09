"""Asking a person before a write, and binding their answer to that write.

A consequential write is refused unless it carries approval. This is where the
approval is obtained rather than assumed: the server asks the client to put the
question to a human, and the client answers accept, decline, or cancel. All
three answers are handled, because the specification requires it and because a
cancelled dialog that read as consent would be the worst possible default.

The ticket from `ApprovalGate` is what makes the answer mean something
specific. It is minted against the exact call the person was shown -- action id
plus a digest of the arguments -- and checked again immediately before the
write runs. So the arguments executed are the arguments displayed, and an
approval cannot be carried to a different call. That check is the whole reason
approval is a ticket rather than a boolean: a boolean says yes, a ticket says
yes to this.

If the client never declared the elicitation capability, no elicitation is
sent. The specification is explicit that a server must not send a request whose
capability the client did not declare, so those callers fall back to asserting
`approved` themselves, which is the ordinary MCP trust model for a local
server: the host is the thing showing tool calls to a person.
"""

from typing import Any, Final

from mcp.server import ServerRequestContext
from mcp.server.elicitation import AcceptedElicitation, elicit_with_validation
from mcp.types import CallToolResult
from pydantic import BaseModel, Field

from salesforce_connector.approval.gate import ApprovalGate, PendingWrite
from salesforce_connector.contract import ActionDescriptor, ActionRequest
from salesforce_connector.observability import get_logger
from salesforce_connector.protocol.translate import refuse

DECLINED: Final = "connector.approval_declined"
TAMPERED: Final = "connector.approval_invalid"
UNREADABLE: Final = "connector.approval_unreadable"

_UNREADABLE_TEXT: Final = (
    "The approval answer could not be read, so nothing was changed in Salesforce.\n\n"
    "What to do: ask the user in your own words whether to go ahead, and call this "
    "tool again only if they say yes."
)

# Neither is the caller's own value, and neither helps a person decide.
_HIDDEN: Final = frozenset({"idempotency_key", "approved"})


class ConfirmWrite(BaseModel):
    """The one question put to the person.

    A single boolean, because an elicitation form may hold only primitives, and
    because a confirmation that asks for anything more has stopped being one.
    """

    confirm: bool = Field(
        default=False,
        description="Yes, make this change in Salesforce.",
    )


class WriteApproval:
    """Obtains a human's approval for a write and binds it to that write."""

    def __init__(self, gate: ApprovalGate) -> None:
        self._gate = gate

    async def granted(
        self,
        ctx: ServerRequestContext[Any],
        described: ActionDescriptor,
        request: ActionRequest,
    ) -> ActionRequest | CallToolResult:
        """Approve a write, or explain why it will not proceed.

        Args:
            ctx: The live request, carrying the session to ask through.
            described: The action being approved, for the question's wording.
            request: The call as the client sent it.

        Returns:
            The request with approval recorded, or a refusal to hand straight
            back. A read, and a write on a client that cannot be asked, return
            the request untouched -- in the second case the action itself
            refuses unless the caller asserted `approved`, which is the right
            answer for a host that confirms elsewhere.
        """
        if not described.requires_approval or not _can_be_asked(ctx):
            return request

        # Deliberately not short-circuited by an `approved` the caller sent.
        # That flag is exactly what cannot be trusted -- a model can set it as
        # easily as a host can -- and a client that declared elicitation never
        # needs to send it, because the answer comes back inside this call.

        # Minted before the question, so it records the call as it stood when
        # the person was shown it, not as it stands afterwards.
        ticket = self._gate.issue(PendingWrite.of(request.action_id, request.params))
        refusal = await _asked(ctx, described, request)
        if refusal is not None:
            return refusal
        return self._bound(ticket, request)

    def _bound(self, ticket: str, request: ActionRequest) -> ActionRequest | CallToolResult:
        """Check the approval still describes the write that is about to run."""
        log = get_logger()
        # Re-derived from the request rather than reused, so the two are equal
        # only if nothing moved between the question and here.
        if not self._gate.accepts(ticket, PendingWrite.of(request.action_id, request.params)):
            log.warning("approval.unbound", action_id=request.action_id)
            return refuse(
                "The approval did not match the write it was given for, so nothing was "
                "changed.\n\nWhat to do: start the write again from the beginning and let "
                "the user confirm the new call.",
                code=TAMPERED,
            )
        log.info("approval.granted", action_id=request.action_id)
        return request.model_copy(update={"approved": True})


async def _asked(
    ctx: ServerRequestContext[Any],
    described: ActionDescriptor,
    request: ActionRequest,
) -> CallToolResult | None:
    """Put the question, and return a refusal unless the answer was a clear yes.

    Decline, cancel, an unchecked box, and an answer that cannot be read all
    mean the same thing here. Only one of the four is a real no, but none of
    them is a yes, and a write is not the place to guess which.
    """
    log = get_logger()
    try:
        answer = await elicit_with_validation(
            ctx.session,
            message=_question(described, request),
            schema=ConfirmWrite,
            related_request_id=ctx.request_id,
        )
    except ValueError:
        log.warning("approval.unreadable", action_id=request.action_id)
        return refuse(_UNREADABLE_TEXT, code=UNREADABLE)
    if isinstance(answer, AcceptedElicitation) and answer.data.confirm:
        return None
    log.info("approval.refused", action_id=request.action_id, answer=answer.action)
    return refuse(
        f"The write was not approved ({answer.action}). Nothing was changed in "
        f"Salesforce.\n\nWhat to do: tell the user it was not carried out. Ask again "
        f"only if they say they want it after all.",
        code=DECLINED,
    )


def _question(described: ActionDescriptor, request: ActionRequest) -> str:
    """State plainly what is about to happen, in the caller's own values."""
    shown = ", ".join(
        f"{name}={value!r}" for name, value in sorted(request.params.items()) if name not in _HIDDEN
    )
    return f"{described.title} in Salesforce with: {shown}. Go ahead?"


def _can_be_asked(ctx: ServerRequestContext[Any]) -> bool:
    """Say whether this client offered to put questions to a person.

    A server must not send an elicitation the client has not declared, so a
    client that stays silent is simply never asked.

    `client_capabilities` rather than `client_params.capabilities`, on the
    SDK's own advice: from 2026-07-28 the request envelope declares
    capabilities while client info stays optional, so this is the one reading
    that works in both eras.
    """
    declared = ctx.session.client_capabilities
    return declared is not None and declared.elicitation is not None
