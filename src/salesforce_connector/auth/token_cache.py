"""Holding an access token in memory for as long as it is safe to reuse.

Nothing is written to disk. A token on disk outlives the process that needed
it and is one stray file copy away from being a leaked credential.

Salesforce does not return an expiry for this grant: the reply carries
issued_at but no expires_in, because the real lifetime is the org's session
timeout, which the connector cannot see. So the cache holds a conservative
time-to-live and the client additionally refreshes once when a call is
rejected. Guessing short costs an extra handshake; guessing long costs a
failed call.
"""

from datetime import datetime, timedelta
from typing import Final

from salesforce_connector.auth.base import Token

DEFAULT_TTL_SECONDS: Final = 3600.0

# Renew slightly early, so a token cannot expire between the check and the call.
_EARLY_RENEWAL_SECONDS: Final = 60.0


class TokenCache:
    """A single token, remembered until it is due for renewal."""

    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._margin = timedelta(seconds=_EARLY_RENEWAL_SECONDS)
        self._token: Token | None = None

    def store(self, token: Token) -> None:
        """Remember a freshly issued token."""
        self._token = token

    def find_valid(self, now: datetime) -> Token | None:
        """Return the held token while it is still worth using.

        Named find_ because absence is an ordinary outcome here, not a failure:
        the first call of the process has nothing cached.
        """
        if self._token is None:
            return None
        if now >= self._token.issued_at + self._ttl - self._margin:
            return None
        return self._token

    def invalidate(self) -> None:
        """Forget the token after the provider has rejected it."""
        self._token = None
