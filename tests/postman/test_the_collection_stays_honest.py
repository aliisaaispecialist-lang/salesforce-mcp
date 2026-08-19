"""Keep the Postman collection true, since nothing else will run it.

A collection is the one artefact in a repository that is guaranteed to rot. It
is committed, it is read by people evaluating the connector, and no build ever
opens it. A tool gets renamed and the collection keeps naming the old one, in a
file whose whole purpose is to be believed.

So it is generated rather than written, and these tests check the generator's
output is what is committed. That turns a rename into a diff instead of a
surprise.

Two of these are not about rot at all. One checks that no credential reached the
file, because a collection is exactly the kind of thing someone exports with
their environment still attached. The other checks every write is still gated,
because a collection runner started by accident should not be able to create
records in somebody's org.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from salesforce_connector.actions.registry import BY_ID
from tests.postman import build_collection

HERE = Path(__file__).parent
COLLECTION: dict[str, Any] = json.loads(
    (HERE / "salesforce-mcp.postman_collection.json").read_text(encoding="utf-8")
)
ENVIRONMENT: dict[str, Any] = json.loads(
    (HERE / "environment.template.json").read_text(encoding="utf-8")
)
PUBLISHED = {action.spec.tool_name for action in BY_ID.values()}

WRITE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})
# A variable, not a value. Anything else in a credential field is a leak.
A_PLACEHOLDER = re.compile(r"^\{\{[a-z_]+\}\}$")


def _requests(node: Any) -> list[dict[str, Any]]:
    """Every request in the collection, however deeply foldered."""
    if isinstance(node, dict):
        if "request" in node:
            return [node]
        return _requests(node.get("item", []))
    if isinstance(node, list):
        return [one for child in node for one in _requests(child)]
    return []


ALL_REQUESTS = _requests(COLLECTION)


def _text(request: dict[str, Any]) -> str:
    """Everything a request would send, as one string."""
    url = request["request"]["url"]
    raw = url if isinstance(url, str) else url.get("raw", "")
    body = request["request"].get("body", {}).get("raw", "")
    headers = json.dumps(request["request"].get("header", []))
    return f"{raw}\n{body}\n{headers}"


def test_the_committed_collection_is_what_the_generator_produces() -> None:
    """The file matches its source. Otherwise it was hand-edited and will rot."""
    assert (HERE / "salesforce-mcp.postman_collection.json").read_text(encoding="utf-8") == (
        json.dumps(build_collection.collection(), indent=2) + "\n"
    ), "The collection was edited by hand. Change build_collection.py and regenerate."


def test_the_committed_environment_is_what_the_generator_produces() -> None:
    assert (HERE / "environment.template.json").read_text(encoding="utf-8") == (
        json.dumps(build_collection.environment(), indent=2) + "\n"
    ), "The environment template was edited by hand. Change build_collection.py and regenerate."


def test_every_tool_it_names_still_exists() -> None:
    """A renamed tool must break this, not a reviewer's afternoon."""
    named = set()
    for request in ALL_REQUESTS:
        for found in re.findall(r"salesforce_[a-z_]+", _text(request)):
            named.add(found)
    unknown = named - PUBLISHED
    assert not unknown, (
        f"The collection calls tools this connector does not publish: {sorted(unknown)}"
    )


def test_it_reaches_the_gateway_rather_than_the_connector_directly() -> None:
    """Postman cannot speak stdio, and a collection that pretends otherwise is a trap.

    Anyone importing this should land on the route an agent actually takes. A
    request pointed straight at the connector would simply never connect, and
    they would conclude the connector is broken.
    """
    gateway = [r for r in ALL_REQUESTS if "{{executor_url}}" in _text(r)]
    assert gateway, "No request reaches Executor, so nothing here exercises a tool at all."


@pytest.mark.parametrize(
    "request_",
    [r for r in ALL_REQUESTS if r["request"]["method"] in WRITE_METHODS],
    ids=lambda r: r["name"],
)
def test_every_write_is_refused_unless_writes_are_turned_on(request_: dict[str, Any]) -> None:
    """A runner started by accident must not be able to change a real org.

    Exempt: the token request and the gateway's JSON-RPC calls, which are POSTs
    that write nothing. Everything aimed at a Salesforce sObject is gated.
    """
    aimed_at_salesforce = "{{instance_url}}" in _text(request_)
    if not aimed_at_salesforce:
        return
    scripts = " ".join(
        line
        for event in request_.get("event", [])
        if event["listen"] == "prerequest"
        for line in event["script"]["exec"]
    )
    assert "allow_writes" in scripts, (
        f"{request_['name']} writes to Salesforce with nothing stopping it. "
        f"A collection run would create real records."
    )


def test_the_template_ships_with_writes_turned_off() -> None:
    values = {entry["key"]: entry["value"] for entry in ENVIRONMENT["values"]}
    assert values["allow_writes"] == "false"


@pytest.mark.security
def test_no_credential_was_committed() -> None:
    """Every secret is an empty variable, in both files.

    The obvious accident is exporting a working environment along with the
    collection. This is cheap to check and catches it before a push rather than
    after one.
    """
    for entry in ENVIRONMENT["values"]:
        if entry["type"] == "secret":
            assert entry["value"] == "", f"{entry['key']} ships with a value in it"

    serialised = json.dumps(COLLECTION)
    for field in ("Authorization", "client_secret", "access_token"):
        for value in re.findall(rf'"{field}"[^}}]*"value":\s*"([^"]*)"', serialised):
            stripped = value.replace("Bearer ", "")
            assert not stripped or A_PLACEHOLDER.match(stripped), (
                f"A real-looking {field} value is committed in the collection: {stripped[:12]}..."
            )
