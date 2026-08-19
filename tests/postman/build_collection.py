"""Generate the Postman collection, from the connector rather than from memory.

A hand-written collection rots the moment a tool is renamed, and rots silently,
because nothing executes it in CI. So it is generated: the gateway folder reads
the tool names out of the registry, and the Salesforce folder is built from the
endpoint map each action actually calls. A tool that does not exist cannot end
up in the file, and a rename shows up as a diff.

Two folders, because "test the connector with Postman" has two honest readings
and neither is the whole thing:

  Gateway       -- Executor's HTTP surface, which is where the connector really
                   answers. Postman cannot speak stdio, so this is the only
                   route to the tools themselves.
  Salesforce    -- the REST endpoints the actions call, one request each. This
                   is the audit in executable form: when a description and the
                   platform disagree, this is where you find out which is right.

Every credential is a variable and every variable is empty here. The committed
file carries no token, no instance, no key. `environment.template.json` names
what to fill in.

Writes are gated behind `allow_writes`, which is `false` in the template. A
pre-request script stops each one unless it is set. This is the same posture the
connector itself takes with `approved`, for the same reason: a collection runner
started by accident should not be able to create records in a real org.

    python tests/postman/build_collection.py            # write the file
    python tests/postman/build_collection.py --check    # verify without writing
"""

# ruff: noqa: T201 - it prints its report.

import argparse
import json
import pathlib
import sys
from dataclasses import dataclass
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

from salesforce_connector.actions.registry import BY_ID
from salesforce_connector.contract import ActionKind

HERE = pathlib.Path(__file__).parent
COLLECTION = HERE / "salesforce-mcp.postman_collection.json"
ENVIRONMENT = HERE / "environment.template.json"

# The collection is JSON all the way down, and every helper here returns a piece
# of it. One alias rather than dict[str, Any] written nine times.
Json = dict[str, Any]

SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"

# Stops a write dead unless someone has deliberately turned writes on.
#
# Two mechanisms, because one of them is not enough. `pm.execution.skipRequest`
# is the right answer and is the newer API, so the URL is also pointed at a host
# that cannot resolve. An older Postman ignores the first and fails on the
# second, which is the outcome we want either way.
#
# What is deliberately *not* used here is `postman.setNextRequest(null)`. It
# reads as though it stops things, and it does -- it stops the request *after*
# this one. The write itself still goes out, and a manual Send ignores it
# entirely. A guard that fires after the damage is worse than none, because it
# is believed.
REFUSE_UNLESS_ALLOWED = [
    "if (pm.environment.get('allow_writes') !== 'true') {",
    "    console.log('Refused: this writes to Salesforce and allow_writes is not true.');",
    "    if (pm.execution && pm.execution.skipRequest) { pm.execution.skipRequest(); }",
    "    pm.request.url = 'https://writes-are-off.invalid/refused';",
    "}",
]

# Captured from the initialize response and reused by every later call. Postman
# has no way to thread a response header through a folder on its own.
CAPTURE_SESSION = [
    "const session = pm.response.headers.get('mcp-session-id');",
    "pm.test('the gateway opened a session', () => pm.expect(session).to.be.a('string'));",
    "pm.environment.set('session_id', session);",
]

LIST_HOLDS_EVERY_TOOL = [
    "const body = pm.response.json();",
    "const names = (body.result && body.result.tools || []).map(t => t.name);",
    "pm.test('the gateway answers with a tool list', () => pm.expect(names).to.be.an('array'));",
    "pm.test('every tool carries a description', () => {",
    "    (body.result && body.result.tools || []).forEach(t =>",
    "        pm.expect(t.description, t.name).to.be.a('string').and.not.empty);",
    "});",
]

ANSWERED_WITHOUT_ERROR = [
    "pm.test('answered 200', () => pm.response.to.have.status(200));",
    "pm.test('no JSON-RPC error', () => {",
    "    const body = pm.response.json();",
    "    pm.expect(body.error, JSON.stringify(body.error)).to.be.undefined;",
    "});",
]

TOKEN_IS_USABLE = [
    "pm.test('answered 200', () => pm.response.to.have.status(200));",
    "const body = pm.response.json();",
    "pm.environment.set('access_token', body.access_token);",
    "pm.environment.set('instance_url', body.instance_url);",
    "pm.test('a token came back', () => pm.expect(body.access_token).to.be.a('string'));",
]

