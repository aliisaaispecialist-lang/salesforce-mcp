# Security

## What this connector is trusted with

This connector holds one Salesforce integration user's credentials — a
private key or a client secret, read once from the environment at startup —
and acts as that user for five actions: searching contacts, creating and
updating contacts, creating opportunities, and logging activity notes. It
does not hold a caller's credentials; it accepts none. Every call it makes
runs as the one configured user, so that user's Salesforce profile is the
real boundary on what any caller can reach through this connector, no matter
what the caller asks for.

It is launched as a local subprocess speaking JSON-RPC over stdio, per the
MCP specification's own recommendation for locally-run servers. It has no
open port, no deployed endpoint, and accepts no bearer token from a client —
the specification's warning about accepting tokens "not explicitly issued
for the MCP server" does not apply here, because this connector accepts no
caller tokens of any kind.

The record data it reads back — contact names, emails, phone numbers, notes,
opportunity fields — was written by other people and is not trustworthy. It
is treated as data everywhere in this codebase, never as instruction.

## Threat model

"Tested" means exercised by a `pytest` test that fails if the control
regresses. A control that is enforced by a pre-commit hook or a CI job, but
not exercised by `pytest`, is marked accordingly rather than counted as
tested — the distinction matters because only a pytest failure blocks a
merge on this machine before code review.

