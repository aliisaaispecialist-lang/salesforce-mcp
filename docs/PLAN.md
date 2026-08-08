# Salesforce Connector: Architecture & Build Plan

**Builder:** Ali Isa · **Mission:** Salesforce (Advanced, Enterprise CRM)
**Program:** Builders League, Connector Test Suite, Cohort 01 (MK Lab × DOO)
**Status:** PLAN, awaiting approval. No implementation code written.
**Date:** 2026-08-06

---

## 1. What we are building

> "One reusable core, five reliable actions, and a thin MCP adapter that is ready to validate."

Five required actions, fixed by the program (verbatim IDs):

| # | Action ID | Kind |
|---|---|---|
| 1 | `salesforce.search_contact` | read |
| 2 | `salesforce.create_contact` | write (additive) |
| 3 | `salesforce.update_contact` | write (mutating) |
| 4 | `salesforce.create_opportunity` | write (additive) |
| 5 | `salesforce.add_activity_note` | write (additive) |

**Scope decision (owner, 2026-08-06):** build exactly these five, to an exceptional standard. Expand later by endpoint and urgency. The ~90-endpoint survey in `research/03-salesforce-api-map.md` becomes documented future scope in the README, not v1 surface.

**Language decision (owner, 2026-08-06):** Python. The program's template uses `.ts` extensions but no rule anywhere on the site mandates a language (`research/06-doo-assignment.md` §5). We keep the folder shape file-for-file and swap extensions. Recorded as ADR-001.

---

## 2. Scoring map: every decision traces to a criterion

| Criterion | Weight | What earns it here |
|---|---|---|
| Working actions & acceptance scenario | 25% | All 5 through one `execute`; one real sandbox run |
| Authentication and security | 20% | JWT Bearer, least privilege, zero secrets, injection-safe search |
| Connector structure and reusability | 15% | Exact template folder shape; core reused by MCP **and** OpenAPI |
| Schemas and developer experience | 10% | Typed JSON Schema in/out + examples per action |
| Reliability, errors, pagination, rate limits | 10% | Normalized errors, request IDs, retry classes, `Sforce-Limit-Info` |
| Testing and fixtures | 10% | Unit + fixture tests, one real sandbox test |
| Documentation and OpenAPI | 5% | `openapi.yaml` from the same schemas; comprehensive README + ADRs |
| Demonstration and technical explanation | 5% | `examples/` runnable scripts + README design rationale |

Auth/security is 20%, the second-largest single block, and larger than testing and docs combined. It gets first-class design, not a section at the end.

---

## 3. Definition of Done: traceability

Each DoD item maps to an artifact. Nothing is "covered by" something else.

| # | DoD item | Artifact |
|---|---|---|
| 1 | Manifest: provider, version, auth, scopes, actions, risks, capabilities | `connector.yaml` |
| 2 | `testConnection` with no side effects | `src/connector.py::test_connection` → `GET /limits` |
| 3 | All 5 actions via shared `execute` | `src/connector.py::execute` + `src/actions/` |
| 4 | Typed JSON Schema in/out + examples | `src/schemas/` + `examples/` |
| 5 | Normalized errors, request IDs, retry classification | `src/errors/` |
| 6 | Pagination + rate-limit metadata | `ActionResult.pagination` / `.rate_limit` |
| 7 | Write approval, idempotency, duplicate, retry behaviour documented | README + per-action schema docs |
| 8 | No secrets in code, git history, logs, fixtures, screenshots | `.env.example`, redaction filter, pre-commit secret scan |
| 9 | Unit + fixture tests, one real sandbox test | `tests/`, `fixtures/` |
| 10 | OpenAPI + thin MCP adapter reuse the same core | `openapi.yaml`, `mcp/server.py` |
| 11 | Known limitations and access blockers listed | README §Limitations |
| 12 | Tagged `v1.0.0` + handoff notes | git tag + CHANGELOG |

---

## 4. Architecture

Three layers. Dependencies point inward; nothing in `actions/` knows MCP exists.

