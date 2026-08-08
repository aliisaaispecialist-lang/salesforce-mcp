# Design decisions

Every decision this connector rests on, with the options that were
considered and what each one cost. Split out of the README, which was 1,572
lines with 58% of them here: a reader wanting to install the thing should
not have to scroll past twenty-seven architecture arguments to reach the
instructions.

Format: Context, Options considered, Decision, Trade-offs accepted,
Consequences. Nothing here is aspirational. Every entry is drawn from a
docstring, a test, or a commit already in this repository.

---

### ADR-001: Python, not TypeScript

**Context.** The programme's own repository template
(`docs/research/06-doo-assignment.md` §3, and slide 11 of the kickoff deck) uses
`.ts` extensions throughout (`connector.ts`, `client.ts`, `mcp/server.ts`),
and slide 10 presents the shared `DooConnector` contract as a literal
TypeScript `interface`. No page or slide states "you must use TypeScript" in
so many words, but the de facto pressure toward it is real and was weighed
knowingly, not missed.

**Options considered.**
1. TypeScript, matches the template's file extensions and the shared
   contract's presentation exactly; zero risk of a grader reading the
   deviation as non-compliance.
2. Python: no rule anywhere on the site or in the deck actually mandates a
   language; the owner's toolchain and the target's own stated evaluation
   criteria (security, structure, reusability, docs) are language-agnostic.

**Decision.** Python 3.12, with the folder shape kept file-for-file
equivalent to the template (`.py` in place of `.ts`).

**Trade-offs accepted.** A grader skimming the repository tree before reading
anything sees a deviation from the implied convention. This is a known,
accepted risk (recorded in `docs/research/06-doo-assignment.md` §5 and
`docs/OPEN-QUESTIONS.md` D3), not an oversight, mitigated by matching the
template's structure exactly everywhere it is not language-specific.

**Consequences.** Every packaging, typing, and tooling decision downstream
(Hatchling, `pydantic`, `mypy --strict`, `ruff`) is a Python-ecosystem choice
with no TypeScript equivalent to keep in sync. A future TypeScript adapter
sharing the same `connector.yaml`/`openapi.yaml` contract is possible but
would be a separate implementation, not a port.

### ADR-002: Five actions, not the ~90-endpoint Salesforce surface

**Context.** `docs/research/03-salesforce-api-map.md` catalogues roughly 90
distinct Salesforce REST endpoints. The programme assigns exactly five action
IDs to this connector (`docs/research/06-doo-assignment.md` §7) and slide 6 of the
deck explicitly permits going further only "after the assigned five work."

**Options considered.**
1. Build all five to a minimal standard, then add breadth.
2. Build exactly the five assigned actions to an exceptional standard,
   typed schemas, full error taxonomy, retries, idempotency, tests, and
   treat the rest as documented future scope.
3. Build a generic pass-through action (raw SOQL / arbitrary sObject CRUD)
   alongside the five, for coverage.

