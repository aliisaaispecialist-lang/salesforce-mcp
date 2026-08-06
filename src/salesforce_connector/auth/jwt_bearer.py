"""The OAuth 2.0 JWT Bearer flow.

The connector signs a short-lived assertion with a private key and exchanges
it for an access token. No secret is transmitted and no password exists, which
is why this is the standard for server-to-server access and why the
username-password flow, which Salesforce began retiring in 2026, is not
implemented here at all.

The matching certificate is uploaded to the Connected App, and the user named
in `sub` must be pre-authorised for it. Salesforce rejects the assertion
otherwise, which is the intended behaviour: the connector cannot act as a user
nobody granted it.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Final

import jwt
from pydantic import SecretStr

from salesforce_connector.auth.base import TOKEN_PATH, Token, TokenRequest
from salesforce_connector.config import Settings
from salesforce_connector.errors.model import AuthenticationError, ConfigurationError

GRANT_TYPE: Final = "urn:ietf:params:oauth:grant-type:jwt-bearer"

# Salesforce rejects an assertion valid for more than five minutes. Three is
# comfortably inside that and still tolerates modest clock drift.
_ASSERTION_LIFETIME: Final = timedelta(minutes=3)


class JwtBearerAuth:
    """Exchange a signed assertion for an access token."""

    name = "oauth2_jwt_bearer"

    def build_request(self, settings: Settings, now: datetime) -> TokenRequest:
        """Sign an assertion for this org and wrap it as a token exchange.

        Args:
            settings: Credentials and the login host to authenticate against.
            now: Current time, passed in so the assertion is reproducible in
                tests rather than depending on the wall clock.

        Returns:
            The exchange to POST.

        Raises:
            ConfigurationError: The private key is not a usable PEM key.
        """
        claims = {
            "iss": settings.client_id.get_secret_value(),
            "sub": settings.username,
            "aud": settings.login_url,
            "exp": int((now + _ASSERTION_LIFETIME).timestamp()),
        }
        return TokenRequest(
            url=f"{settings.login_url.rstrip('/')}{TOKEN_PATH}",
            form={"grant_type": GRANT_TYPE, "assertion": self._sign(claims, settings)},
        )

    def parse_token(self, payload: object, now: datetime) -> Token:
        """Read the access token and its instance host from the reply.

        Args:
            payload: Parsed JSON body of the token response.
            now: Time the token was received.

        Returns:
            The token, bound to the instance host Salesforce named.

        Raises:
            AuthenticationError: The reply is not a token response.
        """
        return _token_from(payload, now)

    def _sign(self, claims: Mapping[str, object], settings: Settings) -> str:
        try:
            return jwt.encode(dict(claims), settings.private_key.get_secret_value(), "RS256")
        except (ValueError, TypeError, jwt.PyJWTError) as exc:
            raise ConfigurationError(
                "SF_PRIVATE_KEY is not a usable RSA private key in PEM form. "
                "Check that the BEGIN and END lines are present and that newlines survived."
            ) from exc


def _token_from(payload: object, now: datetime) -> Token:
    """Build a token from a reply, or explain what the reply was missing."""
    if not isinstance(payload, Mapping):
        raise AuthenticationError(
            "The token endpoint returned something that is not a token response."
        )
    access_token = str(payload.get("access_token") or "")
    instance_url = str(payload.get("instance_url") or "")
    if not access_token or not instance_url:
        missing = "access_token" if not access_token else "instance_url"
        raise AuthenticationError(
            f"The token response carried no {missing}. "
            f"The connected app may not be authorised for this user."
        )
    return Token(
        access_token=SecretStr(access_token),
        instance_url=instance_url,
        issued_at=now,
    )