| # | Threat | Control | Where it lives | Tested? |
|---|--------|---------|-----------------|---------|
| 1 | A search term is parsed as SOQL/SOSL query syntax (query injection) | The search action calls `parameterizedSearch`, which takes the search term as a JSON value, never as text assembled into a query. There is no query string for a term to escape out of. | `actions/search_contact.py` | Yes — `tests/security/test_injection_and_leaks.py::TestQueryInjection`, 6 parametrized injection payloads (SOQL, SOSL, and SQL-shaped strings) plus a check that no `/query` or `/search` endpoint is ever called |
| 2 | A record-id argument is used to reach an object it was never meant to (e.g. a path-traversal-shaped id pointed at a `User` record) | `add_activity_note` accepts only ids whose first three characters are the Contact prefix (`003`) or the Opportunity prefix (`006`); anything else is refused before a request is built | `actions/add_activity_note.py::_attachment` | Yes — `TestQueryInjection::test_a_record_id_that_is_not_one_is_refused_before_a_request` |
| 3 | The model reads record text (a Contact's notes, an Opportunity's description) as an instruction rather than as data | Every tool result is wrapped in `<salesforce_record_data-NONCE>` … `</salesforce_record_data-NONCE>` before it reaches the model | `mcp_translate.py::wrapped` | Yes — `TestPromptInjectionThroughRecords::test_instructions_inside_a_record_arrive_fenced_as_data` |
| 4 | A record forges the fence's own closing tag to escape it and have text after it read as though it came from the connector | The nonce is generated fresh per response with `secrets.token_hex`; a record's author cannot know the value needed to close the fence early, because the fence markers are prefixes, not complete strings, until the nonce is appended | `mcp_translate.py` (`UNTRUSTED_OPEN`/`UNTRUSTED_CLOSE`, `wrapped`) | Yes — `test_a_record_cannot_close_the_fence_and_speak_outside_it`, `test_two_responses_do_not_share_a_fence`. **This was a real vulnerability, not a hypothetical one**: the fence originally used a fixed marker with no nonce, and writing this exact test against that implementation is what found it. Fixed before release, in commit `2dcc0d4` — see `CHANGELOG.md` |
| 5 | A credential (access token, assertion, private key, client secret) reaches a log line | `censor_secrets`, a structlog processor, masks by key name at any depth of a dict, and by regex over string values (bearer tokens, PEM private-key blocks), before a line is rendered | `observability.py` | Yes, with a known gap — see "What this deliberately does not defend against" below. `tests/security/test_injection_and_leaks.py::TestNothingLeaks`, plus `tests/unit/test_observability.py` |
| 6 | A credential reaches a printed, `repr`'d, or logged `Settings` object, or a traceback | Secrets are typed `SecretStr`; printing or logging `Settings` shows a mask, not the value | `config.py` | Yes — `tests/unit/test_config.py::TestSecretsAreNotPrintable`, `test_injection_and_leaks.py::test_settings_cannot_be_printed_into_a_log` |
| 7 | A Salesforce error response leaks a stack trace or an oversized body back into the model's context | `to_connector_error` caps the reported reason to 300 characters and only ever forwards the message and code Salesforce reported, never a raw response body or a Python traceback | `errors/mapping.py` | Yes — `test_a_salesforce_failure_never_carries_a_stack_trace_to_the_model`, `test_a_provider_message_is_capped_so_a_body_cannot_be_dumped` |
| 8 | The connector is pointed at a production org by accident (typo, careless config) instead of the sandbox it is built and tested against | `Settings` refuses to construct if `login_url` is the production host unless `SF_ALLOW_PRODUCTION=true` is set explicitly | `config.py::_production_needs_saying_so` | Yes — `tests/unit/test_config.py::TestProductionGuard`, 4 tests including a trailing-slash bypass attempt |
| 9 | A consequential write (create, update) executes without a human ever approving it | Every write's `ActionSpec` declares `requires_approval=True`; `Action._require_approval` refuses to run the write unless the request's `approved` field is true, before the client is ever asked to send anything | `actions/action.py::_require_approval`, `schemas/*.py` | Yes — `test_a_write_without_approval_reaches_no_endpoint` |
| 10 | A tampered, replayed, or mismatched approval is honoured (approving one call with the token issued for another, an expired token, a forged token) | `ApprovalGate` (itsdangerous) signs a token binding an action id and a SHA-256 digest of its arguments, with a time-to-live; every failure mode — bad signature, expired, wrong action, changed arguments — is rejected identically | `approval.py` | Yes, at the connector's Python API — `tests/unit/test_connector.py::TestApproval` (7 tests: exact-call match, different arguments, different action, tampered token, expired token, token from another process's key, argument-order independence of the digest). **Not wired into the shipped MCP server** — see limitations below |
| 11 | A write retried after a timeout creates a duplicate record | `IdempotencyLedger` remembers, for the life of the process, what each caller-supplied key has already achieved; a repeated key returns the original result instead of writing again | `idempotency.py`, `actions/action.py::_already_done` | Yes — `test_a_repeated_key_writes_once_however_many_times_it_is_called`, `tests/unit/test_durability.py::TestTheLedger` |
| 12 | A write action ships without ever requiring an idempotency key, making the retry-duplicate problem unfixable by any caller | A write cannot be registered, described, or called unless `idempotency_key` is in its input schema's required fields — this is a structural property of every `ActionSpec` marked as a write, not a convention | `schemas/envelope.py`, `actions/registry.py` | Yes — `test_a_write_cannot_be_declared_without_demanding_a_key` |
| 13 | One caller (a model in a loop) exhausts the org's daily API allowance, breaking every other integration on that org | `CallBudget`, a leaky-bucket limiter shared across all five actions, refuses a call over budget rather than queuing it, and states how long to wait | `ratelimit.py`, `connector.py` (one budget per connector instance) | Yes — `tests/unit/test_connector.py::TestTheCallBudget`, 4 tests |
| 14 | A cached or returned result is mutated by a caller, and a later reader trusts the tampered copy | `freeze()` turns every response into a read-only structure recursively — dicts become `MappingProxyType`, lists become tuples — before it is handed back | `immutable.py` | Yes — `tests/unit/test_durability.py::TestFreezing`, 5 tests, plus ledger- and journal-entry immutability tests |
| 15 | A future change lets an action or schema module open its own HTTP connection, bypassing the timeouts, retries, and error mapping that `client.py` owns, or lets a module outside the adapter speak the MCP SDK directly | Import-linter contracts forbid `httpx` outside `client.py`, forbid the `mcp` package outside `mcp_server.py`/`mcp_translate.py`, and forbid the contract layer from importing any vendor library at all | `.importlinter` | Enforced, not pytest-tested — `lint-imports` runs as a CI step and a pre-commit hook, and fails the build on any violation, but no `pytest` test exercises it |
| 16 | A secret (private key, client secret, `.env` file) is committed to source or to Git history | `.gitignore` and `.dockerignore` exclude `.env*`, `*.pem`, `*.key`, `*.p12`, `secrets/`, and raw fixture recordings; pre-commit runs `detect-private-key` and `gitleaks` before a commit exists; a dedicated CI job runs `gitleaks` over the full history (`fetch-depth: 0`) | `.gitignore`, `.dockerignore`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml` | Enforced, not pytest-tested. A manual `git log -p` search of this repository's history for PEM headers and `SF_PRIVATE_KEY=`/`SF_CLIENT_SECRET=` assignments found only test-fixture placeholder values (e.g. `MIIEvQIBADxx`), never a real key. The CI gitleaks job has not yet run, because this repository has no remote to push to yet |
| 17 | A Salesforce credential is baked into the Docker image layer | A multi-stage build copies only `src/`, `mcp/`, and `connector.yaml` into the final image; `.dockerignore` excludes `.env*`, `*.pem`, `*.key`, and `.git`; the process runs as a non-root user (uid 10001) | `Dockerfile`, `.dockerignore` | No dedicated test. CI's `image` job builds the image and confirms the server starts and exits cleanly on stdin EOF, but does not scan the built layers for secrets |
| 18 | The connector's OAuth scope grants more than its five actions need | `connector.yaml` declares only `api` (REST access) and `refresh_token` (session renewal) — nothing broader | `connector.yaml` | Partially — `tests/unit/test_connector.py::test_it_asks_for_no_more_scope_than_the_actions_need` is a regression pin asserting the declared scope set stays exactly `{api, refresh_token}`. Whether the Salesforce Connected App itself grants only that scope is configured on the Salesforce side and cannot be verified from this repository |

## What this deliberately does not defend against

- **Idempotency memory does not survive a restart.** The ledger in
  `idempotency.py` lives in process memory. If the container is restarted
  between a write reaching Salesforce and the response reaching this
  connector, the record of it is gone, and a caller that retries with the
  same key can create a duplicate. Durable, provider-side deduplication
  needs an External Id field on the target object so Salesforce itself
  rejects the second write; that requires schema access to the org that
  this project does not have. `connector.yaml`'s `risks` section states
  this as a declared, not hidden, limitation.
- **Approval is not wired into the shipped MCP server.** `ApprovalGate`'s
  signed, time-limited, call-bound token is implemented and unit-tested
  (`tests/unit/test_connector.py::TestApproval`), and `connector.py` exposes
  `approval_for`/`approves` to mint and check it. But `mcp_server.py` never
  calls either — the bundled stdio server reads a plain `approved: true`
  out of the tool call's own arguments (`_as_request` in `mcp_server.py`).
  This connector cannot distinguish a human who actually confirmed a write
  from a model that decided to set the boolean itself. The specification's
  `InputRequiredResult`/elicitation flow, which would let a client surface
  the confirmation to an actual person and carry the signed state through
  that round trip, is not implemented; `approved` exists as the fallback
  path the specification describes for clients without that capability, but
  it is currently the *only* path.
- **Two nesting gaps in the log censor**, found while writing this document
  and left unfixed per the instructions for this task (only `SECURITY.md`,
  `LICENSE`, and `CHANGELOG.md` were to be written):
  - `_censor_value` in `observability.py` recurses into `dict` values but
    not into `list`/`tuple` values. A secret nested inside a list of dicts —
    for example `{"records": [{"access_token": "..."}]}` — passes through
    unmasked. Every existing test nests secrets inside dicts only.
  - The bearer-token pattern (`(?i)(bearer\s+)[\w.\-]+`) stops matching at
    the first character outside `[\w.\-]`. A Salesforce session id contains
    `!` (for example `00D5g000004abc!AQEAQPgtNhpFCVwt`), so the mask covers
    only the prefix up to and including the `!`, and the suffix after it is
    still written to the log. The existing test
    (`test_a_provider_error_echoing_a_token_is_masked_before_it_is_logged`)
    passes because it checks that the *complete original token string* is
    not a contiguous substring of the output, which remains true even
    though part of the token is visible.
  See `CHANGELOG.md` for both, listed as known limitations rather than
  silently left out.
- **A capped provider error is not fenced.** `refuse()` in `mcp_translate.py`
  returns error text directly, without the untrusted-content fence that
  wraps successful results. Salesforce error messages can echo submitted
  field values, and while the 300-character cap bounds how much reaches the
  model, that text is not marked as data the way a successful result's
  payload is. No test asserts either way; this is a limit, not a control.
- **No live sandbox has been exercised.** Every test in this repository,
  including the security suite, runs against `respx`-mocked HTTP. The
  `learning` and `integration` pytest markers exist for tests that need a
  real Salesforce org and are excluded by default
  (`pyproject.toml`: `addopts = "-m 'not learning and not integration'"`),
  because no sandbox has been provisioned for this project yet. Nothing here
  has been proven against Salesforce's actual behaviour, only against the
  connector's model of it.
- **Tool annotations are hints, not guarantees.** `mcp_translate.py`
  publishes `read_only_hint`, `destructive_hint`, and `idempotent_hint`
  honestly, derived from each action's own declared kind rather than
  written by hand. But the specification itself is explicit that these are
  hints a host is not obliged to honour, and that "clients should never make
  tool use decisions based on ToolAnnotations received from untrusted
  servers." This connector cannot make an MCP host respect them.
- **The profile of the integration user is the real ceiling, and it is
  outside this repository.** Every action runs as one Salesforce user.
  Whatever that user's profile and field-level security permit is what any
  caller of this connector can ultimately reach or change, regardless of
  what the five actions were designed to restrict a caller to.
- **Network egress is not sandboxed by this connector.** There is no
  container-level network policy, egress allowlist, or filesystem isolation
  configured here; the Dockerfile runs the process as a non-root user with
  no declared privileges beyond what reading the environment and opening
  outbound HTTPS require, but nothing enforces that at the container-runtime
  level. Whoever deploys this connector is responsible for that layer.
- **No kill switch.** There is no operational mechanism in this repository
  to stop an in-flight or misbehaving process short of terminating the
  container. Rate limiting bounds the damage per minute; it does not stop it
  outright.

## Reporting a vulnerability

This is a single-builder submission for the Builders League connector
programme with no dedicated security tracker, mailing list, or on-call
rotation. If you find a problem, email
[20144674ali@gmail.com](mailto:20144674ali@gmail.com) with what you found and
how to reproduce it. Please do not open a public issue with exploit details
before there has been a chance to look at it.
