# Research Notes: MCP + Multi-Provider LLM Client

Sources read in full or in targeted sweeps:
- `[LC-MCP]` https://docs.langchain.com/oss/python/langchain/mcp (WebFetch)
- `[LC-Adapters]` https://github.com/langchain-ai/langchain-mcp-adapters (WebFetch)
- `[LC-Models]` https://docs.langchain.com/oss/python/langchain/models (WebFetch; the URL `python.langchain.com/docs/how_to/chat_models_universal_init` 308-redirects here)
- `[LiteLLM-FC]` https://docs.litellm.ai/docs/completion/function_call (WebFetch)
- `[LiteLLM-cmp]` web search: TrueFoundry "LiteLLM vs LangChain" + aigearbase 2026 comparison (WebSearch)
- `[Book: AI Agents w/ MCP]` — O'Reilly early-release book, local PDF `953807192-AI-Agents-With-MCP.pdf` (extracted via `pdftotext`), Chapters 1–6 available (Ch 7–9 not included in this file). Cited as `[AAwMCP p.<line-derived>]` — page numbers aren't printed per-page in the extracted text, so I cite by chapter/section name instead.
- `[Ch09 MCP]` — "The Agentic AI Bible", Part II Chapter 9 "Model Context Protocol" (local PDF, has embedded page footers "...Chapter 9: Model Context Protocol N" — cited as `[Ch09 MCP, p.N]`)
- `[MCP-ProdEng]` — "MCP_Production_Engineering.pdf" — a 12-page NotebookLM-generated **slide-deck visual summary of the same Chapter 9 content** (confirmed by direct comparison — every slide restates a paragraph from Ch09 MCP almost verbatim). It is scanned/image-only (no text layer); read via page-render + vision. Cited as `[MCP-ProdEng, slide N]`. Treat as illustrative, not an independent source.

---

## A. MCP protocol mechanics (ground truth)

### A1. What MCP actually is

MCP is a **JSON-RPC 2.0 wire format** with a small standard library of message types for tool discovery, tool invocation, resource fetching, and prompt-template lookup. It standardizes the *envelope*, not the domain semantics — an MCP-compatible agent talking to an MCP-compatible Salesforce server still has to understand Salesforce's object model. The protocol moves integration cost from "N frameworks × M tools" bespoke glue to a single wire contract. `[Ch09 MCP, p.1-2]` `[MCP-ProdEng, slide 2]`

Core server-side capabilities (three primitives): **tools** (functions the model can call), **resources** (data the model can read), **prompts** (pre-defined, parameterized message templates the client can invoke). `[Ch09 MCP, p.2]` `[AAwMCP Ch.2]`

### A2. Tools vs Resources vs Prompts — when to use which

- **Tools** = actions/functions the model invokes to *do* something (query, write, calculate). Model-invoked, side-effect-capable, described with a JSON Schema input (and optional output schema).
- **Resources** = read-only data the model/application can *read as context*, identified by a URI (`file://`, `https://`, `git://`, or a custom scheme conforming to RFC 3986). The key distinction: resources are data to read, not operations to invoke. `[AAwMCP Ch.5 "Serving Resources"]` `[MCP-ProdEng slide 3]`
- **Prompts** = server-defined, parameterized message templates that standardize how an agent approaches a recurring task type (e.g., `analyze-financial-report(company, date_range)`), more reusable/auditable than ad-hoc system-prompt construction. `[Ch09 MCP p.5]` `[AAwMCP Ch.5]`

**For a REST API wrapper (directly relevant to the Salesforce MCP server), the split is:**
- Read/list/GET-shaped Salesforce operations that exist purely to *feed context* (e.g., "get this Account's field schema", "read this Opportunity record") → candidates for **resources**, addressed by a URI scheme you design (e.g., `salesforce://Account/{id}`), optionally as **resource templates** (parametrized URIs with `{var}` placeholders — directly analogous to a parametrized REST GET endpoint). `[AAwMCP Ch.5 "Exposing Resources", Example 5-15]`
- Anything that performs an **action** with sfide effects, or that the model needs to actively *decide to invoke* with specific arguments (SOQL query, create/update/delete record, run a report, trigger a flow) → **tools**.
- **Explicit antipattern, called out by name:** auto-generating an MCP server 1:1 from an existing REST API (one MCP tool per REST endpoint). REST APIs are granular, stateless, and polymorphic; agents do best when **one tool = one well-defined end-to-end action** with a clean input/output shape. Calling 5 REST-shaped tools to accomplish 1 logical action compounds both (a) tool-selection error rate — a 95%-accurate-per-call agent drops to ~77% success needing 5 correct picks in a row — and (b) token cost, which the book estimates can inflate ~8x in tokens / ~7x in $ versus a single well-designed tool. **Recommendation from the book:** if you must bootstrap from an OpenAPI/REST spec, use codegen only as a *first draft*, then "aggressively curate" — collapse multi-call REST flows into single agent-shaped tools, delete tools the agent doesn't need, and ideally write "agent stories" (like user stories, but from the agent's point of view) to design the tool surface from scratch. `[AAwMCP Ch.5, "Antipattern Alert: Creating MCP Servers from REST APIs"]`

**Design implication for the Salesforce MCP server:** do not wrap the Salesforce REST/Bulk API 1:1. Design a small number of task-shaped tools (e.g., `create_lead`, `find_account_by_domain`, `log_activity`, `run_report`) each doing one full logical unit of work server-side (including any multi-call REST orchestration), and expose read-heavy reference data (schema/describe metadata, picklist values, org limits) as **resources** instead of tools so the model doesn't have to "call a tool" just to get context it should already have.

