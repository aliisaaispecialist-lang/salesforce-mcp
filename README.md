# Salesforce Connector

Five Salesforce actions any AI assistant can use: search for a contact, create
one, update one, open an opportunity, log a note.

It is an MCP server, so it works with Claude, Cursor, VS Code, Gemini CLI, and
anything else that speaks the protocol. One command registers it:

```bash
python scripts/install_client.py claude-desktop
```

Built for the Builders League Connector Test Suite (Cohort 01, MK Lab x DOO).

## What it does

| Tool | Does | Asks first |
|---|---|---|
| `salesforce_search_contact` | Finds people by name, email, phone, or account | no |
| `salesforce_create_contact` | Adds a person | yes |
| `salesforce_update_contact` | Changes fields on an existing person | yes |
| `salesforce_create_opportunity` | Opens a deal, optionally linked to a contact | yes |
| `salesforce_add_activity_note` | Logs a call, email, meeting, or note | yes |

Three things it does that most connectors do not:

**Every write asks a person first.** Not a flag the model sets for itself. If
your client supports it, you get a confirmation dialog before anything changes.

**Retries never duplicate.** Every write carries a key. Retry after a timeout
with the same key and you get the original record back, not a second one.

**Record text is fenced as data.** Notes and descriptions were written by other
people. They arrive marked as data, never as instructions.

## Getting started

New here? [**QUICKSTART.md**](QUICKSTART.md) goes from empty folder to working
assistant, including the Salesforce side, which is the slow part.

Two things worth knowing before you start:

There is no single "API key". You collect three values, and only one is secret:
a Consumer Key and a username, neither secret, plus a private key you generate
yourself that never leaves your machine.

You need none of them to review this. `pytest` runs 443 tests with no
credentials, no org, and no network.

## Status

Provider: Salesforce REST API `v67.0`. Auth: OAuth 2.0 JWT Bearer.
Python 3.12.

Verified against a real Salesforce Developer Edition org: 30 live tests, plus a
full round trip where a client listed the five tools, searched, and had an
unapproved write refused. All twelve Definition of Done items met.

## Where things are

| | |
|---|---|
| [QUICKSTART.md](QUICKSTART.md) | Set it up, step by step |
| [docs/DECISIONS.md](docs/DECISIONS.md) | 27 design decisions and what each cost |
| [SECURITY.md](SECURITY.md) | 19 threats, the control for each, whether it is tested |
| [CHANGELOG.md](CHANGELOG.md) | Release history |
| [docs/GO-LIVE.md](docs/GO-LIVE.md) | Running against a real org |
| [openapi.yaml](openapi.yaml) | The same five actions as HTTP operations |

Below: configuration, the actions in detail, architecture, reliability,
security, testing, and what is not built.

---

## Quick start

### → Setting this up for the first time? Read [**QUICKSTART.md**](QUICKSTART.md), not this section.

It walks the whole path from an empty folder to a working assistant, and opens
with a one-page map of the seven steps: what you do, what you end up holding,
and how long each takes. The Salesforce side: an External Client App and a
certificate, is the only slow part, and it is the part no README section can
skip over honestly.

Two things worth knowing before you start:

- **There is no single "API key".** You collect three values, and only one of
  them is secret: a Consumer Key and a username (neither secret) and a private
  key you generate yourself, which never leaves your machine. Salesforce holds
  only its public half.
- **You need none of them to review this.** `pytest` runs 443 tests with no
  credentials, no org, and no network. Credentials matter only when you want
  to touch a real org.

What follows here assumes you already have all three.

