# Research Agent 6 — The Assignment Reader
Target: https://built2.doo.ooo/ ("Builders League — Connector Test Suite", Cohort 01, MK Lab × DOO)

**Access method used:** The Chrome browser extension (`mcp__claude-in-chrome__*`) was NOT connected — `tabs_context_mcp` failed 3 consecutive times with "Browser extension is not connected." I fell back to (1) WebFetch, which the site's Next.js server-rendering made surprisingly effective, and (2) direct `curl` of the raw HTML plus the Next.js JS chunk (`/_next/static/chunks/079wttz9yzjib.js`) that contains the site's full embedded data model (`BUILD_STEPS`, `DEFINITION_OF_DONE`, `MILESTONES`, `PROGRAM_ASSIGNMENTS`, `CONNECTOR_MISSIONS`). This gave exact, complete, machine-verified source data — more reliable than reading rendered tab text — for everything except the two gated/interactive surfaces (`/console`, `/presentation`) noted below.

---

## 1. THE BRIEF (verbatim)

Hero/mission statement: **"Build one connector. Ship it clean."**

Sub-statement: **"One reusable core, five reliable actions, and a thin MCP adapter that is ready to validate."**

Fuller framing (from `/`, main sections):
> "Independent Package: Build once; connect it to WZRD, CNCT, REST, SDKs, or MCP later."

> "Safe by Default: Least privilege, no committed secrets, explicit approval for consequential writes."

> "Proven in a Sandbox: Tests, fixtures, and a real test-account flow without production customer data."

Restated core objective (WebFetch summary, consistent with source): deliver "one independent, production-oriented connector with five typed actions, safe authentication, tests, OpenAPI, and a thin MCP adapter."

---

## 2. REQUIRED DELIVERABLES — checklist

From the Definition of Done (`DEFINITION_OF_DONE`, verbatim, 12 items) and Build Path:

- [ ] Manifest identifying "provider, version, auth type, scopes, actions, risks, and capabilities"
- [ ] `testConnection` that "verifies credentials without creating side effects"
- [ ] All five assigned actions working "through the shared execute interface"
- [ ] Every action has "typed JSON Schema inputs, outputs, and examples"
- [ ] Normalized errors "include request IDs plus retry classification"
- [ ] Pagination and rate-limit metadata "returned where relevant"
- [ ] Write actions document "approval, idempotency, duplicate, and retry behavior"
- [ ] No secrets "in code, Git history, logs, fixtures, screenshots, or recordings"
- [ ] Unit and fixture tests pass, "with one real sandbox test where access permits"
- [ ] OpenAPI spec, and "the thin MCP adapter reuse the same connector core"
- [ ] "Known limitations and access blockers are clearly listed"
- [ ] Release "tagged v1.0.0 with concise handoff notes"

Submission mechanics deliverable (from `/submit`, WebFetch-rendered, not independently source-verified — see §6/§9): a ZIP upload of "the complete codebase," full name, email, assigned connector, optional "Deployed MCP URL," optional website.

---

## 3. PRESCRIBED STRUCTURE — exact

**THE SITE DOES SPECIFY a repository structure.** It is labeled "Recommended Repository Structure" (and internally named `REPOSITORY_STRUCTURE` in source — a literal template string), and reads exactly:

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

Notes:
- The site calls this "Recommended," not "Required" — it is presented as guidance, not phrased as a strict mandate elsewhere on the page. Since the CLAUDE.md/task framing states the owner said structure "must follow" the site, treat this block as the structure to follow; there is no alternate/stricter structure elsewhere on the site.
- File extensions imply **TypeScript** (`connector.ts`, `client.ts`, `mcp/server.ts`) — see §5 on language, which is an inference, not an explicit rule.
- No other structure, naming convention, or entry-point spec appears anywhere else in the source (checked the full HTML and the JS data chunk for "structure", "folder", "layout", "entry point" — this is the only structural artifact on the site).

---

## 4. JUDGING CRITERIA

Section title: **"Evaluation"** / **"What earns the score"** (verbatim headers, confirmed in raw HTML source, `Evaluation` → `What earns the score`).

Exact criteria and weights (verbatim labels + percentages, cross-checked against raw HTML progress-bar markup):

| Criterion (verbatim) | Weight |
|---|---|
| "Working actions and acceptance scenario" | 25% |
| "Authentication and security" | 20% |
| "Connector structure and reusability" | 15% |
| "Schemas and developer experience" | 10% |
| "Reliability, errors, pagination, rate limits" | 10% |
| "Testing and fixtures" | 10% |
| "Documentation and OpenAPI" | 5% |
| "Demonstration and technical explanation" | 5% |

(Sums to 100%.)

---

## 5. CONSTRAINTS & RULES