**Decision.** Option 2. The wider survey lives in
[Roadmap](#roadmap) as prioritised, not-yet-built scope.

**Trade-offs accepted.** A caller who wants to update an Account or run an
arbitrary query has no tool for it in v1. That gap is explicit, not silent,
`connector.yaml`'s `limitations` says so, and the Roadmap says what would
close it.

**Consequences.** Every action added later must justify itself against the
grouping problem `docs/research/03-salesforce-api-map.md` §4 describes: a flat
90-tool manifest measurably degrades tool-selection accuracy. Expansion
should follow that document's tiered/gated shape, not a flat dump.

### ADR-003: `parameterizedSearch` instead of SOQL or SOSL

**Context.** `search_contact` takes free text from a caller, potentially
relayed from an LLM relaying a user's own words. Building a SOQL `WHERE
Name LIKE '%...%'` clause or a SOSL `FIND {...}` string from that text is
exactly the "user input becomes query syntax" injection class the security
criterion (20% of the score) exists to catch.

**Options considered.**
1. SOQL, string-built with the caller's text interpolated, fast to write,
   directly injectable.
2. SOSL, string-built the same way, same defect, different syntax.
3. `POST .../parameterizedSearch` with the term as a JSON value (`q`).

**Decision.** Option 3. `search_contact.py` sends `{"q": query, "sobjects":
[{"name": "Contact"}], ...}`: the term is a JSON string value, not a
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
(`docs/research/03-salesforce-api-map.md` §6 item 1), inside the programme's own
build window.

**Options considered.**
1. Username-password flow, simplest to configure, but ships a connector
   that would start failing during the cohort itself.
2. OAuth 2.0 JWT Bearer: a signed assertion exchanged for a token; no
   password, no long-lived secret in transit.
3. OAuth 2.0 Client Credentials, simpler setup (no certificate), but does
   transmit a secret.

**Decision.** JWT Bearer as the primary and default flow
(`auth/jwt_bearer.py`); Client Credentials retained only as an explicit
fallback (ADR-020). Username-password is not implemented at all, not
disabled, absent.

**Trade-offs accepted.** JWT Bearer requires uploading a certificate to the
External Client App and pre-authorising the running-as user, more setup than a
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
materials (confirmed by `docs/research/08-doo-presentation.md` §5: no slide names
the target object). Salesforce offers three candidates for "logging an
interaction": `Task`, the classic `Note` object, and `ContentNote`.

**Options considered.**
1. `Task`: one call, appears on the record's Activity timeline, works in
   every org regardless of edition or feature toggles.
2. `Note` (classic): one call, but disabled outright in many modern
   (Lightning) orgs.
3. `ContentNote`, Lightning-native, but needs a base64-encoded body plus a
   second `ContentDocumentLink` call to attach it to a record.

**Decision.** `Task`, written already `Status: Completed`: this action
records something that already happened, not something to schedule.

**Trade-offs accepted.** A `Task` is a more general object than a
purpose-built "note" concept; callers who specifically wanted a Lightning
`ContentNote` (e.g. for rich text or attachments) do not get one from this
action.

**Consequences.** Changing this decision means changing exactly one schema
module (`schemas/add_activity_note.py`) and its action
(`actions/add_activity_note.py`), nothing else in the connector encodes the
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
   schema, relies on every caller reading and following the advice.
2. Require it in each write's Pydantic model, and additionally refuse to
   *register* a write action whose schema does not list it as required.

**Decision.** Option 2. `contract.py::ActionDescriptor._writes_require_an_idempotency_key`
is a `model_validator` that raises if a write action's `input_schema` does
not list `idempotency_key` under `required`: this runs at import time
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
mechanism: it is process-scoped, and one ledger state
(`KeyState.IN_FLIGHT`) is declared but never reached by the current call
path.

### ADR-007: Re-read after PATCH

**Context.** Salesforce answers a successful Contact `PATCH` with `204 No
Content`: no body at all. Returning that as-is would tell a caller only
that nothing went wrong, not what the record now holds.

**Options considered.**
1. Return the bare success with no data, cheapest, but tells a caller
   nothing about the record's actual current state.
2. Echo back exactly what the caller sent, cheap, but wrong the moment a
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
re-fetched state: the two are expected to agree, but are computed
separately by design (the field list is a record of intent, the rest of the
payload is a record of result).

### ADR-008: Opportunity stage read from the org's picklist, never hardcoded

**Context.** `StageName` on Opportunity is a picklist that every Salesforce
org configures independently: there is no universal, correct list of sales
stages across orgs.

**Options considered.**
1. Ship a fixed list of "common" stage names (`Prospecting`, `Closed Won`,
   ...) as an enum in the schema, fails the moment an org renamed or
   reordered its stages, which is common.
2. Accept any string, let Salesforce reject an invalid one, correct but
   unhelpful: the caller gets a raw provider error with no indication of
   what values would have worked.
3. Accept any string, but validate it against the org's live picklist first
   (`GET .../sobjects/Opportunity/describe`) and, on mismatch, return the
   exact accepted values in the error.

**Decision.** Option 3. `create_opportunity.py::_reject_unknown_stage` fetches
and caches the picklist once per action instance and checks before writing.

**Trade-offs accepted.** One extra (cacheable) API call on the common path.
If the running user's profile cannot run `describe` on Opportunity, the check
is skipped entirely and Salesforce is left to be the final judge, losing the
helpful error is accepted in exchange for not losing the action outright.

**Consequences.** `evaluations/questions.xml` includes a direct regression
for this: "True or false: in `salesforce_create_opportunity`'s published
input schema, `stage_name` is restricted to a fixed enum", answer `False`,
by design, forever, unless this ADR is revisited.

### ADR-009: The low-level MCP `Server` over the decorator API

**Context.** The MCP Python SDK offers two surfaces: a decorator-based API
that derives a tool's JSON Schema from a Python function's signature, and a
low-level `Server` that is handed pre-built `Tool` objects. This connector
already has hand-authored, tested Pydantic schemas for every action
(`schemas/*.py`).

**Options considered.**
1. Decorator API, less code to wire up, but a Pydantic parameter passed to
   a decorated function is nested under a `params` key in the resulting tool
   schema rather than published flat, which measurably raises the rate of
   malformed tool calls from callers who read the schema literally.
2. Low-level `Server`, more explicit wiring (`on_list_tools`,
   `on_call_tool`), but tools are published with the exact schema already
   authored and tested, with no parameter nesting.

**Decision.** Option 2 (`mcp_server.py::build_server`).

**Trade-offs accepted.** `list_tools`/`call_tool` are written by hand rather
than generated from function signatures: a few more lines of adapter code,
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
deployed URL field as optional, "Include the deployed HTTPS MCP URL **when
it is ready**", and the MCP specification itself says a server intended to
run locally **should** use stdio specifically to limit access to the
connecting client (`docs/research/09-mcp-spec-compliance.md` §8).

**Options considered.**
1. Deploy a hosted streamable-HTTP MCP endpoint, in line with the deck's
   dominant framing.
2. Ship stdio only, launched by an MCP host or by Docker as a subprocess,
   in line with the MCP specification's own guidance for locally-run
   servers, and with the submission form's actual, softer requirement.

**Decision.** Option 2, and this was the owner's explicit decision, not an
oversight or a resource shortfall.

**Trade-offs accepted.** This connector does not satisfy the deck's
strongest framing ("deployment is required for validation") as written. It
does satisfy the submission mechanics as actually specified ("when it is
ready"), the specification's own transport guidance for a locally-run
server, and, since no external HTTPS surface exists, removes an entire
class of exposure (no public listener, no TLS termination, no bearer-token
management for inbound callers) for a connector holding real CRM
credentials.

**Consequences.** `connector.yaml`'s `capabilities.transports` lists only
`stdio`, and this is repeated plainly in `limitations`. If a hosted endpoint
is later required, it is additive work: a streamable-HTTP transport wired
to the same `connector`/`actions` core, not a rewrite, because nothing
below `mcp_server.py` knows which transport is in use.

### ADR-011: Libraries over hand-rolled mechanics

**Context.** Retry loops, environment parsing, structured logging, rate
limiting, and signed tokens are each easy to write *plausibly* and hard to
write *correctly*, edge cases like partial bucket refill, contextvar
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
them: the layering rule ("the contract layer imports no vendor library at
all," `.importlinter`) means every one of these choices stays swappable
without touching the types every consumer depends on.

### ADR-012: Errors as tool results with `isError`, never protocol errors

**Context.** The MCP specification is explicit: "Clients **SHOULD** provide
tool execution errors to language models to enable self-correction"
(`docs/research/09-mcp-spec-compliance.md` §6). A JSON-RPC protocol error (an
`-32xxx` code) is not routed to the model the same way: it is a transport-
level failure, not something an agent loop can read and act on.

**Options considered.**
1. Raise a JSON-RPC protocol error for any Salesforce or validation failure.
2. Always return a normal `CallToolResult` with `is_error: true` and a
   message written for a model to act on.

**Decision.** Option 2 (`mcp_translate.py::refuse`, `as_result`). Every
`ConnectorError` subclass in `errors/model.py` carries a `category`, a
`reason`, and a `next_step`, "wait and retry," "fix an argument," "stop and
report," or "escalate", because the category alone is not enough when the
only reader is a model that sees text.

**Trade-offs accepted.** Genuine protocol-level problems (an unknown tool
name, a malformed call) are handled the same way as a Salesforce-side
failure, rather than distinguished by JSON-RPC error code. That uniformity is
deliberate: from the caller's perspective, "this call did not succeed, here
is why and what to do" is one shape, not two.

**Consequences.** No action's `run()` method ever lets an exception escape,
`Action.run` catches `ConnectorError` and returns a result, `Connector.execute`
does the same one level up. One bad call cannot end a session or affect the
other four actions.

### ADR-013: The nonce-bearing untrusted-data fence

**Context.** Salesforce records contain text written by other people,
contact titles, opportunity descriptions, activity notes, and an MCP result
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

**Trade-offs accepted.** None of real weight: a few extra bytes per
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
named `mcp`: the same name as this directory.

**Options considered.**
1. Put the adapter's actual implementation inside `mcp/server.py` directly.
2. Keep `mcp/server.py` as a two-line forwarding launcher, and put the real
   implementation in `src/salesforce_connector/mcp_server.py`.

**Decision.** Option 2. A module physically inside a directory named `mcp`
that also does `import mcp.server.stdio` asks Python to disambiguate between
the local directory and the installed SDK package, which one wins depends
on how the process happens to be started (`sys.path[0]` behaviour), which is
exactly the kind of ambiguity that works locally and breaks under a
different launcher.

**Trade-offs accepted.** One extra file and one indirection layer, for a
codebase that otherwise avoids launcher-only files.

**Consequences.** `tests/unit/test_mcp_server.py::TestTheAdapterKnowsNothingAboutSalesforce::test_the_entry_point_file_only_forwards`
pins this: the launcher must mention `salesforce_connector.mcp_server` and
stay under 20 lines: it cannot silently grow real logic without the test
failing.

### ADR-015: Rate limiting our own invocations, refusing rather than queuing

**Context.** The MCP specification states servers **MUST** "Rate limit tool
invocations" (`docs/research/09-mcp-spec-compliance.md` §6). The concrete failure
mode: a model in a retry or exploration loop can exhaust a Salesforce org's
entire daily API allowance in minutes, breaking every other integration on
that org until the daily window resets, damage that lands on people who
never interacted with this connector.

**Options considered.**
1. No self-imposed limit, rely on Salesforce's own quota (`Sforce-Limit-Info`)
   as the only backstop, which only reports the problem after the org-wide
   damage is already done.
2. Queue excess calls until capacity frees up, hides a runaway loop inside
   a call that merely appears slow, and lets an unbounded backlog build.
3. Refuse excess calls immediately, with a stated wait time.

**Decision.** Option 3. `ratelimit.py::CallBudget` wraps `aiolimiter`'s
leaky bucket (default 60 calls/minute/process) and raises `RateLimitError`
retryable, with `retry_after_seconds`: the moment capacity is exhausted,
checked *before* the bucket's own `acquire()` so the check never itself
blocks.

**Trade-offs accepted.** A legitimate burst of calls (e.g. paging through a
large search result quickly) is throttled the same as a runaway loop would
be; the connector cannot distinguish intent, only rate.

**Consequences.** This budget is separate from, and smaller-scoped than, the
Salesforce org's own API quota (surfaced as `rate_limit` in every envelope
via `Sforce-Limit-Info`): a caller can be refused by this connector's own
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
two variables, not one, friction added on purpose.

**Consequences.** "Sandbox only. A production login host is refused unless
explicitly enabled" is stated in `connector.yaml`'s `limitations`, and is
true by construction, not merely by convention: the guard lives in code
that fails startup, not in a note someone could skip past.

### ADR-017: Manifest cross-checked against the registry at startup

**Context.** `connector.yaml` declares what actions this connector offers
(Definition of Done item 1); `actions/registry.py` decides what actually
exists in code. Two independent descriptions of the same thing can drift,
someone adds an action and forgets the manifest, or removes one and leaves a
stale entry.

**Options considered.**
1. Treat the manifest as documentation, trusted as written.
2. Compare the manifest's declared `actions` against the registry's actual
   `BY_ID` keys at startup, and refuse to start on any disagreement.

**Decision.** Option 2. `connector.py::load_manifest` raises
`ConfigurationError` naming both sets, sorted, the moment they disagree.

**Trade-offs accepted.** None material: this check runs once, at startup,
against small sets.

**Consequences.** A manifest read by someone deciding whether to trust this
connector, exactly the audience Definition of Done item 1 has in mind,
cannot be quietly stale. The failure is loud and immediate, not discovered
by a caller invoking an action the manifest never mentioned.

### ADR-018: Deep-freeze at the response boundary

**Context.** `pydantic`'s `frozen=True` freezes a model's own attributes, not
the containers nested inside them: a caller could still mutate a dict or
list buried inside a "frozen" `ActionResult.data` payload. A shallow
immutability guarantee invites exactly the bug it was meant to prevent: a
caller mutates a cached response, and the next reader sees data that never
actually came from Salesforce.

**Options considered.**
1. Rely on `frozen=True` alone and document the shallow limit.
2. Recursively freeze every parsed response at the client boundary,
   mappings become `MappingProxyType`, lists become tuples, before it goes
   anywhere else in the connector.

**Decision.** Option 2 (`immutable.py::freeze`), applied in `client.py`
(every HTTP response body), `idempotency.py` (every ledger entry), and
`checkpoint.py` (every journal entry).

**Trade-offs accepted.** One recursive pass over every parsed response and
every idempotency/journal record: a real but small and one-time cost per
call.

**Consequences.** Strings and bytes are deliberately excluded from the
recursion (both satisfy `Sequence`, and iterating a string element-by-element
would silently turn `"Ada"` into a tuple of letters): a documented edge case
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
if edited carelessly: the file's own comments call this out ("Deliberately
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
uploading it to the app, and getting the signing math right, real
friction for a first-time setup, even though it is the right long-term
default.

**Options considered.**
1. Implement only JWT Bearer, simplest surface area, but a setup failure
   there has no fallback.
2. Also implement OAuth 2.0 Client Credentials: a consumer key and secret
   exchanged directly for a token, no certificate, no signing, as an
   explicitly secondary option.

**Decision.** Option 2 (`auth/client_credentials.py`). Both strategies share
one `AuthStrategy` protocol and produce the same `Token`, so which one is
configured changes nothing downstream of authentication.

**Trade-offs accepted.** Client Credentials transmits `SF_CLIENT_SECRET`
over the wire on every token exchange: a real secret in transit, which is
precisely why JWT Bearer remains the default and this is documented as the
fallback, not an equal alternative.

**Consequences.** `ClientCredentialsAuth.build_request` raises
`ConfigurationError` if `SF_CLIENT_SECRET` is unset, rather than silently
producing a malformed request: a deployer who half-configures the fallback
gets a clear failure naming the missing variable.

### ADR-021: Journal-based partial success for multi-step writes

**Context.** `create_opportunity` is, structurally, two writes: create the
Opportunity, then optionally link a Contact via
`OpportunityContactRole`. The second can fail after the first has already
taken effect. Reporting plain failure in that case would tempt a retrying
caller into creating a second Opportunity; reporting plain success would
hide that the link never happened.

**Options considered.**
1. Treat the whole operation as atomic from the caller's point of view,
   report success or failure only, collapsing the two outcomes.
2. Record each step as it completes (`checkpoint.py::Journal`), and report
   exactly which steps finished and which did not.

**Decision.** Option 2. `create_opportunity.py::_link_contact` catches a
`ConnectorError` from the role-creation call, logs it, and returns `False`
rather than propagating: the Opportunity's own creation is already
journaled and stands.

**Trade-offs accepted.** The output schema carries a three-state
`contact_linked` (`true` / `false` / absent) instead of a simple boolean,
which is one more state every caller must handle correctly.

**Consequences.** `contact_linked: false` is explicitly documented, in the
tool's own error/field guidance, as "a partial success: do not create the
opportunity again": the caller is told what to do, not just what happened.
The same `Journal` mechanism is designed to generalise to any future
multi-step write or resumable multi-page read (the module's docstring notes
the same idea covers an interrupted page walk resuming from its last
cursor), though no other action currently uses it.

### ADR-022: The server asks the client to ask a person, and falls back to a parameter

**Context.** The programme requires "explicit approval for consequential
writes" without specifying a mechanism. The MCP specification (draft, read
2026-08-07) describes one: elicitation, with a signed, time-limited,
request-bound state carried across the round trip
(`docs/research/09-mcp-spec-compliance.md` §5). It also states plainly that a
server must not send a request whose capability the client did not declare,
which means no single mechanism can cover every client.

**Options considered.**
1. An `approved: bool` parameter, declared in each write's own input schema,
   defaulting to `false`; a write arriving without it is refused with a
   message telling the caller how to proceed.
2. Elicitation: before executing a write, the server asks the client to put
   the question to a person and waits for the answer.
3. Both, chosen by what the client declared.

**Decision.** Option 3. `mcp_server.call_tool` runs every write through
`WriteApproval.granted` (`mcp_approval.py`) *before* the connector sees it.
If the client declared the `elicitation` capability, the SDK's
`elicit_with_validation` puts a single-boolean form to it, quoting the
action's title and the caller's own field values with `idempotency_key` and
`approved` left out, neither is the caller's intent, and neither helps a
person decide. Only `accept` with `confirm: true` proceeds. If the client
declared nothing, it is not asked, and the write falls through to option 1:
`Action._require_approval` refuses it and says how to proceed.

**An `approved: true` in the arguments does not skip the question.** It was
tempting to treat it as "already handled" and return early, and that would
have quietly reopened the exact hole this exists to close: a model can set
that flag as easily as a host can, and short-circuiting on it means the one
caller you most want to stop is the one who never gets asked. A client that
declared elicitation never needs to send it anyway, because the answer comes
back inside the same call. The flag's only job is the fallback path.

`ApprovalGate` is what makes the yes specific. A ticket is minted *before*
the question, against the action id and a SHA-256 digest of the arguments,
and re-derived and checked immediately before the write runs.

**Trade-offs accepted.** Two, both stated rather than hidden. First,
`elicit_with_validation` resolves the round trip inside the tool call, so
the ticket never actually leaves the process, its cross-call binding is
belt-and-braces here, and what earns its keep in this shape is the
time-to-live, which turns a dialog left open too long into a refusal. It is
kept rather than simplified away because the binding becomes load-bearing
the moment an answer arrives over a separate request. Second, a client that
declares elicitation may still answer however it likes; the specification
says clients SHOULD surface it to a person, not MUST. What the server
guarantees is that it asked, that it refused every non-answer, and that the
write it executed is the one it described in the question.

**Consequences.** Four different non-answers, `decline`, `cancel`, an
accepted form with the box unchecked, and content the SDK cannot validate,
all end the same way: nothing written, and a refusal that tells the model to
report it rather than retry. That last case matters more than it looks. The
SDK *raises* on malformed accepted content, and an exception escaping into a
tool result reads as "something went wrong", which is exactly the shape a
model retries. Caught and turned into a plain refusal, it does not.
`tests/unit/test_mcp_approval.py` covers all sixteen paths, including the
two ends of the wiring: that a declined write never reaches `execute`, and
that an accepted one arrives there already marked approved.

### ADR-023: The account comes back as an id, not a name

**Context.** `search_contact` returns `account_id`: the Salesforce id of the
account a contact belongs to. A name would obviously read better in a
sentence a model composes for a user. Salesforce exposes it as a relationship
field, `Account.Name`, in the `fields` list sent to `parameterizedSearch`.

**Options considered.**
1. Return `account_id` only.
2. Also request `Account.Name` and return an `account_name` beside it.
3. Declare `account_name` in the output schema and populate it later.

**Decision.** Option 1. Whether `parameterizedSearch` accepts a relationship
field in its `fields` list is exactly the kind of claim this project refuses
to make from general knowledge, and there is no org to check it against. An
unverified field would either come back empty or fail the whole search, and
the second is a real cost paid for a cosmetic gain.

Option 3 was in fact how this stood at one point, and it was the worse of the
three: a field a schema promises and the data never fills teaches a model to
expect a value, and a model that reads `null` where a name should be has no
way to tell "this contact has no account" from "this connector never asked".
A schema is a promise, and an unkept one is worse than a smaller promise.

**Trade-offs accepted.** A caller that wants the account's name must look it
up, and this connector offers no action that does, so in practice it shows
an id or says nothing. That is a real loss in readability, taken knowingly.

**Consequences.** `_FIELDS` in `actions/search_contact.py` and
`ContactSummary` in `schemas/search_contact.py` list the same six fields, and
`_as_summary` populates every one. Adding the name later is one line in each
plus a live check that Salesforce honours it.

### ADR-024: Examples live on the spec, so all three surfaces show the same ones

**Context.** Definition of Done item 4 asks every action for "typed JSON
Schema inputs, outputs, and examples". Examples could be written directly
into the tool description, into `openapi.yaml`, and into this README, three
places, three chances to drift, and no way to notice when they do.

**Options considered.**
1. Prose examples written into each surface by hand.
2. One `examples` field on `ActionSpec`, rendered into every surface.
3. Examples only in the OpenAPI document, where the convention already exists.

**Decision.** Option 2. `ActionExample` lives in `contract.py`: the layer
that imports nothing, carrying a title, the arguments, and the result. From
there it reaches the MCP tool's input schema as the JSON Schema 2020-12
`examples` annotation, the OpenAPI operation as keyed request and response
examples, and the tool description a model actually reads, where the first
example is rendered inline.

**Trade-offs accepted.** The description grows by a few dozen tokens per
tool. That is the cheapest correction available for the mistakes a schema
alone invites: a field left out, a date in the wrong shape, an id from the
wrong object, and it is spent in the one place a model is certain to look.

**Consequences.** `tests/unit/test_examples.py` validates every example's
arguments against the action's own input model and every result against its
output model, so an example that stopped being true fails the build instead
of shipping. That test earned its place immediately: it caught
`activity_kind: "call"` where the enum requires `"Call"`, in an example
written minutes earlier.

### ADR-025: External Client Apps, because Salesforce closed Connected Apps

**Context.** This connector's auth is the OAuth 2.0 JWT Bearer flow, which
needs an app registration in the org holding the signing certificate. Every
version of this document said "Connected App", because that was the only
answer for a decade. In Winter '26 Salesforce disabled connected app creation
in all new orgs, and from Spring '26 will not re-enable it without a support
request. A new org refuses through the API as well as the UI:
*"You can't create a connected app. To enable connected app creation, contact
Salesforce Customer Support."*

This was discovered by trying it, not by reading a release note.

**Options considered.**
1. Ask Salesforce Support to re-enable connected apps for the org.
2. Use **External Client Apps**, the replacement, which support the same JWT
   bearer flow.
3. Fall back to the Client Credentials flow, which needs no certificate.

**Decision.** Option 2. Option 1 makes setup depend on a support ticket, which
is not a setup instruction anyone can follow. Option 3 would trade a
documented, certificate-signed flow for a shared secret in order to dodge a
provisioning problem: the wrong thing to give up.

Nothing in `src/` changed. The flow, the assertion, the token exchange, and
every scope are identical; only where the certificate is registered moved. That
the connector needed no change is the layering working: `auth/jwt_bearer.py`
knows about a signed assertion and a token endpoint, and never about which
Setup page issued the key.

**Trade-offs accepted.** An External Client App is three metadata components
rather than one, plus a fourth for the policy, and the setup instructions are
correspondingly longer. `connector.yaml` still says `auth_type:
oauth2_jwt_bearer`, which remains exactly true.

**Consequences.** QUICKSTART §3b now leads with the change and why, because a
reader following the old instructions reaches a dead end with an error that
sounds like a permissions problem. §3e records the CLI route, including three
things that cost real time to find: `consumerKey` must be omitted from the
deploy and retrieved afterwards; the pre-authorisation policy must be deployed
*after* that retrieve, because an app carrying it cannot be retrieved; and
assigning a user is not expressible in PermissionSet metadata at all: it takes
three records, and `SetupEntityAccess` lives on the standard API rather than
Tooling.

### ADR-026: What the first real org changed

**Context.** Everything here was built and verified against mocked HTTP,
because no org existed. Thirty tests were written to run the day one did. They
found four defects and one wrong assumption in the tests themselves.

**Decision.** All five fixed rather than documented. Each is recorded here with
what made it invisible, since that is the reusable part.

| What was wrong | Why no mocked test could see it |
|---|---|
| A replayed idempotency key reported `created: true` | Every mocked test calls each key once: the one case where the bug cannot appear |
| `changed_fields` returned Salesforce's casing (`Title`) | The unit test asserted the provider's name confidently, so it agreed with the bug |
| A missing record was classified `invalid_input`, not `record_not_found` | `INVALID_CROSS_REFERENCE_KEY` matches `INVALID_*` by shape; only a real 404 shows the mismatch |
| A note invented `TaskSubtype: "Other"`, which the org rejects | It is a restricted picklist configured per org; a mock accepts anything |

**Trade-offs accepted.** The fourth is the one worth dwelling on.
[ADR-008](#adr-008-opportunity-stage-read-from-the-orgs-picklist-never-hardcoded)
argued that a per-org picklist must never be hard-coded, and that reasoning was
applied to sales stages and not carried across to activity kinds, where the
connector supplied its own default for a field the caller had not set. The
principle was right and its application was incomplete, which is a more common
failure than getting the principle wrong.

**Consequences.** The test suite's own bug is equally instructive: it
hard-coded stage `"Prospecting"`, which the org does not have. The connector
caught it and returned the six stages that are valid, ADR-008 working exactly
as designed, demonstrated from the wrong side. The fixture now reads a stage
from the org, because a test that hard-codes a picklist value is making the
assumption the connector refuses to make.

Two things nearly made the run meaningless and are worth naming. The skip
condition read `os.environ` while credentials live in `.env`, so the first live
run skipped all thirty tests and reported success: the worst way to fail. And
the production guard aborted outright, because a Developer Edition org
authenticates at `login.salesforce.com`: the same host as production with none
of the consequences. Both now ask the question the way the connector does.

### ADR-027: One generated OpenAPI file, not one file per action

**Context.** `openapi.yaml` is 1,155 lines for five actions, roughly 230 each.
At twenty actions it would be 4,600, and across the ~90 Salesforce REST
endpoints ADR-002 catalogues it would be enormous. Large specifications are
commonly split into a file per resource, joined by `$ref`.

**Options considered.**
1. One document, generated whole.
2. A file per action, joined by external `$ref`, bundled before publishing.
3. One document now, split when it becomes uncomfortable.

**Decision.** Option 1, because the premise behind splitting does not hold
here. A file is split when a person has to work inside it, and nobody works
inside this one: it is generated by `openapi.py` from the same `ActionSpec`
objects the MCP tools are built from, and a test regenerates it and fails if
the committed copy has drifted. **The source is already one file per action:**
`schemas/search_contact.py`, `schemas/create_contact.py`, and the rest, each
around 200 lines. Adding a sixth action means adding a sixth schema file; the
YAML grows on its own and nobody reads the diff.

Splitting a build artefact because it is long is the same instinct as
splitting a compiled binary.

**Trade-offs accepted.** The honest cost is browsing. A four-thousand-line
YAML on a web interface is unpleasant to scroll, and a reviewer wanting to see
one action's contract has to search rather than open a file. That is real, and
it is smaller than what option 2 costs: external `$ref` is where OpenAPI
tooling most often disagrees. Swagger UI, Postman, and several generators
either fail on relative references or need a bundling step first, so option 2
means shipping a build pipeline to produce, in the end, exactly the single
file option 1 already produces.

There is precedent inside this repository for preferring the self-contained
form: MCP forbids requiring a consumer to dereference `$ref` over the network,
which is why `schema_of` inlines references for the tool schemas. Making the
HTTP surface less self-contained than the MCP one would be inconsistent.

**Consequences.** If the browsing cost ever outweighs this, splitting is a
rendering change rather than a redesign, `openapi.py::build` already assembles
the document from `registry.descriptors()`, so emitting one file per action is
a loop and a `$ref`, not a restructuring. The decision is cheap to reverse,
which is part of why it is safe to defer.