Both paths below were run against this repository: `docker build`, a container
start/stop on closed stdin, `pytest -q`, `ruff check .`, `mypy src tests`, and
`lint-imports` all pass. The Python path has also been run **against a real
Salesforce Developer Edition org**, 30 live tests, and a full stdio round trip
in which a client listed the five tools, searched, and had an unapproved write
refused. See [Testing](#testing).

### Docker

```bash
docker build -t salesforce-connector .
docker run -i --rm --env-file .env salesforce-connector
```

The `-i` is not optional. This image speaks stdio and exposes no port; without
`-i` the container's stdin is closed immediately and the server never sees a
request. Closing stdin is also the correct way to stop it: the process exits
0 on EOF, which is what the `image` job in `.github/workflows/ci.yml` asserts
on every push, and what running `docker run -i --rm ... salesforce-connector
< /dev/null` here confirmed directly.

### Python

```bash
pip install -e ".[dev]"
cp .env.example .env   # fill in SF_CLIENT_ID, SF_USERNAME, SF_PRIVATE_KEY
make check              # format, lint, layering, types, tests, what CI runs
PYTHONPATH=src python mcp/server.py
```

`make check` runs `ruff format .`, `ruff check .`, `lint-imports`, `mypy src
tests`, and `pytest`, in that order: the same sequence and the same tools CI
runs on every push. See [Testing](#testing) for the numbers this produced.

### Point an MCP host at it

`examples/mcp_client_config.json` has two ready-to-paste entries for an MCP
host's `mcpServers` object (for example `claude_desktop_config.json`): one
that runs the Docker image, one that runs `mcp/server.py` directly with
`env` values filled in from `.env.example`. Replace the placeholder absolute
path with the real one on your machine.

---

## Configuration

Every variable the connector reads, and nothing it doesn't, `.env.example`
and `Settings` (`src/salesforce_connector/config.py`) are tested against each
other (`tests/unit/test_env_example.py`) so this table cannot drift from the
code.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SF_CLIENT_ID` | yes |, | Consumer Key of the External Client App. Connected apps can no longer be created in new orgs, see [ADR-025](docs/DECISIONS.md#adr-025-external-client-apps-because-salesforce-closed-connected-apps). |
| `SF_USERNAME` | yes |, | The user the connector acts as. Must be pre-authorised for the app; that user's profile is the real ceiling on what any action can do. |
| `SF_PRIVATE_KEY` | yes |, | PEM private key matching the certificate uploaded to the app. `\n` between lines is accepted and restored, since most container runtimes and CI secret stores cannot hold a literal multi-line value. |
| `SF_CLIENT_SECRET` | no | none | Only used by the Client Credentials fallback flow (ADR-020). Leave blank when using JWT Bearer, which transmits no secret at all. |
| `SF_LOGIN_URL` | no | `https://test.salesforce.com` | Login host. Sandbox by default and deliberately so (ADR-016). |
| `SF_ALLOW_PRODUCTION` | no | `false` | Must be explicitly `true` before `SF_LOGIN_URL` is allowed to point at `https://login.salesforce.com`. A typo cannot silently point this connector at production. |
| `SF_API_VERSION` | no | `v67.0` | Salesforce REST API version, pinned so a platform release cannot change behaviour underneath the connector. |
| `SF_READ_TIMEOUT_SECONDS` | no | `5.0` | Timeout for read calls. |
| `SF_WRITE_TIMEOUT_SECONDS` | no | `15.0` | Timeout for write calls, longer than reads, because a write that times out may already have been applied. |

Two things worth being precise about:

- **`connector.yaml`'s `required_env` list also names `SF_LOGIN_URL`.** The
  code is the source of truth: `Settings.login_url` has a default, so it is
  not actually required to start the server. Treat the manifest's
  `required_env` as "what a deployer should look at," not a strict
  startup-blocking list, only `SF_CLIENT_ID`, `SF_USERNAME`, and
  `SF_PRIVATE_KEY` are enforced by `pydantic-settings` at import time.
- **Two different "versions" appear in this repository.** The Python package
  version (`salesforce_connector.__version__`, `0.1.0` → `1.0.0` at handoff)
  is the connector's own release number. `manifest.version` and the
  `openapi.yaml` `info.version` field are the *Salesforce API version*
  (`v67.0`, from `SF_API_VERSION`): a different axis entirely. Neither one
  is a typo for the other.

A missing or malformed required variable stops the server before any tool is
published, with every fault named at once (`config.py::_explain`), a
connector that starts and then fails every call is harder to diagnose than
one that refuses to start.

---

## The five actions

All five share one envelope (`ActionResult`): `ok`, `request_id`, `data`,
`error`, `pagination`, `rate_limit`, `warnings`. Every write additionally
requires `idempotency_key` (min 8 characters) and `approved` (boolean,
default `false`) in its own input schema, see
[ADR-006](docs/DECISIONS.md#adr-006-idempotency-key-required-on-every-write-enforced-structurally)
and [ADR-022](docs/DECISIONS.md#adr-022-the-server-asks-the-client-to-ask-a-person-and-falls-back-to-a-parameter).

| Action | Kind | Risk | Naturally idempotent | Needs approval |
|---|---|---|---|---|
| `salesforce.search_contact` | read | low | yes | no |
| `salesforce.create_contact` | write | medium | no | yes |
| `salesforce.update_contact` | write | medium | yes | yes |
| `salesforce.create_opportunity` | write | medium | no | yes |
| `salesforce.add_activity_note` | write | low | no | yes |

### `salesforce.search_contact`

Finds contacts by name, email, phone, or account name via `POST
.../parameterizedSearch` (never SOQL/SOSL, see
[ADR-003](docs/DECISIONS.md#adr-003-parameterizedsearch-instead-of-soql-or-sosl)).

- **Required:** `query` (2 to 200 characters).
- **Optional:** `limit` (1 to 200, default 20), `cursor` (opaque, from a previous
  page's `next_cursor`).
- **Returns:** `contacts[]` (`id`, `name`, `email`, `phone`, `account_id`,
  `title`), `returned`, `next_cursor`. Every one of those is requested in
  `_FIELDS` and populated in `_as_summary`, so the schema promises nothing the
  action does not deliver. The account is returned as an id rather than a name
  deliberately, see [ADR-023](docs/DECISIONS.md#adr-023-the-account-comes-back-as-an-id-not-a-name).

### `salesforce.create_contact`

Creates a Contact via `POST .../sobjects/Contact`.

- **Required:** `last_name`, `idempotency_key`.
- **Optional:** `approved` (must be `true` or the write is refused),
  `first_name`, `email` (rejected before sending if malformed), `phone`,
  `title`, `account_id`, `allow_duplicate` (default `false`).
- **Returns:** `id`, `name`, `created` (`false` means an identical
  `idempotency_key` had already produced this record: the original outcome,
  not a new one).
- Salesforce's duplicate rules are left switched on. A match is refused and
  the matched record ids are returned unless `allow_duplicate=true` was sent.

### `salesforce.update_contact`

Changes fields on an existing Contact via `PATCH
.../sobjects/Contact/{id}`, then re-reads the record, because Salesforce
answers a successful `PATCH` with `204 No Content`: no body to report back
(see [ADR-007](docs/DECISIONS.md#adr-007-re-read-after-patch)).

- **Required:** `contact_id` (15 to 18 characters), `idempotency_key`, and at
  least one of the optional fields below: an update naming nothing is
  rejected before any request is sent.
- **Optional:** `approved`, `first_name`, `last_name`, `email`, `phone`,
  `title`, `account_id`.
- **Returns:** `id`, `name`, `changed_fields`, `email`, `phone`, `title`,
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
  (`true`/`false`/absent, see below).
- `stage_name` is validated against the org's own `StageName` picklist
  (`GET .../sobjects/Opportunity/describe`, cached per action instance)
  before the write is sent; an invalid value is rejected with the exact
  accepted values (see
  [ADR-008](docs/DECISIONS.md#adr-008-opportunity-stage-read-from-the-orgs-picklist-never-hardcoded)).
  If the profile cannot run `describe`, the check is skipped and Salesforce is
  left to judge.
- Linking a contact is a second write that can fail after the Opportunity
  already exists. `contact_linked: false` reports that partial state
  honestly rather than as an outright failure: the deal must not be created
  a second time in that case.

### `salesforce.add_activity_note`

Logs a call, email, meeting, or note as a completed `Task`
(`POST .../sobjects/Task`), see
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
and `openapi.py`, see [Architecture](#architecture).

---

## Architecture

Three layers, dependencies pointing only inward. `.importlinter` enforces
this on every commit and in CI (`lint-imports`), not just in prose, four
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
                    │      contract          │  no vendor import at all,
                    │                       │  not httpx, mcp, jwt, yaml,
                    │                       │  tenacity, structlog,
                    │                       │  itsdangerous, aiolimiter
                    └───────────────────────┘
```

**Why the MCP adapter is deliberately thin.** `mcp_server.py` opens the
connector at startup, lists what it offers, forwards a call, and closes on
the way out; `mcp_translate.py` turns the connector's own types into the
protocol's and back; `mcp_approval.py` asks the client to put a write to a
person before the connector ever sees it. None of the three contains an
endpoint, an object name, or a
query, `tests/unit/test_mcp_server.py::TestTheAdapterKnowsNothingAboutSalesforce`
asserts this directly, by searching the adapter's own source for strings like
`sobjects/`, `parameterizedSearch`, `LastName`, `StageName`, and `WhoId` and
failing if any appear. `openapi.py` is symmetric: it builds its document from
the same `registry.descriptors()` the MCP adapter reads, so the two surfaces
cannot describe an action differently. Both are import-linter-forbidden from
reaching past `connector` into `actions`, `client`, or `auth` directly.

**Two narrower rules, each enforced by its own contract:**

- Only `client.py` may import `httpx`: every other layer reaches the network
  only through the client, so its timeouts, retries, and error mapping cannot
  be bypassed by an action that decides to make its own request.
- Only `mcp_server.py`/`mcp_approval.py`/`mcp_translate.py` may import the
  `mcp` package, so
  swapping the protocol layer, or adding a second adapter (a CLI, a batch
  runner), never requires touching `connector.py` or anything below it.

---

## Design decisions

Twenty-seven of them, each with the options considered and what the choice
cost, in [docs/DECISIONS.md](docs/DECISIONS.md).

The ones worth reading first:

| | |
|---|---|
| [Why five actions, not ninety](docs/DECISIONS.md#adr-002-five-actions-not-the-90-endpoint-salesforce-surface) | Tool choice gets worse past roughly 20 tools |
| [Why `parameterizedSearch`](docs/DECISIONS.md#adr-003-parameterizedsearch-instead-of-soql-or-sosl) | There is no query string for a search term to escape out of |
| [Why writes ask a person first](docs/DECISIONS.md#adr-022-the-server-asks-the-client-to-ask-a-person-and-falls-back-to-a-parameter) | A boolean cannot tell a human from a model |
| [What the first real org changed](docs/DECISIONS.md#adr-026-what-the-first-real-org-changed) | Four defects mocks could not have caught |

---

## Reliability

**Retries** (`errors/retry.py`, built on `tenacity`). Three rules, applied
uniformly:

- Only failures marked `retryable` are retried (`RateLimitError`,
  `TransportError`), `input`, `permission`, and `conflict` failures fail
  identically on a second attempt and would only spend the org's quota.
- A write with no `idempotency_key` is never retried: the first attempt may
  already have taken effect.
- The wait is whichever is longer: exponential backoff with jitter
  (1s initial, 60s cap, 1s jitter), or a `Retry-After` the provider itself
  supplied: a retry never lands inside a window Salesforce already refused.
- The loop stops on whichever limit is hit first: 3 attempts, or a 120-second
  total budget: an attempt ceiling alone could still hold a call for
  minutes across three 60-second waits.

**Idempotency** (`idempotency.py`, per-process, in memory). A completed
key's result is returned verbatim on replay
(`Action._already_done`), with a warning noting the original result was
returned rather than a new write performed. A failed, non-retryable write
marks its key `FAILED`, safe to try again. Read the module's docstring
plainly: *"it lives in memory, so it protects a retry within one process and
nothing more... Real protection comes from the provider, by writing through
an external id so Salesforce itself refuses to create a second record, this
is the second line, not the first."* That provider-side line does not exist
yet, see [Known limitations](#known-limitations-and-access-blockers).

One further honest note not stated elsewhere in the codebase's own
docstrings: the ledger's `KeyState.IN_FLIGHT` and its `begin()` method exist
and are tested in isolation (`tests/unit/test_durability.py::TestTheLedger`),
but **no action currently calls `IdempotencyLedger.begin()`**: the live path
only ever calls `find`, `complete`, and `fail`. In practice this means two
concurrent calls sharing the same fresh `idempotency_key`, sent close enough
together that neither has completed yet, are not currently detected as
"already in flight", both would reach Salesforce independently. The
sequential case this connector is built around (retry-after-timeout, one
call at a time) is fully covered; true concurrent duplicate submission of an
unfinished key is not.

**Checkpoints** (`checkpoint.py::Journal`). Used today by
`create_opportunity` to record the Opportunity's own creation before
attempting the Contact link, so a failure in the second step is reported as
`contact_linked: false`: a partial success naming exactly what exists,
rather than a plain failure that would tempt a retry into creating a second
Opportunity. See [ADR-021](docs/DECISIONS.md#adr-021-journal-based-partial-success-for-multi-step-writes).

**Rate limits.** `Sforce-Limit-Info` is parsed off every Salesforce response,
success or failure (`exchange.py::parse_rate_limit`), and surfaced as
`rate_limit` in every envelope, free telemetry, since polling `/limits`
separately would spend a call to learn the same thing. Separately, this
connector's own call budget (60/minute/process by default) refuses excess
calls rather than queuing them, see
[ADR-015](docs/DECISIONS.md#adr-015-rate-limiting-our-own-invocations-refusing-rather-than-queuing).

**Pagination.** `search_contact`'s `next_cursor` is an offset the connector
itself encodes and interprets, Salesforce's `parameterizedSearch` has no
native opaque cursor the way SOQL's `nextRecordsUrl` does, so the connector
manufactures one from an offset and only issues it when a page came back
full (a short page means results ran out). `has_more` is derived from
whether a cursor is present (`Pagination.has_more`), never stored
separately, so it cannot disagree with the cursor it describes, this
matches the specification's own cursor discipline even though `tools/call`
itself is outside the four operations the specification requires pagination
for.

---

## Security

Auth and security carry the largest single weight in the programme's own
scoring (20%). Controls, and where each lives:

| Threat | Control | Location |
|---|---|---|
| SOQL/SOSL injection | Search text sent as a JSON value to `parameterizedSearch`, never assembled into query syntax | `actions/search_contact.py`, [ADR-003](docs/DECISIONS.md#adr-003-parameterizedsearch-instead-of-soql-or-sosl) |
| Prompt injection via record data | Every successful result's text content is wrapped in a nonce-bearing fence before a model sees it | `mcp_translate.py::wrapped`, [ADR-013](docs/DECISIONS.md#adr-013-the-nonce-bearing-untrusted-data-fence) |
| Secret leakage into logs | A structlog processor censors known secret keys and bearer/PEM-shaped patterns in every log line, at any nesting depth, before rendering | `observability.py::censor_secrets` |
| Secret leakage via `repr`/`str` | Credentials are `pydantic.SecretStr`; printing `Settings` shows a mask, never the value | `config.py::Settings` |
| Token exposure | Access tokens live only in memory, for the life of the process; never written to disk or logged | `client.py`, `auth/strategy.py::Token` |
| Unapproved writes | The server asks the client to put the write to a person and refuses on anything but an explicit yes; a client that cannot be asked falls back to `approved: true` in the tool's own schema, refused otherwise with an explanation of how to retry | `mcp_approval.py::WriteApproval`, `actions/action.py::_require_approval`, [ADR-022](docs/DECISIONS.md#adr-022-the-server-asks-the-client-to-ask-a-person-and-falls-back-to-a-parameter) |
| Over-broad OAuth scope | Manifest requests only `api` and `refresh_token`, nothing beyond what the five actions need | `connector.yaml` |
| Over-broad data access | The connector runs as one Salesforce user; that user's own profile, not the connector, is the real ceiling on what any action can reach | `connector.yaml` `risks` |
| Accidental production use | Refused at startup unless `SF_ALLOW_PRODUCTION=true` is set alongside a production `SF_LOGIN_URL` | `config.py::_production_needs_saying_so`, [ADR-016](docs/DECISIONS.md#adr-016-sandbox-by-default-production-requires-explicit-opt-in) |
| Provider error detail leakage | Error reasons are capped at 300 characters and never include a stack trace or file path | `errors/mapping.py::_reason` |
| Runaway call volume | This connector's own call budget refuses excess invocations rather than queuing them | `ratelimit.py::CallBudget`, [ADR-015](docs/DECISIONS.md#adr-015-rate-limiting-our-own-invocations-refusing-rather-than-queuing) |
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
443 passed, 2 skipped, 30 deselected, 2 warnings in 17.91s

$ python -m pytest -m "integration or learning" -q     # needs the org
30 passed, 445 deselected in 96.02s

$ python -m ruff check .
All checks passed!

$ python -m mypy src tests
Success: no issues found in 59 source files

$ PYTHONPATH=src lint-imports
Analyzed 70 files, 219 dependencies.
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
  443-pass run above covers): unit tests (`tests/unit/`, schema validation,
  error mapping, retry classification, idempotency ledger, approval path,
  published examples, OpenAPI generation, MCP adapter thinness), contract
  tests (`tests/contract/`, that `connector.yaml`, the registry, the tool
  list, and `openapi.yaml` still describe one connector rather than four),
  and security tests (`tests/security/`), all against mocked HTTP (`respx`),
  no network and no credentials required. The two skips are the read action
  sitting out a test about idempotency keys, which only writes have.
- **`integration`**, "end to end against a live sandbox (needs an org)."
  22 tests: the connection, the four writes with their cleanup, and the
  pagination walk. **Run against a real Developer Edition org, all passing.**
  They skip rather than fail when no credentials are configured, so a
  contributor without an org sees skips, but a skip proves nothing, and the
  numbers below are from a run that did not skip.
- **`learning`**, "pins real Salesforce behaviour (needs an org)." 8 tests,
  each naming one assumption this connector was built on from documentation
  and the code that leans on it. All passing. A failure there is not a bug
  report; it is a correction to something believed about Salesforce.

Both tiers run with `make live`; `docs/GO-LIVE.md` is the ordered runbook.
Its warning about the pagination walk being the most likely failure turned out
to be wrong in an interesting way: `parameterizedSearch` **does** honour the
`offset` the cursor is built from, so that test passed. Four other things
failed instead, see
[ADR-026](docs/DECISIONS.md#adr-026-what-the-first-real-org-changed).

**A real bug this process caught, and how.** While assembling the
evaluation questions in `evaluations/` (ten Q&A pairs for testing whether a
model can use these tools correctly, see `evaluations/README.md`), a
concrete defect was found: every write tool's own error text instructs a
caller to "call again with `approved` set to `true`," but at the time,
`approved` was not declared in any write's Pydantic input model, which
forbids unknown fields (`extra="forbid"`). A caller doing exactly what the
tool told it to do would have been rejected with a schema validation error
instead of getting the write it asked for, confirmed directly against the
validation layer, no credentials needed. Every existing test had missed this
because each one constructed an `ActionRequest` directly and set `approved`
as a Python field, which is not the path a real MCP client takes: a client
puts `approved` inside the tool call's `arguments`, which get validated
against the schema. The fix (commit `2dcc0d4`, "Let a caller do what the
error message tells it to") declares `approved` in each write's own schema.
`tests/unit/test_approval_path.py` now walks the client's actual path,
`CallToolRequestParams` → `mcp_server._as_request` → the action's own input
model, specifically so this class of bug cannot recur silently. This is
also why `evaluations/README.md` reads as though the bug is still open: it
documents the investigation as it happened, and was not rewritten after the
fix landed; the fix and its regression test are what actually ship.

**A second, later finding, from a threat-model review rather than a test.**
While writing `SECURITY.md`, a review of `observability.py::_censor_value`
found two real gaps in the log censor: it recursed into dictionaries but not
into lists or tuples, so a token at `records[0].access_token`, exactly
where a Salesforce reply's own shape puts one, passed through unmasked; and
the bearer-token pattern matched only word characters, so a real Salesforce
session id containing `!` (`00D5g000004abc!AQEAQ...`) was masked only up to
that character, with the remainder of the token written out in full. The
existing test had passed throughout, correctly by its own narrower
question: it checked whether the *complete* token appeared as one
contiguous substring, which stayed true even with half of it leaking. Fixed
in commit `602a392` ("Follow secrets into lists, and past the mark in a
session id"), with `tests/security/test_censoring_depth.py` added to check
the tail specifically and a secret nested two containers deep. `SECURITY.md`
itself still narrates this as an open, unfixed gap in its "what this
deliberately does not defend against" section, written before the fix
landed and not updated afterward. The code, read directly, is the source of
truth: both gaps are closed.

---

## Known limitations and access blockers

Stated plainly, per Definition of Done item 11, hiding these would be worse
than the gaps themselves.

- **Resolved.** This list opened with *"no live Salesforce org has ever been
  available"*. One now is: a Developer Edition org with an External Client
  App, and all 30 tests in `tests/integration/` and `tests/learning/` pass
  against it, as does a full stdio round trip through the MCP protocol. What
  that run found is
  [ADR-026](docs/DECISIONS.md#adr-026-what-the-first-real-org-changed). The entry is kept
  rather than deleted because the four defects it uncovered are the argument
  for why "passes against mocks" was never the same claim.
- **The ten `evaluations/questions.xml` answers are still hand-derived, not
  executed.** They were worked out by hand from `evaluations/seed_data.md`
  plus the connector's own schemas and action code: the same reasoning an
  LLM using only these tools would have to do. Running them needs the seed
  contacts loaded and the harness pointed at the org;
  `evaluations/README.md` documents exactly how.
- **Idempotency memory is process-scoped, not durable.** A restart between a
  write being sent and its response arriving loses the ledger entirely; a
  retry after that restart is indistinguishable from a first attempt. See
  [ADR-006](docs/DECISIONS.md#adr-006-idempotency-key-required-on-every-write-enforced-structurally)
  and [Reliability](#reliability).
- **Provider-side deduplication needs an org configuration change this
  connector cannot make for itself:** an External Id field on Contact (or
  Opportunity) that Salesforce itself would use to refuse a duplicate write,
  independent of this connector's own in-memory ledger. An org now exists,
  but adding the field changes the org's schema rather than this connector,
  so it is a decision rather than an oversight and remains unmade.
- **The idempotency ledger's `IN_FLIGHT` state is unreached by the current
  call path**, `begin()` is never called by any action. Two truly
  concurrent calls sharing a fresh, not-yet-completed key are not currently
  detected as in-flight; only the sequential retry-after-timeout case is
  covered. See [Reliability](#reliability).
- **A client that declares no elicitation capability is never asked about a
  write.** The specification forbids sending a request whose capability the
  client did not declare, so those callers fall back to setting `approved:
  true` themselves, and there this connector cannot tell a human's
  confirmation from a model setting a boolean. Nothing on the server side
  can close that gap. See
  [ADR-022](docs/DECISIONS.md#adr-022-the-server-asks-the-client-to-ask-a-person-and-falls-back-to-a-parameter).
- **A contact's account comes back as an id, not a name.** `account_id` is
  populated; resolving it to a human-readable account name would need a
  relationship field this project cannot verify without an org. See
  [ADR-023](docs/DECISIONS.md#adr-023-the-account-comes-back-as-an-id-not-a-name).
- **The search pagination cursor's real behaviour against Salesforce is
  unverified.** `search_contact` builds its cursor from an `offset` field
  sent to `parameterizedSearch`; SOSL-backed search results have not
  historically supported an offset parameter the way SOQL query pagination
  does. Whether Salesforce actually honours it, or silently repeats page one,
  is unknown without a live org, flagged directly in
  `evaluations/README.md`.
- **stdio and Docker only: no deployed HTTPS MCP endpoint.** The kickoff
  deck's dominant framing calls a deployed endpoint required; the actual
  submission-page copy softens that to "when it is ready." This connector
  ships stdio-only, deliberately, see
  [ADR-010](docs/DECISIONS.md#adr-010-stdio-and-docker-not-a-hosted-https-endpoint) for the
  full trade-off, quoted from both sides rather than silently picking one.
- **Five actions, not the wider Salesforce surface.** See
  [Roadmap](#roadmap) for what is deliberately not built yet, and why.
- **Sandbox only, by design.** A production login host is refused unless
  `SF_ALLOW_PRODUCTION=true` is explicitly set, see
  [ADR-016](docs/DECISIONS.md#adr-016-sandbox-by-default-production-requires-explicit-opt-in).
  This is a safety choice, not an access blocker, but it does mean this
  connector will refuse to run against production without a deliberate,
  separate opt-in.

---

## Roadmap

`docs/research/03-salesforce-api-map.md` catalogues roughly 90 Salesforce REST
endpoints; this connector implements five. That document's own tiering is
the plan for what comes next, in priority order:

**Next (natural extensions of the always-on core).**
`get_record_by_external_id` / `upsert_record_by_external_id` /
`delete_record_by_external_id`, upsert-by-external-id is how most real
integrations avoid the client-side "query then create-or-update" pattern
this connector's own `create_contact`/`allow_duplicate` flow works around
manually today. `soql_query` / `soql_query_more` / `sosl_search` as
explicit, generic read actions alongside the five purpose-built ones.
`composite_batch` / `collections_create_records` /
`collections_update_records`, bulk efficiency wins, and the connector's
existing per-action idempotency-key pattern extends naturally to a batch
key per subrequest.

**Later (real, but narrower).** Layouts and list views, for agents that need
to mirror what a person sees in the Salesforce UI rather than raw field
data. Quick Actions and invocable Actions, which can trigger Flows or send
email, genuinely powerful, and deliberately deferred until there is a
concrete use case pulling for them rather than built speculatively, given
the blast radius of getting an invocable-action wrapper wrong. Change feeds
(`get_deleted_records`, `get_updated_records`), for a future sync/replication
feature.

**Deliberately not planned as bespoke tools.** Knowledge/data-category
objects, Lightning usage-metrics objects, and similar, these are, in
substance, `soql_query` against a named object with no real behavioural
divergence from the generic pattern; adding them as individually-named tools
would grow the tool list without growing capability, which
`docs/research/03-salesforce-api-map.md` §4 argues directly degrades tool-
selection accuracy once a manifest exceeds roughly 20-25 tools. If genuine
demand appears, the answer is `soql_query` plus documentation, not a new
action per object.

**Also on the list, not yet started:**
- Resolve `account_id` to an account name on a live org, once the relationship
  field can be verified rather than guessed
  ([ADR-023](docs/DECISIONS.md#adr-023-the-account-comes-back-as-an-id-not-a-name)).
- Run `evaluations/questions.xml` for real against a live Developer Edition
  org, once one exists, per the procedure in `evaluations/README.md`.
- A streamable-HTTP transport alongside stdio, additive to the existing
  `connector` core rather than a rewrite of it, if a deployed endpoint
  becomes a hard requirement (see
  [ADR-010](docs/DECISIONS.md#adr-010-stdio-and-docker-not-a-hosted-https-endpoint)).
- An External Id field on the org, once one exists, so provider-side
  deduplication backs up the in-memory idempotency ledger rather than being
  the only line of defence.

---

## Licence

Apache License 2.0, see [`LICENSE`](LICENSE).
