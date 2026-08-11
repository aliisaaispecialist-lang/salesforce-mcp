"""Settings read from the environment, validated once at startup.

Built on pydantic-settings rather than hand-parsed: the library owns reading,
coercing, and reporting, so booleans, floats, and missing values behave the way
every other pydantic project behaves instead of the way one hand-written parser
happened to.

Secrets are SecretStr, so printing the settings, logging them, or rendering
them in a traceback shows a mask rather than the value.

A missing credential stops the server before any tool is exposed. A connector
that starts and then fails every call is harder to diagnose than one that
refuses to start.
"""

from typing import Final, Self

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from salesforce_connector.errors.model import ConfigurationError

SANDBOX_LOGIN_URL: Final = "https://test.salesforce.com"
PRODUCTION_LOGIN_URL: Final = "https://login.salesforce.com"

_ENV_PREFIX: Final = "SF_"


class Settings(BaseSettings):
    """Everything the connector needs to reach one Salesforce org.

    Field names map to SF_-prefixed environment variables, so `client_id` is
    read from SF_CLIENT_ID.

    Satisfies the Credentials protocol, so it can be handed to test_connection
    without exposing its fields to that layer.
    """

    model_config = SettingsConfigDict(
        env_prefix=_ENV_PREFIX,
        frozen=True,
        extra="ignore",  # the environment always holds variables that are not ours
        # `.env.example` tells a reader to copy it to `.env` and fill it in.
        # Without this line that instruction was false: the file was written,
        # ignored, and the connector refused to start over a value sitting
        # right there. Resolved against the working directory, so it helps the
        # person running from the repository and is silently absent otherwise
        # -- which is correct, because a client-launched server is given its
        # environment by the client and should not be reading stray files.
        env_file=".env",
        env_file_encoding="utf-8",
    )

    client_id: SecretStr
    username: str
    private_key: SecretStr
    client_secret: SecretStr | None = None  # only the client credentials flow needs one
    login_url: str = SANDBOX_LOGIN_URL
    api_version: str = "v67.0"
    # A read waits 10 seconds and a write 22. Reads are cheap to abandon: no
    # state changed, and a caller can simply ask again. A write is abandoned
    # reluctantly, because the request may already have been applied and
    # giving up early makes that ambiguity more likely rather than less.
    read_timeout_seconds: float = Field(default=10.0, gt=0)
    write_timeout_seconds: float = Field(default=22.0, gt=0)
    allow_production: bool = False

    # Everything below was a constant inside the module that used it, which
    # meant changing how often this connector retries required reading
    # errors/retry.py and editing a literal. A value somebody might reasonably
    # want to change belongs where changing it is expected.
    max_attempts: int = Field(default=3, ge=1, le=10)
    """How many times a retryable call is tried before it escalates."""

    retry_budget_seconds: float = Field(default=120.0, gt=0)
    """Total wall clock a single call may spend across all its attempts."""

    connect_timeout_seconds: float = Field(default=5.0, gt=0)
    """Waiting for the socket, separate from waiting for an answer."""

    calls_per_minute: float = Field(default=60.0, gt=0)
    """The connector's own budget, well under any org's API allowance."""

    approval_ttl_seconds: int = Field(default=600, gt=0)
    """How long a person's approval of a write stays valid."""

    max_query_rows: int = Field(default=200, gt=0, le=2000)
    """The ceiling a SOQL query is held to when it names no limit of its own."""

    max_field_characters: int = Field(default=4000, gt=0)
    """How long one text value may be before it is shortened on the way out.

    A Salesforce long text area holds thirty-two thousand characters. Generous
    enough that an ordinary description, note, or address arrives whole, and
    low enough that three filled long text areas cannot cost more context than
    the conversation they arrived in. Anything shortened says so and names
    itself, so nothing is lost quietly.
    """

    @field_validator("private_key", mode="before")
    @classmethod
    def _restore_newlines(cls, value: object) -> object:
        """Repair a key that had to travel on a single line.

        Container runtimes and CI secret stores generally cannot hold a
        multi-line value, so the key arrives with literal backslash-n. RSA
        parsing fails on that with a message that never mentions newlines.
        """
        return value.replace("\\n", "\n").strip() if isinstance(value, str) else value

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


def _variable_for(location: tuple[object, ...]) -> str:
    """Name the environment variable behind a validation error."""
    return f"{_ENV_PREFIX}{location[0]}".upper() if location else "the environment"


def _explain(error: ValidationError) -> str:
    """Report every problem at once, named by environment variable.

    One message listing three faults beats three restarts finding them one at
    a time.
    """
    faults = tuple(
        f"{_variable_for(problem['loc'])}: {problem['msg']}" for problem in error.errors()
    )
    return (
        f"The environment is not usable. {'; '.join(faults)}. "
        f"See .env.example for the full list of variables."
    )


def load_settings() -> Settings:
    """Read and validate the environment, or refuse to continue.

    Returns:
        Validated settings.

    Raises:
        ConfigurationError: A required variable is missing or a value is
            unusable, with every fault named.
    """
    try:
        return Settings()
    except ValidationError as exc:
        raise ConfigurationError(_explain(exc)) from exc