### A3. Transports: stdio vs streamable HTTP vs SSE

| | stdio | Streamable HTTP | HTTP+SSE (legacy) |
|---|---|---|---|
| Topology | 1 client spawns 1 server subprocess; 2 file descriptors, no networking | 1 server process, many client sessions over a network boundary | Same as Streamable HTTP predecessor |
| State | Stateless per call by default; simple 1:1 process mapping | Optionally stateful; server can maintain a session and support **resumability** | Persistent SSE stream per session (fully stateful) |
| Status | **Current, recommended default** for local/co-located tools | **Current, recommended default** for remote/shared servers | **Deprecated / being superseded** — "being superseded by Streamable HTTP" |
| Auth | Env-var credentials (process-local trust boundary) | OAuth 2.1 required for transport developers who add authorization; bearer tokens over HTTP | Same idea, but session-per-SSE-connection makes revocation/scaling harder |
| Deployment implication | Zero network boundary; a crash affects only the one session it served | Needs standard web-service ops: process supervision, health checks, graceful shutdown draining active sessions, horizontal scaling with load-balancer **session affinity** (or resumability) | A server crash drops *every* connected session simultaneously — an alerting event |
| Latency | ~2–5ms per round trip locally (vs <1ms in-process) | Network RTT-dependent | Network RTT-dependent |

Sources: `[AAwMCP Ch.2 "transports" overview, Ch.3 "Connecting with Streamable HTTP", Ch.4 "Resuming Connections"]`, `[Ch09 MCP p.2-3]`, `[MCP-ProdEng slide 5]`.

**Verbatim on current-vs-deprecated:** *"The Python MCP SDK also includes a websocket transport and an HTTP Server-Sent Events (SSE) transport, which is being superseded by Streamable HTTP."* `[AAwMCP Ch.4]`. Anthropic's own recommendation, per the book: *"Anthropic strongly recommends that the stdio transport should always be supported, and you can add support for the streamable HTTP transport if you plan to deploy a remote server or have your application support adding remote servers."* `[AAwMCP Ch.2]`

**Streamable HTTP mechanics:** a single endpoint accepts a POST with a JSON-RPC request; the response can be either an immediate standard HTTP response, or (if both client requests it and server supports it) an SSE stream for that one exchange — i.e., SSE-per-request is now *optional*, not a standing connection, which is the core upgrade over legacy HTTP+SSE. `[AAwMCP Ch.3, "Connecting with Streamable HTTP"]` For resumability, the server can attach an `id` to each SSE event; on reconnect the client sends that as a `Last-Event-ID` header, and the SDK exposes a `_get_session_id` callback plus a `_last_event_id` you thread into `headers` on the next `streamablehttp_client(...)` call. `[AAwMCP Ch.4, "Resuming Connections", Example 4-8]`

**When to choose which** (explicit decision tree from the production-engineering source): cross-language boundary? → MCP. Organizational boundary (different team owns the tool)? → MCP. Shared external toolset (e.g., a community GitHub/Slack server)? → MCP. None of the above **and** it's a hot-loop tool called >50×/session where aggregate latency is user-visible? → **skip MCP, call the function directly in-process.** In-process call is <1ms; MCP-over-stdio adds ~2–5ms/call — for 50 calls/session that's 100–250ms added, negligible for a long-running background task but visible in an interactive UI. `[MCP-ProdEng slide 6]` `[Ch09 MCP p.9-10, "When to use MCP and when not to"]`

### A4. Full tool definition shape

A `Tool` object has: `name`, `description`, `inputSchema` (standard JSON Schema: `type`, `properties`, `required`), optional `outputSchema`, optional `annotations`, and (Python SDK) a `model_config` field. `[AAwMCP Ch.3 "list_tools()", Ch.5 Example 5-4]`

**Output schema / structured content:** declaring an `outputSchema` on a tool causes the SDK to validate the tool's return value against it before sending to the client, and to raise an error if required fields are missing/misspelled/wrong-typed. In FastMCP, `structured_output=True/False/None` on the `@mcp.tool()` decorator forces/forbids/infers structured output from the function's return-type annotation. `[AAwMCP Ch.5, Example 5-5, "structured_output" discussion]`

**Annotations (hint properties):** the Python SDK's `ToolAnnotations` object is how a tool signals hints to the client — the book explicitly names `readOnlyHint` with a worked example:
```python
@mcp.tool(
    title="Calculate GPA",
    annotations=ToolAnnotations(readOnlyHint=True),
    structured_output=False,
)
```
`[AAwMCP Ch.5, Example 5-9 area, line ~5041]`. The book does not enumerate `destructiveHint` / `idempotentHint` / `openWorldHint` by name in the text extracted — these are documented in the upstream MCP spec's `ToolAnnotations` type (readOnlyHint, destructiveHint, idempotentHint, openWorldHint) but were not found verbatim in either local source; **treat the spec/live docs as authoritative for the full annotation set** (see Contradictions section).

**Error signaling — `isError` vs protocol error:** the book's treatment is at the SDK level rather than the raw wire level: `call_tool()` returns a `CallToolResult` whose `.content` is a list of typed content blocks (`TextContent`, `ImageContent`, `AudioContent`, `EmbeddedResource`), and the wrapper pattern shown iterates `tool_call_result.content` and dispatches on `content.type` (`"text"`, `"image"`/`"audio"`, `"resource"`). `[AAwMCP Ch.3, Example ~1844-1896]`. This is a *tool-level* result (the tool ran but may represent a business-logic failure inside its content) as distinct from a *protocol-level* JSON-RPC error (`-32700` Parse error, `-32600` Invalid Request, `-32602` Invalid params) — see A6 below. The Anthropic API pattern for surfacing a tool-level failure back to the model is `{"type": "tool_result", ..., "is_error": true}` — this is Anthropic Messages-API vocabulary layered on top of MCP's content, not an MCP protocol field itself; don't conflate the two. `[claude-api skill: Tool Use Patterns]`

