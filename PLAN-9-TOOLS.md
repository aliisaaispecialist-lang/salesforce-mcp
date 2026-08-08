# Plan: nine tools, a router, and nothing hardcoded

Written at the end of a long session, from decisions made in it. The work is
not started. This exists so none of the reasoning has to be rediscovered.

## The reference, and what it changes

Chapter 6, *Tool Use and Function Calling*, has now been read. Four things in
it change this plan, and one of them is a number I had wrong.

**The inflection point is 10 to 12 tools, not 20 to 25.** The chapter is
explicit: three to five tools gives high-nineties first-call accuracy, fifteen
to twenty produces systematic errors, and the practical inflection for current
frontier models is around ten to twelve. Ten tools is *at* that line, which
makes the router not an optimisation but a requirement.

**Domain prefixes in the tool name.** The chapter's convention is
`order_search`, `order_fetch`, `billing_query`, `hr_leave_request` -- the
domain visible at a glance, which increases the similarity distance between
tools in different domains. Applied here: `record_get`, `record_create`,
`record_save`, `record_update`, `query_run`, `query_count`, `schema_describe`.
The chapter also says apply it from the start, because retrofitting means
updating every caller.

**A `side_effects` sentence in every write description.** Not just that a tool
is non-idempotent, but what to do instead of retrying: *"This tool creates a
record and is not idempotent. Do not retry on timeout; call `record_get` to
check whether it succeeded first."*

**Compensating actions, which we have none of.** The chapter's rule is that
for every write tool that creates or modifies state, there is either a
rollback tool or a documented manual recovery procedure. `create_opportunity`
is exactly the case it describes: create a thing, then fail on the second
step. We report that honestly as `contact_linked: false`, which is better than
hiding it, but there is no way to undo it and no documented recovery. Either
`save_together` makes it atomic, or the description names the recovery.

## What this connector already does right

Worth knowing before changing anything, because the chapter's contract is
mostly already implemented:

| Chapter requires | Here |
|---|---|
| Typed result, not a raw string | `ActionResult` with `ok`, `data`, `error` |
| Error distinguishable by category | four categories: transient, input, resource, fatal |
| Errors legible enough to recover from | every error carries a `next_step` |
| Idempotency key on non-idempotent writes | required on all four writes, min 8 chars |
| Timeout enforced by the caller | `SF_READ_TIMEOUT_SECONDS=5`, `SF_WRITE_TIMEOUT_SECONDS=15` -- the chapter's exact recommendation |
| Backoff with jitter in the loop, not the model | `errors/retry.py`, on tenacity |
| Enums over free text where bounded | `ActivityKind`; `stage_name` is deliberately free text because it is per-org |
| A description saying when *not* to use it | every `ActionSpec` has `when_not_to_use` |
| Recovery when a required input is missing | `MissingInput` exists on `ActionSpec`, underused |

**The gap is not the contract. It is coverage.** The nine tools apply an
existing, correct contract to more of Salesforce.

## The opening bug, checked here

The chapter opens with a required field whose description says what it is but
not what to do when the value cannot be determined -- so the model fills it
with the description string. The test is: *for every required field, if the
value is unavailable at call time, does the description say what to do?*

Ours partly pass. `MissingInput` carries the question to ask, but it is
populated for some fields and not others, and the guidance is not in the field
description where the model reads it. **Fix: every required field on all ten
tools gets an explicit fallback sentence in its own description**, not only in
`missing_inputs`.

## What exists today

Five tools, all working, live-tested against a real Developer Edition org,
443 offline tests plus 30 live ones.

| Tool | Object | Operation |
|---|---|---|
| `salesforce_search_contact` | Contact | fuzzy search |
| `salesforce_create_contact` | Contact | create |
| `salesforce_update_contact` | Contact | update, re-reads after |
| `salesforce_create_opportunity` | Opportunity | create, plus a contact link |
| `salesforce_add_activity_note` | Task | create |

**These are DOO's assigned five and Definition of Done item 3 names them. Do
not delete or rename them.** The generic tools go alongside.

## The nine

