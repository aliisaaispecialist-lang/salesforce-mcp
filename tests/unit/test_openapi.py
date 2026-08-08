"""The OpenAPI document, and the one property that makes it worth having.

Definition of Done item 10 asks that the specification and the MCP adapter
reuse the same core. That is only true while the committed file still matches
what the schemas produce, so the last test here fails the moment someone edits
a schema and forgets to regenerate.
"""

from pathlib import Path

import pytest
import yaml

from salesforce_connector.actions import registry
from salesforce_connector.config import Settings
from salesforce_connector.connector import load_manifest
from salesforce_connector.openapi import OPENAPI_VERSION, build, to_yaml

COMMITTED = Path(__file__).resolve().parents[2] / "openapi.yaml"


@pytest.fixture
def document() -> dict[str, object]:
    settings = Settings(
        client_id="placeholder",  # type: ignore[arg-type]
        username="placeholder@example.com",
        private_key="placeholder",  # type: ignore[arg-type]
    )
    return build(load_manifest(settings))


class TestTheDocument:
    def test_it_declares_the_version_that_matches_json_schema_2020_12(
        self, document: dict[str, object]
    ) -> None:
        assert document["openapi"] == OPENAPI_VERSION
        assert OPENAPI_VERSION.startswith("3.1")

    def test_every_action_has_an_operation(self, document: dict[str, object]) -> None:
        paths = document["paths"]

        assert isinstance(paths, dict)
        assert len(paths) == 7
        assert set(paths) == {f"/actions/{a}" for a in registry.BY_ID}

    def test_each_operation_carries_the_schema_the_tool_publishes(
        self, document: dict[str, object]
    ) -> None:
        paths = document["paths"]
        assert isinstance(paths, dict)

        for described in registry.descriptors():
            operation = paths[f"/actions/{described.action_id}"]["post"]
            body = operation["requestBody"]["content"]["application/json"]["schema"]

            assert body == dict(described.input_schema)

    def test_the_answer_is_the_same_envelope_for_every_action(
        self, document: dict[str, object]
    ) -> None:
        paths = document["paths"]
        assert isinstance(paths, dict)

        for path in paths.values():
            envelope = path["post"]["responses"]["200"]["content"]["application/json"]["schema"]

            assert set(envelope["required"]) == {"ok", "request_id"}
            assert "error" in envelope["properties"]

    def test_a_read_and_a_write_are_tagged_differently(self, document: dict[str, object]) -> None:
        paths = document["paths"]
        assert isinstance(paths, dict)

        assert paths["/actions/salesforce.search_contact"]["post"]["tags"] == ["read"]
        assert paths["/actions/salesforce.create_contact"]["post"]["tags"] == ["write"]

    def test_it_says_no_caller_credential_is_accepted(self, document: dict[str, object]) -> None:
        info = document["info"]

        assert isinstance(info, dict)
        assert "No caller credential is accepted or forwarded" in info["description"]


class TestTheCommittedFile:
    def test_it_exists_and_parses(self) -> None:
        assert COMMITTED.exists()
        assert yaml.safe_load(COMMITTED.read_text(encoding="utf-8"))["openapi"] == OPENAPI_VERSION

    def test_it_still_matches_what_the_schemas_produce(self) -> None:
        settings = Settings(
            client_id="placeholder",  # type: ignore[arg-type]
            username="placeholder@example.com",
            private_key="placeholder",  # type: ignore[arg-type]
        )

        regenerated = to_yaml(load_manifest(settings))

        assert COMMITTED.read_text(encoding="utf-8") == regenerated, (
            "openapi.yaml is stale. Regenerate it with scripts/regenerate_openapi.py."
        )
