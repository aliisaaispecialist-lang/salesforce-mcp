"""Signing an assertion, reading a token reply, and knowing when to renew.

The assertion is verified by decoding it with the matching public key, so the
test proves Salesforce could verify it, rather than proving we produced a
string.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

from salesforce_connector.auth.base import Token
from salesforce_connector.auth.client_credentials import ClientCredentialsAuth
from salesforce_connector.auth.jwt_bearer import GRANT_TYPE, JwtBearerAuth
from salesforce_connector.auth.token_cache import DEFAULT_TTL_SECONDS, TokenCache
from salesforce_connector.config import Settings, load_settings
from salesforce_connector.errors.model import AuthenticationError, ConfigurationError

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_KEY_PEM = _key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
PUBLIC_KEY_PEM = (
    _key.public_key()
    .public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)


def settings_with(**overrides: str) -> Settings:
    env = {
        "SF_CLIENT_ID": "3MVG9consumerkey",
        "SF_USERNAME": "integration@example.com.sandbox",
        "SF_PRIVATE_KEY": PRIVATE_KEY_PEM,
    }
    env.update(overrides)
    return load_settings(env)


def token_reply(**overrides: str) -> dict[str, str]:
    reply = {
        "access_token": "00D5g000004abc!AQEAQ",
        "instance_url": "https://mycompany--dev.sandbox.my.salesforce.com",
        "token_type": "Bearer",
    }
    reply.update(overrides)
    return reply


class TestTheAssertionSalesforceWillVerify:
    def test_the_assertion_verifies_against_the_matching_public_key(self) -> None:
        request = JwtBearerAuth().build_request(settings_with(), NOW)

        claims = jwt.decode(
            request.form["assertion"],
            PUBLIC_KEY_PEM,
            algorithms=["RS256"],
            audience="https://test.salesforce.com",
            # The assertion is signed against a fixed clock, so freshness is
            # asserted separately rather than judged against the real one.
            options={"verify_exp": False},
        )

        assert claims["iss"] == "3MVG9consumerkey"
        assert claims["sub"] == "integration@example.com.sandbox"

    def test_the_assertion_expires_within_the_five_minutes_salesforce_allows(self) -> None:
        request = JwtBearerAuth().build_request(settings_with(), NOW)

        claims = jwt.decode(
            request.form["assertion"],
            PUBLIC_KEY_PEM,
            algorithms=["RS256"],
            audience="https://test.salesforce.com",
            # The assertion is signed against a fixed clock, so freshness is
            # asserted separately rather than judged against the real one.
            options={"verify_exp": False},
        )

        assert 0 < claims["exp"] - NOW.timestamp() <= timedelta(minutes=5).total_seconds()

    def test_the_exchange_is_posted_to_the_login_host(self) -> None:
        request = JwtBearerAuth().build_request(settings_with(), NOW)

        assert request.url == "https://test.salesforce.com/services/oauth2/token"
        assert request.form["grant_type"] == GRANT_TYPE

    def test_no_secret_is_transmitted(self) -> None:
        request = JwtBearerAuth().build_request(settings_with(), NOW)

        assert set(request.form) == {"grant_type", "assertion"}

    def test_a_key_that_travelled_on_one_line_is_still_usable(self) -> None:
        flattened = PRIVATE_KEY_PEM.replace("\n", "\\n")

        request = JwtBearerAuth().build_request(settings_with(SF_PRIVATE_KEY=flattened), NOW)

        assert request.form["assertion"]

    def test_an_unusable_key_names_the_variable_and_the_likely_cause(self) -> None:
        with pytest.raises(ConfigurationError, match="SF_PRIVATE_KEY"):
            JwtBearerAuth().build_request(settings_with(SF_PRIVATE_KEY="not a key"), NOW)


class TestReadingTheReply:
    def test_the_instance_host_comes_from_the_reply_not_the_login_host(self) -> None:
        token = JwtBearerAuth().parse_token(token_reply(), NOW)

        assert token.instance_url == "https://mycompany--dev.sandbox.my.salesforce.com"
        assert token.instance_url != "https://test.salesforce.com"

    @pytest.mark.parametrize("missing", ["access_token", "instance_url"])
    def test_a_reply_missing_a_required_field_says_which(self, missing: str) -> None:
        reply = token_reply()
        del reply[missing]

        with pytest.raises(AuthenticationError, match=missing):
            JwtBearerAuth().parse_token(reply, NOW)

    def test_a_reply_that_is_not_an_object_is_refused(self) -> None:
        with pytest.raises(AuthenticationError):
            JwtBearerAuth().parse_token("<html>gateway error</html>", NOW)

    def test_the_token_describes_itself_without_revealing_itself(self) -> None:
        token = JwtBearerAuth().parse_token(token_reply(), NOW)

        assert "00D5g000004abc" not in token.redacted()
        assert "00D5g000004abc" not in repr(token)


class TestClientCredentialsFallback:
    def test_it_sends_the_key_and_secret(self) -> None:
        settings = settings_with(SF_CLIENT_SECRET="shhh")

        request = ClientCredentialsAuth().build_request(settings, NOW)

        assert request.form["grant_type"] == "client_credentials"
        assert request.form["client_secret"] == "shhh"

    def test_without_a_secret_it_says_which_variable_and_offers_the_alternative(self) -> None:
        with pytest.raises(ConfigurationError, match="SF_CLIENT_SECRET"):
            ClientCredentialsAuth().build_request(settings_with(), NOW)

    def test_both_flows_produce_the_same_token_shape(self) -> None:
        from_jwt = JwtBearerAuth().parse_token(token_reply(), NOW)
        from_secret = ClientCredentialsAuth().parse_token(token_reply(), NOW)

        assert from_jwt == from_secret


class TestTokenCache:
    def token(self, issued: datetime = NOW) -> Token:
        return Token(
            access_token=SecretStr("tok"),
            instance_url="https://x.my.salesforce.com",
            issued_at=issued,
        )

    def test_nothing_is_held_before_the_first_handshake(self) -> None:
        assert TokenCache().find_valid(NOW) is None

    def test_a_fresh_token_is_reused(self) -> None:
        cache = TokenCache()
        cache.store(self.token())

        assert cache.find_valid(NOW + timedelta(minutes=5)) is not None

    def test_a_token_is_renewed_before_it_actually_expires(self) -> None:
        cache = TokenCache()
        cache.store(self.token())

        just_inside = NOW + timedelta(seconds=DEFAULT_TTL_SECONDS - 30)

        assert cache.find_valid(just_inside) is None

    def test_an_expired_token_is_not_reused(self) -> None:
        cache = TokenCache()
        cache.store(self.token())

        assert cache.find_valid(NOW + timedelta(seconds=DEFAULT_TTL_SECONDS + 1)) is None

    def test_a_rejected_token_is_forgotten_at_once(self) -> None:
        cache = TokenCache()
        cache.store(self.token())

        cache.invalidate()

        assert cache.find_valid(NOW) is None
