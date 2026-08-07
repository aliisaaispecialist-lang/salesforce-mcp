# Open Questions — to settle before the plan is final

Status: OPEN. Nothing here is decided. We discuss this list, then the plan is agreed, then code.
Last updated: 2026-08-06

---

## A. Blocking — a schema or a file cannot be written until these are answered

### A1. `add_activity_note` — which Salesforce object?
The action name is ambiguous and the program gives no definition.

| Option | Object | Cost | Risk |
|---|---|---|---|
| **A (my recommendation)** | `Task` | one call | none — "activity" in Salesforce means Task/Event |
| B | `Note` (classic) | one call | disabled in many modern orgs |
| C | `ContentNote` | two calls + base64 body | Lightning-only, more moving parts |

Blocks: `src/actions/add_activity_note.py`, its schema, its fixtures.

### A2. Is the multi-provider LLM client in scope?
Your original brief asked for a client accepting any LLM provider's API. The program's Definition of Done never mentions an LLM client — it wants the connector core, five actions, OpenAPI, thin MCP adapter. My plan followed the DoD and dropped it. Options: build it anyway as an extra (agent 1's research is done), park it until the connector ships, or drop it. Earns no rubric points either way.

### A3. Project name and location on disk
Currently everything sits in `C:\Users\Admin\salesforce-mcp\`. The program template says `connector-name/`, and this is a *connector* whose MCP server is one thin adapter — so `salesforce-connector` reads more accurately. Rename, or keep?

---

## B. External access — we cannot answer these ourselves

### B1. Salesforce org
DoD item 9 requires "one real sandbox test where access permits." Needs a Developer Edition org plus a Connected App with a certificate for JWT Bearer. Not provisioned. Everything else can be built without it; this one item cannot. Who provisions, and when?

### B2. `/console` — gated
Requires an `@doo.ooo` sign-in, which the research agent correctly did not attempt. It is the "Validation console — run validations and review results." Since the brief says the connector must be "ready to validate," this page likely defines what validation actually checks. Worth you logging in and reporting back — it may contain acceptance criteria we are currently guessing at.

### B3. `/presentation` slides 2–14 — unread
A 14-slide kickoff deck; only slide 1 was retrievable (the browser extension was disconnected during research). Slides 2–14 may contain requirements not on the homepage. Re-runnable if the Chrome extension is reconnected.

---

## C. Product decisions — I have a default, confirm or override

| # | Question | My default | Why it matters |
|---|---|---|---|
| C1 | Transport: stdio only, or stdio + streamable HTTP? | both | The submission form has an optional "Deployed MCP URL" field — that needs HTTP plus hosting. Do you want to submit one? |
| C2 | `search_contact` — Contact only, or also Lead/Account? | Contact only | Action is named `search_contact`; broader search is scope creep, but a grader may expect useful breadth |
| C3 | Duplicate handling on `create_contact` | `allow_duplicate` defaults to `false`, error lists matched IDs | Safer default; costs an extra round trip when duplicate rules fire |
| C4 | Idempotency durability | process-scoped in-memory cache | Durable would need storage we have no requirement for. Documented honestly either way |
| C5 | Write approval mechanism | MCP annotations + explicit `confirm` param on destructive actions | Program says "explicit approval for consequential writes" but does not say how |
| C6 | Salesforce API version | pin `v67.0` | Pinning is safer than floating; needs a documented bump policy |
| C7 | Python version | 3.12 | Matches the toolchain config in the standard |
| C8 | Licence | Apache-2.0 | No licensing rule found anywhere on the program site |
| C9 | Git repo — init here, and when to tag `v1.0.0`? | init now, tag at final handoff | Submission is a ZIP ≤50MB, but DoD 12 requires a tagged release |
| C10 | "Demonstration and technical explanation" (5%) | runnable `examples/` + README rationale | Unclear whether they expect a recorded video or live walkthrough |

---

## D. Deferred by your instruction — recorded so they are not lost

- **D1. Endpoint expansion.** You said: build the five perfectly, then add more "based on the endpoint and their urgency." The ~90-endpoint survey is in `research/03-salesforce-api-map.md`. When we revisit, we choose which and in what order.
- **D2. Deadline.** You said ignore it. Building to the milestone sequence instead.
- **D3. Language deviation.** Python is decided. ADR-001 will document that no language was mandated. Residual risk: a grader may still expect TypeScript to match the template. Accepted knowingly.

---

## E. Answered — kept for the record

| Question | Answer | When |
|---|---|---|
| Language | Python | 2026-08-06 |
| Scope | The five assigned actions, perfected; expand later | 2026-08-06 |
| Deadline | Disregard | 2026-08-06 |
| Username-password OAuth | Excluded — Salesforce retiring it from 29 Aug 2026 | research |
| SSE transport | Excluded — superseded by streamable HTTP | research |
