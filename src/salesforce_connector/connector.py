"""The one door into this connector.

Everything that consumes it — the MCP adapter, the OpenAPI document, a test —
goes through these four members and nothing else. That is what makes the core
reusable rather than merely described as reusable: a second consumer cannot
grow its own logic, because there is nowhere to put it.

Two things live here because there is exactly one door: the call budget, which
would otherwise be five separate guards that could disagree, and the approval
check, for the same reason.
"""

from pathlib import Path
from typing import Final

import yaml

from salesforce_connector.actions import registry
from salesforce_connector.approval import ApprovalGate, PendingWrite
from salesforce_connector.client import SalesforceClient
from salesforce_connector.config import Settings
from salesforce_connector.contract import (
    ActionDescriptor,
    ActionRequest,
    ActionResult,
    ConnectionTestResult,
    ConnectorManifest,
    Credentials,
)
from salesforce_connector.errors.model import ConfigurationError, ConnectorError
from salesforce_connector.exchange import RequestSpec
from salesforce_connector.observability import get_logger
from salesforce_connector.ratelimit import CallBudget

# Authenticated, cheap, and provably read-only: exactly what a connection test
# needs, since a test that writes something is not a test.
_LIMITS_PATH: Final = "limits"


class SalesforceConnector:
    """Implements the programme's connector contract over one Salesforce org."""

    def __init__(self, client: SalesforceClient, manifest: ConnectorManifest) -> None:
        self._client = client
        self._manifest = manifest
        self._budget = CallBudget()
        self._approvals = ApprovalGate()
        self._log = get_logger()

    @property
    def manifest(self) -> ConnectorManifest:
        """What this connector is, as declared rather than inferred."""
        return self._manifest

    async def test_connection(self, credentials: Credentials) -> ConnectionTestResult:
        """Confirm the credentials work, without changing anything.

        Args:
            credentials: What to authenticate with, described only in a form
                safe to log.

        Returns:
            Whether the org answered, and which host and version answered.
        """
        try:
            response = await self._client.request(RequestSpec(method="GET", path=_LIMITS_PATH))
        except ConnectorError as failure:
            return ConnectionTestResult(
                ok=False,
                api_version=self._api_version(),
                instance_url="",
                message=f"{failure.reason} "
                f"{failure.context.next_step or failure.default_next_step}",
            )
        token = await self._client.token()
        self._log.info("connection.verified", who=credentials.redacted())
        return ConnectionTestResult(
            ok=True,
            api_version=self._api_version(),
            instance_url=token.instance_url,
            message=f"Reached Salesforce as {credentials.redacted()}. "
            f"Read {len(response.body or {})} limit counters; nothing was changed.",
        )

    def list_actions(self) -> tuple[ActionDescriptor, ...]:
        """Describe every action, in the same order on every connection."""
        return registry.descriptors()

    async def execute(self, request: ActionRequest) -> ActionResult:
        """Run one action and return the envelope, whatever happened.

        Args:
            request: Which action, its arguments, its key, and whether a human
                approved it.

        Returns:
            The uniform envelope. Never raises: a failure here is an answer,
            not a crash, so one bad call cannot end a session or affect the
            other four actions.
        """
        try:
            await self._budget.claim(request.action_id)
            action = registry.build(request.action_id, self._client)
        except ConnectorError as failure:
            return ActionResult(
                ok=False, request_id=request.request_id, error=failure.to_action_error()
            )
        return await action.run(request)

    def approval_for(self, request: ActionRequest) -> str:
        """Mint the state that would approve exactly this call, and no other."""
        return self._approvals.issue(PendingWrite.of(request.action_id, dict(request.params)))

    def approves(self, request: ActionRequest, state: str) -> bool:
        """Say whether this state approves this call, unchanged and in time."""
        return self._approvals.accepts(
            state, PendingWrite.of(request.action_id, dict(request.params))
        )

    def _api_version(self) -> str:
        return self._manifest.version


def load_manifest(settings: Settings) -> ConnectorManifest:
    """Read connector.yaml and check it against the actions that exist.

    The manifest declares what this connector offers; the registry decides it.
    Comparing them here means the two cannot drift apart quietly, and the
    failure arrives at startup rather than in front of whoever is reading the
    manifest to decide whether to trust the connector.

    Args:
        settings: Where the API version comes from, so it is stated once.

    Returns:
        The validated manifest.

    Raises:
        ConfigurationError: The file is missing, unreadable, or disagrees with
            the actions this connector actually has.
    """
    path = _manifest_path()
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"{path.name} could not be read: {exc}") from exc

    manifest = _parse(document, settings)
    declared = set(manifest.actions)
    implemented = set(registry.BY_ID)
    if declared != implemented:
        raise ConfigurationError(
            f"{path.name} declares {sorted(declared)} but this connector implements "
            f"{sorted(implemented)}. Bring them back into agreement."
        )
    return manifest


def _manifest_path() -> Path:
    return Path(__file__).resolve().parents[2] / "connector.yaml"


def _parse(document: object, settings: Settings) -> ConnectorManifest:
    if not isinstance(document, dict):
        raise ConfigurationError("connector.yaml is not a mapping.")
    try:
        return ConnectorManifest(**{**document, "version": settings.api_version})
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"connector.yaml is not a valid manifest: {exc}") from exc