| # | Tool | Endpoint | Status | Remaining |
|---|---|---|---|---|
| 1 | `soql_query` | `GET /query/?q=` | none | build it: query construction, injection safety, paging |
| 2 | `search_records` | `POST /parameterizedSearch` | half | take `object` as an argument, per-object field list |
| 3 | `get_record` | `GET /sobjects/{obj}/{id}` | half | lift out of `update_contact`, own schema, register |
| 4 | `count_records` | `GET /limits/recordCount` | none | trivial once #1 exists |
| 5 | `describe_object` | `GET /sobjects/{obj}/describe` | half | lift out of `create_opportunity`, decide how much of a large payload to return |
| 6 | `save_record` | `PATCH /sobjects/{obj}/{field}/{value}` | half | switch create to upsert; needs an External Id field on the org |
| 7 | `update_record` | `PATCH /sobjects/{obj}/{id}` | half | `object` argument, generic field mapping |
| 8 | `get_related` | `GET /sobjects/{obj}/{id}/{rel}` | none | small, new action |
| 9 | `save_together` | `POST /composite` | half | route the two opportunity writes through composite so they are atomic |

**Order:** 1, then the field-mapping work, then 5, 3, 2, 7, 4, 8, 9, 6 last
because it is blocked on an org change.

## Removing the hardcoding

Twelve lines, and they are all the same mistake in different files.

```
search_contact.py:18   _FIELDS = ("Id","Name","Email","Phone","Title","AccountId")
search_contact.py:37   "sobjects": [{"name": "Contact"}]
update_contact.py:16   _FIELD_NAMES = {"title": "Title", "last_name": "LastName", ...}
update_contact.py:25   _READ_BACK = ("Id","Name","Email","Phone","Title")
update_contact.py:40   path=f"sobjects/Contact/{id}"
update_contact.py:71   path=f"sobjects/Contact/{id}"
create_contact.py:22   _FIELD_NAMES = {...}
create_opportunity.py:25  _ROLE_PATH = "sobjects/OpportunityContactRole"
add_activity_note.py:24   _CONTACT_PREFIX = "003"
add_activity_note.py:25   _OPPORTUNITY_PREFIX = "006"
```

**The one piece of work that unlocks four tools:** replace the hand-written
`_FIELD_NAMES` maps with field names read from `describe` at call time, cached
per object for the life of the process. Do this first and #2, #5, #6 and #7
all become straightforward.

`_CONTACT_PREFIX` / `_OPPORTUNITY_PREFIX` also become dynamic: an object's id
prefix is in its describe response as `keyPrefix`, so the mapping can be
learned rather than written down.

**What must stay fixed:** the tool list itself. MCP expects the same tools on
every connection, and clients cache it. Tools are static; what each tool
*accepts* is discovered per org at call time. Never generate tools from an
org's schema.

**What must not be touched:** the approval gate, idempotency ledger, retry
classification, error taxonomy, rate limiter, nonce fence, censoring logger.
All of them are already object-agnostic and proven against a live org. A
generic tool inherits every one of them for free.

## The router

Three levels, so a model never sees nine tools at once.

```
list_domains()          -> the domains, one line each
describe_domain(name)   -> that domain's tools, with full guidance
<the tools themselves>
```

Domains for the nine: **Read** (1, 2, 3, 4, 8), **Write** (6, 7, 9),
**Schema** (5).

The reason is measured, not aesthetic. The chapter puts the inflection at ten
to twelve tools, and ten is what this plan produces. The router keeps the
visible set at three or four, which is inside the high-nineties band.

The chapter calls this a meta-tool: `get_available_tools` takes a task
description and returns the relevant subset, moving routing into the model's
own reasoning rather than pre-processing code. The cost is one extra round
trip before any work begins. Worth it here, because rule-based keyword routing
would misclassify anything novel.

## What every tool description must contain

Four parts. The third and fourth are the ones usually missing.

**1. What it does**, in one line.

**2. Use this when**, in the user's terms rather than the API's.

**3. Do not use this when, and what to use instead.** Explicitly, as a
condition the model can evaluate:

> Do not use this to list or filter records. If the user described a
> *condition* rather than typed a *name*, use `soql_query` instead. If they
> already have the record id, use `get_record`.

Every overlapping pair needs this in both directions. The known overlaps:

| These look alike | The rule |
|---|---|
| `search_records` vs `soql_query` | fuzzy human words vs a precise condition |
| `save_record` vs `update_record` | might not exist yet vs known id |
| `get_record` vs `get_related` | this record vs the one attached to it |
| `count_records` vs `soql_query` | a plain count vs a filtered count |

**4. What to do when a required input is missing.** Name the question to ask
rather than guessing a value. The existing `MissingInput` type on `ActionSpec`
already carries this and is currently underused: it should be populated for
every required field on all nine.

## One tool, one action

The rule, and it comes before the nine: **a tool does one thing.** Two actions
in one tool only when they are genuinely the same operation and a caller would
never want one without the other.

Where the nine already break this, and the fix:

| Tool | Does | Verdict |
|---|---|---|
| `save_record` | create **or** update | **Split.** "Add someone new" and "change someone" are different intentions with different risk. A model that means create should not be able to silently overwrite |
| `save_together` | several writes atomically | **Keep as one.** The whole point is that they are one operation; splitting it is what causes the half-done state it exists to prevent |
| `update_record` | PATCH then re-read | **Keep as one.** The re-read is not a second action, it is how the first one reports its result. Salesforce answers a PATCH with an empty 204 |
| `soql_query` | filter, sort, count, page | **Keep as one.** All the same question with different clauses, and splitting it would mean guessing which clause combinations deserve a tool |

So the count moves from nine to ten:

```
create_record     always creates, fails if a match exists
save_record       upsert, keyed on a unique field
update_record     changes one that already exists
```

Three tools where there was one, because "make a new one", "make sure one
exists", and "change this one" are three things a user means and three
different consequences when the model picks wrong.

`create_opportunity` today is the counter-example worth remembering. It creates
a deal **and** links a contact, and the second half can fail after the first
succeeded. That is exactly the cost of two actions in one tool, and it is why
`save_together` has to be explicitly atomic rather than merely convenient.


## Splitting create_opportunity into three chained tools

The current tool does three things: reads the org's stages, creates the deal,
and, if a `contact_id` was passed, links the contact. The third is a second
write hidden behind an optional parameter, which is the pitfall Chapter 6 names
directly: *"Tools should do one thing. The orchestration of multiple things is
the agent's job, and doing it in the open, via multiple tool calls the model
chooses to make, is what makes the agent's behavior auditable and
correctable."*

Three tools, chained by what each one says rather than by hidden control flow.

### 1. `describe_object` (read, no approval)

Returns the org's picklists for an object. Cacheable, changes nothing, cannot
half-fail.

> **Use this before creating an opportunity**, to learn which sales stages this
> org accepts. Stage lists are configured per org and no universal list is
> correct. Once you have a valid stage, call `create_opportunity`.

### 2. `create_opportunity` (write, approval, one record)

Creates the deal and nothing else. `contact_id` is **removed from its schema**:
a parameter that silently triggers a second write is the thing being fixed.

> Creates one opportunity and returns its id. This tool does not attach a
> contact. **If the user named a person the deal is for, call
> `link_contact_to_opportunity` next**, passing the `opportunity_id` returned
> here and that person's contact id.
>
> Do not use this when the deal already exists. If `describe_object` has not
> been called and you are unsure of the stage, send your best guess: an invalid
> stage is rejected before anything is created and the error lists the valid
> values.

The **result** carries the handover, not just the description, because that is
what the model reads at the moment the decision is due:

```json
{
  "id": "006...", "name": "...", "stage_name": "...", "created": true,
  "next_action": "The deal exists but has no contact attached. If this deal is
                  for a specific person, call link_contact_to_opportunity with
                  opportunity_id=006... and their contact id."
}
```

`next_action` is present only when the caller has not yet linked anyone. A
field that always appears becomes noise the model stops reading.

### 3. `link_contact_to_opportunity` (write, approval, one record)

The optional parameter becomes this tool's **required** one, which is the whole
point of the split: what was hidden and optional is now named and mandatory.

> Attaches a contact to an existing opportunity, creating a contact role.
> Requires both ids. Call this after `create_opportunity`, or on any
> opportunity that already exists.
>
> Do not call this to create an opportunity; it only links to one that exists.
> **If you do not have the opportunity id**, call `create_opportunity` first, or
> `search_records` if the deal already exists.

