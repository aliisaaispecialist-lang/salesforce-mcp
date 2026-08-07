# Research Agent 8 — Presentation Reader — Findings

Source: https://built2.doo.ooo/presentation ("Kickoff Presentation — Builders League")

## 1. ACCESS METHOD

**Route 1 (JS bundle extraction) worked completely — no browser needed.**

Steps taken:
1. `curl`'d the raw HTML of `/presentation`. It is a Next.js (App Router, RSC) page. The prerendered HTML only paints slide 1 (client-side state `useState(0)`), matching what the prior agent found.
2. Extracted all `/_next/static/chunks/*.js` URLs referenced in the HTML's `<script>`/RSC flight payload. The RSC flight data showed the `PresentationDeck` component (webpack module id `79387`) is loaded from chunk `21zhh5hv6l164.js` (plus shared vendor chunks).
3. Downloaded `chunk_21zhh5hv6l164.js` directly (`https://built2.doo.ooo/_next/static/chunks/21zhh5hv6l164.js`, ~58.8KB) and grepped it for `"Build one connector"` — found the entire `PresentationDeck` component source, including the full `useMemo` array of all 14 slide JSX trees, verbatim as literal strings (this is the actual, un-obfuscated slide content — titles, body copy, bullet lists, checklists, table/tree text — because it's JSX with string children, not a minified data blob).
4. The same chunk also contains the underlying data modules the deck imports: `BUILD_STEPS`, `DEFINITION_OF_DONE` (module `O`, i.e. `46985`), and `CONNECTOR_MISSIONS` / `CONNECTOR_BY_ID` (module `P`, i.e. `56674`), including the full Salesforce mission record and a `PROGRAM_ASSIGNMENTS` array confirming `{connectorId:"salesforce", builder:"Ali Isa"}`.

**Verification of completeness:** The slide array has exactly 14 entries, each with a unique React `key`: `intro, overview, ctrl, cnct, wzrd, deliverable, architecture, path, mission, contract, repository, milestones, validation, done`. The deck's own footer counter renders as `String(index+1).padStart(2,"0") + " / " + String(T.length).padStart(2,"0")` where `T.length` is the array length (14) — confirming the array itself is the full, authoritative slide count and I have all of it, sourced directly from the component's source code rather than by stepping through the UI. No slide is a placeholder or lazy-loaded stub; all text is present as literal strings in this one chunk.

Routes 2 (WebFetch/deep-link URLs) and 3 (browser automation) were **not needed** and were not attempted — Route 1 yielded 100% of the content with page-source fidelity (arguably more reliable than reading rendered text, since nothing can be visually truncated or missed by a scroll).

## 2. SLIDE-BY-SLIDE (verbatim)

### Slide 1 — "intro" (eyebrow: "Builders League · Cohort 01")
- Badge: "MK Lab × DOO"
- H1: "Build one connector." / "Ship it clean." (second line styled as accent)
- Subtitle: "One reusable core, five reliable actions, and a thin MCP adapter that is ready to validate."
- DOO logo linking to https://try.doo.ooo

### Slide 2 — "overview" (eyebrow: "Why this matters", title: "Connectors power DOO's flagship products")
- Card "Why we are building them": "DOO's products need safe, reliable access to the systems where customers already work — from Google and Salesforce to Slack, Stripe, and beyond."
  - Callout: "Every connector turns a provider API into consistent, typed actions that any DOO product can trust."
- Card "What we are building toward" → "One action layer. Three product experiences."
  - CTRL: "Build agents with approved tools"
  - CNCT: "Take action inside conversations"
  - WZRD: "Trigger actions from experiences"
  - Callout: "Build each connector once → reuse it everywhere across DOO."

### Slide 3 — "ctrl" (DOO product 01)
- Product: CTRL, label "Agent builder"
- Description: "Teams give agents approved connector tools, configure how they behave, and assemble them into reliable workflows."
- Outcomes: "Choose connector actions", "Set safe approval rules", "Build reusable agent workflows"
- Media: YouTube embed (video id `22xZAIo2ZiA`)

### Slide 4 — "cnct" (DOO product 02)
- Product: CNCT, label "Customer OS"
- Description: "Chatbots and agents understand the customer, retrieve context, and take approved actions inside connected systems."
- Outcomes: "Retrieve customer context", "Create updates and follow-ups", "Keep every conversation connected"
- Media: video `/media/cnct-demo.mp4`

### Slide 5 — "wzrd" (DOO product 03)
- Product: WZRD, label "Interactive experience maker"
- Description: "Teams create guided, personalized experiences that collect input and trigger actions across connected apps."
- Outcomes: "Capture structured input", "Personalize every step", "Trigger actions in connected apps"
- Media: image `/media/wzrd-home.png`

### Slide 6 — "deliverable" (eyebrow: "Your mission", title: "What you are building")
Four cards:
- 01 "Independent package" — "Provider logic stays reusable outside MCP."
- 02 "Five typed actions" — "Exact IDs, JSON Schema, examples, and safe writes."
- 03 "Thin MCP adapter" — "Expose the same core actions as MCP tools."
- 04 "Production handoff" — "Tests, fixtures, OpenAPI, docs, and a deployed endpoint."
Footer line: **"Extra actions are welcome after the assigned five work."**

### Slide 7 — "architecture" (eyebrow: "Architecture", title: "One core. Multiple surfaces.")
Four boxes, left to right: "Provider API" ("Google, Stripe, Slack…") → "Connector core" ("Auth, actions, schemas, errors") → "Thin MCP" ("Tool discovery and execution") → "DOO products" ("WZRD, CNCT, future clients")
Callout: **"Rule: no provider calls or duplicated business logic inside the MCP adapter."**

### Slide 8 — "path" (eyebrow: "The build path", title: "Five steps from research to validation")
`BUILD_STEPS` (5 steps, verbatim):
1. "Understand the provider" — "Confirm the current API, test account, authentication flow, minimum scopes, rate limits, and access blockers before coding."
2. "Design the five actions" — "Use the exact assigned action IDs. Define JSON Schema inputs, outputs, examples, and approval requirements for writes."
3. "Build one reusable core" — "Implement testConnection, listActions, and execute once. Keep provider, auth, schemas, and normalized errors isolated."
4. "Expose a thin MCP adapter" — "Map the same connector actions to MCP tools. Do not duplicate provider calls or business logic inside the MCP server."
5. "Test, deploy, and validate" — "Run unit and fixture tests, prove one sandbox flow, deploy an HTTPS MCP endpoint, and submit it to the validation console."

### Slide 9 — "mission" (eyebrow: "Find your work", title: "Every mission has five required actions")
Interactive connector picker (defaults to Google Sheets in the deck's own component state, but the underlying data for **Salesforce** — Ali's assignment — is, verbatim from `CONNECTOR_MISSIONS`:
```
{
  id: "salesforce",
  name: "Salesforce",
  difficulty: "Advanced",
  category: "Enterprise CRM",
  requiredActions: [
    "salesforce.search_contact",
    "salesforce.create_contact",
    "salesforce.update_contact",
    "salesforce.create_opportunity",
    "salesforce.add_activity_note"
  ]
}
```
This matches the homepage's "Ali's 5 required actions" — confirmed, not contradicted, and now double-sourced from the app's own data module.

Also recovered — the full `PROGRAM_ASSIGNMENTS` roster confirms: `{connectorId:"salesforce", builder:"Ali Isa"}`.

### Slide 10 — "contract" (eyebrow: "Shared standard", title: "Every connector speaks the same contract")
Left: a code block (`<pre>`), verbatim:
```ts
interface DooConnector {
  manifest: ConnectorManifest;
  testConnection(credentials): Promise<ConnectionTestResult>;
  listActions(): ConnectorAction[];
  execute(request): Promise<ConnectorExecutionResult>;
}
```
Right: checklist —
"JSON Schema 2020-12", "OpenAPI 3.1.x", "Normalized errors + request IDs", "Pagination + rate-limit metadata", "Approval metadata for writes", "Least privilege and no leaked secrets"

### Slide 11 — "repository" (eyebrow: "Repository", title: "Keep the handoff predictable")
Left: `REPOSITORY_STRUCTURE` tree, verbatim:
```
connector-name/
├── connector.yaml
├── src/
│   ├── connector.ts
│   ├── client.ts
│   ├── auth/
│   ├── actions/
│   ├── schemas/
│   └── errors/
├── mcp/server.ts
├── tests/
├── fixtures/
├── examples/
├── openapi.yaml
├── .env.example
└── README.md
```
Right:
- "Yes, use an `.env`."
- "Commit only `.env.example`. Never commit live credentials, tokens, customer data, or secret-bearing screenshots."
- Callout (bold lead-in): **"Production deployment is required for validation:"** "expose a stable HTTPS MCP URL and keep the credential vault outside the connector."

### Slide 12 — "milestones" (eyebrow: "Milestones", title: "Build through visible gates")
`MILESTONES` (4), verbatim:
1. **Kickoff** — output: "API/auth research, manifest, five action schemas, repository plan, access risks" — gate: "Mission accepted"
2. **First checkpoint** — output: "Repository, testConnection, mocks, one read action, provider access confirmed or escalated" — gate: "Build continues"
3. **Week 1 demo** — output: "Working auth, two real actions, normalized errors, tests, initial MCP tools" — gate: "Integration candidate"
4. **Final handoff** — output: "All actions, fixtures, OpenAPI, thin MCP server, demo, limitations, versioned release" — gate: "v1.0.0 ready"

### Slide 13 — "validation" (eyebrow: "Final handoff", title: "Package it. Submit it. Prove it.")
Three steps:
- "Upload codebase" — "Submit the complete connector repository as a ZIP."
- "Add endpoint" — "Include the deployed HTTPS MCP URL when it is ready."
- "Keep confirmation" — "Save the submission ID and upload newer versions anytime."
Button: "Open submission page" → links to `/submit`.

### Slide 14 — "done" (eyebrow: "Before handoff", title: "Ready means all of this is true")
Shows `DEFINITION_OF_DONE.slice(0,10)` — i.e., **only the first 10 of the 12 items** are rendered on this slide (grid layout choice, not a data change). Full `DEFINITION_OF_DONE` array (12 items) recovered from the data module, verbatim:
1. "Manifest identifies provider, version, auth type, scopes, actions, risks, and capabilities."
2. "testConnection verifies credentials without creating side effects."
3. "All five assigned actions work through the shared execute interface."
4. "Every action has typed JSON Schema inputs, outputs, and examples."
5. "Errors are normalized and include request IDs plus retry classification."
6. "Pagination and rate-limit metadata are returned where relevant."
7. "Write actions document approval, idempotency, duplicate, and retry behavior."
8. "No secrets appear in code, Git history, logs, fixtures, screenshots, or recordings."
9. "Unit and fixture tests pass, with one real sandbox test where access permits."
10. "OpenAPI and the thin MCP adapter reuse the same connector core."
11. "Known limitations and access blockers are clearly listed." *(NOT shown on slide 14 due to `.slice(0,10)`, but present in code — this is the "12th item on the homepage" territory)*
12. "The release is tagged v1.0.0 with concise handoff notes." *(also not shown on slide 14 for the same reason)*
Footer: **"Research first. Build once. Explain everything."**

## 3. NEW REQUIREMENTS NOT ON THE HOMEPAGE

- **"Extra actions are welcome after the assigned five work."** (Slide 6) — explicit permission/invitation for scope beyond the 5 required actions, framed as optional/after-the-fact, not a requirement.
- **"Rule: no provider calls or duplicated business logic inside the MCP adapter."** (Slide 7) — stated as a hard architectural "Rule," more emphatic than the homepage's general "thin MCP adapter" phrasing, and repeated near-verbatim in Build Step 4 ("Do not duplicate provider calls or business logic inside the MCP server.") and in the DooConnector contract framing.
- **Milestone stage names/gates/outputs are more granular here** than what the homepage summary likely conveys as "4 named milestones" — the deck gives the exact gate name per stage (e.g., "Mission accepted," "Build continues," "Integration candidate," "v1.0.0 ready") plus a checklist of expected outputs per stage.
- **The `DooConnector` TypeScript interface itself** is new, concrete content not summarized on the homepage: `manifest`, `testConnection(credentials)`, `listActions()`, `execute(request)` as the four required interface members of "the shared connector core."

## 4. CONTRADICTIONS WITH THE HOMEPAGE (or internal tension within the deck)

**Most important finding — deployment requirement severity is inconsistent, and stronger/harder than the homepage implies:**

- Slide 11 ("repository"), bold callout: **"Production deployment is required for validation: expose a stable HTTPS MCP URL and keep the credential vault outside the connector."** — this states deployment is *required*, unconditionally.
- Slide 6 ("deliverable") lists "a deployed endpoint" as one of the four things under "Production handoff" you are building — again framed as required, not optional.
- Build Step 5 (Slide 8): "...deploy an HTTPS MCP endpoint, and submit it to the validation console." — also framed as a required step in the build path.
- **But** Slide 13 ("validation"), the actual submission-mechanics slide, says: "Add endpoint — Include the deployed HTTPS MCP URL **when it is ready**." That phrasing ("when it is ready") is optional/conditional language, not "required."

This is a direct tension inside the deck itself (repository slide says "required"; submission slide says "when it is ready"), and it conflicts with the task brief's characterization of the homepage's "optional Deployed MCP URL" field. **My recommendation: treat the deployed MCP URL as something you should strongly aim to have — the deck's dominant framing (3 of 4 mentions) is "required for validation" — but the actual submission form UI copy hedges with "when it is ready," implying the ZIP alone may be accepted at submission time with the endpoint added later ("upload newer versions anytime" — Slide 13).** Quote both sides if this goes into your build plan; do not silently pick one.

No other outright contradictions were found — everything else (5 actions, Definition of Done wording, milestones existing, repo structure, "least privilege / no committed secrets") is consistent with what the homepage is known to say.

## 5. ANSWERS TO OUR OPEN QUESTIONS

- **Which Salesforce object does "activity note" mean?** Not disambiguated anywhere in the deck. The action ID is exactly `salesforce.add_activity_note` (Slide 9 / `CONNECTOR_MISSIONS`) — no further schema, object name (Task vs. Note vs. custom object), or field mapping is given. **Still unknown** — you'll need to decide/research this yourself (Salesforce's own object model: Task, or the newer Note/ContentNote via Files, are the two most common candidates for "activity note" against a Contact/Opportunity).
- **Is an LLM client expected for the demo?** No mention anywhere in the deck of an LLM client, chat client, or specific agent harness being required for the "Week 1 demo" or "Final handoff" demo. The milestones only require "one sandbox flow" proven and MCP tools functioning. **Still unknown / not specified.**
- **Required MCP transport?** Never named explicitly (no "stdio," "SSE," "Streamable HTTP," or transport keyword appears anywhere in the deck's source). However, the repeated requirement for "a stable HTTPS MCP URL" / "deploy an HTTPS MCP endpoint" strongly implies the MCP server must be reachable over HTTP(S) as a network service, i.e., **not** a purely local stdio-only server. This is an inference from the deployment language, not a stated transport mandate.
- **Is a deployed URL expected?** Yes — see Section 4 above. Framed as "required for validation" in 3 places, but softened to "when it is ready" in the actual submission-page copy. Net: expected/strongly encouraged, mechanically possibly deferrable.
- **Demo format?** The deck describes deliverables/gates ("Week 1 demo" → "Working auth, two real actions, normalized errors, tests, initial MCP tools" as its content) but never specifies *how* the demo is delivered (live call, recorded video, screenshare, etc.). **Still unknown.**
- **Language mandate?** No sentence says "you must use TypeScript" in so many words. But the evidence is now much stronger than the homepage's mere `.ts` file extensions in the repo tree:
  - The repo tree (Slide 11) again shows `connector.ts`, `client.ts`, `mcp/server.ts`.
  - Slide 10's "shared contract every connector speaks" is presented as a literal **TypeScript `interface` block** (`interface DooConnector { manifest: ConnectorManifest; testConnection(credentials): Promise<ConnectionTestResult>; listActions(): ConnectorAction[]; execute(request): Promise<ConnectorExecutionResult>; }`), described as the standard contract, not just an example.
  - **Flagging loudly per instructions: while no slide contains the literal words "you must use TypeScript" or "language: TypeScript," the deck's own definition of "the shared contract every connector speaks" is written in TypeScript syntax, and every filename shown throughout the deck uses `.ts`. Treat this as a very strong de facto mandate for TypeScript** even though it is technically never asserted as a rule in prose.

## 6. STILL UNKNOWN

- Any literal calendar date or deadline (day/month) for kickoff, checkpoints, demo, or final handoff — none appear anywhere in the deck's data (checked for "august," "september," "2026," "deadline," "due date" — zero hits). Only relative/named stage labels exist ("Kickoff," "First checkpoint," "Week 1 demo," "Final handoff").
- Judging criteria / weights — no keyword hits for "judg," "criteria," or "weight" anywhere in the deck's source; the 8 weighted judging criteria referenced in the task brief do not appear in `/presentation` at all. They must live elsewhere (e.g. `/console`, which is off-limits, or a separate page not yet checked).
- Exact Salesforce object/field mapping for `add_activity_note`.
- Whether an LLM client is required for any demo, and the demo's format/medium.
- Explicit MCP transport name (only inferable from the HTTPS-URL requirement, not stated).
- Any auth/security expectations beyond what's already in the Definition of Done and the "least privilege, no leaked secrets" checklist item on Slide 10 — nothing further Salesforce-specific or auth-specific was found.

No slides are missing — all 14 were recovered with full fidelity directly from application source. If deeper detail on judging weights/dates is needed, it is not in `/presentation`'s bundle and would require checking other pages (e.g. `/submit`, whose page HTML was not fetched in this task) or the gated `/console`.
