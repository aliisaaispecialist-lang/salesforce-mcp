# MCP Specification — binding requirements for this connector

Read from the live draft specification on 2026-08-07. These take priority over
the books, over the SDK's convenience APIs, and over anything decided earlier
in this project: where they conflict, the specification wins.

Pages read in full: basic/index, basic/versioning (lifecycle), basic/transports/stdio,
basic/patterns/mrtr, server/discover, server/tools, server/utilities/pagination,
server/utilities/logging, client/elicitation, basic/security_best_practices.

Not read, and not needed for v1 because we expose only tools: server/resources,
server/prompts, server/utilities/completion, server/utilities/caching,
basic/patterns/subscriptions, basic/transports/streamable-http,
basic/authorization. Resources and caching become required the moment we expose
describe metadata or picklists as resources.

---

## 1. The correction that matters most: there is no session

Earlier in this project I said the token could be created when the model
connects and destroyed when it disconnects, because stdio spawns one process
per client. The specification now says the opposite about what that process
means:

> "The Model Context Protocol (MCP) is a **stateless protocol**: all the
> information needed to process a request is contained in the request itself.
> A server processes each request independently; no state should be inferred
> from previous requests, even those on the same connection or stream."

> "Clients **SHOULD NOT** use an individual task, thread, or conversation as
> the lifetime boundary for the stdio process."

> "an open connection, such as a STDIO process, is not a conversation or
> session: clients may interleave unrelated requests on the same transport"

**What this changes.** The token's lifetime is the **process**, not the
conversation. One process may serve several unrelated conversations, and one
conversation may outlive or span processes. So:

- Holding the token in memory for the life of the process remains correct.
- Describing it as "per conversation" is wrong and must not appear in the
  README or the manifest.
- Nothing may be cached against "the current conversation", because the server
  cannot know what that is. Our idempotency ledger and journal are keyed by an
  explicit key the caller supplies, which is what the specification requires:

> "State that needs to span multiple requests **MUST** be referenced by an
> explicit identifier the client passes on each request."

That rule vindicates the ledger and journal design, and forbids ever inferring
the caller from the connection.

## 2. The initialize handshake is gone

Modern protocol versions (`2026-07-28` and later) carry version, identity, and
capabilities in each request's `_meta`. There is no negotiation handshake.

- Every request **MUST** carry `io.modelcontextprotocol/protocolVersion` and
  `io.modelcontextprotocol/clientCapabilities`. A request missing either is
  malformed and the server **MUST** reject it with `-32602`.
- Servers **MUST** implement `server/discover`, returning `supportedVersions`,
  `capabilities`, and `serverInfo`.
- Unsupported version -> `UnsupportedProtocolVersionError` (`-32022`) listing
  what we do support.
- A server **MUST NOT** rely on a capability the client did not declare; if it
  needs one, it returns `MissingRequiredClientCapabilityError` (`-32021`)
  naming the missing capability.
- Every result **MUST** carry `resultType`, either `complete` or
  `input_required`.

Most of this is the SDK's job. Ours is to verify the installed SDK does it,
and to never assume a capability we were not handed.

## 3. stdio rules, verbatim

> "The server **MUST NOT** write anything to its `stdout` that is not a valid
> MCP message."

> "The server **MAY** write UTF-8 strings to `stderr` for any logging purposes"

> "Messages are delimited by newlines, and **MUST NOT** contain embedded
> newlines."

> "Servers **SHOULD** exit promptly when their standard input is closed or
> reads return end-of-file."

Consequences for us: logging to stderr is not a preference, it is the only
lawful channel; the `T20` lint rule banning `print` enforces a MUST. Our JSON
log lines must not contain raw newlines. And the server must handle EOF on
stdin by shutting down, which is the one graceful-shutdown signal that works
everywhere.

Also: the server **MUST NOT** write JSON-RPC requests to stdout at all.
Anything the server needs from the user goes back as an `InputRequiredResult`.

## 4. The logging feature is deprecated

> "**Deprecated**: The Logging feature is deprecated as of protocol version
> `2026-07-28`... New implementations **SHOULD NOT** adopt it; existing
> implementations **SHOULD** migrate to logging to `stderr` for stdio
> transports, or to OpenTelemetry for structured observability."

So we do **not** declare the `logging` capability and do not emit
`notifications/message`. Our structlog-to-stderr design is what the
specification now recommends.

The security rules still bind us:

> "Log messages **MUST NOT** contain: Credentials or secrets · Personal
> identifying information · Internal system details that could aid attacks"

Our censoring processor and the rule against logging record field values are
therefore MUST-level, not house style.

`_meta` reserves `traceparent`, `tracestate`, and `baggage` for W3C trace
context. If a client sends them we should propagate them into our log context.

## 5. Approval for consequential writes: elicitation via MRTR

This replaces the `approved: bool` parameter planned earlier.

- Servers **MUST** send elicitation as an `InputRequiredResult` on the
  `tools/call` response. Server-initiated requests are gone: "This is a
  breaking change."
- Three response actions exist and all three **MUST** be handled: `accept`,
  `decline`, `cancel`.
- Form schemas are restricted to flat objects of primitives. A confirmation
  boolean or an enum qualifies.
- Servers **MUST NOT** request secrets by form mode. We never need to, since
  credentials come from the environment.
- Servers **MUST NOT** send an elicitation the client has not declared support
  for. So the `approved` parameter survives as the fallback path for clients
  without the capability, rather than as the primary mechanism.
