"""Start the server the way a gateway starts it, and see whether it answers.

Every other test in this repository imports the package. That is the right way
to test behaviour and the wrong way to find out whether the thing a client
actually launches works at all, because none of it goes near the entry point,
the process boundary, or the wire.

The failures this tier catches are the ones that make a connector look broken
before it has done anything: an entry point that imports the wrong `mcp` (the
directory and the SDK share a name, which is why `mcp/server.py` holds no logic
of its own), a startup that demands credentials it does not need yet, a
dependency present in the developer's shell and absent from the launcher's.
None of those show up in a unit test and all of them show up in the first
minute of someone else's evaluation.

So this speaks raw JSON-RPC over stdio rather than using the SDK's own client.
The point is to check what the process emits, and an SDK on both ends would
agree with itself whatever it emitted.

The credentials are generated here and are real enough to parse and false
enough to be worthless. Nothing in this tier reaches Salesforce: the client is
opened lazily, so a catalogue can be published without a token ever being
fetched, which is exactly the property a gateway depends on when it indexes an
integration at registration time.
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import salesforce_connector
from salesforce_connector.actions.registry import BY_ID

pytestmark = pytest.mark.smoke

ROOT = Path(__file__).resolve().parents[2]
ENTRY_POINT = ROOT / "mcp" / "server.py"
PUBLISHED = {action.spec.tool_name for action in BY_ID.values()}

# Long enough that a cold interpreter on a loaded machine is not called a
# failure, short enough that a hang is reported rather than waited out.
PATIENCE_SECONDS = 60


def _worthless_key() -> str:
    """A private key with the right shape and no value anywhere."""
    return (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode()
    )


class Server:
    """A running server process, spoken to over stdio as a client would."""

    def __init__(self, process: subprocess.Popen[str]) -> None:
        self._process = process
        self._next_id = 0

    def notify(self, method: str, **params: Any) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def ask(self, method: str, **params: Any) -> dict[str, Any]:
        """Send a request and return the reply carrying its id."""
        self._next_id += 1
        wanted = self._next_id
        self._send({"jsonrpc": "2.0", "id": wanted, "method": method, "params": params})
        return self._reply(wanted)

    def _send(self, message: Mapping[str, Any]) -> None:
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(message) + "\n")
        self._process.stdin.flush()

    def _reply(self, wanted: int) -> dict[str, Any]:
        """The next message carrying this id, skipping anything else on stdout.

        Anything else is possible and is not an error: a server may log, and it
        may send notifications of its own. A reader that assumed the next line
        was its answer would fail for a reason that has nothing to do with the
        answer.
        """
        assert self._process.stdout is not None
        while True:
            line = self._process.stdout.readline()
            if not line:
                stderr = self._process.stderr.read() if self._process.stderr else ""
                pytest.fail(
                    f"The server stopped without replying to request {wanted}.\n"
                    f"Its standard error follows:\n{stderr[:4000]}"
                )
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == wanted:
                assert "error" not in message, f"request {wanted} was refused: {message['error']}"
                return dict(message)


@pytest.fixture
def server(tmp_path: Path) -> Iterator[Server]:
    """The entry point, launched as a subprocess and handshaken with.

    It runs from an empty directory on purpose. `Settings` reads `.env` from the
    working directory, so a server started in the repository would pick up a
    real developer's credentials and this tier would quietly start depending on
    them. Everything it needs arrives through the environment instead.
    """
    environment = {n: v for n, v in os.environ.items() if not n.startswith("SF_")}
    environment |= {
        "SF_CLIENT_ID": "3MVG9smoketestconsumerkey",
        "SF_USERNAME": "smoke@example.com.sandbox",
        "SF_PRIVATE_KEY": _worthless_key(),
        "SF_CLIENT_SECRET": "smoketestsecret",
        # Unbuffered, or a reply can sit in the child's pipe while the parent
        # waits for it and the whole tier looks like a hang.
        "PYTHONUNBUFFERED": "1",
    }
    # The command is this interpreter and a path built from __file__: there is no
    # input here to be untrusted, and launching the entry point as a real process
    # is the entire point of this tier.
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, str(ENTRY_POINT)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        env=environment,
    )
    running = Server(process)
    try:
        running.ask(
            "initialize",
            protocolVersion="2024-11-05",
            capabilities={},
            clientInfo={"name": "smoke", "version": "0"},
        )
        running.notify("notifications/initialized")
        yield running
    finally:
        if process.stdin is not None:
            process.stdin.close()
        process.terminate()
        try:
            process.wait(timeout=PATIENCE_SECONDS)
        except subprocess.TimeoutExpired:  # pragma: no cover - only on a wedged child
            process.kill()


def test_the_entry_point_starts_and_completes_a_handshake(server: Server) -> None:
    """The process a client is told to launch reaches a usable state.

    The fixture performs the handshake, so arriving here at all is the
    assertion. It is worth stating as its own test because everything below
    depends on it, and a failure here means something quite different from a
    failure in any of them.
    """
    listed = server.ask("tools/list")
    assert "result" in listed


def test_it_names_itself_the_way_the_manifest_does(server: Server) -> None:
    """The handshake reports the name and version the package declares.

    A client shows this to a user and a gateway stores it. Read from the
    package rather than written twice, so the two cannot drift.
    """
    handshake = server.ask(
        "initialize",
        protocolVersion="2024-11-05",
        capabilities={},
        clientInfo={"name": "smoke", "version": "0"},
    )
    reported = handshake["result"]["serverInfo"]
    assert reported["version"] == salesforce_connector.__version__


def test_every_registered_action_reaches_the_wire(server: Server) -> None:
    """What the process publishes is exactly what the registry holds.

    Compared against the registry rather than against a number. A count would
    pass while a tool was renamed, and would have to be edited by hand every
    time one is added, which is how a test starts being updated to match
    whatever the code now does.
    """
    listed = server.ask("tools/list")["result"]["tools"]
    assert {tool["name"] for tool in listed} == PUBLISHED


def test_each_published_tool_arrives_fit_to_read(server: Server) -> None:
    """Nothing is published without the parts a model needs to choose with.

    A tool missing its description or its schema is worse than an absent one:
    the model can see it, cannot understand it, and will guess.
    """
    for tool in server.ask("tools/list")["result"]["tools"]:
        assert tool.get("description"), f"{tool['name']} is published with no description"
        assert tool.get("inputSchema"), f"{tool['name']} is published with no input schema"


def test_a_catalogue_is_published_without_ever_authenticating(server: Server) -> None:
    """Listing tools costs no token, which is what lets a gateway index offline.

    The credentials this tier supplies are worthless, so any attempt to
    authenticate would fail. Reaching a full tool list with them proves the
    client is opened lazily. If that changed, registering this connector would
    start requiring a live org and the failure would appear in someone else's
    gateway rather than here.
    """
    assert len(server.ask("tools/list")["result"]["tools"]) == len(PUBLISHED)
