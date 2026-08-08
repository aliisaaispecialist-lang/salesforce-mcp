# Plan: nine tools, a router, and nothing hardcoded

Written at the end of a long session, from decisions made in it. The work is
not started. This exists so none of the reasoning has to be rediscovered.

## Step 0, before any code

Read `C:\Users\Admin\Desktop\The Agentic AI Bible - PDF\Part 2 - Core
Capabilities\Chapter 06 - Tool Use and Function Calling\Chapter 06 - Tool Use
and Function Calling.pdf`.

It is the reference for this design and it has **not** been read yet. Nothing
below should be treated as final until it has been, because the whole point of
this plan is tool design and that chapter is about tool design.

Also re-read the existing `docs/` decisions, which are inside
`ALL-DOCS-ARCHIVE.md` until the README rewrite lands.

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

The reason is measured, not aesthetic: tool-selection accuracy degrades past
roughly 20 to 25 visible tools. The router keeps the visible set at three or
four.

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