- The JSON-RPC id of the retry differs from the original; the two requests are
  independent.

`requestState` carries the pending write across the round trip, and the
specification is strict about it:

> "servers **MUST** treat `requestState` as an attacker-controlled input. If
> `requestState` influences authorization, resource access, or business logic,
> servers **MUST** protect its integrity (e.g. HMAC or AEAD) and **MUST**
> reject state that fails verification."

And to prevent replay it **SHOULD** contain the authenticated principal, a
short TTL, and an identifier for the originating request.

A pending Salesforce write absolutely influences business logic, so ours must
be HMAC-signed, time-limited, and bound to the originating call.

## 6. Tools

- Tool names: 1–128 characters; allowed characters are letters, digits,
  underscore, hyphen, **and dot**. So MCP permits `salesforce.search_contact`.
  The binding constraint is the LLM providers, whose function names match
  `^[a-zA-Z0-9_-]{1,64}$` and reject the dot. The dual-name design stands, but
  for the provider's reason, not MCP's.
- `inputSchema` **MUST** be a valid JSON Schema object. For no parameters, use
  `{"type": "object", "additionalProperties": false}`.
- If an `outputSchema` is declared, servers **MUST** return
  `structuredContent` conforming to it, and **SHOULD** also return the
  serialized JSON as a text block for compatibility.
- The tool list **MUST NOT** vary per connection, and **SHOULD** be returned in
  a deterministic order, because clients cache it and it affects prompt cache
  hit rates. Our registry must sort explicitly.
- Errors split two ways: protocol errors for unknown tool or malformed request;
  **tool execution errors** returned as a normal result with `isError: true`,
  because "Clients **SHOULD** provide tool execution errors to language models
  to enable self-correction". Our graceful-degradation design is exactly this.

Security requirements on servers, verbatim:

> "Servers **MUST**: Validate all tool inputs · Implement proper access
> controls · Rate limit tool invocations · Sanitize tool outputs"

**Rate limiting our own tool invocations is the one we do not yet do.** A model
in a loop can exhaust the org's daily API allowance. This is now required.

## 7. Pagination

Only four operations paginate: `resources/list`, `resources/templates/list`,
`prompts/list`, `tools/list`. **`tools/call` is not among them**, so action
results paginate on our own terms, inside the result.

The cursor discipline still applies to our own cursor by analogy, and is
required for anything we do expose:

> "Clients **MUST** treat cursors as opaque tokens... Don't attempt to parse or
> modify cursors... an empty string is a valid cursor and thus **MUST NOT** be
> treated as the end of results"

Our `Pagination` model currently carries both `has_more` and `next_cursor`,
which can disagree. "More results exist" is precisely "a cursor was returned",
so `has_more` must be derived rather than stored.

## 8. Auth, for a stdio server

> "Implementations using an HTTP-based transport **SHOULD** conform to this
> specification, whereas implementations using STDIO transport **SHOULD NOT**
> follow this specification, and instead retrieve credentials from the
> environment."

Exactly what we do. And the anti-pattern the security document names first
does not apply to us, which is worth stating rather than leaving implicit:

> "MCP servers **MUST NOT** accept any tokens that were not explicitly issued
> for the MCP server."

We accept no caller tokens at all; we hold our own Salesforce credentials from
the environment.

Running locally is also endorsed:

> "MCP servers intending for their servers to be run locally **SHOULD** ... Use
> the `stdio` transport to limit access to just the MCP client"

## 9. JSON Schema handling

- **MUST** support 2020-12, which is the default when `$schema` is absent.
- **MUST NOT** automatically dereference a `$ref` that resolves to a network
  URI. Our schemas are local and self-contained, so this is satisfied by
  construction, but it must stay true.
- Composition keywords should be bounded to avoid a schema acting as a
  denial-of-service vector against the validator.

## 10. Error codes

`-32020` to `-32099` are reserved for the specification; we **MUST NOT** emit
any code in that range that the specification does not define, and **MUST NOT**
emit `-32002`, retired in this revision. Application errors belong outside the
JSON-RPC reserved range entirely — which is why our failures travel as
`isError` tool results carrying our own string codes, not as numeric protocol
errors.

---

## Work this creates

| # | Change | Where |
|---|---|---|
| 1 | Derive `has_more` from the cursor instead of storing it | `contract.py` |
| 2 | Correct the tool-name comment: providers reject the dot, MCP does not | `contract.py` |
| 3 | Rate limit our own tool invocations | new, before `mcp/server.py` |
| 4 | Elicitation approval via `InputRequiredResult`, `approved` as fallback | `connector.py`, `mcp/server.py` |
| 5 | HMAC-signed, TTL-bounded, request-bound `requestState` | new module |
| 6 | Declared `outputSchema` plus `structuredContent` and a text block | `schemas/`, `mcp/server.py` |
| 7 | Deterministic, connection-invariant tool ordering | `actions/registry.py` |
| 8 | Exit promptly on stdin EOF | `mcp/server.py` |
| 9 | Do not declare the `logging` capability | `mcp/server.py` |
| 10 | Propagate `traceparent` into the log context when present | `observability.py` |
| 11 | Verify the SDK supplies `server/discover`, `resultType`, `_meta` handling | `mcp/server.py` |
| 12 | Never describe the token as per-conversation | README, `connector.yaml` |