```
  ┌──────────────────┐   ┌──────────────────┐
  │  mcp/server.py   │   │   openapi.yaml   │   ← adapters (thin, no logic)
  └────────┬─────────┘   └────────┬─────────┘
           └──────────┬───────────┘
                ┌─────▼──────┐
                │ connector  │  test_connection() / list_actions() / execute()
                └─────┬──────┘
        ┌─────────────┼─────────────┐
   ┌────▼────┐   ┌────▼────┐   ┌────▼────┐
   │ actions │   │ schemas │   │ errors  │
   └────┬────┘   └─────────┘   └─────────┘
   ┌────▼────┐   ┌─────────┐
   │ client  │◄──┤  auth   │        ← the only code that touches the network
   └─────────┘   └─────────┘
```

**The rule that protects 15% of the score:** the MCP server contains no Salesforce knowledge. It enumerates `list_actions()`, converts each to an MCP tool, and forwards to `execute()`. If a Salesforce URL, field name, or SOQL string ever appears in `mcp/server.py`, the design has failed. Same for the OpenAPI spec, generated from the same schema objects, never hand-maintained in parallel.

### The core contract

```python
def test_connection() -> ConnectionStatus      # side-effect free
def list_actions() -> list[ActionDescriptor]   # id, schemas, risk, idempotency
def execute(action_id: str, params: dict) -> ActionResult
```

**SDK version, build against v2, not the books.** The MCP Python SDK reached **v2.0.0 (2026-07-28)**: `FastMCP` was renamed to `MCPServer` and the v1 import path removed outright, transport config moved from the constructor to `run()`, and context injection changed. Every sample in our source books is v1-era and will not import (`research/07-reference-repos.md`). We pin the SDK version in `pyproject.toml` and verify the API against the installed package before writing the adapter, no code written from remembered or summarized APIs.

`ActionResult` is uniform across all five actions:

```
ok | data | error | request_id | pagination | rate_limit | warnings
```

Uniformity is what makes the adapter thin. The MCP layer never special-cases an action.

---

## 5. File skeleton

```
salesforce-connector/
├── connector.yaml              # manifest (DoD 1)
├── pyproject.toml              # hatchling, src-layout, PEP 639 licence
├── openapi.yaml                # generated from src/schemas/
├── .env.example                # every var, no real values
├── README.md                   # + ADR log
├── CHANGELOG.md
├── src/salesforce_connector/
│   ├── connector.py            # test_connection / list_actions / execute
│   ├── client.py               # httpx client, retries, rate limits, pagination
│   ├── auth/
│   │   ├── jwt_bearer.py       # primary flow
│   │   ├── client_credentials.py
│   │   └── token_cache.py      # in-memory, TTL, never on disk
│   ├── actions/
│   │   ├── search_contact.py
│   │   ├── create_contact.py
│   │   ├── update_contact.py
│   │   ├── create_opportunity.py
│   │   └── add_activity_note.py
│   ├── schemas/                # one module per action: input, output, examples
│   └── errors/
│       ├── model.py            # ConnectorError + retry classification
│       └── mapping.py          # Salesforce error code → normalized error
├── mcp/server.py               # thin adapter, stdio + streamable HTTP
├── tests/                      # unit + fixture + one live sandbox test
├── fixtures/                   # recorded, scrubbed API responses
└── examples/                   # runnable script per action
```

Matches the program template exactly, with `.py` for `.ts` and a `src/salesforce_connector/` package (src-layout, an MCP host spawns the server as a subprocess with unpredictable CWD, so flat layout risks import shadowing; `research/05-packaging-and-readme.md`).

---

## 6. The five actions

### 5.1 `search_contact`: read

`POST /services/data/v67.0/parameterizedSearch` with a JSON body.

**Why not SOQL/SOSL string building:** the obvious implementation concatenates user input into `FIND {…}` or `WHERE Name LIKE '%…%'`, which is injectable. The parameterized search endpoint takes a JSON body with `q`, `sobjects`, `fields`, no query string is ever assembled from user input. This is a direct answer to the 20% auth/security criterion and to the SOQL-injection control in `research/04-tool-design-and-security.md`.

Input: `query` (required, min length 2), `fields`, `limit` (default 20, max 200), `offset`.
Output: `records[]`, `total_size`, `pagination`.

### 5.2 `create_contact`: write, additive

`POST /services/data/v67.0/sobjects/Contact`

