"""The OpenAPI document, built from the same declarations the tools use.

Definition of Done item 10 asks that the OpenAPI specification and the MCP
adapter reuse the same connector core. Generating the document rather than
writing it is what makes that true instead of merely claimed: both descriptions
of every action come from one place, so they cannot disagree, and a change to a
schema appears in both or in neither.

The version is pinned to OpenAPI 3.1.x because that is the first release fully
compatible with JSON Schema 2020-12, which is the dialect MCP defaults to and
the dialect pydantic emits. One schema, valid in both worlds.
"""

from typing import Any, Final

import yaml

from salesforce_connector.actions import registry
from salesforce_connector.contract import ActionDescriptor, ActionKind, ConnectorManifest

OPENAPI_VERSION: Final = "3.1.0"

_ERROR_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "description": "A failure described so its reader knows what to do next.",
    "properties": {
        "code": {"type": "string", "description": "Stable identifier for this failure."},
        "category": {
            "type": "string",
            "enum": ["transient", "input", "resource", "fatal"],
            "description": (
                "What the caller should do: wait and retry, fix an argument, stop and "
                "report, or escalate."
            ),
        },
        "reason": {"type": "string", "description": "What went wrong."},
        "next_step": {"type": "string", "description": "What to do about it."},
        "retryable": {"type": "boolean"},
        "retry_after_seconds": {"type": ["number", "null"]},
        "invalid_fields": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["code", "category", "reason", "next_step"],
}


def _envelope(output_schema: dict[str, Any]) -> dict[str, Any]:
    """Wrap an action's output in the envelope every action returns."""
    return {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "request_id": {"type": "string", "description": "Correlates this call in the logs."},
            "data": output_schema,
            "error": {"oneOf": [_ERROR_SCHEMA, {"type": "null"}]},
            "pagination": {"$ref": "#/components/schemas/Pagination"},
            "rate_limit": {"$ref": "#/components/schemas/RateLimit"},
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["ok", "request_id"],
    }


def _sent(described: ActionDescriptor) -> dict[str, Any]:
    """The worked calls, as OpenAPI names examples: keyed, each with a summary."""
    return {
        shown.title: {"summary": shown.title, "value": dict(shown.arguments)}
        for shown in described.examples
    }


def _received(described: ActionDescriptor) -> dict[str, Any]:
    """The same worked calls from the other end, wrapped in the envelope.

    A response example is worth more than a request example here, because the
    envelope is the part a first-time reader has to learn: every action answers
    with the same shape, and seeing one filled in explains it faster than the
    schema does.
    """
    return {
        shown.title: {
            "summary": shown.title,
            "value": {"ok": True, "request_id": "req-01HZY6", "data": dict(shown.result)},
        }
        for shown in described.examples
    }


def _operation(described: ActionDescriptor) -> dict[str, Any]:
    """Describe one action as an operation."""
    writes = described.kind is ActionKind.WRITE
    return {
        "operationId": described.tool_name,
        "summary": described.title,
        "description": described.description,
        "tags": ["write" if writes else "read"],
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": dict(described.input_schema),
                    "examples": _sent(described),
                }
            },
        },
        "responses": {
            "200": {
                "description": "The action ran. Read `ok` to learn whether it succeeded.",
                "content": {
                    "application/json": {
                        "schema": _envelope(dict(described.output_schema)),
                        "examples": _received(described),
                    }
                },
            }
        },
    }


def build(manifest: ConnectorManifest) -> dict[str, Any]:
    """Assemble the document from the manifest and the registry.

    Args:
        manifest: What the connector declares about itself.

    Returns:
        An OpenAPI 3.1 document, ready to serialise.
    """
    described = registry.descriptors()
    return {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": "Salesforce connector",
            "version": manifest.version,
            "description": (
                "One reusable core with five typed actions. Every action takes a JSON "
                "body and answers with the same envelope, so a caller handles one "
                "shape rather than five. Generated from the same schemas the MCP "
                "tools publish, so the two cannot disagree.\n\n"
                "Authentication is the OAuth 2.0 JWT Bearer flow, held by the "
                "connector and read from its environment. No caller credential is "
                "accepted or forwarded."
            ),
        },
        "tags": [
            {"name": "read", "description": "Changes nothing."},
            {"name": "write", "description": "Changes Salesforce. Needs an idempotency key."},
        ],
        "paths": {
            f"/actions/{action.action_id}": {"post": _operation(action)} for action in described
        },
        "components": {
            "schemas": {
                "Pagination": {
                    "type": "object",
                    "description": (
                        "Where a paged read stopped. Send `next_cursor` back verbatim for "
                        "the next page; its absence means there are none."
                    ),
                    "properties": {
                        "returned": {"type": "integer"},
                        "next_cursor": {"type": ["string", "null"]},
                        "total_size": {"type": ["integer", "null"]},
                    },
                    "required": ["returned"],
                },
                "RateLimit": {
                    "type": "object",
                    "description": "The org's API quota, as of the response that carried it.",
                    "properties": {
                        "used": {"type": "integer"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["used", "limit"],
                },
                "ActionError": _ERROR_SCHEMA,
            }
        },
    }


def to_yaml(manifest: ConnectorManifest) -> str:
    """Serialise the document, keys in the order they were written."""
    return yaml.safe_dump(build(manifest), sort_keys=False, width=88, allow_unicode=True)
