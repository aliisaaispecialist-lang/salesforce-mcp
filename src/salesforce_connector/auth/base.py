"""What every authentication flow produces, and what it must implement.

A strategy never opens a connection. It returns the request to send and reads
the reply it gets back, so the signing and the parsing are testable on their
own and the network stays in one module.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, SecretStr

from salesforce_connector.config import Settings

TOKEN_PATH = "/services/oauth2/token"  # noqa: S105 - a URL path, not a credential


class Token(BaseModel):
    """An access token and the host it is valid against.

    `instance_url` comes from the token response and is authoritative. It is
    often a different host from the one authentication was sent to, so
    assuming the login host works until the day it does not.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    access_token: SecretStr
    instance_url: str
    issued_at: datetime

    def redacted(self) -> str:
        """Describe this token in a form safe to write to a log."""
        return f"token for {self.instance_url} issued at {self.issued_at.isoformat()}"


class TokenRequest(BaseModel):
    """A ready-to-send token exchange, built but not performed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    form: Mapping[str, str]


class AuthStrategy(Protocol):
    """One way of exchanging credentials for an access token."""

    name: str

    def build_request(self, settings: Settings, now: datetime) -> TokenRequest:
        """Produce the exchange to send, signing it where the flow requires."""
        ...

    def parse_token(self, payload: object, now: datetime) -> Token:
        """Read a token from the reply, or say why the reply is unusable."""
        ...
