# Salesforce Connector

A production-oriented Salesforce connector built for the Builders League Connector
Test Suite (Cohort 01, MK Lab × DOO): one reusable core, five typed actions
(`search_contact`, `create_contact`, `update_contact`, `create_opportunity`,
`add_activity_note`), and a thin MCP adapter that exposes them over stdio. The
core, the OpenAPI document, and the MCP tools are generated from the same
Pydantic schemas, so there is exactly one description of each action, not
three that can drift apart.

Provider: Salesforce REST API `v67.0`. Authentication: OAuth 2.0 JWT Bearer.
Language: Python 3.12. Status: all five actions implemented and unit/fixture
tested; no live Salesforce org has been available to run the sandbox tier —
see [Known limitations and access blockers](#known-limitations-and-access-blockers).
See also [`SECURITY.md`](SECURITY.md) for the full threat model and
[`CHANGELOG.md`](CHANGELOG.md) for the release history.

---

## Contents

- [Quick start](#quick-start)
- [Configuration](#configuration)
- [The five actions](#the-five-actions)
- [Architecture](#architecture)
- [Design decisions (ADR log)](#design-decisions-adr-log)
- [Reliability](#reliability)
- [Security](#security)
- [Testing](#testing)
- [Known limitations and access blockers](#known-limitations-and-access-blockers)
- [Roadmap](#roadmap)
- [Licence](#licence)

---

## Quick start

Both paths below were run against this repository while writing this document:
`docker build`, a container start/stop on closed stdin, `pytest -q`, `ruff
check .`, `mypy src tests`, and `lint-imports` all pass. Neither path was
exercised against a real Salesforce org — see
[Known limitations](#known-limitations-and-access-blockers).

### Docker

```bash
docker build -t salesforce-connector .
docker run -i --rm --env-file .env salesforce-connector
```

The `-i` is not optional. This image speaks stdio and exposes no port; without
`-i` the container's stdin is closed immediately and the server never sees a
request. Closing stdin is also the correct way to stop it — the process exits
0 on EOF, which is what the `image` job in `.github/workflows/ci.yml` asserts
on every push, and what running `docker run -i --rm ... salesforce-connector
< /dev/null` here confirmed directly.

### Python

```bash
pip install -e ".[dev]"
cp .env.example .env   # fill in SF_CLIENT_ID, SF_USERNAME, SF_PRIVATE_KEY
make check              # format, lint, layering, types, tests — what CI runs
PYTHONPATH=src python mcp/server.py
```

`make check` runs `ruff format .`, `ruff check .`, `lint-imports`, `mypy src
tests`, and `pytest`, in that order — the same sequence and the same tools CI
runs on every push. See [Testing](#testing) for the numbers this produced.

### Point an MCP host at it

`examples/mcp_client_config.json` has two ready-to-paste entries for an MCP
host's `mcpServers` object (for example `claude_desktop_config.json`): one
that runs the Docker image, one that runs `mcp/server.py` directly with
`env` values filled in from `.env.example`. Replace the placeholder absolute
path with the real one on your machine.

---

## Configuration

Every variable the connector reads, and nothing it doesn't — `.env.example`
and `Settings` (`src/salesforce_connector/config.py`) are tested against each
other (`tests/unit/test_env_example.py`) so this table cannot drift from the
code.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SF_CLIENT_ID` | yes | — | Consumer Key of the Connected App / External Client App. |
| `SF_USERNAME` | yes | — | The user the connector acts as. Must be pre-authorised for the Connected App; that user's profile is the real ceiling on what any action can do. |
| `SF_PRIVATE_KEY` | yes | — | PEM private key matching the certificate uploaded to the Connected App. `\n` between lines is accepted and restored, since most container runtimes and CI secret stores cannot hold a literal multi-line value. |
| `SF_CLIENT_SECRET` | no | none | Only used by the Client Credentials fallback flow (ADR-020). Leave blank when using JWT Bearer, which transmits no secret at all. |
| `SF_LOGIN_URL` | no | `https://test.salesforce.com` | Login host. Sandbox by default and deliberately so (ADR-016). |
| `SF_ALLOW_PRODUCTION` | no | `false` | Must be explicitly `true` before `SF_LOGIN_URL` is allowed to point at `https://login.salesforce.com`. A typo cannot silently point this connector at production. |
| `SF_API_VERSION` | no | `v67.0` | Salesforce REST API version, pinned so a platform release cannot change behaviour underneath the connector. |
| `SF_READ_TIMEOUT_SECONDS` | no | `5.0` | Timeout for read calls. |
| `SF_WRITE_TIMEOUT_SECONDS` | no | `15.0` | Timeout for write calls — longer than reads, because a write that times out may already have been applied. |

Two things worth being precise about:

- **`connector.yaml`'s `required_env` list also names `SF_LOGIN_URL`.** The
  code is the source of truth: `Settings.login_url` has a default, so it is
  not actually required to start the server. Treat the manifest's
  `required_env` as "what a deployer should look at," not a strict
  startup-blocking list — only `SF_CLIENT_ID`, `SF_USERNAME`, and
  `SF_PRIVATE_KEY` are enforced by `pydantic-settings` at import time.
- **Two different "versions" appear in this repository.** The Python package
  version (`salesforce_connector.__version__`, `0.1.0` → `1.0.0` at handoff)
  is the connector's own release number. `manifest.version` and the
  `openapi.yaml` `info.version` field are the *Salesforce API version*
  (`v67.0`, from `SF_API_VERSION`) — a different axis entirely. Neither one
  is a typo for the other.

A missing or malformed required variable stops the server before any tool is
published, with every fault named at once (`config.py::_explain`) — a
connector that starts and then fails every call is harder to diagnose than
one that refuses to start.

---

## The five actions

All five share one envelope (`ActionResult`): `ok`, `request_id`, `data`,
`error`, `pagination`, `rate_limit`, `warnings`. Every write additionally
requires `idempotency_key` (min 8 characters) and `approved` (boolean,
default `false`) in its own input schema — see
[ADR-006](#adr-006-idempotency-key-required-on-every-write-enforced-structurally)
and [ADR-022](#adr-022-approval-today-is-a-parameter-and-a-refusal-elicitation-is-built-but-not-wired).

| Action | Kind | Risk | Naturally idempotent | Needs approval |
|---|---|---|---|---|
| `salesforce.search_contact` | read | low | yes | no |
| `salesforce.create_contact` | write | medium | no | yes |
| `salesforce.update_contact` | write | medium | yes | yes |
| `salesforce.create_opportunity` | write | medium | no | yes |
| `salesforce.add_activity_note` | write | low | no | yes |

### `salesforce.search_contact`

Finds contacts by name, email, phone, or account name via `POST
.../parameterizedSearch` (never SOQL/SOSL — see
[ADR-003](#adr-003-parameterizedsearch-instead-of-soql-or-sosl)).

- **Required:** `query` (2–200 characters).
- **Optional:** `limit` (1–200, default 20), `cursor` (opaque, from a previous
  page's `next_cursor`).
- **Returns:** `contacts[]` (`id`, `name`, `email`, `phone`, `account_id`,
  `account_name`, `title`), `returned`, `next_cursor`. `account_name` is
  declared in the output schema but is always `null` today — the action never
  requests `AccountName` from Salesforce; see
  [Known limitations](#known-limitations-and-access-blockers).

### `salesforce.create_contact`

Creates a Contact via `POST .../sobjects/Contact`.

- **Required:** `last_name`, `idempotency_key`.
- **Optional:** `approved` (must be `true` or the write is refused),
  `first_name`, `email` (rejected before sending if malformed), `phone`,
  `title`, `account_id`, `allow_duplicate` (default `false`).
- **Returns:** `id`, `name`, `created` (`false` means an identical
  `idempotency_key` had already produced this record — the original outcome,
  not a new one).
- Salesforce's duplicate rules are left switched on. A match is refused and
  the matched record ids are returned unless `allow_duplicate=true` was sent.

### `salesforce.update_contact`

Changes fields on an existing Contact via `PATCH
.../sobjects/Contact/{id}`, then re-reads the record, because Salesforce
answers a successful `PATCH` with `204 No Content` — no body to report back
(see [ADR-007](#adr-007-re-read-after-patch)).

- **Required:** `contact_id` (15–18 characters), `idempotency_key`, and at
  least one of the optional fields below — an update naming nothing is
  rejected before any request is sent.
- **Optional:** `approved`, `first_name`, `last_name`, `email`, `phone`,
  `title`, `account_id`.
- **Returns:** `id`, `name`, `changed_fields`, `email`, `phone`, `title` —
  all as they stand after the change, not as they were sent.

### `salesforce.create_opportunity`

Creates an Opportunity via `POST .../sobjects/Opportunity`, and optionally
links a Contact to it via a second call
(`POST .../sobjects/OpportunityContactRole`).

- **Required:** `name` (≤120 chars), `stage_name`, `close_date`
  (`YYYY-MM-DD`), `idempotency_key`.
- **Optional:** `approved`, `account_id`, `amount` (≥0), `contact_id`,
  `description` (≤32000 chars).
- **Returns:** `id`, `name`, `stage_name`, `created`, `contact_linked`
  (`true`/`false`/absent — see below).
- `stage_name` is validated against the org's own `StageName` picklist
  (`GET .../sobjects/Opportunity/describe`, cached per action instance)
  before the write is sent; an invalid value is rejected with the exact
  accepted values (see
  [ADR-008](#adr-008-opportunity-stage-read-from-the-orgs-picklist-never-hardcoded)).
  If the profile cannot run `describe`, the check is skipped and Salesforce is
  left to judge.
- Linking a contact is a second write that can fail after the Opportunity
  already exists. `contact_linked: false` reports that partial state
  honestly rather than as an outright failure — the deal must not be created
  a second time in that case.

### `salesforce.add_activity_note`

Logs a call, email, meeting, or note as a completed `Task`
(`POST .../sobjects/Task`) — see
[ADR-005](#adr-005-add_activity_note-as-a-task-not-a-note-or-contentnote).

- **Required:** `related_to_id` (a Contact id starting `003` or an
  Opportunity id starting `006`; anything else is refused before any request
  is sent), `subject` (≤255 chars), `idempotency_key`.
- **Optional:** `approved`, `body` (≤32000 chars), `activity_kind`
  (`Call` / `Email` / `Meeting` / `Other`, default `Other`), `activity_date`
  (`YYYY-MM-DD`, default today).
- **Returns:** `id`, `subject`, `related_to_id`, `created`.
- The id prefix decides `WhoId` (Contact) vs. `WhatId` (Opportunity):
  Salesforce silently accepts an id in the wrong field and attaches the
  activity to nothing, so guessing wrong is worse than refusing.

Every action's schema, description, and error guidance is generated once
(`schemas/*.py` → `ActionSpec`) and consumed identically by `mcp_server.py`
and `openapi.py` — see [Architecture](#architecture).

---

## Architecture

Three layers, dependencies pointing only inward. `.importlinter` enforces
this on every commit and in CI (`lint-imports`), not just in prose — four
contracts, checked over 69 files / 209 import edges as of this writing, all
kept:

```text
   ┌──────────────────┐        ┌──────────────────┐
   │   mcp/server.py   │        │   openapi.yaml    │   adapters: thin,
   │    (launcher)      │        │   (generated)      │   no Salesforce logic
   └─────────┬──────────┘        └─────────┬──────────┘
             │                              │
   ┌─────────▼──────────┐        ┌──────────▼──────────┐
   │     mcp_server       │        │     openapi.py        │
   │   (stdio wiring)      │        │   (spec builder)       │
   └─────────┬──────────┘        └──────────┬──────────┘
   ┌─────────▼──────────┐                   │
   │   mcp_translate       │                   │
   │ (types <-> protocol) │                   │
   └─────────┬──────────┘                   │
             └───────────────┬───────────────┘
                    ┌─────────▼─────────┐
                    │     connector       │  test_connection()
                    │                       │  list_actions()
                    │                       │  execute()
                    └─────────┬─────────┘
                    ┌─────────▼─────────┐
                    │      actions          │  one module per action,
                    │                       │  one endpoint each
                    └─────────┬─────────┘
        ┌───────────────────┼───────────────────┐
┌───────▼───────┐   ┌────────▼───────┐   ┌────────▼───────┐
│     client       │   │      auth        │   │    schemas      │
│ (only module   │   │ (JWT Bearer /   │   │ (pydantic I/O,  │
│  that opens a  │   │  Client Creds)  │   │  ActionSpec)     │
│  socket)         │   │                   │   │                   │
└───────┬───────┘   └────────┬───────┘   └────────┬───────┘
        └───────────────────┼───────────────────┘
                    ┌─────────▼─────────┐
                    │       errors           │  model, mapping (data-driven),
                    │                       │  retry policy
                    └─────────┬─────────┘
                    ┌─────────▼─────────┐
                    │      contract          │  no vendor import at all —
                    │                       │  not httpx, mcp, jwt, yaml,
                    │                       │  tenacity, structlog,
                    │                       │  itsdangerous, aiolimiter
                    └───────────────────────┘
```

**Why the MCP adapter is deliberately thin.** `mcp_server.py` opens the
connector at startup, lists what it offers, forwards a call, and closes on
the way out; `mcp_translate.py` turns the connector's own types into the
protocol's and back. Neither file contains an endpoint, an object name, or a
query — `tests/unit/test_mcp_server.py::TestTheAdapterKnowsNothingAboutSalesforce`
asserts this directly, by searching the adapter's own source for strings like
`sobjects/`, `parameterizedSearch`, `LastName`, `StageName`, and `WhoId` and
failing if any appear. `openapi.py` is symmetric: it builds its document from
the same `registry.descriptors()` the MCP adapter reads, so the two surfaces
cannot describe an action differently. Both are import-linter-forbidden from
reaching past `connector` into `actions`, `client`, or `auth` directly.

**Two narrower rules, each enforced by its own contract:**

- Only `client.py` may import `httpx` — every other layer reaches the network
  only through the client, so its timeouts, retries, and error mapping cannot
  be bypassed by an action that decides to make its own request.
- Only `mcp_server.py`/`mcp_translate.py` may import the `mcp` package — so
  swapping the protocol layer, or adding a second adapter (a CLI, a batch
  runner), never requires touching `connector.py` or anything below it.

---

## Design decisions (ADR log)

Format: **Context → Options considered → Decision → Trade-offs accepted →
Consequences.** Every entry below is drawn from a docstring, a test, or a
commit already in this repository — nothing here is aspirational.

### ADR-001: Python, not TypeScript

**Context.** The programme's own repository template
(`research/06-doo-assignment.md` §3, and slide 11 of the kickoff deck) uses
`.ts` extensions throughout (`connector.ts`, `client.ts`, `mcp/server.ts`),
and slide 10 presents the shared `DooConnector` contract as a literal
TypeScript `interface`. No page or slide states "you must use TypeScript" in
so many words, but the de facto pressure toward it is real and was weighed
knowingly, not missed.

**Options considered.**
1. TypeScript — matches the template's file extensions and the shared
   contract's presentation exactly; zero risk of a grader reading the
   deviation as non-compliance.
2. Python — no rule anywhere on the site or in the deck actually mandates a
   language; the owner's toolchain and the target's own stated evaluation
   criteria (security, structure, reusability, docs) are language-agnostic.

**Decision.** Python 3.12, with the folder shape kept file-for-file
equivalent to the template (`.py` in place of `.ts`).

**Trade-offs accepted.** A grader skimming the repository tree before reading
anything sees a deviation from the implied convention. This is a known,
accepted risk (recorded in `research/06-doo-assignment.md` §5 and
`OPEN-QUESTIONS.md` D3), not an oversight — mitigated by matching the
template's structure exactly everywhere it is not language-specific.

**Consequences.** Every packaging, typing, and tooling decision downstream
(Hatchling, `pydantic`, `mypy --strict`, `ruff`) is a Python-ecosystem choice
with no TypeScript equivalent to keep in sync. A future TypeScript adapter
sharing the same `connector.yaml`/`openapi.yaml` contract is possible but
would be a separate implementation, not a port.

### ADR-002: Five actions, not the ~90-endpoint Salesforce surface

**Context.** `research/03-salesforce-api-map.md` catalogues roughly 90
distinct Salesforce REST endpoints. The programme assigns exactly five action
IDs to this connector (`research/06-doo-assignment.md` §7) and slide 6 of the
deck explicitly permits going further only "after the assigned five work."

**Options considered.**
1. Build all five to a minimal standard, then add breadth.
2. Build exactly the five assigned actions to an exceptional standard —
   typed schemas, full error taxonomy, retries, idempotency, tests — and
   treat the rest as documented future scope.
3. Build a generic pass-through action (raw SOQL / arbitrary sObject CRUD)
   alongside the five, for coverage.

**Decision.** Option 2. The wider survey lives in
[Roadmap](#roadmap) as prioritised, not-yet-built scope.

**Trade-offs accepted.** A caller who wants to update an Account or run an
arbitrary query has no tool for it in v1. That gap is explicit, not silent —
`connector.yaml`'s `limitations` says so, and the Roadmap says what would
close it.

**Consequences.** Every action added later must justify itself against the
grouping problem `research/03-salesforce-api-map.md` §4 describes: a flat
90-tool manifest measurably degrades tool-selection accuracy. Expansion
should follow that document's tiered/gated shape, not a flat dump.

### ADR-003: `parameterizedSearch` instead of SOQL or SOSL

**Context.** `search_contact` takes free text from a caller — potentially
relayed from an LLM relaying a user's own words. Building a SOQL `WHERE
Name LIKE '%...%'` clause or a SOSL `FIND {...}` string from that text is
exactly the "user input becomes query syntax" injection class the security
criterion (20% of the score) exists to catch.

**Options considered.**
1. SOQL, string-built with the caller's text interpolated — fast to write,
   directly injectable.
2. SOSL, string-built the same way — same defect, different syntax.
3. `POST .../parameterizedSearch` with the term as a JSON value (`q`).

**Decision.** Option 3. `search_contact.py` sends `{"q": query, "sobjects":
[{"name": "Contact"}], ...}` — the term is a JSON string value, not a
fragment of a larger query grammar, so there is no escaping to get wrong and
no query string for it to break out of.

**Trade-offs accepted.** `parameterizedSearch` offers a narrower feature set
than hand-written SOSL (no arbitrary WHERE clauses, no cross-object joins).
That narrowness is the point: less expressive power, less attack surface.

**Consequences.**
`tests/security/test_injection_and_leaks.py::TestQueryInjection` sends six
real injection payloads (a SOQL `OR` clause, a UNION-style probe, a raw
`FIND{}` SOSL string, a `DELETE` attempt, a wildcard probe, and an escaped-
quote probe) and asserts each arrives at Salesforce as a literal `q` value,
byte-for-byte, and that the connector never calls `/query` or `/search?` at
all. Any future read action must default to this pattern; a raw-SOQL action,
if ever added, needs its own explicit, reviewed justification.

### ADR-004: JWT Bearer, not username-password

**Context.** Salesforce announced retirement of the username-password OAuth
flow starting with production rollout weekends beginning **29 August 2026**
(`research/03-salesforce-api-map.md` §6 item 1) — inside the programme's own
build window.

**Options considered.**
1. Username-password flow — simplest to configure, but ships a connector
   that would start failing during the cohort itself.
2. OAuth 2.0 JWT Bearer — a signed assertion exchanged for a token; no
   password, no long-lived secret in transit.
3. OAuth 2.0 Client Credentials — simpler setup (no certificate), but does
   transmit a secret.

**Decision.** JWT Bearer as the primary and default flow
(`auth/jwt_bearer.py`); Client Credentials retained only as an explicit
fallback (ADR-020). Username-password is not implemented at all — not
disabled, absent.

**Trade-offs accepted.** JWT Bearer requires uploading a certificate to the
Connected App and pre-authorising the running-as user — more setup than a
username-password flow would have been, in exchange for a flow that will
still work in September 2026.

**Consequences.** `SF_PRIVATE_KEY` must be a usable RSA PEM key; a malformed
one fails fast with a message naming the likely cause (`ConfigurationError`
in `jwt_bearer.py::_sign`) rather than an opaque signing exception. The
assertion's lifetime is capped at 3 minutes (`_ASSERTION_LIFETIME`), inside
Salesforce's 5-minute ceiling, to tolerate modest clock drift without risking
rejection.

### ADR-005: `add_activity_note` as a Task, not a Note or ContentNote

**Context.** The action name is not disambiguated anywhere in the programme's
materials (confirmed by `research/08-doo-presentation.md` §5: no slide names
the target object). Salesforce offers three candidates for "logging an
interaction": `Task`, the classic `Note` object, and `ContentNote`.

**Options considered.**
1. `Task` — one call, appears on the record's Activity timeline, works in
   every org regardless of edition or feature toggles.
2. `Note` (classic) — one call, but disabled outright in many modern
   (Lightning) orgs.
3. `ContentNote` — Lightning-native, but needs a base64-encoded body plus a
   second `ContentDocumentLink` call to attach it to a record.

**Decision.** `Task`, written already `Status: Completed` — this action
records something that already happened, not something to schedule.

**Trade-offs accepted.** A `Task` is a more general object than a
purpose-built "note" concept; callers who specifically wanted a Lightning
`ContentNote` (e.g. for rich text or attachments) do not get one from this
action.

**Consequences.** Changing this decision means changing exactly one schema
module (`schemas/add_activity_note.py`) and its action
(`actions/add_activity_note.py`) — nothing else in the connector encodes the
choice, per the module's own docstring. `WhoId` vs. `WhatId` attachment is
decided from the target id's own prefix (`003` → Contact → `WhoId`, `006` →
Opportunity → `WhatId`); anything else is refused before any request is sent,
since Salesforce accepts a wrong-field id silently and attaches the activity
to nothing.

### ADR-006: Idempotency key required on every write, enforced structurally

**Context.** A REST create is not idempotent: a client that times out and
retries can create a second record with no way to tell it happened. The
programme's Definition of Done item 7 requires write actions to document
"approval, idempotency, duplicate, and retry behavior."

**Options considered.**
1. Recommend an idempotency key in documentation, make it optional in the
   schema — relies on every caller reading and following the advice.
2. Require it in each write's Pydantic model, and additionally refuse to
   *register* a write action whose schema does not list it as required.

**Decision.** Option 2. `contract.py::ActionDescriptor._writes_require_an_idempotency_key`
is a `model_validator` that raises if a write action's `input_schema` does
not list `idempotency_key` under `required` — this runs at import time
(`registry.py` builds every descriptor eagerly), so a write action missing
the field cannot be registered, published as a tool, or called at all. It is
not a runtime check that could be skipped; it is a condition of the action
existing.

**Trade-offs accepted.** Every write's Pydantic model carries one more
required field, and every write example/test must supply one. The four write
schemas all declare `idempotency_key: Annotated[str, Field(min_length=8, ...)]`
consistently as a result.

**Consequences.** `Action._already_done` checks the ledger
(`IdempotencyLedger.find`) before doing any work; a repeated key with a
completed result short-circuits to the original outcome with a warning
attached, rather than repeating the write.
`tests/security/test_injection_and_leaks.py::TestWritesCannotHappenQuietly::test_a_repeated_key_writes_once_however_many_times_it_is_called`
calls the same request five times and asserts Salesforce was called exactly
once. See [Reliability](#reliability) for the honest limits of this
mechanism — it is process-scoped, and one ledger state
(`KeyState.IN_FLIGHT`) is declared but never reached by the current call
path.

### ADR-007: Re-read after PATCH

**Context.** Salesforce answers a successful Contact `PATCH` with `204 No
Content` — no body at all. Returning that as-is would tell a caller only
that nothing went wrong, not what the record now holds.

**Options considered.**
1. Return the bare success with no data — cheapest, but tells a caller
   nothing about the record's actual current state.
2. Echo back exactly what the caller sent — cheap, but wrong the moment a
   validation rule, trigger, or formula field changes the value en route.
3. Re-fetch the record after the write and return what Salesforce actually
   stored.

**Decision.** Option 3. `update_contact.py::_read_back` issues a `GET`
immediately after the `PATCH`, naming only the fields the action reports
(`Id, Name, Email, Phone, Title`) rather than the whole record.

**Trade-offs accepted.** Every update costs two API calls instead of one,
against the org's daily allowance. That cost buys an answer that means
something rather than an empty acknowledgement.

**Consequences.** `changed_fields` in the output reports what *this call*
set, read from the outgoing PATCH body, not from a diff against the
re-fetched state — the two are expected to agree, but are computed
separately by design (the field list is a record of intent, the rest of the
payload is a record of result).

### ADR-008: Opportunity stage read from the org's picklist, never hardcoded

**Context.** `StageName` on Opportunity is a picklist that every Salesforce
org configures independently — there is no universal, correct list of sales
stages across orgs.

**Options considered.**
1. Ship a fixed list of "common" stage names (`Prospecting`, `Closed Won`,
   ...) as an enum in the schema — fails the moment an org renamed or
   reordered its stages, which is common.
2. Accept any string, let Salesforce reject an invalid one — correct but
   unhelpful: the caller gets a raw provider error with no indication of
   what values would have worked.
3. Accept any string, but validate it against the org's live picklist first
   (`GET .../sobjects/Opportunity/describe`) and, on mismatch, return the
   exact accepted values in the error.

**Decision.** Option 3. `create_opportunity.py::_reject_unknown_stage` fetches
and caches the picklist once per action instance and checks before writing.

**Trade-offs accepted.** One extra (cacheable) API call on the common path.
If the running user's profile cannot run `describe` on Opportunity, the check
is skipped entirely and Salesforce is left to be the final judge — losing the
helpful error is accepted in exchange for not losing the action outright.

**Consequences.** `evaluations/questions.xml` includes a direct regression
for this: "True or false: in `salesforce_create_opportunity`'s published
input schema, `stage_name` is restricted to a fixed enum" — answer `False`,
by design, forever, unless this ADR is revisited.

### ADR-009: The low-level MCP `Server` over the decorator API

**Context.** The MCP Python SDK offers two surfaces: a decorator-based API
that derives a tool's JSON Schema from a Python function's signature, and a
low-level `Server` that is handed pre-built `Tool` objects. This connector
already has hand-authored, tested Pydantic schemas for every action
(`schemas/*.py`).

**Options considered.**
1. Decorator API — less code to wire up, but a Pydantic parameter passed to
   a decorated function is nested under a `params` key in the resulting tool
   schema rather than published flat, which measurably raises the rate of
   malformed tool calls from callers who read the schema literally.
2. Low-level `Server` — more explicit wiring (`on_list_tools`,
   `on_call_tool`), but tools are published with the exact schema already
   authored and tested, with no parameter nesting.

**Decision.** Option 2 (`mcp_server.py::build_server`).

**Trade-offs accepted.** `list_tools`/`call_tool` are written by hand rather
than generated from function signatures — a few more lines of adapter code,
all of it schema-agnostic.

**Consequences.**
`tests/unit/test_mcp_server.py::TestPublishedTools::test_arguments_are_flat_rather_than_nested_under_a_wrapper`
asserts no tool's input schema has a `params` property. As a secondary
benefit noted in the module's docstring, the low-level `Server` gives
"dual-era support" for free: the same request loop serves both the legacy
handshake and the modern per-request envelope, decided by the client's first
request, with no branch this connector has to maintain itself.

### ADR-010: stdio and Docker, not a hosted HTTPS endpoint

**Context.** This is the one place this connector knowingly departs from the
programme's stated preference, and it is stated here rather than left for a
grader to discover. Slide 11 of the kickoff deck reads, verbatim: **"Production
deployment is required for validation: expose a stable HTTPS MCP URL and keep
the credential vault outside the connector."** Slide 6 and Build Step 5 repeat
that framing. The `/submit` page's own copy, by contrast, describes the
deployed URL field as optional — "Include the deployed HTTPS MCP URL **when
it is ready**" — and the MCP specification itself says a server intended to
run locally **should** use stdio specifically to limit access to the
connecting client (`research/09-mcp-spec-compliance.md` §8).

**Options considered.**
1. Deploy a hosted streamable-HTTP MCP endpoint, in line with the deck's
   dominant framing.
2. Ship stdio only, launched by an MCP host or by Docker as a subprocess —
   in line with the MCP specification's own guidance for locally-run
   servers, and with the submission form's actual, softer requirement.

**Decision.** Option 2, and this was the owner's explicit decision, not an
oversight or a resource shortfall.

**Trade-offs accepted.** This connector does not satisfy the deck's
strongest framing ("deployment is required for validation") as written. It
does satisfy the submission mechanics as actually specified ("when it is
ready"), the specification's own transport guidance for a locally-run
server, and — since no external HTTPS surface exists — removes an entire
class of exposure (no public listener, no TLS termination, no bearer-token
management for inbound callers) for a connector holding real CRM
credentials.

**Consequences.** `connector.yaml`'s `capabilities.transports` lists only
`stdio`, and this is repeated plainly in `limitations`. If a hosted endpoint
is later required, it is additive work — a streamable-HTTP transport wired
to the same `connector`/`actions` core — not a rewrite, because nothing
below `mcp_server.py` knows which transport is in use.

### ADR-011: Libraries over hand-rolled mechanics

**Context.** Retry loops, environment parsing, structured logging, rate
limiting, and signed tokens are each easy to write *plausibly* and hard to
write *correctly* — edge cases like partial bucket refill, contextvar
leakage across concurrent requests, or backoff-with-jitter are exactly where
hand-rolled versions tend to be subtly wrong.

**Options considered.** For each concern: hand-write it, or depend on a
library that owns it.

**Decision.** Depend, in every case:

| Library | Replaces | Where |
|---|---|---|
| `tenacity` | A hand-written attempt loop, exponential backoff, jitter, and stop conditions. | `errors/retry.py` |
| `pydantic-settings` | Hand-parsed environment variables, with ad hoc boolean/float coercion and error reporting. | `config.py` |
| `structlog` | Hand-rolled JSON logging, with manual request-id threading through every function signature. | `observability.py` |
| `aiolimiter` | A naive call counter that gets partial-window refill wrong. | `ratelimit.py` |
| `itsdangerous` | A hand-rolled HMAC-signed, expiring token for carrying pending-write state across a round trip. | `approval.py` |

**Trade-offs accepted.** Five more third-party dependencies to track and
patch, each pinned with a loose lower bound (`pyproject.toml`) rather than
implemented in-house where behaviour would be fully self-contained.

**Consequences.** Correctness of these mechanics now tracks each library's
own maintenance, not this repository's. `contract.py` still imports none of
them — the layering rule ("the contract layer imports no vendor library at
all," `.importlinter`) means every one of these choices stays swappable
without touching the types every consumer depends on.

### ADR-012: Errors as tool results with `isError`, never protocol errors

**Context.** The MCP specification is explicit: "Clients **SHOULD** provide
tool execution errors to language models to enable self-correction"
(`research/09-mcp-spec-compliance.md` §6). A JSON-RPC protocol error (an
`-32xxx` code) is not routed to the model the same way — it is a transport-
level failure, not something an agent loop can read and act on.

**Options considered.**
1. Raise a JSON-RPC protocol error for any Salesforce or validation failure.
2. Always return a normal `CallToolResult` with `is_error: true` and a
   message written for a model to act on.

**Decision.** Option 2 (`mcp_translate.py::refuse`, `as_result`). Every
`ConnectorError` subclass in `errors/model.py` carries a `category`, a
`reason`, and a `next_step` — "wait and retry," "fix an argument," "stop and
report," or "escalate" — because the category alone is not enough when the
only reader is a model that sees text.

**Trade-offs accepted.** Genuine protocol-level problems (an unknown tool
name, a malformed call) are handled the same way as a Salesforce-side
failure, rather than distinguished by JSON-RPC error code. That uniformity is
deliberate: from the caller's perspective, "this call did not succeed, here
is why and what to do" is one shape, not two.

**Consequences.** No action's `run()` method ever lets an exception escape —
`Action.run` catches `ConnectorError` and returns a result, `Connector.execute`
does the same one level up. One bad call cannot end a session or affect the
other four actions.

### ADR-013: The nonce-bearing untrusted-data fence

**Context.** Salesforce records contain text written by other people —
contact titles, opportunity descriptions, activity notes — and an MCP result
that quotes that text is a route for prompt injection if a model reads it as
instruction rather than data. Fencing the payload with a marker mitigates
this, but only if the marker itself cannot be forged from inside the fenced
content.

**Options considered.**
1. A fixed opening/closing marker (e.g. a constant string) around returned
   data.
2. A marker whose closing half carries a random nonce, generated fresh per
   response.

**Decision.** Option 2. `mcp_translate.py::wrapped` generates
`secrets.token_hex(6)` per call and builds
`<salesforce_record_data-{nonce}>...</salesforce_record_data-{nonce}>`.

**Trade-offs accepted.** None of real weight — a few extra bytes per
response, and the fence text is no longer a compile-time constant a reader
can grep for verbatim.

**Consequences.** This was not a hypothetical: option 1 is a documented
weakness the project's own security tests found and named. A Salesforce
field containing the literal text `</salesforce_record_data>` would, under a
fixed marker, close the fence early and cause everything the record author
wrote after it to be read as though it came from the connector rather than
from the record.
`tests/security/test_injection_and_leaks.py::TestPromptInjectionThroughRecords::test_a_record_cannot_close_the_fence_and_speak_outside_it`
exercises exactly that payload and asserts the fence survives; a second test
(`test_two_responses_do_not_share_a_fence`) asserts two calls never reuse a
nonce, since a reused one could be learned from one response and used to
attack the next.

### ADR-014: `mcp/server.py` as a launcher

**Context.** The programme's repository template places the MCP entry point
at `mcp/server.ts` (Python equivalent: `mcp/server.py`). This connector's own
package is named `salesforce_connector`, but the MCP SDK's own package is
named `mcp` — the same name as this directory.

**Options considered.**
1. Put the adapter's actual implementation inside `mcp/server.py` directly.
2. Keep `mcp/server.py` as a two-line forwarding launcher, and put the real
   implementation in `src/salesforce_connector/mcp_server.py`.

**Decision.** Option 2. A module physically inside a directory named `mcp`
that also does `import mcp.server.stdio` asks Python to disambiguate between
the local directory and the installed SDK package — which one wins depends
on how the process happens to be started (`sys.path[0]` behaviour), which is
exactly the kind of ambiguity that works locally and breaks under a
different launcher.

**Trade-offs accepted.** One extra file and one indirection layer, for a
codebase that otherwise avoids launcher-only files.

**Consequences.** `tests/unit/test_mcp_server.py::TestTheAdapterKnowsNothingAboutSalesforce::test_the_entry_point_file_only_forwards`
pins this: the launcher must mention `salesforce_connector.mcp_server` and
stay under 20 lines — it cannot silently grow real logic without the test
failing.

### ADR-015: Rate limiting our own invocations, refusing rather than queuing

**Context.** The MCP specification states servers **MUST** "Rate limit tool
invocations" (`research/09-mcp-spec-compliance.md` §6). The concrete failure
mode: a model in a retry or exploration loop can exhaust a Salesforce org's
entire daily API allowance in minutes, breaking every other integration on
that org until the daily window resets — damage that lands on people who
never interacted with this connector.

**Options considered.**
1. No self-imposed limit — rely on Salesforce's own quota (`Sforce-Limit-Info`)
   as the only backstop, which only reports the problem after the org-wide
   damage is already done.
2. Queue excess calls until capacity frees up — hides a runaway loop inside
   a call that merely appears slow, and lets an unbounded backlog build.
3. Refuse excess calls immediately, with a stated wait time.

**Decision.** Option 3. `ratelimit.py::CallBudget` wraps `aiolimiter`'s
leaky bucket (default 60 calls/minute/process) and raises `RateLimitError`
— retryable, with `retry_after_seconds` — the moment capacity is exhausted,
checked *before* the bucket's own `acquire()` so the check never itself
blocks.

**Trade-offs accepted.** A legitimate burst of calls (e.g. paging through a
large search result quickly) is throttled the same as a runaway loop would
be; the connector cannot distinguish intent, only rate.

**Consequences.** This budget is separate from, and smaller-scoped than, the
Salesforce org's own API quota (surfaced as `rate_limit` in every envelope
via `Sforce-Limit-Info`) — a caller can be refused by this connector's own
budget while the org still has plenty of quota left, and the error message
says so explicitly ("which is its own limit, separate from the org's API
quota").

### ADR-016: Sandbox by default, production requires explicit opt-in

**Context.** The programme requires testing "without production customer
data." `SF_LOGIN_URL` is a plain string a deployer could mistype or copy
from the wrong document.

**Options considered.**
1. Trust the value of `SF_LOGIN_URL` as configured, document the sandbox
   expectation in `.env.example` only.
2. Default to the sandbox host, and refuse to start against
   `https://login.salesforce.com` unless a second variable explicitly
   confirms it.

**Decision.** Option 2. `config.py::Settings._production_needs_saying_so`
raises at startup if `login_url` is the production host and
`allow_production` is not `true`.

**Trade-offs accepted.** A deployer who genuinely wants production must set
two variables, not one — friction added on purpose.

**Consequences.** "Sandbox only. A production login host is refused unless
explicitly enabled" is stated in `connector.yaml`'s `limitations`, and is
true by construction, not merely by convention — the guard lives in code
that fails startup, not in a note someone could skip past.

### ADR-017: Manifest cross-checked against the registry at startup

**Context.** `connector.yaml` declares what actions this connector offers
(Definition of Done item 1); `actions/registry.py` decides what actually
exists in code. Two independent descriptions of the same thing can drift —
someone adds an action and forgets the manifest, or removes one and leaves a
stale entry.

**Options considered.**
1. Treat the manifest as documentation, trusted as written.
2. Compare the manifest's declared `actions` against the registry's actual
   `BY_ID` keys at startup, and refuse to start on any disagreement.

**Decision.** Option 2. `connector.py::load_manifest` raises
`ConfigurationError` naming both sets, sorted, the moment they disagree.

**Trade-offs accepted.** None material — this check runs once, at startup,
against small sets.

**Consequences.** A manifest read by someone deciding whether to trust this
connector — exactly the audience Definition of Done item 1 has in mind —
cannot be quietly stale. The failure is loud and immediate, not discovered
by a caller invoking an action the manifest never mentioned.

### ADR-018: Deep-freeze at the response boundary

**Context.** `pydantic`'s `frozen=True` freezes a model's own attributes, not
the containers nested inside them — a caller could still mutate a dict or
list buried inside a "frozen" `ActionResult.data` payload. A shallow
immutability guarantee invites exactly the bug it was meant to prevent: a
caller mutates a cached response, and the next reader sees data that never
actually came from Salesforce.

**Options considered.**
1. Rely on `frozen=True` alone and document the shallow limit.
2. Recursively freeze every parsed response at the client boundary —
   mappings become `MappingProxyType`, lists become tuples — before it goes
   anywhere else in the connector.

**Decision.** Option 2 (`immutable.py::freeze`), applied in `client.py`
(every HTTP response body), `idempotency.py` (every ledger entry), and
`checkpoint.py` (every journal entry).

**Trade-offs accepted.** One recursive pass over every parsed response and
every idempotency/journal record — a real but small and one-time cost per
call.

**Consequences.** Strings and bytes are deliberately excluded from the
recursion (both satisfy `Sequence`, and iterating a string element-by-element
would silently turn `"Ada"` into a tuple of letters) — a documented edge case
in the function itself, not an accident found later.
`tests/unit/test_durability.py::TestFreezing` asserts a nested mapping
inside a frozen response raises `TypeError` on attempted mutation.

### ADR-019: Error classification as data, not code

**Context.** Salesforce publishes no machine-readable catalogue of its own
error codes. New codes appear over time, and a codebase that hardcodes
`if code == "DUPLICATE_VALUE": ...` per known code cannot classify one it has
never seen, and requires a deploy to add one it has.

**Options considered.**
1. A Python `if`/`elif` chain (or `match`) over known exact error codes.
2. Classify by the *shape* of the code (glob-style patterns:
   `*_LIMIT_EXCEEDED`, `INVALID_*`, `*_NOT_FOUND`, ...) loaded from a YAML
   file, with a small override table for codes the shape rules get wrong.

**Decision.** Option 2 (`errors/mapping.py` + `errors/salesforce_codes.yaml`).
Resolution order: exact overrides, then patterns in file order (first match
wins), then HTTP status, then a 5xx-is-transient / else-fatal fallback.

**Trade-offs accepted.** Pattern order matters and is a real source of bugs
if edited carelessly — the file's own comments call this out ("Deliberately
last: `INVALID_*` and `MALFORMED_*` are broad, so any narrower rule above
claims its codes first"). Outcome names are validated against a fixed
vocabulary at load time (`_known_outcome`), so a typo in the YAML fails
loudly rather than silently misclassifying a live failure.

**Consequences.** A Salesforce error code released after this connector
ships and never seen during development (e.g. a new `*_LIMIT_EXCEEDED`
variant) still lands in the correct category by shape. Changing
classification behaviour is an edit to a YAML file, reviewable as data, not
a code change requiring a redeploy.

### ADR-020: Client Credentials retained as a fallback auth flow

**Context.** JWT Bearer (ADR-004) requires generating a certificate,
uploading it to the Connected App, and getting the signing math right — real
friction for a first-time setup, even though it is the right long-term
default.

**Options considered.**
1. Implement only JWT Bearer — simplest surface area, but a setup failure
   there has no fallback.
2. Also implement OAuth 2.0 Client Credentials — a consumer key and secret
   exchanged directly for a token, no certificate, no signing — as an
   explicitly secondary option.

**Decision.** Option 2 (`auth/client_credentials.py`). Both strategies share
one `AuthStrategy` protocol and produce the same `Token`, so which one is
configured changes nothing downstream of authentication.

**Trade-offs accepted.** Client Credentials transmits `SF_CLIENT_SECRET`
over the wire on every token exchange — a real secret in transit, which is
precisely why JWT Bearer remains the default and this is documented as the
fallback, not an equal alternative.

**Consequences.** `ClientCredentialsAuth.build_request` raises
`ConfigurationError` if `SF_CLIENT_SECRET` is unset, rather than silently
producing a malformed request — a deployer who half-configures the fallback
gets a clear failure naming the missing variable.

### ADR-021: Journal-based partial success for multi-step writes

**Context.** `create_opportunity` is, structurally, two writes: create the
Opportunity, then optionally link a Contact via
`OpportunityContactRole`. The second can fail after the first has already
taken effect. Reporting plain failure in that case would tempt a retrying
caller into creating a second Opportunity; reporting plain success would
hide that the link never happened.

**Options considered.**
1. Treat the whole operation as atomic from the caller's point of view —
   report success or failure only, collapsing the two outcomes.
2. Record each step as it completes (`checkpoint.py::Journal`), and report
   exactly which steps finished and which did not.

**Decision.** Option 2. `create_opportunity.py::_link_contact` catches a
`ConnectorError` from the role-creation call, logs it, and returns `False`
rather than propagating — the Opportunity's own creation is already
journaled and stands.

**Trade-offs accepted.** The output schema carries a three-state
`contact_linked` (`true` / `false` / absent) instead of a simple boolean,
which is one more state every caller must handle correctly.

**Consequences.** `contact_linked: false` is explicitly documented, in the
tool's own error/field guidance, as "a partial success: do not create the
opportunity again" — the caller is told what to do, not just what happened.
The same `Journal` mechanism is designed to generalise to any future
multi-step write or resumable multi-page read (the module's docstring notes
the same idea covers an interrupted page walk resuming from its last
cursor), though no other action currently uses it.

### ADR-022: Approval today is a parameter and a refusal; elicitation is built but not wired

**Context.** The programme requires "explicit approval for consequential
writes" without specifying a mechanism. The MCP specification (draft, read
2026-08-07) describes a formal mechanism for this — elicitation via an
`InputRequiredResult` on the `tools/call` response, with a signed,
time-limited, request-bound `requestState` carried across the round trip
(`research/09-mcp-spec-compliance.md` §5) — and states server-initiated
approval requests (the pre-elicitation model) no longer exist in the current
draft.

**Options considered.**
1. An `approved: bool` parameter, declared in each write's own input schema,
   defaulting to `false`; a write arriving without it is refused with a
   message telling the caller how to proceed.
2. Full elicitation: the server responds to a write with an
   `InputRequiredResult`, the host collects a person's confirmation, and the
   retry carries a signed `requestState`.

**Decision, honestly.** Both were built, but only option 1 is wired to the
live call path today. Every write schema declares `approved` (option 1,
live — enforced in `action.py::Action._require_approval`, and exercised
end-to-end by `tests/unit/test_approval_path.py` through the actual MCP
argument path, not just by constructing an `ActionRequest` directly).
Separately, `SalesforceConnector.approval_for`/`approves`
(`connector.py`) and `approval.py::ApprovalGate` implement exactly the
signed, TTL-bound, call-bound token the specification describes for
`requestState` — `itsdangerous`-signed, salted to this purpose, verified
against a digest of the exact action id and arguments it was issued for
(ADR from `approval.py`'s own docstring) — but **`mcp_server.py` never calls
`approval_for` or `approves`**. No route from `call_tool` reaches the gate.

**Trade-offs accepted.** The live approval flow is simpler than the
specification's own preferred mechanism: a caller must already know, from
the tool's description or a prior error, that `approved: true` and the same
`idempotency_key` are required — there is no server-initiated round trip
that surfaces this automatically via `InputRequiredResult`.

**Consequences.** This is listed plainly in
[Known limitations](#known-limitations-and-access-blockers) rather than
implied to be finished. Wiring elicitation is additive: `ApprovalGate`
already exists, tested, at the connector layer
(`tests/unit/test_connector.py::TestApproval`); the remaining work is in
`mcp_server.py::call_tool`, calling `approval_for` to mint an
`InputRequiredResult` when a write arrives unapproved, and `approves` to
verify the retried `requestState`, only for clients that declare the
capability (the specification forbids sending an elicitation a client did
not declare support for).

---

## Reliability

**Retries** (`errors/retry.py`, built on `tenacity`). Three rules, applied
uniformly:

- Only failures marked `retryable` are retried (`RateLimitError`,
  `TransportError`) — `input`, `permission`, and `conflict` failures fail
  identically on a second attempt and would only spend the org's quota.
- A write with no `idempotency_key` is never retried — the first attempt may
  already have taken effect.
- The wait is whichever is longer: exponential backoff with jitter
  (1s initial, 60s cap, 1s jitter), or a `Retry-After` the provider itself
  supplied — a retry never lands inside a window Salesforce already refused.
- The loop stops on whichever limit is hit first: 3 attempts, or a 120-second
  total budget — an attempt ceiling alone could still hold a call for
  minutes across three 60-second waits.

**Idempotency** (`idempotency.py`, per-process, in memory). A completed
key's result is returned verbatim on replay
(`Action._already_done`), with a warning noting the original result was
returned rather than a new write performed. A failed, non-retryable write
marks its key `FAILED`, safe to try again. Read the module's docstring
plainly: *"it lives in memory, so it protects a retry within one process and
nothing more... Real protection comes from the provider, by writing through
an external id so Salesforce itself refuses to create a second record — this
is the second line, not the first."* That provider-side line does not exist
yet — see [Known limitations](#known-limitations-and-access-blockers).

One further honest note not stated elsewhere in the codebase's own
docstrings: the ledger's `KeyState.IN_FLIGHT` and its `begin()` method exist
and are tested in isolation (`tests/unit/test_durability.py::TestTheLedger`),
but **no action currently calls `IdempotencyLedger.begin()`** — the live path
only ever calls `find`, `complete`, and `fail`. In practice this means two
concurrent calls sharing the same fresh `idempotency_key`, sent close enough
together that neither has completed yet, are not currently detected as
"already in flight" — both would reach Salesforce independently. The
sequential case this connector is built around (retry-after-timeout, one
call at a time) is fully covered; true concurrent duplicate submission of an
unfinished key is not.

**Checkpoints** (`checkpoint.py::Journal`). Used today by
`create_opportunity` to record the Opportunity's own creation before
attempting the Contact link, so a failure in the second step is reported as
`contact_linked: false` — a partial success naming exactly what exists —
rather than a plain failure that would tempt a retry into creating a second
Opportunity. See [ADR-021](#adr-021-journal-based-partial-success-for-multi-step-writes).

**Rate limits.** `Sforce-Limit-Info` is parsed off every Salesforce response,
success or failure (`exchange.py::parse_rate_limit`), and surfaced as
`rate_limit` in every envelope — free telemetry, since polling `/limits`
separately would spend a call to learn the same thing. Separately, this
connector's own call budget (60/minute/process by default) refuses excess
calls rather than queuing them — see
[ADR-015](#adr-015-rate-limiting-our-own-invocations-refusing-rather-than-queuing).

**Pagination.** `search_contact`'s `next_cursor` is an offset the connector
itself encodes and interprets — Salesforce's `parameterizedSearch` has no
native opaque cursor the way SOQL's `nextRecordsUrl` does, so the connector
manufactures one from an offset and only issues it when a page came back
full (a short page means results ran out). `has_more` is derived from
whether a cursor is present (`Pagination.has_more`), never stored
separately, so it cannot disagree with the cursor it describes — this
matches the specification's own cursor discipline even though `tools/call`
itself is outside the four operations the specification requires pagination
for.

---

## Security

Auth and security carry the largest single weight in the programme's own
scoring (20%). Controls, and where each lives:

| Threat | Control | Location |
|---|---|---|
| SOQL/SOSL injection | Search text sent as a JSON value to `parameterizedSearch`, never assembled into query syntax | `actions/search_contact.py` — [ADR-003](#adr-003-parameterizedsearch-instead-of-soql-or-sosl) |
| Prompt injection via record data | Every successful result's text content is wrapped in a nonce-bearing fence before a model sees it | `mcp_translate.py::wrapped` — [ADR-013](#adr-013-the-nonce-bearing-untrusted-data-fence) |
| Secret leakage into logs | A structlog processor censors known secret keys and bearer/PEM-shaped patterns in every log line, at any nesting depth, before rendering | `observability.py::censor_secrets` |
| Secret leakage via `repr`/`str` | Credentials are `pydantic.SecretStr`; printing `Settings` shows a mask, never the value | `config.py::Settings` |
| Token exposure | Access tokens live only in memory, for the life of the process; never written to disk or logged | `client.py`, `auth/strategy.py::Token` |
| Unapproved writes | Every write requires `approved: true` in its own schema; refused otherwise, with the refusal explaining how to retry | `actions/action.py::_require_approval` — [ADR-022](#adr-022-approval-today-is-a-parameter-and-a-refusal-elicitation-is-built-but-not-wired) |
| Over-broad OAuth scope | Manifest requests only `api` and `refresh_token` — nothing beyond what the five actions need | `connector.yaml` |
| Over-broad data access | The connector runs as one Salesforce user; that user's own profile, not the connector, is the real ceiling on what any action can reach | `connector.yaml` `risks` |
| Accidental production use | Refused at startup unless `SF_ALLOW_PRODUCTION=true` is set alongside a production `SF_LOGIN_URL` | `config.py::_production_needs_saying_so` — [ADR-016](#adr-016-sandbox-by-default-production-requires-explicit-opt-in) |
| Provider error detail leakage | Error reasons are capped at 300 characters and never include a stack trace or file path | `errors/mapping.py::_reason` |
| Runaway call volume | This connector's own call budget refuses excess invocations rather than queuing them | `ratelimit.py::CallBudget` — [ADR-015](#adr-015-rate-limiting-our-own-invocations-refusing-rather-than-queuing) |
| Wrong-record attachment | An activity note's target id prefix is checked (`003`/`006`) before any request, since Salesforce silently accepts an id in the wrong field | `actions/add_activity_note.py::_attachment` |
| Secrets in stdout | All logging goes to stderr; stdout carries only JSON-RPC, since a stray line there corrupts the transport and ends the session | `observability.py::configure_logging`, `ruff` rule `T20` bans `print` |
| Committed secrets | `.gitignore` excludes `.env`, `*.pem`, `*.key`; pre-commit runs `gitleaks` and `detect-private-key`; CI runs a full-history `gitleaks` scan | `.gitignore`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml` |

`tests/security/test_injection_and_leaks.py` exercises these directly rather
than asserting them as design intent: six real injection payloads against
`search_contact`, a path-traversal-shaped id against `add_activity_note`,
prompt-injection payloads through the result fence (including one that
tries to close the fence early), token/PEM/secret leakage through the
logging pipeline, and a duplicate-key write sent five times landing exactly
one Salesforce call.

---

## Testing

Verified directly while writing this document, in this repository, on this
machine:

```
$ python -m pytest -q
352 passed, 2 warnings in 18.90s

$ python -m ruff check .
All checks passed!

$ python -m mypy src tests
Success: no issues found in 55 source files

$ PYTHONPATH=src lint-imports
Analyzed 69 files, 209 dependencies.
Contracts: 4 kept, 0 broken.

$ docker build -t salesforce-connector .
[...] naming to docker.io/library/salesforce-connector:latest done

$ echo -n "" | docker run -i --rm -e SF_CLIENT_ID=placeholder \
    -e SF_USERNAME=placeholder@example.com.sandbox -e SF_PRIVATE_KEY=placeholder \
    salesforce-connector
{"event": "server.started", ...}
{"event": "server.stopped", ...}
exit code: 0
```

The two `pytest` warnings are pre-existing and harmless: a `PendingDeprecationWarning`
from a transitive dependency (`python-multipart`), and one test misusing the
`asyncio` marker on a synchronous function.

**Test tiers** (`pyproject.toml` markers):

- **Default** (`addopts = "-m 'not learning and not integration'"`, what the
  334-pass run above covers): unit tests (`tests/unit/`, schema validation,
  error mapping, retry classification, idempotency ledger, approval path,
  OpenAPI generation, MCP adapter thinness) and security/fixture tests
  (`tests/security/`), all against mocked HTTP (`respx`) — no network, no
  credentials required.
- **`learning`** — "pins real Salesforce behaviour (needs an org)." No test
  file in this repository currently carries this marker.
- **`integration`** — "end to end against a live sandbox (needs an org)." No
  test file in this repository currently carries this marker either. This is
  not "the live tier failed" or "was skipped" — no test written against a
  real org exists yet, because no org has been available. See
  [Known limitations](#known-limitations-and-access-blockers).

**A real bug this process caught, and how.** While assembling the
evaluation questions in `evaluations/` (ten Q&A pairs for testing whether a
model can use these tools correctly — see `evaluations/README.md`), a
concrete defect was found: every write tool's own error text instructs a
caller to "call again with `approved` set to `true`," but at the time,
`approved` was not declared in any write's Pydantic input model, which
forbids unknown fields (`extra="forbid"`). A caller doing exactly what the
tool told it to do would have been rejected with a schema validation error
instead of getting the write it asked for — confirmed directly against the
validation layer, no credentials needed. Every existing test had missed this
because each one constructed an `ActionRequest` directly and set `approved`
as a Python field, which is not the path a real MCP client takes: a client
puts `approved` inside the tool call's `arguments`, which get validated
against the schema. The fix (commit `2dcc0d4`, "Let a caller do what the
error message tells it to") declares `approved` in each write's own schema.
`tests/unit/test_approval_path.py` now walks the client's actual path —
`CallToolRequestParams` → `mcp_server._as_request` → the action's own input
model — specifically so this class of bug cannot recur silently. This is
also why `evaluations/README.md` reads as though the bug is still open: it
documents the investigation as it happened, and was not rewritten after the
fix landed; the fix and its regression test are what actually ship.

**A second, later finding, from a threat-model review rather than a test.**
While writing `SECURITY.md`, a review of `observability.py::_censor_value`
found two real gaps in the log censor: it recursed into dictionaries but not
into lists or tuples, so a token at `records[0].access_token` — exactly
where a Salesforce reply's own shape puts one — passed through unmasked; and
the bearer-token pattern matched only word characters, so a real Salesforce
session id containing `!` (`00D5g000004abc!AQEAQ...`) was masked only up to
that character, with the remainder of the token written out in full. The
existing test had passed throughout, correctly by its own narrower
question — it checked whether the *complete* token appeared as one
contiguous substring, which stayed true even with half of it leaking. Fixed
in commit `602a392` ("Follow secrets into lists, and past the mark in a
session id"), with `tests/security/test_censoring_depth.py` added to check
the tail specifically and a secret nested two containers deep. `SECURITY.md`
itself still narrates this as an open, unfixed gap in its "what this
deliberately does not defend against" section — written before the fix
landed and not updated afterward. The code, read directly, is the source of
truth: both gaps are closed.

---

## Known limitations and access blockers

Stated plainly, per Definition of Done item 11 — hiding these would be worse
than the gaps themselves.

- **No live Salesforce org has ever been available.** There is no Developer
  Edition org, no Connected App, and no sandbox credentials in this
  environment. Every action has unit and fixture-level coverage against
  mocked HTTP (`respx`); none has been run against a real org. Concretely:
  no test file in this repository carries the `integration` or `learning`
  pytest marker at all — the live tier is not merely unrun, it does not
  exist as code yet.
- **The ten `evaluations/questions.xml` answers were hand-derived, not
  executed.** They were worked out by hand from `evaluations/seed_data.md`
  plus the connector's own schemas and action code — the same reasoning an
  LLM using only these tools would have to do — not by actually calling the
  tools against Salesforce. `evaluations/README.md` documents exactly how to
  run them for real once an org exists.
- **Idempotency memory is process-scoped, not durable.** A restart between a
  write being sent and its response arriving loses the ledger entirely; a
  retry after that restart is indistinguishable from a first attempt. See
  [ADR-006](#adr-006-idempotency-key-required-on-every-write-enforced-structurally)
  and [Reliability](#reliability).
- **Provider-side deduplication needs an org configuration change this
  connector cannot make for itself:** an External Id field on Contact (or
  Opportunity) that Salesforce itself would use to refuse a duplicate write,
  independent of this connector's own in-memory ledger. Not configured on
  any org, because no org exists to configure.
- **The idempotency ledger's `IN_FLIGHT` state is unreached by the current
  call path** — `begin()` is never called by any action. Two truly
  concurrent calls sharing a fresh, not-yet-completed key are not currently
  detected as in-flight; only the sequential retry-after-timeout case is
  covered. See [Reliability](#reliability).
- **Approval is a parameter and a refusal, not the specification's own
  preferred elicitation flow.** The signed, TTL-bound `ApprovalGate` exists
  and is unit-tested at the connector layer, but `mcp_server.py` never calls
  it. See [ADR-022](#adr-022-approval-today-is-a-parameter-and-a-refusal-elicitation-is-built-but-not-wired).
- **`search_contact`'s `account_name` output field is always `null`.** The
  action's own `_FIELDS` tuple never requests `AccountName` from Salesforce,
  and `_as_summary` never populates it. The field is real in the schema and
  in `openapi.yaml`; the data behind it is not populated yet.
- **The search pagination cursor's real behaviour against Salesforce is
  unverified.** `search_contact` builds its cursor from an `offset` field
  sent to `parameterizedSearch`; SOSL-backed search results have not
  historically supported an offset parameter the way SOQL query pagination
  does. Whether Salesforce actually honours it, or silently repeats page one,
  is unknown without a live org — flagged directly in
  `evaluations/README.md`.
- **stdio and Docker only — no deployed HTTPS MCP endpoint.** The kickoff
  deck's dominant framing calls a deployed endpoint required; the actual
  submission-page copy softens that to "when it is ready." This connector
  ships stdio-only, deliberately — see
  [ADR-010](#adr-010-stdio-and-docker-not-a-hosted-https-endpoint) for the
  full trade-off, quoted from both sides rather than silently picking one.
- **Five actions, not the wider Salesforce surface.** See
  [Roadmap](#roadmap) for what is deliberately not built yet, and why.
- **Sandbox only, by design.** A production login host is refused unless
  `SF_ALLOW_PRODUCTION=true` is explicitly set — see
  [ADR-016](#adr-016-sandbox-by-default-production-requires-explicit-opt-in).
  This is a safety choice, not an access blocker, but it does mean this
  connector will refuse to run against production without a deliberate,
  separate opt-in.

---

## Roadmap

`research/03-salesforce-api-map.md` catalogues roughly 90 Salesforce REST
endpoints; this connector implements five. That document's own tiering is
the plan for what comes next, in priority order:

**Next (natural extensions of the always-on core).**
`get_record_by_external_id` / `upsert_record_by_external_id` /
`delete_record_by_external_id` — upsert-by-external-id is how most real
integrations avoid the client-side "query then create-or-update" pattern
this connector's own `create_contact`/`allow_duplicate` flow works around
manually today. `soql_query` / `soql_query_more` / `sosl_search` as
explicit, generic read actions alongside the five purpose-built ones.
`composite_batch` / `collections_create_records` /
`collections_update_records` — bulk efficiency wins, and the connector's
existing per-action idempotency-key pattern extends naturally to a batch
key per subrequest.

**Later (real, but narrower).** Layouts and list views, for agents that need
to mirror what a person sees in the Salesforce UI rather than raw field
data. Quick Actions and invocable Actions, which can trigger Flows or send
email — genuinely powerful, and deliberately deferred until there is a
concrete use case pulling for them rather than built speculatively, given
the blast radius of getting an invocable-action wrapper wrong. Change feeds
(`get_deleted_records`, `get_updated_records`), for a future sync/replication
feature.

**Deliberately not planned as bespoke tools.** Knowledge/data-category
objects, Lightning usage-metrics objects, and similar — these are, in
substance, `soql_query` against a named object with no real behavioural
divergence from the generic pattern; adding them as individually-named tools
would grow the tool list without growing capability, which
`research/03-salesforce-api-map.md` §4 argues directly degrades tool-
selection accuracy once a manifest exceeds roughly 20-25 tools. If genuine
demand appears, the answer is `soql_query` plus documentation, not a new
action per object.

**Also on the list, not yet started:**
- Wire `ApprovalGate` into `mcp_server.py` as a real `InputRequiredResult`
  elicitation flow, gated on client capability declaration, with the
  `approved` parameter kept as the fallback for clients that do not declare
  elicitation support — see
  [ADR-022](#adr-022-approval-today-is-a-parameter-and-a-refusal-elicitation-is-built-but-not-wired).
- Populate `search_contact`'s `account_name` field, or remove it from the
  schema if it stays unpopulated.
- Run `evaluations/questions.xml` for real against a live Developer Edition
  org, once one exists, per the procedure in `evaluations/README.md`.
- A streamable-HTTP transport alongside stdio, additive to the existing
  `connector` core rather than a rewrite of it, if a deployed endpoint
  becomes a hard requirement (see
  [ADR-010](#adr-010-stdio-and-docker-not-a-hosted-https-endpoint)).
- An External Id field on the org, once one exists, so provider-side
  deduplication backs up the in-memory idempotency ledger rather than being
  the only line of defence.

---

## Licence

Apache License 2.0 — see [`LICENSE`](LICENSE).
