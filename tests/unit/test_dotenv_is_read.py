"""`.env.example` tells a reader to copy it to `.env`. That has to be true.

It was not. `Settings` read the process environment and nothing else, so a
user who followed the instruction watched the connector refuse to start over a
value sitting in a file it had been told about. Nothing failed loudly; the file
was simply never opened.

These tests pin both halves of the behaviour: the file is read, and the
environment still wins over it, which is what lets a client launching this
server pass credentials without a stray `.env` in some working directory
overriding them.
"""

import os
from pathlib import Path

import pytest

from salesforce_connector.config import Settings

KEY_LINES = "-----BEGIN PRIVATE KEY-----\\nMIIEvQIBADxx\\n-----END PRIVATE KEY-----"

ENV_BODY = "\n".join(
    (
        "SF_CLIENT_ID=3MVG9from_file",
        "SF_USERNAME=from.file@example.com.sandbox",
        f"SF_PRIVATE_KEY={KEY_LINES}",
        "SF_API_VERSION=v61.0",
    )
)


@pytest.fixture
def in_a_folder_with_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run from a directory holding a `.env`, as a user of the repo would.

    Every SF_ variable is cleared first: this machine may have real ones set,
    and a test that passes only because of them proves nothing.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(ENV_BODY, encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove any SF_ variable this machine happens to have set."""
    for name in [n for n in os.environ if n.startswith("SF_")]:
        monkeypatch.delenv(name, raising=False)


class TestTheFileIsActuallyRead:
    def test_settings_come_from_dotenv_when_nothing_is_exported(
        self, in_a_folder_with_env: Path
    ) -> None:
        settings = Settings()

        assert settings.username == "from.file@example.com.sandbox"
        assert settings.client_id.get_secret_value() == "3MVG9from_file"

    def test_a_non_secret_default_is_overridden_too(self, in_a_folder_with_env: Path) -> None:
        assert Settings().api_version == "v61.0"

    def test_the_key_survives_the_file_as_a_usable_pem(self, in_a_folder_with_env: Path) -> None:
        # `.env` cannot hold real newlines in a value, so the file carries \n
        # escapes and the connector repairs them. A key that arrived with
        # literal backslash-n would fail to sign, later and less clearly.
        key = Settings().private_key.get_secret_value()

        assert key.startswith("-----BEGIN PRIVATE KEY-----\n")
        assert "\\n" not in key


class TestTheEnvironmentStillWins:
    def test_an_exported_variable_beats_the_file(
        self, in_a_folder_with_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # This is what keeps a client-launched server correct: it is handed its
        # credentials, and a `.env` left in whatever directory it was started
        # from must not quietly replace them.
        monkeypatch.setenv("SF_USERNAME", "from.environment@example.com.sandbox")

        assert Settings().username == "from.environment@example.com.sandbox"


class TestNoFileIsFine:
    def test_a_folder_without_dotenv_still_reads_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SF_CLIENT_ID", "3MVG9exported")
        monkeypatch.setenv("SF_USERNAME", "exported@example.com.sandbox")
        monkeypatch.setenv("SF_PRIVATE_KEY", KEY_LINES)

        assert Settings().username == "exported@example.com.sandbox"
