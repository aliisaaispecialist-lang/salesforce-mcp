"""Keep the offline tests out of reach of a real developer's credentials.

`Settings` reads `.env` from the working directory, which is what makes the
documented setup work. It also means that the moment someone follows QUICKSTART
and creates a real `.env` in this repository, every test asserting what happens
when configuration is *missing* starts finding it present, and fails.

That happened here, immediately, and the tests were right to fail: they were
depending on the absence of a file rather than on anything they controlled.

So every test outside the live tiers runs from a temporary directory with no
`SF_` variables set. A test that wants configuration sets it itself, which is
the only way its assertion means anything. The live tiers are exempt, because
finding real credentials is precisely their job.

Nothing else breaks: every test that reads a committed file — `.env.example`,
`openapi.yaml`, `connector.yaml` — resolves it from `__file__` rather than the
working directory, which is why they can be moved out from under it safely.
"""

import os
from pathlib import Path

import pytest

# The live fixtures are defined once, in a module of their own, and made
# visible everywhere by being imported here. Two directories cannot both own a
# `conftest.py` of the same name without confusing mypy, and copying the
# fixtures into each would let the safety rules in them drift apart -- which
# are the last rules that should.
from tests.live_org import (  # noqa: F401 - imported to register them as fixtures
    live_client,
    live_settings,
    org,
)

LIVE_TIERS = ("integration", "learning")


@pytest.fixture(autouse=True)
def sealed_from_real_credentials(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run offline tests where no `.env` and no `SF_` variable can reach them."""
    if any(request.node.get_closest_marker(tier) for tier in LIVE_TIERS):
        return
    for name in [n for n in os.environ if n.startswith("SF_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
