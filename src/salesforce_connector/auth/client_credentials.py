"""The OAuth 2.0 Client Credentials flow.

The simpler alternative: no certificate and no signing, just a consumer key
and secret exchanged for a token. The Connected App carries a run-as user, so
the identity comes from configuration in Salesforce rather than from the
request.

Offered as a fallback because the certificate step in the JWT flow is the part
most likely to block someone. Both flows end at the same place, so which one
is configured changes nothing downstream.

It does transmit a secret, which is why it is the fallback and not the default.
"""

from datetime import datetime
from typing import Final

from salesforce_connector.auth.base import TOKEN_PATH, Token, TokenRequest
from salesforce_connector.auth.jwt_bearer import _token_from
from salesforce_connector.config import Settings
from salesforce_connector.errors.model import ConfigurationError

GRANT_TYPE: Final = "client_credentials"


class ClientCredentialsAuth:
    """Exchange a consumer key and secret for an access token."""

    name = "oauth2_client_credentials"

    def build_request(self, settings: Settings, now: datetime) -> TokenRequest:  # noqa: ARG002
        """Wrap the key and secret as a token exchange.

        Args:
            settings: Credentials and the login host to authenticate against.
            now: Unused. Present so both strategies share one shape, since
                nothing in this flow is time-bound.

        Returns:
            The exchange to POST.

        Raises:
            ConfigurationError: No client secret is configured.
        """
        if settings.client_secret is None:
            raise ConfigurationError(
                "SF_CLIENT_SECRET is required for the client credentials flow. "
                "Set it, or use the JWT bearer flow, which needs no secret."
            )
        return TokenRequest(
            url=f"{settings.login_url.rstrip('/')}{TOKEN_PATH}",
            form={
                "grant_type": GRANT_TYPE,
                "client_id": settings.client_id.get_secret_value(),
                "client_secret": settings.client_secret.get_secret_value(),
            },
        )

    def parse_token(self, payload: object, now: datetime) -> Token:
        """Read the access token and its instance host from the reply."""
        return _token_from(payload, now)