- **No dedicated "Constraints" or "Rules" section exists anywhere on the site.** I searched the full raw HTML and the JS data bundle for: "constraint", "rule", "team size", "solo", "individual", "license", "licensing", "AI usage", "Claude", "Copilot", "forbidden", "allowed" — none returned a substantive hit (the few "forbidden"/"allowed" matches were CSS utility-class noise, e.g. Tailwind's `disabled:cursor-not-allowed`).
- **Language/framework**: not explicitly mandated anywhere. TypeScript is strongly implied by the repository structure's file extensions (`.ts`) and the whole site's own stack, but this is an inference, not a stated rule. **State this to the owner as an open question if a Python implementation is planned** — the site gives no explicit permission or prohibition either way.
- **Team size / solo vs. team**: not mentioned. Each connector maps to exactly one named builder in `PROGRAM_ASSIGNMENTS` (one person per connector), which implies individual ownership, but no explicit "solo only" or "teams allowed" rule is stated.
- **AI-usage policy**: not mentioned anywhere (neither permitted nor forbidden).
- **Originality/licensing**: not mentioned.
- **Security posture required** (from "Safe by Default" block and DoD items 2, 8): least-privilege scopes, no committed secrets anywhere (code/Git history/logs/fixtures/screenshots/recordings), explicit approval required before "consequential writes," `testConnection` must not cause side effects.
- **Architecture rule** (Build Path step 03/04, and DoD item 10): implement one reusable core (`testConnection`, `listActions`, `execute`) with provider/auth/schemas/errors isolated; the MCP adapter must be "thin" — "Do not duplicate provider calls or business logic inside the MCP server" — and both OpenAPI and MCP must "reuse the same connector core."
- **Sandbox rule** (Proven in a Sandbox / DoD item 9): "a real test-account flow without production customer data."

---

## 6. DEADLINES (+ time remaining)

- Only date information on the entire site: **"Cohort 01 · August–September 2026"** (banner text). No day-level date, no specific deadline, no timezone is given anywhere in the HTML or the JS data bundle (confirmed by exhaustive search for "deadline", "due", specific month/day patterns).
- **Milestones are staged by name/output, not by date** (`MILESTONES`, verbatim from source):

| Stage | Output (verbatim) | Gate (verbatim) |
|---|---|---|
| Kickoff | "API/auth research, manifest, five action schemas, repository plan, access risks" | "Mission accepted" |
| First checkpoint | "Repository, testConnection, mocks, one read action, provider access confirmed or escalated" | "Build continues" |
| Week 1 demo | "Working auth, two real actions, normalized errors, tests, initial MCP tools" | "Integration candidate" |
| Final handoff | "All actions, fixtures, OpenAPI, thin MCP server, demo, limitations, versioned release" | "v1.0.0 ready" |

- **Time remaining**: Cannot be computed precisely — the cohort window is only given as "August–September 2026" with no end day. Today is 2026-08-06, so the cohort is in progress; **assume the window could close as early as end of September 2026, i.e. roughly 7-8 weeks from today**, but this is my inference, not a stated fact — flag it as an open question for the owner to confirm the exact end date (likely only visible after logging into `/console`, which is gated — see §8).

---

## 7. ALI ISA — everything found

Confirmed via the site's own embedded data (`PROGRAM_ASSIGNMENTS` array in `/_next/static/chunks/079wttz9yzjib.js`, and mirrored in the rendered "Mission finder" builder-picker list on the homepage):

```json
{"connectorId":"salesforce","builder":"Ali Isa"}
```

Cross-referenced against `CONNECTOR_MISSIONS`:

```json
{
  "id": "salesforce",
  "name": "Salesforce",
  "difficulty": "Advanced",
  "category": "Enterprise CRM",
  "requiredActions": [
    "salesforce.search_contact",
    "salesforce.create_contact",
    "salesforce.update_contact",
    "salesforce.create_opportunity",
    "salesforce.add_activity_note"
  ]
}
```

**So: Ali Isa is assigned the Salesforce connector, difficulty "Advanced," category "Enterprise CRM," with these exact five required action IDs**: `salesforce.search_contact`, `salesforce.create_contact`, `salesforce.update_contact`, `salesforce.create_opportunity`, `salesforce.add_activity_note`.

Important caveats:
- The rendered "Your assigned connector" panel on the homepage **defaults to showing Google Sheets** (builder Manar Majeed Ahmed Hasan Mohamed) because the UI component's default React state is `useState("google-sheets")` — this is just the default example shown before a user clicks their name in the builder-picker list, **not evidence that Ali Isa's mission is Google Sheets.** Clicking the "Ali Isa" button in the picker (a client-side state change) would switch the panel to show exactly the Salesforce data above — I did not need to click it because the same data is present verbatim in the downloaded JS source.
- No other personalized text (custom brief, personal note, submission status, "already submitted" flag) exists anywhere in the source for Ali Isa specifically. His only footprint on the site is the one assignment record above.
- Full context string as it appears embedded in the static HTML's builder-picker (concatenated, no separators, exactly as served):
  > "Ali IsaSalesforceRabab Mansoor HasanMicrosoft 365 / Graph...Manar Majeed Ahmed Hasan MohamedGoogle Sheets...")
  (full 27-person roster reproduced in Source Map data dump below)