Required: `last_name` (Salesforce's only mandatory Contact field). Optional: `first_name`, `email`, `phone`, `account_id`, `title`, `extra_fields`.

**Duplicate behaviour:** Salesforce duplicate rules may block or warn. We surface the rule result explicitly rather than silently succeeding. Optional `allow_duplicate` (default `false`); when false and a duplicate is detected, return a structured error listing the matched record IDs so the caller can decide.

**Idempotency:** REST create is not idempotent, a timed-out retry can create two Contacts. We accept an `idempotency_key`, cache it against the resulting record ID for the process lifetime, and return the cached result on replay. Documented honestly in the README as process-scoped, not durable.

### 5.3 `update_contact`: write, mutating

`PATCH /services/data/v67.0/sobjects/Contact/{id}`

Naturally idempotent. Returns **204 No Content with no body**, so we re-fetch and return the updated record, otherwise callers get an empty success and cannot confirm what changed.

Requires at least one field beyond `contact_id`; an empty update is rejected as an input error, not sent.

### 5.4 `create_opportunity`: write, additive

`POST /services/data/v67.0/sobjects/Opportunity`

Required by Salesforce: `Name`, `StageName`, `CloseDate`. `StageName` is **org-specific picklist data**, hardcoding stage values is the classic failure. We fetch valid stages via describe, cache them, and validate before sending, returning the allowed set in the error when invalid.

Optional `contact_id` creates the `OpportunityContactRole` link, a second call, so it is a multi-step write: if the role fails after the Opportunity is created, we return partial success naming exactly what exists and what does not. No silent rollback illusion.

### 5.5 `add_activity_note`: write, additive · **OPEN DECISION**

Ambiguous by name. Three plausible Salesforce mappings:

| Option | Object | Behaviour |
|---|---|---|
| **A (recommended)** | `Task` | Appears in the Activity timeline. "Activity" in Salesforce means Task/Event, so this is the most literal reading of the action name. |
| B | `Note` (classic) | Simple `ParentId` + `Body`; disabled in many modern orgs. |
| C | `ContentNote` | Lightning notes; requires base64 body **and** a second `ContentDocumentLink` call. |

Recommending **A**: it matches the word "activity", works in every org, and is a single call. Needs your confirmation, if the graders mean Lightning notes, C is the answer and costs an extra call plus link handling.

---

## 7. Authentication

**JWT Bearer flow** (primary), Client Credentials (fallback). Both headless.

**Username-password flow is excluded by design.** Salesforce is retiring it starting Winter '27, with production rollout weekends of **29 Aug, 3 Oct, 10 Oct 2026**, the first is roughly three weeks from today. Building it would ship a connector that breaks during the cohort. Recorded as ADR-004.

Rules:
- `instance_url` comes from the token response and is authoritative, never assume it equals the login host.
- Tokens live in memory only, with TTL and refresh-on-401-once. Never written to disk, never logged.
- Secrets from environment only. `.env.example` lists every variable with placeholder values.
- Least privilege: the Connected App requests only the scopes the five actions need, documented in `connector.yaml`.
- `test_connection` calls `GET /limits`, authenticated, cheap, and provably side-effect free (DoD 2).

---

## 8. Errors, reliability, pagination

**Normalized error model:**

```
code · message · category · retryable · request_id · provider_code · details · retry_after
```

Categories: `auth` · `input` · `not_found` · `permission` · `rate_limit` · `conflict` · `provider` · `transient`.

`request_id` comes from Salesforce's response headers where present, otherwise generated locally, and appears in every log line for that call.

**Retry policy:** exponential backoff with jitter on `transient` and `rate_limit` only. Never retry `input`, `permission`, `conflict`. Writes retry only when an `idempotency_key` is present, otherwise a retry risks duplicate records, which is worse than a visible failure.

**Rate limits:** read `Sforce-Limit-Info` from every response and return it as `rate_limit` metadata. Free telemetry, no polling of `/limits`.

**Pagination:** `nextRecordsUrl` is an opaque token, passed back verbatim, never reconstructed.

**Timeouts:** 5s reads, 15s writes, enforced by the client, not left to library defaults.

---

## 9. Security controls

| Threat | Control | Location |
|---|---|---|
| SOQL/SOSL injection | Parameterized search endpoint; no query string assembly from input | `actions/search_contact.py` |
| Prompt injection via record data | Contact/Opportunity free-text fields wrapped in explicit untrusted-data delimiters before reaching a model | `mcp/server.py` result formatting |
| Secret leakage | Env-only secrets, redaction filter on all logs, pre-commit secret scan, scrubbed fixtures | cross-cutting |
| Token exposure | In-memory only, TTL, never serialized | `auth/token_cache.py` |
| Unapproved consequential writes | Write actions carry `destructiveHint`/`readOnlyHint` annotations; MCP layer surfaces confirmation | `mcp/server.py` |
| Over-broad access | Minimum scopes, documented in manifest | `connector.yaml` |
| Error message leakage | Provider errors mapped, stack traces never returned to caller | `errors/mapping.py` |

Sandbox only. No production customer data at any point, including fixtures.

---

## 10. Code style

Governed by `research/02-clean-code-standard.md` ("THE 20 RULES"). Enforced mechanically, because a standard nobody can check is decoration:

- **ruff**, format + lint, line length 100
- **mypy**, strict; every public function fully annotated
- **pytest** + **pytest-cov**
- **pre-commit**, runs all of the above plus a secret scan before every commit

Non-negotiables carried into this project: functions small and doing one thing; one level of abstraction per function; no flag arguments; exceptions not error codes; no commented-out code; third-party APIs wrapped at a boundary (`client.py` is the only module that knows `httpx` exists); tests F.I.R.S.T.

---

## 11. Testing

| Layer | What | Network |
|---|---|---|
| Unit | Schema validation, error mapping, retry classification, idempotency cache | none |
| Fixture | Each action against recorded, scrubbed responses | none |
| Contract | Client behaviour on 400/401/403/404/429/500, timeouts, malformed JSON | mocked |
| Live sandbox | One end-to-end run of all five actions against a real Developer Edition org | real |

Fixtures are recorded from a real sandbox then scrubbed of IDs, emails, and org identifiers, DoD 8 covers fixtures explicitly, and a real recorded response with a real org ID in it fails that.

---

## 12. README + ADR log

Sections: What this is → Install → Quickstart → Configuration → The five actions (with schemas + examples) → Architecture → **Design Decisions (ADRs)** → Reliability → Security → Testing → Known limitations & access blockers → Roadmap (the ~90-endpoint map) → Changelog.

Each ADR: **Context → Options considered → Decision → Trade-offs accepted → Consequences.**

Planned ADRs: 001 Python over TypeScript · 002 five actions over full coverage · 003 parameterized search over SOQL · 004 JWT Bearer over username-password · 005 Task for activity note · 006 process-scoped idempotency · 007 re-fetch after PATCH · 008 thin adapter over MCP-native tools · 009 hatchling/src-layout · 010 stdio + streamable HTTP, no SSE.

---

## 13. Build sequence

Mapped to the program's own milestones:

| Milestone | Deliverable |
|---|---|
| **Kickoff**, "Mission accepted" | This plan, `connector.yaml`, five action schemas, access risks |
| **First checkpoint**, "Build continues" | Repo skeleton, auth + `test_connection`, `search_contact`, fixtures |
| **Week 1 demo**, "Integration candidate" | Two real actions, normalized errors, tests, initial MCP tools |
| **Final handoff**, "v1.0.0 ready" | All five actions, OpenAPI, thin MCP server, examples, limitations, tag |

---

## 14. Open questions & risks

1. **`add_activity_note` mapping**, Task (recommended), Note, or ContentNote? §5.5. Blocks that action's schema.
2. ~~**Deadline unknown**~~, CLOSED (owner, 2026-08-06): disregard the deadline. Build to the milestone sequence in §13, not to a date.
3. **`/presentation` slides 2 to 14 unread**, client-side deck, browser extension was disconnected. May contain requirements we have not seen.
4. **Salesforce org access**, a Developer Edition org with a Connected App is needed for the live sandbox test (DoD 9). Not yet provisioned. This is the single largest schedule risk: everything else can proceed without it, but DoD 9 cannot.
5. **Language deviation**, Python is a documented, defensible choice, but it is a deviation from the template's implied TypeScript. ADR-001 states the reasoning.
