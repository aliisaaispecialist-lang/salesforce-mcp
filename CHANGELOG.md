# Changelog

All notable changes to this connector are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.0.0] — 2026-08-07

First release. Handoff notes for whoever picks this up next are at the bottom
of this entry.

### Added

- **Five typed actions** behind one `execute` interface: `salesforce.search_contact`
  (read), `salesforce.create_contact`, `salesforce.update_contact`,
  `salesforce.create_opportunity`, `salesforce.add_activity_note` (writes).
  Each validates its own input model, knows one Salesforce endpoint, and
  returns the same success/error envelope. (`src/salesforce_connector/actions/`)
- **OAuth 2.0 JWT Bearer authentication** as the default flow — a signed
  assertion exchanged for an access token, no password and no secret in
  transit. **OAuth 2.0 Client Credentials** as a fallback for anyone who
  cannot complete the certificate step. (`auth/jwt_bearer.py`,
  `auth/client_credentials.py`)
- **`test_connection`**, which reads the org's limits endpoint and changes
  nothing, and **`list_actions`**, which describes all five actions in a
  stable order. Both go through the same `SalesforceConnector` door as
  `execute`. (`connector.py`)
- **A production-org guard**: `SF_LOGIN_URL` pointing at
  `login.salesforce.com` is refused unless `SF_ALLOW_PRODUCTION=true` is set
  explicitly. (`config.py`)
- **Idempotency for writes**: every write action requires a caller-supplied
  `idempotency_key`; a repeated key within the same process returns the
  original result instead of writing twice. Deduplication is process-scoped
  — see Known limitations. (`idempotency.py`, `actions/action.py`)
- **A checkpoint journal** for multi-step operations, so a resumed attempt
  skips whatever already finished instead of repeating it or reporting a
  false failure. (`checkpoint.py`)
- **Signed, time-limited, call-bound write approval**: `ApprovalGate` mints a
  token that approves exactly one action id with exactly one set of
  arguments, expires after ten minutes by default, and is generated fresh
  per process. Any write action refuses to run without an approved request.
  (`approval.py`, `actions/action.py`)
- **A worked example on every action**, carried on the `ActionSpec` and
  rendered into all three surfaces: the MCP tool's input schema as the JSON
  Schema `examples` annotation, the OpenAPI operation as keyed request and
  response examples, and the tool description a model reads. Each one is
  validated against the action's own input and output models by
  `tests/unit/test_examples.py`, so an example that stopped being true fails
  the build. (`contract.py::ActionExample`, `schemas/*.py`)
- **Contract tests** (`tests/contract/`) asserting that the four descriptions
  of this connector stay one description: `connector.yaml`, the action
  registry, the MCP tool list, and `openapi.yaml`. Also that
  `SalesforceConnector` still has every member `DooConnector` declares —
  asked of the Protocol itself rather than copied into the test.
- **The server asks before it writes.** Every write goes through an MCP
  elicitation — a single-boolean confirmation quoting the action and the
  caller's own values — before the connector is called at all, whether or not
  the caller sent `approved: true`. `decline`, `cancel`, an unchecked box, and
  content the SDK cannot validate all refuse and write nothing. A client that
  declares no `elicitation` capability is never asked, per the specification,
  and falls back to the `approved` parameter. (`mcp_approval.py`,
  `mcp_server.py`)
- **A leaky-bucket rate limiter** (60 calls/minute by default) that refuses
  calls over budget rather than queuing them, and tells the caller how long
  to wait. (`ratelimit.py`)
- **An error taxonomy of eight failure types**, each carrying a category, a
  reason, and a next step a model can act on, translated from Salesforce's
  own error codes by shape rather than a fixed table.
  (`errors/model.py`, `errors/mapping.py`, `errors/salesforce_codes.yaml`)
- **Structured logging to stderr** with a censoring processor that masks
  secrets by key name (at any nesting depth of dict-shaped data) and by
  in-string pattern (bearer tokens, PEM private key blocks), plus in-process
  metrics separating calls from attempts. (`observability.py`)
- **Untrusted-content fencing**: every tool result is wrapped in a
  `<salesforce_record_data-NONCE>` / `</salesforce_record_data-NONCE>` pair
  with a nonce generated fresh per response, so record text is marked as
  data rather than instruction and a record cannot forge the fence's own
  closing tag. (`mcp_translate.py`)
- **A thin MCP adapter** using the low-level `Server` API (not the decorator
  API, which measurably raised malformed-call rates by nesting arguments
  under a `params` key) so schemas are published exactly as authored.
  (`mcp_server.py`)
- **A generated OpenAPI 3.1.0 document**, produced from the same action
  specifications the MCP adapter reads, so the two descriptions cannot
  disagree. A test regenerates the document and fails by name if it drifts
  from the committed file. (`openapi.py`, `openapi.yaml`)
- **`connector.yaml`**, declaring provider, auth type, scopes, actions,
  capabilities, risks, and limitations. Startup compares it against the
  actions actually registered and refuses to run if they disagree.
- **Import-linter layering**: a docstring's claim that "only the client opens
  a socket" or "only the adapter knows the protocol" is enforced as a
  contract (`.importlinter`), not left as a promise, and checked in CI and
  pre-commit on every change.
