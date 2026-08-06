"""Settings read from the environment, validated once at startup.

The only place credentials enter the process. Secrets are held as SecretStr so
that printing the settings, logging them, or rendering them in a traceback
shows a mask rather than the value.

Nothing here has a default that is a secret. A missing credential stops the
server before any tool is exposed, because a connector that starts and then
fails every call is harder to diagnose than one that refuses to start.
"""

import os
from collections.abc import Mapping
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from salesforce_connector.errors.model import ConfigurationError

SANDBOX_LOGIN_URL: Final = "https://test.salesforce.com"
PRODUCTION_LOGIN_URL: Final = "https://login.salesforce.com"

_REQUIRED: Final = ("SF_CLIENT_ID", "SF_USERNAME", "SF_PRIVATE_KEY")

_TRUE_VALUES: Final = frozenset({"1", "true", "yes", "on"})


class Settings(BaseModel):
    """Everything the connector needs to reach one Salesforce org.

    Satisfies the Credentials protocol, so it can be handed to
    test_connection without exposing its fields to that layer.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_id: SecretStr
    username: str
    private_key: SecretStr
    login_url: str = SANDBOX_LOGIN_URL
    api_version: str = "v67.0"
    read_timeout_seconds: float = Field(default=5.0, gt=0)
    write_timeout_seconds: float = Field(default=15.0, gt=0)
    allow_production: bool = False

    @model_validator(mode="after")
    def _production_needs_saying_so(self) -> Self:
        """Refuse a production org unless someone deliberately asked for one.

        The programme requires a sandbox and no production customer data. A
        mistyped login URL is the likely way that happens by accident, so the
        guard lives in code rather than in a note in the README.
        """
        if self.login_url.rstrip("/") == PRODUCTION_LOGIN_URL and not self.allow_production:
            raise ValueError(
                f"SF_LOGIN_URL points at production ({PRODUCTION_LOGIN_URL}). "
                f"This connector is built and tested against a sandbox. "
                f"Set SF_ALLOW_PRODUCTION=true only if that is genuinely intended."
            )
        return self

    def redacted(self) -> str:
        """Describe this configuration in a form safe to write to a log."""
        return f"{self.username} at {self.login_url} ({self.api_version})"


def _missing(env: Mapping[str, str]) -> tuple[str, ...]:
    """Name every required variable that is absent or blank, not just the first."""
    return tuple(name for name in _REQUIRED if not env.get(name, "").strip())


def _flag(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in _TRUE_VALUES


def _number(env: Mapping[str, str], name: str, fallback: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return fallback
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number of seconds, but was {raw!r}.") from exc


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read and validate the environment, or refuse to continue.

    Args:
        env: Source of variables. Defaults to the real environment; tests pass
            a mapping instead of mutating the process.

    Returns:
        Validated settings.

    Raises:
        ConfigurationError: A required variable is missing, or a value is
            unusable. The message names every problem found, so the operator
            fixes them in one pass rather than one restart each.
    """
    source = os.environ if env is None else env

    absent = _missing(source)
    if absent:
        raise ConfigurationError(
            f"Missing required environment variable(s): {', '.join(absent)}. "
            f"See .env.example for the full list."
        )

    try:
        return Settings(
            client_id=SecretStr(source["SF_CLIENT_ID"].strip()),
            username=source["SF_USERNAME"].strip(),
            private_key=SecretStr(source["SF_PRIVATE_KEY"]),
            login_url=source.get("SF_LOGIN_URL", "").strip() or SANDBOX_LOGIN_URL,
            api_version=source.get("SF_API_VERSION", "").strip() or "v67.0",
            read_timeout_seconds=_number(source, "SF_READ_TIMEOUT", 5.0),
            write_timeout_seconds=_number(source, "SF_WRITE_TIMEOUT", 15.0),
            allow_production=_flag(source, "SF_ALLOW_PRODUCTION"),
        )
    except ValueError as exc:
        raise ConfigurationError(f"The environment is not usable: {exc}") from exc