# One entry per action, naming the endpoint it actually calls. Taken from the
# source, not from the description: the point of this folder is to be able to
# check a description against the platform, so it must not be built out of the
# thing it is checking.
ENDPOINTS: list[tuple[str, str, str, str, Json | None]] = [
    (
        "Search across objects (parameterizedSearch)",
        "GET",
        "{{instance_url}}/services/data/{{api_version}}/parameterizedSearch/"
        "?q=Acme&sobject=Account&Account.fields=Id,Name",
        "Backs contact_search_by_text and record_search_by_text. SOSL tokenises: an "
        "asterisk matches at the middle or end of a term, never the start. Use this "
        "request to check whether a partial word really does find a record.",
        None,
    ),
    (
        "Run a SOQL query",
        "GET",
        "{{instance_url}}/services/data/{{api_version}}/query/"
        "?q=SELECT Id, Name FROM Account LIMIT 5",
        "Backs record_query_by_soql. A response over the page size carries "
        "nextRecordsUrl; the connector follows it as an opaque cursor.",
        None,
    ),
    (
        "Read one record",
        "GET",
        "{{instance_url}}/services/data/{{api_version}}/sobjects/Contact/{{contact_id}}",
        "Backs record_get_by_id.",
        None,
    ),
    (
        "Follow a relationship",
        "GET",
        "{{instance_url}}/services/data/{{api_version}}/sobjects/Contact/{{contact_id}}/Account",
        "Backs record_get_related_by_id. Salesforce answers 404 when the lookup field "
        "is not set, which is the same status as a bad id and a different problem. "
        "Point this at a contact with no account to see it.",
        None,
    ),
    (
        "Count records",
        "GET",
        "{{instance_url}}/services/data/{{api_version}}/limits/recordCount?sObjects=Account,Contact",
        "Backs record_count_by_object. The count is a cached snapshot, excludes the "
        "recycle bin and archived records, and is documented as possibly inexact.",
        None,
    ),
    (
        "Describe an object",
        "GET",
        "{{instance_url}}/services/data/{{api_version}}/sobjects/Opportunity/describe",
        "Backs object_describe_by_name. Also the way to find a valid relationshipName "
        "when the request above returns 404.",
        None,
    ),
    (
        "Create a contact",
        "POST",
        "{{instance_url}}/services/data/{{api_version}}/sobjects/Contact",
        "Backs contact_create.",
        {"LastName": "Lovelace", "FirstName": "Ada", "Email": "ada@example.com"},
    ),
    (
        "Update a contact",
        "PATCH",
        "{{instance_url}}/services/data/{{api_version}}/sobjects/Contact/{{contact_id}}",
        "Backs contact_update_by_id. Answers 204 with no body on success.",
        {"Title": "Chief Analyst"},
    ),
    (
        "Create an opportunity",
        "POST",
        "{{instance_url}}/services/data/{{api_version}}/sobjects/Opportunity",
        "Backs opportunity_create. Salesforce accepts any CloseDate, including one in "
        "the past, which is why the connector refuses to guess it.",
        {"Name": "Contoso expansion", "StageName": "Prospecting", "CloseDate": "2026-11-30"},
    ),
    (
        "Create an opportunity and its contact role together",
        "POST",
        "{{instance_url}}/services/data/{{api_version}}/composite",
        "Backs opportunity_create_with_contact_by_id. allOrNone makes the pair atomic: "
        "without it a failed second step leaves an orphan opportunity behind.",
        {
            "allOrNone": True,
            "compositeRequest": [
                {
                    "method": "POST",
                    "url": "/services/data/{{api_version}}/sobjects/Opportunity",
                    "referenceId": "newOpportunity",
                    "body": {
                        "Name": "Contoso pilot",
                        "StageName": "Prospecting",
                        "CloseDate": "2026-09-30",
                    },
                },
                {
                    "method": "POST",
                    "url": "/services/data/{{api_version}}/sobjects/OpportunityContactRole",
                    "referenceId": "newRole",
                    "body": {
                        "OpportunityId": "@{newOpportunity.id}",
                        "ContactId": "{{contact_id}}",
                    },
                },
            ],
        },
    ),
    (
        "Link a contact to an opportunity",
        "POST",
        "{{instance_url}}/services/data/{{api_version}}/sobjects/OpportunityContactRole",
        "Backs opportunity_link_contact_by_id.",
        {"OpportunityId": "{{opportunity_id}}", "ContactId": "{{contact_id}}"},
    ),
    (
        "Log an activity",
        "POST",
        "{{instance_url}}/services/data/{{api_version}}/sobjects/Task",
        "Backs activity_create_by_related_id. WhoId takes a Lead or a Contact, WhatId "
        "an Account, Opportunity and others. An id in the wrong one is ignored in "
        "silence, and the task attaches to nothing.",
        {"Subject": "Discovery call", "WhoId": "{{contact_id}}"},
    ),
    (
        "Update any record",
        "PATCH",
        "{{instance_url}}/services/data/{{api_version}}/sobjects/Account/{{account_id}}",
        "Backs record_update_by_id.",
        {"Industry": "Manufacturing"},
    ),
    (
        "Upsert on an external id",
        "PATCH",
        "{{instance_url}}/services/data/{{api_version}}/sobjects/Account/ERP_Id__c/A-1042",
        "Backs record_upsert_by_external_id. An external id matching more than one "
        "record answers 300 with a list of URLs and no error code at all, and writes "
        "nothing.",
        {"Name": "Contoso Gulf"},
    ),
]

