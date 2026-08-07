"""The documented environment and the one the code reads are the same.

This exists because they were not. `.env.example` documented SF_READ_TIMEOUT,
while the settings field is read_timeout_seconds, so with the SF_ prefix the
code was looking for SF_READ_TIMEOUT_SECONDS. Extra variables are ignored
rather than rejected, by necessity — the environment always holds things that
are not ours — so setting the documented name did nothing at all and silently
left the default in place.

A wrong instruction is worse than a missing one: someone follows it, sees no
error, and believes the setting took effect.
"""

import re
from pathlib import Path

import pytest

from salesforce_connector.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"

_ASSIGNMENT = re.compile(r"^(SF_[A-Z0-9_]+)=", re.MULTILINE)


def documented() -> set[str]:
    """Every variable .env.example tells someone to set."""
    return set(_ASSIGNMENT.findall(ENV_EXAMPLE.read_text(encoding="utf-8")))


def understood() -> set[str]:
    """Every variable the settings model would actually read."""
    return {f"SF_{name.upper()}" for name in Settings.model_fields}


class TestTheDocumentedEnvironment:
    def test_every_documented_variable_is_one_the_code_reads(self) -> None:
        unread = documented() - understood()

        assert not unread, (
            f".env.example documents {sorted(unread)}, which the settings model never "
            f"reads. Setting them would silently do nothing."
        )

    def test_every_required_setting_is_documented(self) -> None:
        required = {
            f"SF_{name.upper()}"
            for name, field in Settings.model_fields.items()
            if field.is_required()
        }

        assert required <= documented()

    @pytest.mark.parametrize("name", ["SF_CLIENT_ID", "SF_PRIVATE_KEY", "SF_CLIENT_SECRET"])
    def test_the_secrets_are_named_but_left_empty(self, name: str) -> None:
        body = ENV_EXAMPLE.read_text(encoding="utf-8")

        assert f"{name}=" in body
        # An example file that ships a value is a secret waiting to be copied
        # into a real one and committed. The username is exempt below: it is an
        # identifier rather than a credential, and showing its shape helps.
        assert re.search(rf"^{name}=\S", body, re.MULTILINE) is None

    def test_the_username_shows_its_shape_without_being_a_real_one(self) -> None:
        body = ENV_EXAMPLE.read_text(encoding="utf-8")

        line = next(row for row in body.splitlines() if row.startswith("SF_USERNAME="))

        assert "example.com" in line

    def test_it_defaults_to_the_sandbox_rather_than_production(self) -> None:
        body = ENV_EXAMPLE.read_text(encoding="utf-8")

        assert "SF_LOGIN_URL=https://test.salesforce.com" in body
        assert "SF_ALLOW_PRODUCTION=false" in body