**Pagination:** server responses for list operations can include a `nextCursor` property; the client re-calls the same list method passing that value as `cursor` to get the next page. Only `list_resources()`, `list_resource_templates()`, `list_prompts()`, and `list_tools()` currently support pagination. `[AAwMCP Ch.4, "Paginating Results"]`

**Progress:** `send_progress_notification(progress_token, progress: float, total: float | None, message: str | None)` — sends a progress update associated with a `progress_token`; how the client renders it (progress bar, log line) is up to the client/host app. `[AAwMCP Ch.4, line ~2988]`

**Cancellation:** a notification message (from either client or server) carrying a request ID and a reason, used to cancel an in-flight request. `[Ch09 style overview]` `[AAwMCP Ch.2, line ~1046]`

**Ping:** a parameterless JSON-RPC message either side can send to check liveness. `[AAwMCP Ch.2, line ~1048]`

**List-changed notifications:** servers can push `tools/list_changed`, `prompts/list_changed`, `resources/list_changed` when their capability list changes; in the Python SDK a tool can trigger this manually via `ctx.session.send_tool_list_changed()`. Client behavior on receipt is implementation-defined but typically triggers a fresh `tools/list` call. `[AAwMCP Ch.5, line ~4951-4957]` `[AAwMCP Ch.3, line ~5580-5583 for prompts]`

### A5. Capability negotiation, initialization handshake, protocol versioning

Lifecycle has three phases: **initialization** (client/server exchange protocol version + capabilities and negotiate what the session supports) → **capability discovery** (`tools/list`, etc., returning names/descriptions/schemas) → **invocation** (`tools/call` with name+args → result). `[Ch09 MCP p.2]` `[MCP-ProdEng slide 4]`

In the Python SDK this collapses to a single call: `await self._session.initialize()`, which "handles initiating the connection to the server, advertising the client's capabilities to the server, checking the protocol version supported by the server, and telling the server that the client has been successfully initialized." `[AAwMCP Ch.3, line ~1519-1523]` On the low-level server API, capabilities are declared explicitly via `server.get_capabilities(notification_options=..., experimental_capabilities={})`, which inspects which handlers (tools/resources/prompts) are actually registered and builds a `ServerCapabilities` object included in `InitializationOptions`. `[AAwMCP Ch.5, Example 5-3 area]`

**Version negotiation:** client sends its supported protocol versions in preference order in the `initialize` request; server picks one it supports and replies with that single version. If there's no overlap, the connection fails with an explicit version-mismatch error. Per `[Ch09 MCP p.8]`, "As of April 2026, the current stable version is 2024-11-05" — **flag: this specific date string looks like a documentation/training artifact and should be verified against live MCP spec docs before being treated as current** (see Contradictions).