WRITE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})


def _write_names() -> list[str]:
    """Every tool that changes state, read from the registry.

    The policy check used to match these with a regular expression over the
    names, which looked fine and quietly missed
    `salesforce_opportunity_link_contact_by_id`: it creates a record and says
    neither "create" nor "update". A hand-written pattern standing in for the
    registry is the exact mistake this generator exists to avoid.
    """
    return [
        action.spec.tool_name
        for action in BY_ID.values()
        if action.spec.kind is not ActionKind.READ
    ]


def _script(lines: list[str], when: str) -> Json:
    return {"listen": when, "script": {"type": "text/javascript", "exec": lines}}


@dataclass(frozen=True)
class Rpc:
    """One JSON-RPC call to the gateway, and what should be true of its answer."""

    name: str
    description: str
    payload: Json
    tests: list[str]


def _rpc(call: Rpc) -> Json:
    """Render one gateway call as a Postman request."""
    headers = [
        {"key": "Content-Type", "value": "application/json"},
        {"key": "Accept", "value": "application/json, text/event-stream"},
        {"key": "Authorization", "value": "Bearer {{executor_token}}"},
    ]
    if call.payload.get("method") != "initialize":
        headers.append({"key": "mcp-session-id", "value": "{{session_id}}"})
    return {
        "name": call.name,
        "event": [_script(call.tests, "test")] if call.tests else [],
        "request": {
            "method": "POST",
            "header": headers,
            "body": {"mode": "raw", "raw": json.dumps(call.payload, indent=2)},
            "url": {"raw": "{{executor_url}}/mcp", "host": ["{{executor_url}}"], "path": ["mcp"]},
            "description": call.description,
        },
    }


