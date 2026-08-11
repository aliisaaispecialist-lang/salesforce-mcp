# Salesforce Connector

An MCP server that lets an AI assistant read and change Salesforce records
safely. Seventeen tools, every write gated behind a person's approval, and
every record's text marked as data rather than as instructions before a model
ever reads it.

It speaks stdio and nothing else. An MCP host launches it as a subprocess, or
Executor launches it once and shares it with every agent on your machine.

---

## What you need

| | Why | If you do not have it |
|---|---|---|
| **Node.js 20+** | Runs Executor, the integration layer that fronts this connector | [nodejs.org](https://nodejs.org), or `winget install OpenJS.NodeJS` / `brew install node` |
| **Executor** | One MCP endpoint shared by every agent, so you configure this connector once instead of once per client | `npm install -g executor` (below) |
| **Docker** *or* **Python 3.12+** | Runs the connector itself. Pick either | Docker: [docker.com/get-started](https://www.docker.com/get-started). Python: [python.org/downloads](https://www.python.org/downloads) |
| **A Salesforce sandbox** | Three values: a Consumer Key, a username, and a private key you generate | See [Salesforce credentials](#3-salesforce-credentials) |

You need none of it to review the code. `pytest` runs 783 tests with no
credentials, no org, and no network.

---

## 1. Install Executor

Executor is the integration layer your agents talk to. You add this connector
to it once, and Claude Code, Cursor, and anything else MCP-compatible all share
it, with the same credentials and the same policies.

It also keeps the connector's tool list out of your context. Connected
directly, seventeen tools cost **20,597 tokens** at startup, before you have
said anything. Behind Executor the same seventeen cost **293**, a **98.6%
reduction**, because Executor keeps them in a catalogue and hands the model a
search instead of a list. Both figures were measured; the full comparison is in
[What it costs at connect](#what-it-costs-at-connect).

**If you do not have Executor, install it:**

```bash
npm install -g executor
executor install
executor web
```

`executor install` sets up the background service so it survives a reboot.
`executor web` opens the console in your browser, which is where integrations
and their policies live.

**If you do not have Node.js**, install that first. It ships with `npm`:

```bash
# macOS
brew install node

# Windows
winget install OpenJS.NodeJS

# Linux (Debian/Ubuntu)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs
```

Check it took:

```bash
executor daemon status
```

---

## 2. Install the connector

Two routes. Pick one. Both were run against this repository.

### Route A: Docker

```bash
docker build -t salesforce-connector .
```

**If you do not have Docker**, install it first:

```bash
# macOS
brew install --cask docker

# Windows
winget install Docker.DockerDesktop

# Linux (Debian/Ubuntu)
curl -fsSL https://get.docker.com | sudo sh
```

Then open Docker Desktop once so the daemon is running, and re-run the build.

To run the image by hand:

```bash
docker run -i --rm --read-only --cap-drop ALL --env-file .env salesforce-connector
```

The `-i` is not optional. This image speaks stdio and exposes no port; without
it the container's stdin is closed immediately and the server never sees a
request. Closing stdin is also how you stop it: the process exits 0 on EOF.

`--read-only` and `--cap-drop ALL` both work because the connector writes
nothing to disk and needs no privilege beyond outbound HTTPS. They are not the
default only because Docker has no way to make them one.

### Route B: Python

```bash
pip install -e ".[dev]"
cp .env.example .env
PYTHONPATH=src python mcp/server.py
```

Or with `uv`, which installs the exact dependency tree this was tested against
rather than resolving fresh versions:

```bash
uv sync --all-extras --frozen
uv run python mcp/server.py
```

---

## 3. Salesforce credentials

Three values, and only one of them is secret.

1. **Generate a key pair.** The private key never leaves your machine;
   Salesforce holds only the public half.

   ```bash
   openssl req -x509 -sha256 -nodes -days 365 -newkey rsa:2048 \
     -keyout server.key -out server.crt \
     -subj "/CN=salesforce-connector"
   ```

2. **Create an External Client App** in your sandbox (Setup, App Manager). Not
   a Connected App: those are the older form and the JWT flow behaves
   differently. Enable the OAuth JWT bearer flow, upload `server.crt`, and give
   it the `api` and `refresh_token` scopes.

3. **Pre-authorise your user** so the flow does not need an interactive
   consent, then copy the Consumer Key.

Fill in `.env`:

```bash
cp .env.example .env
```

```
SF_CLIENT_ID=<the Consumer Key>
SF_USERNAME=you@example.com.sandbox
SF_PRIVATE_KEY=<paste server.key, or a single line with \n between lines>
```

The connector repairs a key that had to travel on one line, because container
runtimes and CI secret stores generally cannot hold a multi-line value.

Check it reaches Salesforce before wiring any client to it:

```bash
python scripts/check_connection.py
```

---

## 4. Connect it

### Through Executor (recommended)

Open the console:

```bash
executor web
```

**Add Integration**, choose an MCP server, and give it the command that starts
this connector:

```
docker run -i --rm --read-only --cap-drop ALL --env-file /absolute/path/to/.env salesforce-connector
```

or, on the Python route:

```
python /absolute/path/to/mcp/server.py
```

Executor connects, calls `tools/list`, and indexes all seventeen tools into its
catalogue. Set the policy on each one there. The eight write tools should be
**needs approval**; the nine read tools can be **always allowed**.

Then point your agent at Executor, once, for everything:

```bash
npx add-mcp http://127.0.0.1:4788/mcp --transport http --name executor
```

Restart your client, or open a new chat. Most MCP clients only load servers at
startup, and this is the step people skip before deciding it is broken.

Confirm:

```bash
executor tools integrations
```

If the connector appears there but not in your client, the problem is the
restart, not the config.

### Straight to one MCP host, without Executor

`examples/mcp_client_config.json` has two ready-to-paste entries for an MCP
host's `mcpServers` object: one that runs the Docker image, one that runs
`mcp/server.py` directly. Replace the placeholder absolute path.

This works, and it is what a reviewer reading the repository will do. It is
also the expensive way: all seventeen tools land in context at startup, about
20,597 tokens, because a client fetches the whole list and there is nothing in
front of it to keep them in a catalogue. See
[What it costs at connect](#what-it-costs-at-connect).

---

## The tools

Nine read, eight write. Every write requires approval before it runs.

### Read

| Tool | What it is for |
|---|---|
| `salesforce_contact_search_by_text` | Search contacts by one piece of text, matched against name, email, phone and their other own fields at once, and return the matches with their record ids |
| `salesforce_record_search_by_text` | Find records of any object by free text, the way a search box finds them |
| `salesforce_record_query_by_soql` | Run a read-only SOQL query to list, filter, sort, or count |
| `salesforce_record_get_by_id` | Read one record by id, every field or only the ones asked for |
| `salesforce_record_get_related_by_id` | Read what a record is attached to: a contact's account, an opportunity's contact roles |
| `salesforce_record_count_by_object` | Count records without reading them |
| `salesforce_object_describe_by_name` | List an object's fields, types, and the picklist values this org accepts |
| `salesforce_tool_list_by_kind` | Name the tools that read, or the tools that change, each with what it is for |
| `salesforce_tool_describe_by_name` | Report one tool's fields, the exact type each expects, and a worked call |

### Write

| Tool | What it is for |
|---|---|
| `salesforce_contact_create` | Create a person and return its record id |
| `salesforce_contact_update_by_id` | Change fields on a contact and return the record afterwards |
| `salesforce_opportunity_create` | Open a deal, optionally linked to an account and a contact |
| `salesforce_opportunity_create_with_contact_by_id` | Open a deal and attach its person in one write that either fully succeeds or changes nothing |
| `salesforce_opportunity_link_contact_by_id` | Attach an existing contact to an existing deal |
| `salesforce_activity_create_by_related_id` | Record a call, email, meeting, or note on a record's activity timeline |
| `salesforce_record_update_by_id` | Change named fields on any object, then read back what they hold |
| `salesforce_record_upsert_by_external_id` | Write a record by an outside system's id: create if new, update if it exists |

---

## What it costs at connect

Every MCP client fetches the tool list when it starts and holds it in context
for the whole session, before the user has said anything. That fetch is the
number below. It was measured, not estimated: the `tools/list` result was
serialised the way it travels on the wire and counted with a real tokenizer.

| Setup | Tools the model sees | Tokens | Against the baseline |
|---|---:|---:|---:|
| Straight to one MCP host | 17 | 20,597 | baseline |
| Behind Executor | 7 | 1,363 | **93.4% less** |
| Behind Executor, `?artifacts=false` | 3 | 293 | **98.6% less** |

Executor publishes three tools of its own (`execute`, `skills`, `resume`) and
four more for rendering artifacts, which its endpoint can be told to leave out.
It never shows the model this connector's seventeen. They live in a catalog
that generated code searches at runtime, which is why seventeen tools cost 293
tokens instead of 20,597.

**Read the first-use number honestly.** Executor's 293 is not the whole cost of
the first action: a model must fetch its `execute` guide once, about 3,900
tokens, before it can write code, and then pull each tool's schema as a result.
On the very first call it comes out around 4,200 rather than 293.

The advantage is what happens next. That 293 stays flat as you add
integrations, because only the inventory list grows, one line per integration.
A direct connection is per server: connect a second MCP server and you pay its
whole surface again. Add GitHub and a database and Executor still costs 293.
That is why routing belongs in the gateway rather than in each connector, and
why this one no longer has a router of its own.

Measured with `cl100k_base`, so the ratios are exact and the absolute figures
are close rather than precise. The Executor rows were reconstructed from its
published source; the artifact schemas were approximated downward, so the 1,363
row understates if anything.

---

## Configuration

Everything the connector reads. Full annotations are in `.env.example`.

### Required

| Variable | |
|---|---|
| `SF_CLIENT_ID` | The External Client App's Consumer Key |
| `SF_USERNAME` | The integration user to act as |
| `SF_PRIVATE_KEY` | The private key whose public half Salesforce holds |

### Everything else has a default

| Variable | Default | |
|---|---|---|
| `SF_LOGIN_URL` | `https://test.salesforce.com` | Sandbox. Production is refused unless deliberately allowed |
| `SF_ALLOW_PRODUCTION` | `false` | A mistyped login URL is how production data gets touched by accident |
| `SF_API_VERSION` | `v67.0` | |
| `SF_CLIENT_SECRET` | unset | Only the client credentials flow needs one |
| `SF_READ_TIMEOUT_SECONDS` | `10.0` | A read is cheap to abandon |
| `SF_WRITE_TIMEOUT_SECONDS` | `22.0` | A write is abandoned reluctantly: it may already have been applied |
| `SF_CONNECT_TIMEOUT_SECONDS` | `5.0` | Waiting for the socket, not for an answer |
| `SF_MAX_ATTEMPTS` | `3` | |
| `SF_RETRY_BUDGET_SECONDS` | `120.0` | Wall clock across every attempt of one call |
| `SF_CALLS_PER_MINUTE` | `60.0` | Well under any org's allowance. A model in a loop can spend a day's quota in minutes |
| `SF_APPROVAL_TTL_SECONDS` | `600` | How long a person's approval of a write stays valid |
| `SF_MAX_QUERY_ROWS` | `200` | The row ceiling a query or a relationship is held to |
| `SF_MAX_FIELD_CHARACTERS` | `4000` | How wide one text value may be before it is shortened and says so |

Nothing is hardcoded. Every value above is read from the environment and
validated once at startup; a missing or unusable one stops the server rather
than letting it accept calls that can only fail.

---

## How it is built

```
mcp/server.py               the entry point an MCP host launches
src/salesforce_connector/
  protocol/                 the MCP adapter: server, surface, translate
  actions/                  one module per tool, plus the base class
  schemas/read|write/       the pydantic models each tool validates against
  transport/                the only code that opens a socket
  errors/                   nine failure types, one per required response
  approval/                 the signed, expiring write gate
  replay/                   the idempotency ledger
```

The MCP layer knows nothing about Salesforce, and the Salesforce layer knows
nothing about MCP. A test asserts it: the moment an endpoint or a field name
appears in `protocol/`, the core has stopped being reusable.

The low-level `Server` is used rather than the decorator API, because the
decorator derives a tool's schema from the function signature and lands a
pydantic parameter nested under a `params` key, which measurably raises the
rate of malformed calls. The schemas here are published exactly as authored.

---

## How failures are handled

A tool that fails silently is worse than one that fails loudly, because the
model proceeds as though it worked. Every failure here comes back as a result
the model can read and act on.

### Bad arguments do not come back as a protocol error

The MCP specification puts tool execution errors inside the result rather than
in a JSON-RPC error, because a protocol error is handled by the client's
transport layer and never reaches the model that made the mistake. So a
malformed call returns `is_error: true` with the explanation in `content`.

What the model gets is better than an error code. Pydantic reports "Input
should be a valid number", which names the problem and not the remedy, so the
connector appends the expected type in plain words and a correct value, both
read from the field's own schema:

```
[connector.invalid_input] salesforce_opportunity_create rejected its arguments.
close_date: Input should be a valid date. Send a date, written as YYYY-MM-DD,
for example '2026-12-01'.

What to do: Correct the named field and call this action again. The same input
will fail identically.
```

Schema staleness, the usual cause of `-32602`, cannot happen: schemas are built
at import time, so within one process the published list is frozen.

### Nine failure types, one per required response

Not one per Salesforce error code. The question a caller needs answered is what
to do next, and there are only nine distinct answers: configuration invalid,
authentication failed, permission denied, invalid input, record not found,
conflict, rate limited, transport failed, escalate to a human. Each carries a
`next_step`, and on escalation the action's own manual recovery procedure is
attached.

### Timeouts, and a write that may already have happened

A read waits 10 seconds and a write 22. Reads are cheap to abandon: nothing
changed, so asking again is safe. A write is abandoned reluctantly, because the
request may already have been applied and giving up early makes that ambiguity
more likely rather than less. Retries stop at three attempts or 120 seconds,
whichever comes first.

For the gap no timeout can close, the moment between a write leaving and the
answer arriving, every write carries an idempotency key. The ledger records it
before the call and completes it after, so a repeat of the same key returns the
original result with a warning saying so rather than writing twice. A composite
write that partly applied escalates to a person, naming the orphaned records.

### Nothing is swallowed

A write that Salesforce accepted but answered without a record id used to
report success with an empty id; it now raises, saying there is no way to
confirm what was written. A read-back that fails after a successful update used
to fail the whole action, telling the caller the update had not happened when
it had; it now warns and reports the write.

---

## Security

**Every write needs a person.** The approval token is signed, expires after ten
minutes, and is bound to a digest of the exact arguments shown to the user. You
cannot approve one write and present that approval for another, or approve a
write and then change its arguments. The signing key dies with the process, so
a restart invalidates everything pending.

**Record text is data, never instruction.** Everything read out of Salesforce
comes back inside a marker carrying a random suffix minted for that response,
so a contact whose description contains the closing tag cannot end the fence
early. The rule for reading that marker is stated in the server's
`instructions` and repeated above every result. Text quoted back by a failure
is fenced the same way; this connector's own remedy is not, because that is the
part a model should act on.

**A tool that does not exist gets a real answer.** A call naming something this
connector cannot do is refused with the full list of what it can do, a
suggestion only when the mistake was spelling rather than intent, and a plain
instruction not to substitute a nearby tool. Without that last part, a model
refused a delete reaches for an update and blanks the fields instead.

**The token cannot leave the org.** Every request carries a bearer token, and
the client refuses any absolute URL outside this org's `/services/data/`.

**Nothing secret reaches a log.** Secrets are `SecretStr`, censoring is a
structlog processor rather than a regex over rendered text, and record field
values are never logged at all. CI scans the whole git history with gitleaks.

**Reproducible builds.** `uv.lock` pins 58 packages with 614 hashes. CI
installs with `--frozen`; the image installs the same export with
`--require-hashes`, so a substituted artefact fails the build rather than
shipping inside it.

---

## Design decisions

The ones that are not obvious from reading the code, and the reasoning behind
each, so nobody has to rediscover it.

**stdio only, no HTTP.** The transport governs how a host reaches this server,
not what the server does inside. Our tools call Salesforce over HTTPS, but that
is a second hop and has no bearing on the first. An MCP host launches this
process on the same machine, which is exactly the case stdio is for. Streamable
HTTP would add a network hop between the host and this connector plus mandatory
OAuth 2.1, origin validation, and session resumability, for no benefit while
one host launches one process.

**No router of our own.** This connector used to publish two doors behind an
`SF_TOOL_SURFACE` switch, so a model could ask what existed before reading any
of it: 20,597 tokens down to 2,950. It was removed. Executor does the same job
one layer up, takes the cost to 293, keeps it flat as integrations are added,
and applies to every server rather than to this one. Two routers in series
would have meant generated code opening a door for nothing and a catalogue
holding four entries instead of seventeen, which is the opposite of what a
catalogue search needs.

**The low-level `Server`, not the decorator API.** The decorator derives a
tool's schema from the function signature, and a pydantic parameter lands
nested under a `params` key, which measurably raises the rate of malformed
calls. The schemas here are written and tested, so they are published exactly
as authored.

**One tool, one end-to-end action.** Generating a tool per REST endpoint is the
common antipattern: agents chain several calls for one intent, and tool-choice
error compounds. At 95% per-choice accuracy, five chained choices land near
77%. `salesforce_opportunity_create_with_contact_by_id` is one call and one atomic
composite request rather than create, create, link.

**Resources and prompts are not served.** The protocol defines three server
primitives; this connector serves one. Everything it can read is already
reached by a tool that has an approval story and a fence, and prompts are
user-selected templates that the competition surface does not use. Exposing a
CRM as unscoped resource URIs is the chapter's own cautionary example.

**Nothing is hardcoded.** Every timeout, ceiling, retry count, and rate limit
is read from the environment and validated at startup. A value somebody might
reasonably want to change belongs where changing it is expected.

---

## Conformance

Measured against Chapter 9 of *The Agentic AI Bible* ("Model Context
Protocol"), the O'Reilly *AI Agents with MCP* early release, and the current
specification. Where a book and the specification disagree, the specification
wins: both books predate protocol revision 2026-07-28, and one still describes
HTTP+SSE as current and `notifications/message` logging as live, which it is
not.

| Area | Verdict |
|---|---|
| stdio transport and lifecycle | Met |
| Protocol errors (-32700, -32600, -32602) | Met, with one deliberate divergence documented above |
| Tool error taxonomy | Met |
| Timeouts | Met |
| Crash mid write | Met, stronger than asked: idempotency ledger and compensating escalation |
| Capability scoping | Met, in Executor, where a policy is set per tool and shared by every agent |
| Audit logging | Met: identity, tool, status, category, elapsed, secrets censored, payloads never logged |
| Sandboxing | Met: non-root, and `--read-only --cap-drop ALL` both work |
| Tool result injection | Met: nonce fence, and the rule for reading it stated in `instructions` and repeated above every result |
| Output sanitising and size | Met: errors fenced, structured twin marked, width and row counts both bounded |
| Input guards on an unknown tool | Met: the closed set, a verb-guarded suggestion, and an instruction not to substitute |
| Tool design, one tool one action | Exceeds |
| Tool count and discovery cost | Met, in Executor: 20,597 tokens to 293 |
| Structured output schemas | Met, and validated before return |
| Resources and prompts | Deliberately absent |
| Protocol version negotiation | Met, handled by the SDK |
| Breaking change policy | Met, written below |
| Reproducible dependencies | Met: `uv.lock`, 58 packages, 614 hashes, CI and image both install from it |

---

## Changing a tool

MCP has no per-tool versioning. A tool's name is the only identifier a client
uses, and clients cache the tool list. So:

- **A breaking change ships under a new name.** `search_orders` becomes
  `search_orders_v2`, the old name stays alive through a migration window, and
  it is retired only after every client has moved.
- **A new field is optional in the schema and required in the code.** Adding a
  required field to an existing tool breaks every client holding a cached list,
  even though the tool's name did not change.

Both rules are enforced by review, not by a test, which is why they are written
here.

---

## Testing

```bash
pytest -q                    # 783 tests, no credentials, no network
pytest -m security           # the attacks this connector must be immune to
ruff check . && mypy src tests
```

Four tiers. `unit` and `contract` need nothing. `security` writes the attacks
as attempts rather than as assertions about design, so a refactor that quietly
removes a defence fails there rather than in production. `learning` and
`integration` run against a real sandbox and are excluded by marker.

### Does the model pick the right tool?

Tests prove a tool works when called correctly. They say nothing about whether
a model chooses it in the first place, which is what a tool's name and
description are for. `evals/` measures that:

```bash
python evals/run_tool_choice.py --limit 12          # a cheap smoke run first
python evals/run_tool_choice.py --out runs/before.json
```

By default this drives **Claude Code** against the real MCP server: it launches
`mcp/server.py` with placeholder credentials, lets the host perform the real
handshake and `tools/list`, and records which tool the model reaches for. That
measures the descriptions as a host actually receives them, and it bills the
Claude Code subscription rather than an API account.

`--via api` calls the Messages API instead, with the tool list rebuilt into a
`tools` array. That isolates the connector from any host's own prompt and
tools, which makes the number cleaner and less representative. It needs
`pip install anthropic` and `ANTHROPIC_API_KEY`.

Two things the CLI backend does deliberately. It **denies the shell and
filesystem tools**: placeholder credentials make every call fail, and a model
that has just failed to reach Salesforce goes looking for the real ones, which
in the first trial run meant grepping `.env` for `SF_PRIVATE_KEY`. And it
**kills the run at the first Salesforce tool call**, because there is no
`--max-turns` in the CLI and the choice is the only thing being scored. A
consequence of that kill is that the per-run cost is never reported.

Eighty prompts in `evals/tool_choice.jsonl`, plain JSONL you can edit by hand.
The model is given the published tool list and one prompt; the only thing
recorded is which tool it reached for. Nothing is executed, so a run cannot
touch Salesforce.

Four numbers come out, and the last is the useful one:

| | |
|---|---|
| **selection** | of the prompts with a right answer, how many got it |
| **abstention** | of the prompts with none, how many were correctly refused |
| **per tool** | which tools are chosen reliably and which are not |
| **confusion** | what got picked instead, which is the only output that says *why* a tool is losing |

Selection and abstention are scored separately on purpose. A connector that
always picks something scores well on the first and nothing on the second, and
this one is built to refuse what it cannot do, so the refusal is the half worth
measuring. Eleven of the eighty prompts ask for something the connector does
not offer, deleting a record among them.

Run it before and after any change to a name or a description, and compare.

---

## Licence

MIT. See [LICENSE](LICENSE).