---

## 8. UNKNOWNS / GATED PAGES

- **`/console` (Validation console) — GATED.** Requires sign-in: "Team access" / "Use your @doo.ooo email to run validations and review results." / input labeled "Doo email" / button "Email me a secure link" / "Anyone with an @doo.ooo address can sign in. No password is required." I did NOT attempt to enter an email or sign in. Its actual validation UI/results and any hidden deadline/date detail it might show are unknown.
- **`/presentation` (kickoff slide deck) — PARTIALLY READ.** It's a 14-slide client-side deck ("01 / 14", arrow-key/F-key navigation). Only slide 1 was retrievable via WebFetch (title "Build one connector. Ship it clean." + the same descriptive subtext as the homepage hero). Slides 2–14 require JS keyboard/click navigation, which was unreachable since the Chrome extension was disconnected. **Content of slides 2–14 is unknown.**
- **Browser automation (`mcp__claude-in-chrome__*`) — UNAVAILABLE for this entire session.** `tabs_context_mcp` failed 3/3 times with "Browser extension is not connected." I was not able to click through the homepage's own tab strip (Build path / My mission / Definition of done — these are actually anchor-scrolled sections on one page per the `#build-path`/`#missions`/`#done` hrefs, not separate SPA tab panels, so this matters less) or interact with the Mission Finder's search/click UI directly. I compensated by pulling the exact same underlying data via `curl` + reading the Next.js JS bundle, which is authoritative (it's the literal source-of-truth array the UI renders from), so I'm confident the data in §3, §4, §6, §7 is complete and accurate despite not clicking through the UI.
- **Exact cohort end date/deadline** is not published anywhere I could find (see §6) — likely only inside the gated `/console`.
- **No stated language mandate** (§5) — open question for the owner: is TypeScript actually required, or just modeled in the example repo structure?

---

## 9. SOURCE MAP — every URL/resource read

- `https://built2.doo.ooo/` — WebFetch (multiple targeted passes) + raw `curl` HTML download + read via Read tool
- `https://built2.doo.ooo/submit` — WebFetch (form fields, ZIP upload requirement, "Challenge guide" link → resolves to `/`)
- `https://built2.doo.ooo/console` — WebFetch (confirmed gated behind @doo.ooo email sign-in; not entered)
- `https://built2.doo.ooo/presentation` — WebFetch (slide 1 of 14 only)
- `https://built2.doo.ooo/_next/static/chunks/079wttz9yzjib.js` — downloaded via `curl`, contains the site's full data model: `BUILD_STEPS`, `DEFINITION_OF_DONE`, `MILESTONES`, `PROGRAM_ASSIGNMENTS` (all 27 builder→connector mappings), `CONNECTOR_MISSIONS` (all 27 connectors with difficulty/category/5 actions each), `REPOSITORY_STRUCTURE` template string.

Full `PROGRAM_ASSIGNMENTS` roster (verbatim from source, for completeness/context):
Salesforce–Ali Isa · Microsoft 365/Graph–Rabab Mansoor Hasan · Microsoft Dynamics 365–Shatha Ebrahem · Shopify–Haitham Al Amri · Google Drive–Alia Burashed · Google Calendar–Yousif Alblooshi · Odoo–Muntadher Almutawaj · Stripe–Hawra Fadhel Abbas Khalifa · Moyasar–Lamees Dawood · Google Sheets–Manar Majeed Ahmed Hasan Mohamed · Slack–Sayed Haider AlHashemi · Notion–Ahmed AlMerbati · Canva–Duaa Ahmed · Asana–Idrees Khaled · Webflow–Ali Mohamed Altal · Google Docs–Laith Alhaddad · Gmail–Abdulla AlHejairi · Zoho CRM–Fatema AlQassab · HubSpot–Hussain Alboori · Freshsales–Baraah Mohammed Eliase · Zid–Zahra Almosawi · Generic HTTP/Webhook–Hashem Saeed Alkhanaizi · Salla–Mohammed Majeed Alasad · WooCommerce–Rehab Khalid · Foodics–Murtadha Dakheel · Squarespace–Alia Mahfoodh · Wix–Abdalameer Yusuf

(Note: Ali Isa appears once, for Salesforce, only — there is also an "Ali Mohamed Altal" on Webflow, a different person; do not confuse the two.)
