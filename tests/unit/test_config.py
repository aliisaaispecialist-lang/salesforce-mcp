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

KEY_BODY = "MIIEvQIBADxx"
PRIVATE_KEY = f"-----BEGIN PRIVATE KEY-----\n{KEY_BODY}\n-----END PRIVATE KEY-----"
CONSUMER_KEY = "3MVG9abc"

_ALL_VARIABLES = (
    "SF_CLIENT_ID",
    "SF_USERNAME",
    "SF_PRIVATE_KEY",
    "SF_CLIENT_SECRET",
    "SF_LOGIN_URL",
    "SF_API_VERSION",
    "SF_READ_TIMEOUT_SECONDS",
    "SF_WRITE_TIMEOUT_SECONDS",
    "SF_ALLOW_PRODUCTION",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Start from an environment holding none of our variables."""
    for name in _ALL_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def configured(clean_env: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """A minimally complete environment."""
    clean_env.setenv("SF_CLIENT_ID", CONSUMER_KEY)
    clean_env.setenv("SF_USERNAME", "integration@example.com.sandbox")
    clean_env.setenv("SF_PRIVATE_KEY", PRIVATE_KEY)
    return clean_env


class TestRequiredVariables:
    def test_a_complete_environment_loads(self, configured: pytest.MonkeyPatch) -> None:
        settings = load_settings()

        assert settings.username == "integration@example.com.sandbox"
        assert settings.login_url == SANDBOX_LOGIN_URL

    def test_every_missing_variable_is_named_at_once(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("SF_USERNAME", "someone@example.com")

        with pytest.raises(ConfigurationError) as raised:
            load_settings()

        message = str(raised.value)
        assert "SF_CLIENT_ID" in message
        assert "SF_PRIVATE_KEY" in message

    def test_the_failure_says_what_to_do_next(self, clean_env: pytest.MonkeyPatch) -> None:
        with pytest.raises(ConfigurationError) as raised:
            load_settings()

        assert raised.value.to_action_error().next_step


class TestSecretsAreNotPrintable:
    def test_secrets_are_masked_in_the_repr(self, configured: pytest.MonkeyPatch) -> None:
        settings = load_settings()

        assert KEY_BODY not in repr(settings)
        assert CONSUMER_KEY not in repr(settings)

    def test_the_value_is_still_reachable_deliberately(
        self, configured: pytest.MonkeyPatch
    ) -> None:
        assert load_settings().client_id.get_secret_value() == CONSUMER_KEY

    def test_the_log_safe_description_carries_no_secret(
        self, configured: pytest.MonkeyPatch
    ) -> None:
        described = load_settings().redacted()

        assert KEY_BODY not in described
        assert CONSUMER_KEY not in described
        assert "integration@example.com.sandbox" in described


class TestTheKeyItself:
    def test_a_key_that_travelled_on_one_line_is_repaired(
        self, configured: pytest.MonkeyPatch
    ) -> None:
        configured.setenv("SF_PRIVATE_KEY", PRIVATE_KEY.replace("\n", "\\n"))

        assert "\n" in load_settings().private_key.get_secret_value()


class TestProductionGuard:
    def test_production_is_refused_unless_asked_for(self, configured: pytest.MonkeyPatch) -> None:
        configured.setenv("SF_LOGIN_URL", PRODUCTION_LOGIN_URL)

        with pytest.raises(ConfigurationError, match="production"):
            load_settings()

    def test_a_trailing_slash_does_not_slip_past_the_guard(
        self, configured: pytest.MonkeyPatch
    ) -> None:
        configured.setenv("SF_LOGIN_URL", f"{PRODUCTION_LOGIN_URL}/")

        with pytest.raises(ConfigurationError, match="production"):
            load_settings()

    def test_production_is_allowed_when_stated_explicitly(
        self, configured: pytest.MonkeyPatch
    ) -> None:
        configured.setenv("SF_LOGIN_URL", PRODUCTION_LOGIN_URL)
        configured.setenv("SF_ALLOW_PRODUCTION", "true")

        assert load_settings().login_url == PRODUCTION_LOGIN_URL

    def test_a_sandbox_host_needs_no_permission(self, configured: pytest.MonkeyPatch) -> None:
        assert load_settings().allow_production is False


class TestOptionalValues:
    @pytest.mark.parametrize("raw", ["true", "True", "yes", "1", "on"])
    def test_a_flag_is_read_the_way_pydantic_reads_flags(
        self, configured: pytest.MonkeyPatch, raw: str
    ) -> None:
        configured.setenv("SF_LOGIN_URL", PRODUCTION_LOGIN_URL)
        configured.setenv("SF_ALLOW_PRODUCTION", raw)

        assert load_settings().allow_production is True

    @pytest.mark.parametrize("raw", ["false", "no", "0", "off"])
    def test_a_negative_flag_leaves_it_off(self, configured: pytest.MonkeyPatch, raw: str) -> None:
        configured.setenv("SF_ALLOW_PRODUCTION", raw)

        assert load_settings().allow_production is False

    def test_timeouts_fall_back_when_unset(self, configured: pytest.MonkeyPatch) -> None:
        settings = load_settings()

        assert settings.read_timeout_seconds == 5.0
        assert settings.write_timeout_seconds == 15.0

    def test_a_timeout_that_is_not_a_number_is_rejected_by_name(
        self, configured: pytest.MonkeyPatch
    ) -> None:
        configured.setenv("SF_READ_TIMEOUT_SECONDS", "soon")

        with pytest.raises(ConfigurationError, match="SF_READ_TIMEOUT_SECONDS"):
            load_settings()

    def test_a_negative_timeout_is_rejected(self, configured: pytest.MonkeyPatch) -> None:
        configured.setenv("SF_WRITE_TIMEOUT_SECONDS", "-1")

        with pytest.raises(ConfigurationError):
            load_settings()

    def test_the_api_version_is_pinned_by_default(self, configured: pytest.MonkeyPatch) -> None:
        assert load_settings().api_version == "v67.0"

    def test_unrelated_environment_variables_are_ignored(
        self, configured: pytest.MonkeyPatch
    ) -> None:
        configured.setenv("SF_SOMETHING_ELSE", "irrelevant")

        assert isinstance(load_settings(), Settings)
