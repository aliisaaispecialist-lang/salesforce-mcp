"""The four descriptions of this connector must be one description.

Four artefacts each claim to say what this connector offers: `connector.yaml`,
which a reviewer reads to decide whether to trust it; the action registry,
which decides what actually runs; the MCP tool list, which a model sees; and
`openapi.yaml`, which an HTTP consumer reads. Nothing in the language stops
them disagreeing, and a connector whose manifest promises an action its
registry does not have is worse than one that never promised.

These are contract tests rather than unit tests because none of them is about
a function's behaviour. Each asks whether two independently-produced artefacts
still describe the same thing, which is a property of the system rather than
of any part of it.

`connector.py` already refuses to start when the manifest and registry
disagree. This file is the wider version of that check, and it runs without
starting anything.
"""

import inspect
from pathlib import Path
from typing import Any

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from salesforce_connector import openapi
from salesforce_connector.actions import registry
from salesforce_connector.config import Settings
from salesforce_connector.connector import SalesforceConnector, load_manifest
from salesforce_connector.contract import DooConnector
from salesforce_connector.mcp_translate import as_tool

ROOT = Path(__file__).resolve().parents[2]

PRIVATE_KEY = (
    rsa.generate_private_key(public_exponent=65537, key_size=2048)
    .private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    .decode()
)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        client_id="3MVG9key",  # type: ignore[arg-type]
        username="integration@example.com.sandbox",
        private_key=PRIVATE_KEY,  # type: ignore[arg-type]
    )


def _loaded(name: str) -> dict[str, Any]:
    """Read one of the committed documents as a file, not through any loader."""
    parsed: dict[str, Any] = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
    return parsed


def declared() -> dict[str, Any]:
    """What `connector.yaml` says a reviewer is being promised."""
    return _loaded("connector.yaml")


def committed_openapi() -> dict[str, Any]:
    """The document as committed, not as regenerated."""
    return _loaded("openapi.yaml")


def registered() -> set[str]:
    return {action.action_id for action in registry.descriptors()}


def promised_members() -> set[str]:
    """The members `DooConnector` declares, asked of the Protocol itself.

    `__protocol_attrs__` is how the interpreter records them. Reading it keeps
    this test honest when a member is added: the list is derived, not copied.
    """
    declared = getattr(DooConnector, "__protocol_attrs__", None)
    if declared is None:  # pragma: no cover - interpreter-dependent
        pytest.skip("this interpreter does not expose a protocol's members")
    return set(declared)


class TestEveryoneListsTheSameActions:
    def test_the_manifest_matches_the_registry(self) -> None:
        assert set(declared()["actions"]) == registered()

    def test_the_tool_list_matches_the_registry(self) -> None:
        published = {as_tool(action).name for action in registry.descriptors()}

        assert published == {action.tool_name for action in registry.descriptors()}

    def test_the_openapi_paths_match_the_registry(self) -> None:
        paths = {path.removeprefix("/actions/") for path in committed_openapi()["paths"]}

        assert paths == registered()

    def test_each_action_has_exactly_one_tool_name(self) -> None:
        names = [action.tool_name for action in registry.descriptors()]

        assert len(set(names)) == len(names)


class TestTheTwoSurfacesDescribeActionsIdentically:
    @pytest.mark.parametrize("action", registry.descriptors(), ids=lambda d: d.tool_name)
    def test_the_input_schema_is_the_same_on_both(self, action: Any) -> None:
        # Generated from one source, so a difference here means the committed
        # openapi.yaml is stale rather than that the two disagree by design.
        operation = committed_openapi()["paths"][f"/actions/{action.action_id}"]["post"]
        sent = operation["requestBody"]["content"]["application/json"]["schema"]

        assert sent == dict(action.input_schema)

    @pytest.mark.parametrize("action", registry.descriptors(), ids=lambda d: d.tool_name)
    def test_the_description_is_the_same_on_both(self, action: Any) -> None:
        operation = committed_openapi()["paths"][f"/actions/{action.action_id}"]["post"]

        assert operation["description"] == action.description


class TestTheCoreSatisfiesTheInterfaceItPromises:
    """Structural, not nominal.

    `SalesforceConnector` never names `DooConnector` — it satisfies it by
    shape, which is the point of a Protocol and also the risk: nothing shouts
    when the shape stops matching. So the members are asked of the Protocol
    itself rather than typed out here, where they would quietly go stale.

    `issubclass` is not the tool for this. A Protocol with a non-method member
    — `manifest` is a property — cannot be used with it at all, and the
    runtime check it does offer looks only at names, never at whether a
    property stayed a property.
    """

    def test_the_connector_has_every_member_the_protocol_declares(self) -> None:
        for member in sorted(promised_members()):
            assert inspect.getattr_static(SalesforceConnector, member, None) is not None, member

    def test_the_protocol_still_declares_the_four_a_consumer_was_promised(self) -> None:
        assert promised_members() == {"manifest", "test_connection", "list_actions", "execute"}

    def test_the_manifest_is_read_rather_than_called(self) -> None:
        # A consumer writes `connector.manifest`, not `connector.manifest()`.
        # Turning it into a method would break every caller silently.
        assert isinstance(inspect.getattr_static(SalesforceConnector, "manifest"), property)

    @pytest.mark.parametrize("member", ["test_connection", "list_actions", "execute"])
    def test_the_other_three_are_callable(self, member: str) -> None:
        assert callable(inspect.getattr_static(SalesforceConnector, member))


class TestTheManifestDoesNotOverpromise:
    def test_it_declares_no_capability_the_code_does_not_have(self) -> None:
        capabilities = declared()["capabilities"]

        assert capabilities["transports"] == ["stdio"]
        assert capabilities["idempotency"] == "with_key"
        assert capabilities["approval_required_for_writes"] is True

    def test_every_required_variable_is_one_settings_actually_reads(self) -> None:
        readable = {f"SF_{name.upper()}" for name in Settings.model_fields}

        assert set(declared()["required_env"]) <= readable

    def test_the_openapi_version_comes_from_the_manifest(self, settings: Settings) -> None:
        assert committed_openapi()["info"]["version"] == load_manifest(settings).version
        assert committed_openapi()["openapi"] == openapi.OPENAPI_VERSION
