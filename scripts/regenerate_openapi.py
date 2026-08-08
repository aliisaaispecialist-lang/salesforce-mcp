"""Rewrite openapi.yaml from the action schemas.

The document is generated, never edited, and a test fails if the committed copy
has drifted from what the schemas produce. This is what you run when it has.

Placeholder credentials are passed directly rather than read from anywhere: the
document describes the actions, and nothing in it depends on which org you can
reach. `_env_file=None` keeps a real `.env` out of it entirely.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from salesforce_connector.config import Settings
from salesforce_connector.connector import load_manifest
from salesforce_connector.openapi import to_yaml


def main() -> None:
    """Regenerate the document and say how large it came out."""
    settings = Settings(
        client_id="placeholder",  # type: ignore[arg-type]
        username="placeholder@example.com.sandbox",
        private_key="placeholder",  # type: ignore[arg-type]
        _env_file=None,
    )
    target = REPO / "openapi.yaml"
    target.write_text(to_yaml(load_manifest(settings)), encoding="utf-8")
    lines = len(target.read_text(encoding="utf-8").splitlines())
    print(f"regenerated {target.name}: {lines} lines")


if __name__ == "__main__":
    main()