def gateway_folder() -> Json:
    """The connector as an agent reaches it: through Executor, over HTTP."""
    a_read = "salesforce_tool_list_by_kind"
    assert a_read in {action.spec.tool_name for action in BY_ID.values()}
    return {
        "name": "1. Gateway (Executor)",
        "description": (
            "The route an agent actually takes. Postman cannot speak stdio, so these "
            "reach the connector through Executor's HTTP endpoint, which is where it "
            "is meant to be reached anyway. Run them in order: initialize stores the "
            "session id every later request needs."
        ),
        "item": [
            _rpc(
                Rpc(
                    name="Initialize (stores the session id)",
                    description="Opens an MCP session. The session id comes back as a response "
                    "header, and the test script stores it, so run this first.",
                    payload={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "postman", "version": "1.0"},
                        },
                    },
                    tests=CAPTURE_SESSION + ANSWERED_WITHOUT_ERROR,
                )
            ),
            _rpc(
                Rpc(
                    name="List tools",
                    description="What the gateway publishes. Expect Executor's own handful, not "
                    "this connector's seventeen: the seventeen live in a catalogue that generated "
                    "code searches, which is the entire point of the gateway.",
                    payload={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    tests=LIST_HOLDS_EVERY_TOOL + ANSWERED_WITHOUT_ERROR,
                )
            ),
            _rpc(
                Rpc(
                    name=f"Call a read tool ({a_read})",
                    description="A read that needs no Salesforce call at all, so it exercises "
                    "the whole path -- gateway, policy, connector, dispatch -- and touches no "
                    "org.\n\nNOT YET VERIFIED. It assumes the gateway's MCP endpoint accepts a "
                    "namespaced tool path, which is the vocabulary its CLI and its `execute` "
                    "tool use. If this answers 'unknown tool', reach the same tool through "
                    "`execute` instead, and correct this request. Run it first: it is the "
                    "cheapest way to find out whether the whole path works.",
                    payload={
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": f"salesforce.org.default.{a_read}",
                            "arguments": {"kind": "write"},
                        },
                    },
                    tests=ANSWERED_WITHOUT_ERROR,
                )
            ),
            {
                "name": "Integrations and tool counts",
                "event": [
                    _script(
                        [
                            "pm.test('answered 200', () => pm.response.to.have.status(200));",
                            "const found = pm.response.json().find(i => i.slug === 'salesforce');",
                            "pm.test('the connector is registered', () =>"
                            " pm.expect(found, 'no salesforce integration').to.not.be.undefined);",
                        ],
                        "test",
                    )
                ],
                "request": {
                    "method": "GET",
                    "header": [{"key": "Authorization", "value": "Bearer {{executor_token}}"}],
                    "url": {
                        "raw": "{{executor_url}}/api/integrations",
                        "host": ["{{executor_url}}"],
                        "path": ["api", "integrations"],
                    },
                    "description": "Confirms the connector is registered and how many tools "
                    "the gateway indexed from it.",
                },
            },
            {
                "name": "Policies",
                "event": [
                    _script(
                        [
                            f"const WRITES = {json.dumps(sorted(_write_names()))};",
                            "pm.test('answered 200', () => pm.response.to.have.status(200));",
                            "const approving = pm.response.json()",
                            "    .filter(p => p.action === 'approve')",
                            "    .map(p => p.pattern || '');",
                            "pm.test('no write is auto-approved', () => {",
                            "    const loose = WRITES.filter(w =>"
                            " approving.some(p => p.endsWith(w)));",
                            "    pm.expect(loose, 'these writes run unattended').to.be.empty;",
                            "});",
                            "pm.test('every write is covered by a policy', () => {",
                            "    const all = pm.response.json().map(p => p.pattern || '');",
                            "    const uncovered = WRITES.filter(w =>"
                            " !all.some(p => p.endsWith(w)));",
                            "    pm.expect(uncovered, 'no policy names these').to.be.empty;",
                            "});",
                        ],
                        "test",
                    )
                ],
                "request": {
                    "method": "GET",
                    "header": [{"key": "Authorization", "value": "Bearer {{executor_token}}"}],
                    "url": {
                        "raw": "{{executor_url}}/api/policies",
                        "host": ["{{executor_url}}"],
                        "path": ["api", "policies"],
                    },
                    "description": "Every write should need approval and every read should not. "
                    "The test fails if a write has been left on approve.",
                },
            },
        ],
    }


def salesforce_folder() -> Json:
    """One request per endpoint the connector calls, for checking claims against."""
    items = [
        {
            "name": "Get a token (run this first)",
            "event": [_script(TOKEN_IS_USABLE, "test")],
            "request": {
                "method": "POST",
                "header": [{"key": "Content-Type", "value": "application/x-www-form-urlencoded"}],
                "body": {
                    "mode": "urlencoded",
                    "urlencoded": [
                        {"key": "grant_type", "value": "client_credentials"},
                        {"key": "client_id", "value": "{{sf_client_id}}"},
                        {"key": "client_secret", "value": "{{sf_client_secret}}"},
                    ],
                },
                "url": {
                    "raw": "{{sf_login_url}}/services/oauth2/token",
                    "host": ["{{sf_login_url}}"],
                    "path": ["services", "oauth2", "token"],
                },
                "description": "Stores access_token and instance_url for everything below.",
            },
        }
    ]
    for name, method, url, description, body in ENDPOINTS:
        writes = method in WRITE_METHODS
        request: Json = {
            "method": method,
            "header": [
                {"key": "Authorization", "value": "Bearer {{access_token}}"},
                {"key": "Content-Type", "value": "application/json"},
            ],
            "url": url,
            "description": description
            + ("\n\nWRITES. Refused unless allow_writes is true." if writes else ""),
        }
        if body is not None:
            request["body"] = {"mode": "raw", "raw": json.dumps(body, indent=2)}
        events = [
            _script(["pm.test('answered', () => pm.response.to.not.have.status(0));"], "test")
        ]
        if writes:
            events.insert(0, _script(REFUSE_UNLESS_ALLOWED, "prerequest"))
        items.append({"name": name, "event": events, "request": request})
    return {
        "name": "2. Salesforce REST",
        "description": (
            "One request per endpoint the connector calls. This is the audit in a form "
            "you can run: when a tool description and the platform disagree, this is "
            "where you find out which of them is right.\n\n"
            "Writes here hit a real org. They are refused unless allow_writes is true, "
            "and the template ships it false. Point the environment at a sandbox."
        ),
        "item": items,
    }