**Tool-level breaking-change strategy** (since MCP has no per-tool version field — the tool's `name` in `tools/list` is the only identifier): ship a breaking schema change under a **new tool name** (`search_orders` → `search_orders_v2`), run both concurrently during a migration window, retire the old name only once all clients have moved — same pattern as REST API versioning, for the same reason (no atomic-upgrade requirement). Adding a new **required** field to an existing tool's schema is *itself* a breaking change for clients that cached the old schema — the mitigation is to add new fields as **optional** with defaults, and enforce "required-ness" at the application layer instead of the JSON-Schema layer. `[Ch09 MCP p.8-9]` `[MCP-ProdEng slide 11]`

### A6. Server-side auth patterns and where credentials must NOT live

- **stdio:** trust boundary is the local OS process; credentials are best supplied via **environment variables** read by the server process. `[AAwMCP Ch.4 "Security", line ~3910-3916]`
- **Streamable HTTP / remote:** the client should use a Python **OAuth 2.1** client library; the client initiates auth after reaching the server, obtains an access token, and uses it for protected tools/resources. MCP's own spec requires transport developers who implement authorization to implement **OAuth 2.1**. `[AAwMCP Ch.2, line ~1022-1024]` `[AAwMCP Ch.4]`
- **Server-side implementation pattern (production):** implement authentication as **HTTP middleware in front of the MCP session handler** — validate a bearer token (`Authorization` header) against an identity store/JWT signing key *before* the MCP `initialize` handshake begins; on failure return **HTTP 401 before** any MCP-level exchange. Encode the client's identity **and its authorized capability scope** in the token so the `list_tools` handler can filter which tools are even *visible* to that client without a second authorization round-trip. Per-tool checks inside `call_tool` are defense-in-depth, not a substitute for the transport-layer gate. `[Ch09 MCP p.6]` `[MCP-ProdEng slide 9]`
- **Where secrets must NOT live:** MCP's protocol layer defines **no** authentication, authorization, or rate limiting at all — "a client that can reach an MCP server can call any tool it exposes." This is fine for local stdio (OS-process boundary *is* the security boundary) but is a **hard requirement gap** for any HTTP-exposed server — you must build it yourself. `[Ch09 MCP p.6]`
- **Capability scoping as a first line of defense:** discovery is all-or-nothing by default — *every* connected client sees *every* tool the server exposes, including destructive ones, unless you (a) run separate server instances with different tool sets per audience, or (b) implement per-client filtering inside `list_tools` keyed off the authenticated identity/scope from the token. `[Ch09 MCP p.6]`

---

## B. LangChain side (langchain-mcp-adapters / MultiServerMCPClient)

### B1. Core model

`MultiServerMCPClient` is **stateless by default**: *"Each tool invocation creates a fresh MCP `ClientSession`, executes the tool, and then cleans up."* `[LC-MCP]` It accepts a dict mapping server-name → transport config, and exposes `get_tools()`, `get_resources()`, `get_prompt()` — all **async**. There is no documented synchronous wrapper — everything is `await`-based. `[LC-MCP]`

### B2. Verbatim connection config (from the LangChain MCP page)

```python
client = MultiServerMCPClient({
    "math": {
        "transport": "stdio",
        "command": "python",
        "args": ["/path/to/math_server.py"],
    },
    "weather": {
        "transport": "http",
        "url": "http://localhost:8000/mcp",
    }
})
tools = await client.get_tools()
agent = create_agent("claude-sonnet-4-6", tools)
```
`[source: docs.langchain.com/oss/python/langchain/mcp]`

Equivalent stdio/http config forms from the adapters repo itself:
```python
# stdio
client = MultiServerMCPClient({
    "math": {
        "command": "python",
        "args": ["/path/to/math_server.py"],
        "transport": "stdio",
    },
})

# streamable http, with auth headers
client = MultiServerMCPClient({
    "weather": {
        "transport": "http",
        "url": "http://localhost:8000/mcp",
        "headers": {
            "Authorization": "Bearer YOUR_TOKEN",
            "X-Custom-Header": "custom-value",
        },
    }
})
```
`[source: github.com/langchain-ai/langchain-mcp-adapters]`. SSE is a supported transport key (`"transport": "sse"`) following the same header-bearing HTTP-like shape, but the adapters docs mark it same family as HTTP rather than giving it distinct first-class examples — consistent with the book's framing of SSE as the legacy/superseded transport (A3).

### B3. Session lifecycle: stateless vs stateful

**Stateless (default, per-tool-call session):**
```python
tools = await client.get_tools()
```
**Stateful (explicit persistent session, needed when a tool must share server-side state across calls):**
```python
async with client.session("math") as session:
    tools = await load_mcp_tools(session)
```
Or fully manual, going straight to the MCP SDK primitives:
```python
async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await load_mcp_tools(session)
```
`[source: github.com/langchain-ai/langchain-mcp-adapters]`

### B4. Tool conversion and error propagation

- `client.get_tools()` (or `load_mcp_tools(session)`) converts MCP `Tool` objects into LangChain `Tool`/`BaseTool` objects automatically, handling multimodal content (text/images) and wrapping structured content in an `MCPToolArtifact`. `[LC-MCP]`
- **Default error behavior:** a tool execution error comes back as a LangChain `ToolMessage` with `status="error"` (`handle_tool_errors=True` is the default) — i.e., the *agent loop keeps running* and the model sees the failure as a normal turn, rather than the whole chain raising. Set `handle_tool_errors=False` (on `load_mcp_tools(session, handle_tool_errors=False)` or on the `MultiServerMCPClient` constructor) to get the old behavior of raising a `ToolException` instead. **Transport/session failures always raise** regardless of this flag — only *tool-level* errors are catchable this way. `[LC-MCP]` `[source: github.com/langchain-ai/langchain-mcp-adapters]`

### B5. Advanced features worth knowing

- **Interceptors:** middleware-like functions that wrap tool execution — can inject runtime context, update graph state via `Command`, modify headers, and implement retry/backoff logic around a tool call. `[LC-MCP]`
- **Progress notifications:** subscribe via `Callbacks(on_progress=...)` for long-running MCP operations — this is the LangChain-side hook onto the MCP progress-notification primitive from A4. `[LC-MCP]`
- **Logging callbacks:** `on_logging_message` surfaces MCP server-side log messages to the LangChain client.
- **Elicitation:** when a server asks the user for input mid-tool-call, the client responds via an `on_elicitation` callback with `accept` / `decline` / `cancel`.

### B6. Binding tools to a model — what it implies for design

Tools loaded from `get_tools()` are plain LangChain `BaseTool` objects, so they compose with the rest of the LangChain tool-calling surface unchanged: pass them to `create_agent(model, tools)` (prebuilt agent loop) or to `model.bind_tools(tools)` directly for a manual loop (see C-section — `bind_tools` is exactly the mechanism that also normalizes tool schemas per-provider). **Design implication:** because MCP tool objects convert into the *same* `BaseTool` shape LangChain uses for hand-written tools, the provider-agnostic layer (`init_chat_model` + `bind_tools`) sits **above** the MCP layer and is completely unaware that a given tool's implementation happens to live behind an MCP server — this is the seam that makes "any provider ↔ our MCP server" work: MCP standardizes the tool-supply side, `bind_tools`/`BaseChatModel` standardizes the model-consumption side, and LangChain's tool-calling loop is the connective tissue in the middle.

---

## C. THE KEY QUESTION — provider-agnostic client

### C1. Options compared

| Approach | What it is | Tool-schema normalization | Streaming | Message format | Retries / rate limits | Cost/token accounting |
|---|---|---|---|---|---|---|
| **(a) LangChain `init_chat_model` / `BaseChatModel`** | A factory that returns a `BaseChatModel` subclass per provider, selected by a `"{provider}:{model}"` string or model-name inference; every subclass implements the same interface (`invoke`, `stream`, `batch`, `bind_tools`). `[LC-Models]` | `bind_tools()` on any `BaseChatModel` converts a **provider-agnostic tool description (LangChain `Tool`/pydantic schema)** into that provider's native tool-calling wire format internally, and normalizes `response.tool_calls` back to a single shape regardless of provider. `[LC-Models]` | `invoke()`/`stream()`/`batch()` are uniform methods across every provider package. | Each provider package translates LangChain's internal message objects (`HumanMessage`, `AIMessage`, `ToolMessage`, `SystemMessage`) to/from that provider's wire message shape. | Provider packages have their own retry/backoff (e.g., `max_retries` param on `init_chat_model`, default 6). | Not unified out of the box — usage accounting is per-provider-package; LangChain doesn't itself impose a billing ledger. |
| **(b) LiteLLM-style unified gateway** | A single `completion()` function (or an OpenAI-compatible proxy server) that maps ~100+ providers onto **one wire shape modeled on the OpenAI Chat Completions API**. `[LiteLLM-FC]` `[LiteLLM-cmp]` | `tools` param is OpenAI's `{"type":"function","function":{...}}` shape for every provider; LiteLLM translates to/from each provider's native tool format under the hood; response always exposes `response.choices[0].message.tool_calls` in OpenAI shape. `[LiteLLM-FC]` | Uniform streaming interface, OpenAI-shaped SSE-style chunks regardless of backend. | Everything coerced to OpenAI chat message shape (`role`/`content`), including system-prompt handling. | LiteLLM's proxy adds automatic failover/retries and rate-limit/cost tracking as first-class features — this is a large part of its value proposition. `[LiteLLM-cmp]` | Built-in cost tracking / budget management is a first-class LiteLLm feature (part of why teams pick it over LangChain for pure multi-provider routing). `[LiteLLM-cmp]` |
| **(c) Hand-rolled provider adapter interface** | You define your own `LLMClient` protocol (e.g., `.chat(messages, tools) -> Response`) and write one adapter per provider SDK. | 100% your responsibility — you must track every provider's tool-schema quirks yourself (see C3) and keep adapters in sync as providers change their APIs. | Your responsibility. | Your responsibility. | Your responsibility (though you can lean on each provider's official SDK's built-in retry). | Your responsibility. |
| **(d) OpenAI-compatible endpoint assumption** | Treat every provider as if it speaks the OpenAI Chat Completions wire format (many providers — Mistral, Groq, Ollama, some Gemini-compat shims, self-hosted vLLM/TGI — offer an OpenAI-compatible endpoint). You point one OpenAI SDK client at different `base_url`s. | Works **only** for providers that actually ship an OpenAI-compatible surface; Anthropic and native Gemini/Cohere do **not** — you'd need a shim (which is effectively re-deriving option (b) or (c) yourself) for those. | Works for the compatible subset; breaks silently for the rest (different streaming event shapes, different finish-reason semantics). | Works for the compatible subset. | Whatever the OpenAI SDK's client-side retry does; server-side behavior varies per compatible backend. | Whatever `usage` fields the compatible backend actually populates — very inconsistent in practice (many self-hosted backends fill this in partially or not at all). |

### C2. Recommendation

**Primary recommendation: (a) LangChain `init_chat_model` + `BaseChatModel` + `bind_tools`.** Rationale specific to this project:
1. We are *already* building on LangChain for the MCP client side (`langchain-mcp-adapters`, `MultiServerMCPClient`) — tools loaded from MCP already arrive as LangChain `BaseTool` objects (§B6). Using LangChain's own model abstraction means **zero glue code** between "tool comes from MCP" and "tool gets bound to whatever provider the user picked" — it's the same `BaseTool` object handed to `bind_tools()` regardless of which `BaseChatModel` subclass is in play.
2. `init_chat_model("{provider}:{model}")` is a **one-line provider switch** with no application-logic changes, which is exactly the stated goal ("one client that can accept the API of ANY LLM provider"). `[LC-Models]`
3. It keeps us on each provider's **native, first-party SDK semantics** underneath (via each LangChain integration package), so provider-specific features (e.g., Anthropic prompt caching, extended thinking) remain reachable via provider-specific kwargs / `.bind()` extras, rather than being flattened away by a lowest-common-denominator OpenAI-shaped gateway.

**Second-best: (b) LiteLLM-style unified gateway**, specifically if/when any of these become true:
- We need **first-class cost/budget tracking and cross-provider rate-limit management** as an operational concern (LiteLLM's proxy has this built in; LangChain does not). `[LiteLLM-cmp]`
- We want **99+ provider coverage** including many long-tail/self-hosted backends with minimal integration work (LiteLLM ~100+ providers vs LangChain's ~60, per community comparisons — **medium-confidence, community source, verify against current provider-count pages before quoting externally**). `[LiteLLM-cmp]`
- We want a **language-agnostic proxy boundary** (LiteLLM can run as a standalone OpenAI-compatible HTTP proxy, so a non-Python caller, or a caller in a different service, can talk to "any provider" without embedding LangChain at all).

Trade-off to state explicitly: choosing LiteLLM as the *model* layer while keeping LangChain's `MultiServerMCPClient` as the *tool* layer means giving up the direct `BaseTool → bind_tools` seam described in B6 — you'd instead have to convert MCP tools into LiteLLM/OpenAI-shaped `tools` JSON yourself (LiteLLM expects the same `{"type":"function","function":{...}}` shape MCP's own `inputSchema` already resembles, so this conversion is mechanical but is still a piece of glue code LangChain gives you for free).

**Not recommended as primary:** (c) hand-rolled adapters (highest long-term maintenance cost, no upside over (a) unless you have exactly one or two providers and want zero dependencies) and (d) OpenAI-compatible-endpoint-assumption (silently breaks the moment someone points it at Anthropic/native Gemini/Cohere — too fragile for a project whose explicit requirement is "ANY LLM provider").

### C3. What breaks when you swap providers — concrete failure modes to design around

These are the specific normalization gaps that (a)/(b) each paper over to different degrees, and that a hand-rolled (c) must handle explicitly:

1. **Tool name constraints differ per provider.** Different providers enforce different regex/length limits on function/tool names (e.g., alphanumeric + underscore only, length caps around 64 chars is a common ballpark across providers). A tool name derived from a Salesforce object/field name with special characters can pass validation on one provider and be rejected on another. **Design implication:** sanitize/normalize tool names in the MCP→LLM conversion layer to the *strictest* common denominator, not the loosest.
2. **Parallel tool calls** are supported by some providers/models and not others (or are supported but must be explicitly enabled/disabled, e.g., Anthropic's `disable_parallel_tool_use`). Code that assumes "the model returns 0 or 1 tool call" breaks when swapped onto a provider/model that returns several `tool_use` blocks in one turn.
3. **Strict-schema / guaranteed-valid-JSON support** is not universal. Anthropic's `strict: true` and OpenAI's structured-output/strict mode guarantee the tool call's arguments validate against your JSON Schema; providers without an equivalent can return malformed or partially-conforming arguments, so a provider-agnostic layer must **always** defensively parse (`json.loads`) and validate tool-call arguments rather than trusting them — this is stated explicitly for MCP tool-call JSON too: *"Always parse tool inputs with `json.loads()` / `JSON.parse()` — never do raw string matching on the serialized input"* because different models escape Unicode/forward-slashes differently. `[claude-api skill: Common Pitfalls]`
4. **Max tool count** — very large tool lists (tens to low hundreds) degrade tool-selection accuracy on every provider, but the *threshold* and the failure mode (silent wrong-tool-pick vs an outright API error for exceeding a hard limit) differ by provider/model. The MCP book's own worked example: 95%→77% success dropping from 1 to 5 required correct tool picks is a *selection-accuracy* argument for keeping tool count low regardless of provider, independent of any hard API ceiling. `[AAwMCP Ch.5, antipattern section]`
5. **System-prompt handling** varies: some providers accept a dedicated `system` field, others expect the system prompt folded into the first message; some support inserting an operator-role message mid-conversation (e.g., Anthropic's `role: "system"` mid-conversation messages on supported models) and others don't — a provider-agnostic layer needs a system-prompt strategy with a documented fallback (e.g., collapse into a leading user-turn `<system-reminder>` block) for providers that don't support one of these mechanisms.
6. **Tool-result / tool-call block shape in message history** differs at the wire level (OpenAI: `tool_calls` array on the assistant message + `role: "tool"` follow-up messages keyed by `tool_call_id`; Anthropic: `tool_use` content blocks + `tool_result` content blocks keyed by `tool_use_id`) — LangChain's `AIMessage.tool_calls` / `ToolMessage` is the normalized shape that absorbs this difference (§C1a); a hand-rolled adapter must reimplement this translation per provider.
7. **Streaming event shapes** differ (OpenAI-style delta chunks vs Anthropic's `content_block_start/delta/stop` + `message_delta` event taxonomy) — `BaseChatModel.stream()` normalizes this in LangChain; LiteLLM normalizes it to OpenAI-shaped chunks for every backend.
8. **Retries/rate-limits** are provider-specific in trigger condition (429 vs 529 "overloaded" vs a provider-specific error code) and in backoff guidance (`retry-after` header support varies) — this is exactly the kind of cross-cutting concern LiteLLM's proxy centralizes, and that a LangChain-only approach leaves to each provider package's own (usually reasonable, but inconsistent) defaults.
9. **Cost/token accounting fields** differ in name and granularity (e.g., Anthropic's `cache_creation_input_tokens`/`cache_read_input_tokens` vs a provider with no prompt-caching concept at all) — a provider-agnostic cost ledger needs a normalized usage schema with optional/nullable provider-specific fields, not a single fixed set of counters.

---

## D. Production hardening for MCP servers

Consolidated from `[Ch09 MCP]`, `[MCP-ProdEng]`, and `[AAwMCP]`:

**Timeouts.** stdio tool calls have **no built-in client-side timeout** — a hung tool call blocks the agent loop indefinitely unless the client wraps it itself (`asyncio.wait_for` or equivalent). HTTP-transport calls eventually surface a transport-level timeout (HTTP 504 or a connection error) on their own. Either way, the client's correct response is to **return the timeout as an observation to the model** (error category + transport type + elapsed time) so the model can decide to retry/escalate — not to silently hang or silently retry forever. `[Ch09 MCP p.4]` `[MCP-ProdEng slide 7]`

**Retries.** Distinguish **protocol-level** errors from **transient** ones: `-32700`/`-32600` (malformed JSON-RPC) are client *code bugs* — log and do **not** retry. `-32602` (schema mismatch, e.g. server added a new required field mid-session while the client held a stale cached schema) is a **staleness signal** — the correct response is to re-call `tools/list` to refresh the schema, then retry the call once with updated arguments; treat it as staleness, not permanent failure. `[Ch09 MCP p.4]` `[MCP-ProdEng slide 7]`

**Idempotency.** Not covered explicitly as a named concept in either local source, but implied by the annotation system (A4): a tool's `readOnlyHint`/`destructiveHint`/`idempotentHint` (per upstream MCP spec — see Contradictions) should drive whether your client auto-retries a failed call without confirmation. A tool with no idempotency guarantee should never be blindly retried by client-side logic after an ambiguous failure (e.g., a network drop *during* the server-side write, where you don't know if the write landed) — this is a general "treat writes to Salesforce with the same caution as any external side-effecting API call" concern the project must design explicit idempotency keys for on any create/update tool.

**Rate limits.** Not covered in MCP-protocol terms by the local sources (MCP itself defines none — see A6) — this is squarely an application/server responsibility: rate-limit at the HTTP-middleware layer alongside auth, before requests reach the MCP session handler. `[Ch09 MCP p.6]`

**Logging / observability.** **Audit-log every tool invocation**, implemented as a wrapper around `call_tool` that logs before dispatching and after returning *regardless of success/failure*. Log entry should include: calling client's identity (from the auth token), tool name, **sanitized** arguments (redact secrets/PII), result status (success or error category), and elapsed time. This is both the forensic record for security incidents and the primary diagnostic source for production bugs. `[Ch09 MCP p.6-7]` `[MCP-ProdEng slide 9]`

**Secrets handling.** Never in tool arguments/results that get logged unredacted; never hardcoded in server code; env-var injection for stdio, OAuth 2.1 token flow for HTTP (A6). Explicit anti-pattern to avoid: silently swallowing a server crash and returning an empty tool result — "the most dangerous error handling choice because it allows the model to proceed as though the tool succeeded." `[Ch09 MCP p.4-5]`

**Prompt-injection risk coming back through tool results.** This is treated as a first-class threat model, not an edge case: *"An attacker who controls an MCP server can return arbitrary content in tool results. That content is injected into the model's context and interpreted as observations from the environment."* Concretely: instructions embedded in tool output that the model follows; false factual claims the model treats as ground truth; content engineered to manipulate the model's next tool choice. **The protocol provides zero protection against this.** Mitigation is architectural, not protocol-level: (1) explicit system-prompt instruction that tool results are *observations to reason about*, never *instructions to follow*, and that any apparent instruction inside a tool result should be treated with the same suspicion as an instruction from an unknown third party; (2) **wrap any user-controlled content a tool returns in an explicit delimiter** (e.g., `<user_content>...</user_content>`) and instruct the model that content inside those delimiters is data, not instructions. `[Ch09 MCP p.7]` `[MCP-ProdEng slide 10, "Threat Modeling: The Compromised Server"]`

**Sandboxing.** Run MCP servers handling sensitive operations in **Docker containers**: read-only filesystem except explicitly-mounted data directories, network egress restricted to an allowlist of destinations, process runs as **non-root** with minimal capabilities. The protocol enforces none of this — it's entirely an operational choice, and many teams only adopt it *after* a security incident forces the issue. `[Ch09 MCP p.6]` `[MCP-ProdEng slide 9]`

**Supply-chain risk (third-party MCP servers).** Treat a community/vendor MCP server with the same scrutiny as a third-party npm/PyPI package with network access: a compromised server can exfiltrate data from every tool-call argument it receives, inject malicious content into tool results, and persist in your environment for the life of the compromised version. Mitigations: **audit source before deploying, pin to a specific commit/release, review every version-upgrade diff before applying, run in a sandboxed environment with restricted blast radius.** `[Ch09 MCP p.7]` `[MCP-ProdEng slide 10]`

**Testing strategy.** The book (Chapter 5+) points at **MCP Inspector** — an official web UI/proxy client that connects to a server over any transport and lets you visually list/call tools, send pings, and exercise sampling/elicitation flows for manual testing — plus repurposing traditional AI-system **evaluations** for server-level testing (tool-selection accuracy, schema-validity of outputs, etc.). `[AAwMCP Ch.2, "MCP Inspector"; Ch.5 intro, "testing your server... MCP Inspector... evaluations"]`. Chapter 7, "Testing, Securing, and Sharing Your MCP Server," is the book's dedicated chapter on this topic but was **not available** in the extracted PDF (marked "(unavailable)" in the table of contents) — treat this as a documented gap, not an omission on my part; if deeper testing-strategy detail is needed, pull the finished/paid edition of this book or the live O'Reilly page.

**Common pitfalls (explicit checklist from the sources):**
- Assuming tool discovery is compile-time — it's runtime; if the server isn't up when the client connects, discovery silently fails and the agent proceeds with zero tools unless you add a startup health check. `[Ch09 MCP p.9]` `[MCP-ProdEng slide 11]`
- Using HTTP transport for co-located/local tools — pure added latency with no benefit; use stdio.
- Not sanitizing tool results containing user-controlled content — wrap in delimiters (see prompt-injection above).
- Exposing an entire database (or, for us, entire Salesforce org) as MCP resources with no per-resource authorization — design the resource URI namespace so authorization is natural to enforce (e.g., prefix URIs with owning-entity/tenant identifiers) and check it in the `resources/read` handler. `[Ch09 MCP p.10]`

---

## DESIGN DECISIONS THIS FORCES

1. **Transport for the Salesforce MCP server.** Options: stdio-only, streamable-HTTP-only, or both. **Recommendation:** support **both**, stdio as the default/always-on baseline (per Anthropic's own guidance in §A3) for local/dev use and for any host application that can co-locate the server, plus streamable HTTP for any deployment where the server needs to be reachable remotely or shared across multiple agent instances/users (which is likely, given Salesforce credentials are typically org-wide, not per-laptop). Do **not** build SSE — it's the deprecated predecessor.

2. **Tool surface design.** Options: (a) auto-generate tools 1:1 from the Salesforce REST API, (b) hand-design a small set of task-shaped tools. **Recommendation: (b), explicitly.** Per §A2, 1:1 REST wrapping is a named antipattern with a quantified cost (accuracy drop, ~7-8x token/cost inflation). Design tools around agent-relevant tasks (e.g., `find_or_create_contact`, `log_call_activity`, `run_soql_report`) each doing one full logical unit of work, potentially orchestrating multiple underlying Salesforce API calls server-side so the *model* only ever sees one tool call.

3. **Tools vs resources split for Salesforce data.** **Recommendation:** expose read-only reference/context data (object schemas, picklist values, field metadata, org limits, maybe recently-viewed records) as **MCP resources** with a `salesforce://` URI scheme and resource templates for parametrized lookups; reserve **tools** for anything the model must actively decide to invoke with specific write or query intent.

4. **Auth architecture.** **Recommendation:** implement Salesforce OAuth (likely a connected-app JWT-bearer or OAuth 2.0 web-server flow, held server-side) **plus** a separate MCP-transport-level bearer-token auth layer as HTTP middleware in front of the MCP session handler (per §A6) — these are two different auth concerns (the server's own credential to talk to Salesforce vs. the MCP client's credential to talk to *this* server) and must not be conflated. Store the Salesforce credential as a server-side secret (env var / secrets manager), never passed through as an MCP tool argument.

5. **Provider-agnostic LLM client architecture.** **Recommendation: LangChain `init_chat_model` + `BaseChatModel.bind_tools()`** as the primary abstraction (§C2), specifically because it composes directly with `MultiServerMCPClient`'s `BaseTool` output with zero glue code. Revisit LiteLLM only if cost/budget tracking or 100+-provider coverage becomes a hard requirement.

6. **Defensive tool-call parsing.** **Recommendation:** regardless of provider, always `json.loads()`/validate tool-call arguments defensively (§C3.3) rather than trusting provider-side strict-schema guarantees, since not all providers offer them and even those that do can be bypassed by a misconfigured client.

7. **Tool-name normalization layer.** **Recommendation:** build a single name-sanitization function in the MCP→LLM conversion path (strip/replace characters outside `[A-Za-z0-9_-]`, enforce a conservative length cap e.g. 64 chars) applied uniformly regardless of which provider is active, to avoid provider-specific silent tool-registration failures (§C3.1).

8. **Prompt-injection defense for tool results.** **Recommendation:** every tool result returned by the Salesforce MCP server that contains user-authored or externally-sourced text (case notes, email bodies, chatter posts) must be wrapped in an explicit delimiter (e.g. `<salesforce_data>...</salesforce_data>`) and the system prompt must explicitly instruct the model to treat delimited content as untrusted data, never as instructions (§D, prompt-injection).

9. **Idempotency for write tools.** **Recommendation:** every write-capable tool (`create_*`, `update_*`) should accept or generate an idempotency key and the server should de-duplicate on it, since MCP itself provides no delivery guarantees and client-side retry-after-timeout is a documented, expected failure mode (§A4 timeouts, §D idempotency).

10. **Sandboxing/deployment posture.** **Recommendation:** run the Salesforce MCP server in a container with non-root execution and an explicit network egress allowlist (Salesforce API domains only), matching the production-hardening guidance in §D, given it holds live Salesforce credentials.

---

## CONTRADICTIONS / STALE INFO

- **MCP protocol version date.** `[Ch09 MCP p.8]` states *"As of April 2026, the current stable version is 2024-11-05."* This date pairing looks internally inconsistent (a 2024-dated spec version being called "current" as of April 2026 is plausible only if no newer spec version shipped in the interim, which is unlikely given MCP's fast iteration pace described elsewhere in the same sources). **Live MCP spec docs (modelcontextprotocol.io/specification) are authoritative here, not this book** — verify the current protocol version string before hardcoding it anywhere (e.g., in `initialize` request construction).
- **Tool annotation set (readOnlyHint/destructiveHint/idempotentHint/openWorldHint).** Neither local source enumerates all four hint properties verbatim — `[AAwMCP]` only demonstrates `readOnlyHint`. The task brief presumes all four are current MCP spec fields; **treat live MCP spec / TypeScript-SDK type definitions as authoritative** for the complete `ToolAnnotations` shape rather than either local source.
- **SSE deprecation language.** `[AAwMCP]` uses the softer "being superseded by Streamable HTTP" (implying continued, if discouraged, support), while `[LC-MCP]` (live LangChain docs, fetched fresh) says *"Earlier documentation mentions SSE (deprecated by MCP spec)"* — a stronger "deprecated" framing. **The live LangChain docs are more current and should be treated as authoritative**; do not build new SSE support regardless of which framing is technically more precise.
- **`MCP_Production_Engineering.pdf` is not an independent source.** On inspection (all 12 pages viewed as rendered images, since the PDF is scanned/image-only with no text layer), it is a NotebookLM-generated slide-deck restating `Chapter 09 - Model Context Protocol.pdf` almost paragraph-for-paragraph. I have **not** double-counted it as a second independent citation anywhere above where it would materially change confidence — it corroborates but does not add new ground truth beyond Ch09.
- **LiteLLM "~100 vs ~60 providers" figures.** Sourced from a WebSearch aggregation of third-party comparison blogs (TrueFoundry, aigearbase — both dated "2026" but of unverified authorship/rigor), not from LiteLLM's or LangChain's own docs. **Medium-to-low confidence** — treat as directionally indicative ("LiteLLM covers more long-tail providers") rather than a number to cite externally without re-verification against each project's own current integrations list.
- **`python.langchain.com/docs/how_to/chat_models_universal_init` no longer exists** as a live URL — it 308-redirects to `docs.langchain.com/oss/python/langchain/overview`, and the actual `init_chat_model` content now lives at `docs.langchain.com/oss/python/langchain/models`. Any older bookmarks/notes pointing at the `python.langchain.com/docs/how_to/...` URL tree are stale; the `docs.langchain.com/oss/...` tree is current.