### What this buys, and what it costs

**Buys:** every step visible in the trace. A failed link is a failed tool call
the model can see and retry, rather than a `contact_linked: false` buried in a
successful result. Each tool has one approval prompt describing one change,
instead of one prompt for a write that turns out to be two.

**Costs:** the two writes are no longer atomic, and were never truly atomic
anyway. Today an opportunity can exist without its link; after the split the
same thing can happen, but the model is told so directly and can act.

`save_together` via `/composite` remains a separate tool for a caller who
explicitly wants atomicity. That is Pattern 4 territory: there the operation
genuinely is "apply these together", which is a different request from "create
a deal".

### The rule this establishes

Every tool that leaves work unfinished says so **in its result**, names the tool
that finishes it, and names the argument to carry across. Chaining lives in
what tools say, never in hidden parameters.


## The rule: multi-step work is multiple tools, chained by results

Generalised from the `create_opportunity` split, and it applies to every tool
in this connector and every endpoint added later.

**When an operation touches more than one record, it is more than one tool.**
Not one tool with an optional parameter, not one tool with a `mode`, and not
one tool that quietly makes two calls. One tool, one record, one approval
prompt describing one change.

**The tools are joined by what they return, not by hidden control flow.** A
tool that leaves work unfinished says so in its result: what is still
incomplete, which tool finishes it, and which value to carry across.

```json
"next_action": "<what is unfinished>. Call <tool> with <field>=<value>."
```

Three things it must always contain, because a model missing any one of them
guesses at that part:

| | |
|---|---|
| **what is unfinished** | so it is not read as a plain success |
| **which tool** | by name, not "another tool" |
| **which value** | the id to carry, spelled out |

**It appears only when work is genuinely unfinished.** A field present on every
response becomes noise a model stops reading, and then it is absent exactly
when it matters.

### How to tell whether to split

| Ask | Split? |
|---|---|
| Does it write to more than one record type? | **yes** |
| Can one half succeed while the other fails? | **yes** |
| Is a parameter optional *and* does supplying it cause an extra write? | **yes** |
| Is the second call a read that reports the first call's result? | no, keep together |
| Is the whole point that they apply atomically? | no, that is Pattern 4 |

### Applied across what exists and what is planned

| Tool | Verdict |
|---|---|
| `create_opportunity` | **split into three.** Two record types, either can fail alone |
| `update_contact` | keep. The re-read reports the write, Salesforce answers PATCH with an empty 204 |
| `search_contact`, `create_contact`, `add_activity_note` | keep. One record each |
| `save_together` | keep. Atomicity is the request, not a side effect |
| `soql_query` | keep. Clauses of one question |

### Why this beats doing it inside the tool

The orchestration becomes visible. A failed second step is a failed tool call
in the trace that the model can see and retry, rather than a `false` buried
inside a result the caller reads as success. Chapter 6's phrasing: doing it in
the open is what makes an agent's behaviour auditable and correctable.

It also fixes approval. One prompt per tool means one prompt per change. Today
approving `create_opportunity` approves two writes, and the person confirming
only sees one described.

## Naming

Name the action and what it works from, not the noun alone. A model picks
better from a name that carries the condition:

```
search_contacts_by_text        fuzzy, a name or an email
get_contact_by_id              exact, id already known
list_contacts_by_condition     filtered, sorted, counted
save_contact_by_email          upsert keyed on a unique field
update_contact_by_id           changes one that exists
```

`search` versus `query` is the pair models confuse most.
`search_by_text` versus `list_by_condition` is much harder to get wrong.

## Regulations every new tool inherits

Non-negotiable, and all already implemented:

- a write refuses unless a person approved it, and the server asks the client
  to ask a person
- every write requires a caller-supplied `idempotency_key`
- errors carry a category and a next step, never a bare failure
- results are fenced as untrusted data before a model reads them
- no picklist, stage, or field name is ever hardcoded
- secrets never reach a log line
- the layering holds: only `client.py` opens a socket, only the adapter knows
  the protocol

## What "done" looks like

All nine registered, the router working, no object name literal anywhere in
`actions/`, the original five still present and passing, and the live tier
still green against a real org.