def collection() -> Json:
    reads = sum(1 for a in BY_ID.values() if a.spec.kind is ActionKind.READ)
    writes = sum(1 for a in BY_ID.values() if a.spec.kind is not ActionKind.READ)
    return {
        "info": {
            "name": "Salesforce MCP connector",
            "schema": SCHEMA,
            "description": (
                f"Two ways to exercise this connector: through the gateway an agent uses, "
                f"and against the Salesforce endpoints it calls.\n\n"
                f"{reads} read tools, {writes} write tools. Generated by "
                f"tests/postman/build_collection.py -- edit that, not this file, or the "
                f"next run will overwrite you.\n\n"
                f"Import environment.template.json, fill it in, and select it. Nothing "
                f"in this collection carries a credential."
            ),
        },
        "item": [gateway_folder(), salesforce_folder()],
    }


def environment() -> Json:
    """Names every variable, supplies no value that matters."""
    filled = [
        ("executor_url", "http://127.0.0.1:4789", "Where Executor is listening."),
        ("executor_token", "", "From ~/.executor/server-control/auth.json. Secret."),
        ("session_id", "", "Filled in by the initialize request. Leave empty."),
        (
            "sf_login_url",
            "https://test.salesforce.com",
            "test. for a sandbox, login. for production.",
        ),
        ("sf_client_id", "", "Consumer key of the External Client App. Secret."),
        ("sf_client_secret", "", "Consumer secret. Secret."),
        ("access_token", "", "Filled in by the token request. Leave empty."),
        ("instance_url", "", "Filled in by the token request. Leave empty."),
        ("api_version", "v67.0", "Match SF_API_VERSION in your .env."),
        ("contact_id", "", "A real contact in your sandbox, starting 003."),
        ("opportunity_id", "", "A real opportunity, starting 006."),
        ("account_id", "", "A real account, starting 001."),
        ("allow_writes", "false", "Set to true only against a sandbox you can afford to dirty."),
    ]
    return {
        "name": "Salesforce MCP (fill this in)",
        "values": [
            {
                "key": key,
                "value": value,
                "type": "secret" if "Secret." in note else "default",
                "enabled": True,
                "description": note,
            }
            for key, value, note in filled
        ],
    }


def main() -> None:
    parsed = argparse.ArgumentParser(description=__doc__)
    parsed.add_argument("--check", action="store_true", help="verify without writing")
    args = parsed.parse_args()

    built = json.dumps(collection(), indent=2) + "\n"
    template = json.dumps(environment(), indent=2) + "\n"

    if args.check:
        for path, wanted in ((COLLECTION, built), (ENVIRONMENT, template)):
            if not path.exists() or path.read_text(encoding="utf-8") != wanted:
                print(f"{path.name} is out of date. Run: python {pathlib.Path(__file__).name}")
                raise SystemExit(1)
        print("collection and environment template are up to date")
        return

    COLLECTION.write_text(built, encoding="utf-8")
    ENVIRONMENT.write_text(template, encoding="utf-8")
    gateway, salesforce = collection()["item"]
    print(f"{len(gateway['item'])} gateway requests, {len(salesforce['item'])} Salesforce requests")
    print(f"written to {COLLECTION.name} and {ENVIRONMENT.name}")


if __name__ == "__main__":
    main()
