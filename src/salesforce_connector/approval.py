"""Carrying a pending write across a round trip, safely.

When a write needs a human's approval, the connector answers the call by asking
for it and the client calls back with the answer. Between those two moments the
pending write travels through the client, which the specification is explicit
about: request state must be treated as attacker-controlled input, its
integrity protected, and state that fails verification rejected.

So the token is signed, time-limited, and bound to the exact call it was issued
for. A caller cannot approve one write and then present that approval for
another, cannot approve a write with different arguments than the ones shown to
the user, and cannot approve one an hour later.

itsdangerous does the signing. Its salt binds a token to a purpose, and its
max_age enforces the expiry, both of which are precisely the properties the
specification asks for.

The signing key is generated per process rather than configured. Approval is
meaningful only within the call it was issued for, so a key that dies with the
process is not a limitation: it means a restart invalidates pending approvals,
which is the correct outcome.
"""

import hashlib
import json
import secrets
from collections.abc import Mapping
from typing import Any, Final

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, ConfigDict

DEFAULT_TTL_SECONDS: Final = 600
_SALT: Final = "salesforce-connector/write-approval"


class PendingWrite(BaseModel):
    """The write a user is being asked to approve."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str
    arguments_digest: str

    @classmethod
    def of(cls, action_id: str, arguments: Mapping[str, Any]) -> "PendingWrite":
        """Describe a call by its id and a digest of its arguments.

        The digest, rather than the arguments themselves, keeps record data out
        of a token that passes through the client, and still makes an approval
        useless for a call with any argument changed.
        """
        return cls(action_id=action_id, arguments_digest=digest_of(arguments))


def digest_of(arguments: Mapping[str, Any]) -> str:
    """Fingerprint a call's arguments, stably across key ordering."""
    canonical = json.dumps(arguments, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class ApprovalGate:
    """Issues and checks the token that carries an approval."""

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._serializer = URLSafeTimedSerializer(secrets.token_urlsafe(32), salt=_SALT)

    def issue(self, pending: PendingWrite) -> str:
        """Mint the state to hand back with the request for approval."""
        return self._serializer.dumps(pending.model_dump())

    def accepts(self, state: str, pending: PendingWrite) -> bool:
        """Say whether this state approves exactly this call.

        Every failure answers no: a tampered token, an expired one, and one
        issued for a different call are all equally unusable, and telling them
        apart would only help someone probing.
        """
        try:
            carried = self._serializer.loads(state, max_age=self._ttl)
        except (BadSignature, SignatureExpired):
            return False
        return bool(carried == pending.model_dump())
