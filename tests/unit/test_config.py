"""Reading the environment, and refusing to start when it is not usable.

Two properties matter beyond parsing: a secret must not be printable, and a
production login host must not be reachable by accident.
"""

import pytest

from salesforce_connector.config import (
    PRODUCTION_LOGIN_URL,
    SANDBOX_LOGIN_URL,
    Settings,
    load_settings,
)
from salesforce_connector.errors.model import ConfigurationError


def minimal_env(**overrides: str) -> dict[str, str]:
    env = {
        "SF_CLIENT_ID": "3MVG9abc",
        "SF_USERNAME": "integration@example.com.sandbox",
        "SF_PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----",
    }
    env.update(overrides)
    return env


class TestRequiredVariables:
    def test_a_complete_environment_loads(self) -> None:
        settings = load_settings(minimal_env())

        assert settings.username == "integration@example.com.sandbox"
        assert settings.login_url == SANDBOX_LOGIN_URL

    def test_every_missing_variable_is_named_at_once(self) -> None:
        with pytest.raises(ConfigurationError) as raised:
            load_settings({"SF_USERNAME": "someone@example.com"})

        message = str(raised.value)
        assert "SF_CLIENT_ID" in message
        assert "SF_PRIVATE_KEY" in message

    def test_a_blank_value_counts_as_missing(self) -> None:
        with pytest.raises(ConfigurationError, match="SF_CLIENT_ID"):
            load_settings(minimal_env(SF_CLIENT_ID="   "))

    def test_the_failure_says_what_to_do_next(self) -> None:
        with pytest.raises(ConfigurationError) as raised:
            load_settings({})

        assert raised.value.to_action_error().next_step


class TestSecretsAreNotPrintable:
    def test_the_private_key_is_masked_in_the_repr(self) -> None:
        settings = load_settings(minimal_env())

        assert "secret" not in repr(settings)
        assert "3MVG9abc" not in repr(settings)

    def test_the_value_is_still_reachable_deliberately(self) -> None:
        settings = load_settings(minimal_env())

        assert settings.client_id.get_secret_value() == "3MVG9abc"

    def test_the_log_safe_description_carries_no_secret(self) -> None:
        described = load_settings(minimal_env()).redacted()

        assert "secret" not in described
        assert "3MVG9abc" not in described
        assert "integration@example.com.sandbox" in described


class TestProductionGuard:
    def test_production_is_refused_unless_asked_for(self) -> None:
        with pytest.raises(ConfigurationError, match="production"):
            load_settings(minimal_env(SF_LOGIN_URL=PRODUCTION_LOGIN_URL))

    def test_a_trailing_slash_does_not_slip_past_the_guard(self) -> None:
        with pytest.raises(ConfigurationError, match="production"):
            load_settings(minimal_env(SF_LOGIN_URL=f"{PRODUCTION_LOGIN_URL}/"))

    def test_production_is_allowed_when_stated_explicitly(self) -> None:
        settings = load_settings(
            minimal_env(SF_LOGIN_URL=PRODUCTION_LOGIN_URL, SF_ALLOW_PRODUCTION="true")
        )

        assert settings.login_url == PRODUCTION_LOGIN_URL

    def test_a_sandbox_host_needs_no_permission(self) -> None:
        assert load_settings(minimal_env()).allow_production is False


class TestOptionalValues:
    @pytest.mark.parametrize("raw", ["true", "TRUE", "yes", "1", "on"])
    def test_a_flag_is_read_forgivingly(self, raw: str) -> None:
        env = minimal_env(SF_LOGIN_URL=PRODUCTION_LOGIN_URL, SF_ALLOW_PRODUCTION=raw)

        assert load_settings(env).allow_production is True

    @pytest.mark.parametrize("raw", ["false", "no", "", "0", "anything else"])
    def test_anything_else_leaves_the_flag_off(self, raw: str) -> None:
        assert load_settings(minimal_env(SF_ALLOW_PRODUCTION=raw)).allow_production is False

    def test_timeouts_fall_back_when_unset(self) -> None:
        settings = load_settings(minimal_env())

        assert settings.read_timeout_seconds == 5.0
        assert settings.write_timeout_seconds == 15.0

    def test_a_timeout_that_is_not_a_number_is_rejected_by_name(self) -> None:
        with pytest.raises(ConfigurationError, match="SF_READ_TIMEOUT"):
            load_settings(minimal_env(SF_READ_TIMEOUT="soon"))

    def test_a_negative_timeout_is_rejected(self) -> None:
        with pytest.raises(ConfigurationError):
            load_settings(minimal_env(SF_WRITE_TIMEOUT="-1"))

    def test_the_api_version_is_pinned_by_default(self) -> None:
        assert load_settings(minimal_env()).api_version == "v67.0"


class TestSettingsSatisfiesTheCredentialsProtocol:
    def test_it_offers_a_redacted_rendering(self) -> None:
        settings: Settings = load_settings(minimal_env())

        assert isinstance(settings.redacted(), str)