- **A multi-stage, non-root Docker image** speaking stdio only, built from
  `src/`, `mcp/`, and `connector.yaml` alone — no test fixtures, no `.env`,
  no Git history layer. (`Dockerfile`, `.dockerignore`)
- **A three-family security test suite** (`tests/security/test_injection_and_leaks.py`):
  query injection through search terms, prompt injection through record
  text, and credential/secret leakage through logs, errors, and printed
  settings.
- **Secret-scanning gates**: `detect-private-key` and `gitleaks` in
  pre-commit, plus a dedicated `gitleaks` CI job scanning full Git history
  (`fetch-depth: 0`), addressing Definition of Done item 8.

### Security

- **Fixed a fence-escape vulnerability found by this release's own security
  test suite, before it ever shipped.** The untrusted-content fence
  originally used a fixed marker (`<salesforce_record_data>` /
  `</salesforce_record_data>`). A Salesforce field containing the literal
  closing tag as text could end the fence early, and everything the record
  wrote after that point would have been read as though it came from the
  connector rather than from the record — a working prompt-injection
  primitive. `test_a_record_cannot_close_the_fence_and_speak_outside_it`
  was written to prove the fence held and failed against the original
  implementation. The fix appends a `secrets.token_hex` nonce to both
  markers, generated fresh per response, so a record's author cannot know
  the value needed to close a fence early. (`mcp_translate.py`)
- This fix, and the security suite that found it, landed in commit
  `2dcc0d4` ("Let a caller do what the error message tells it to").

### Known limitations

- **Sandbox only.** `SF_LOGIN_URL` defaults to `test.salesforce.com`, and a
  production host is refused unless explicitly permitted.
- **Five actions.** The wider Salesforce REST surface is out of scope for
  v1; see `connector.yaml`.
- **stdio transport only.** There is no deployed HTTPS endpoint.
- **Idempotency memory is process-scoped, not durable.** A restart between
  a write reaching Salesforce and the response reaching this connector
  loses the record of it, and a subsequent retry with the same key can
  create a duplicate record. Durable, provider-side deduplication would
  require writing through an External Id field on the org, which needs
  schema access this project does not have.
- **No live sandbox test has run.** The `learning` and `integration` pytest
  markers exist for tests that need a real org (`pyproject.toml`
  `addopts = "-m 'not learning and not integration'"`), because no
  Salesforce sandbox has been provisioned yet. Every test that has run
  against this connector runs against `respx`-mocked HTTP, not a live org.
- **A client that declares no elicitation capability is never asked about a
  write.** The specification forbids sending a request whose capability the
  client did not declare, so those callers still fall back to setting
  `approved: true` themselves, and there this connector cannot tell a human's
  confirmation from a model setting a boolean. Nothing on the server side can
  close that gap.
- **Even a client that is asked may answer on its own.** The specification
  says clients SHOULD put an elicitation to a person, not MUST. What this
  server guarantees is that it asked, that it refused every non-answer, and
  that the write it executed is the one it described in the question.
- **Two-step writes are not transactional.** Creating an opportunity and
  attaching a note or contact to it is two calls; the second can fail after
  the first has taken effect, and the result reports that partial state
  rather than a clean success or failure.

### Verified against a real org

A Salesforce Developer Edition org now exists, and the Definition of Done's
"one real sandbox test where access permits" item is met: all 30 tests in
`tests/integration/` and `tests/learning/` pass against it, as does a full
stdio round trip in which a client listed the five tools, searched, and had an
unapproved write refused.

That run found four defects no mocked test could have, all fixed:

- a replayed idempotency key reported `created: true`, because the ledger
  returned the stored result verbatim — invisible to every mocked test, since
  each calls a key exactly once
- `changed_fields` came back in Salesforce's casing rather than the caller's
- a missing record was classified as invalid input rather than not-found,
  so the code every write tool documents for that case was never produced
- an activity note supplied its own `TaskSubtype` default, which a restricted
  per-org picklist rejected — the same reasoning as ADR-008, not carried across

The org needed an **External Client App**: Salesforce disabled connected app
creation in new orgs in Winter '26. Nothing in `src/` changed for that — the
flow, the assertion, and the scopes are identical; only where the certificate
is registered moved.

### Still blocked

- **Nothing by access.** The remaining gaps are decisions: whether to add an
  External Id field to the org for provider-side deduplication, and running
  the ten evaluation questions live, which needs the seed contacts loaded.

### Handoff notes

What exists: a reusable core (`connector.py`) behind one door, five actions,
JWT Bearer and Client Credentials auth, an elicitation-based approval flow
bound to a signed, expiring ticket, process-scoped idempotency, rate limiting,
a censoring logger, a generated OpenAPI document, a thin MCP adapter, and a
security test suite that has already found and fixed three real defects before
release.

What is deliberately not built: HTTP/SSE transport, durable cross-restart
idempotency, and anything beyond the five assigned actions.

What is blocked: one thing, and it is an asset rather than a decision — a
Salesforce sandbox org. It blocks the live evaluation run, the one real
sandbox test, and two questions that cannot be answered from documentation
(whether `parameterizedSearch` honours `offset`, and whether an External Id
field is the right answer to cross-restart idempotency). None of it blocks
reading or reviewing the code as it stands.
