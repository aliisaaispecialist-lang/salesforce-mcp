# Research 07: Sample Code Repo Hunter — Books' Referenced Repos + Authoritative MCP Repos
### For the Salesforce MCP server (~40+ REST endpoints exposed as LLM tools, provider-agnostic client)

Method: PDF text extracted with `pdftotext -layout` (poppler, via mingw64) for all text-layer PDFs; PyMuPDF (`fitz`) used as a fallback for two zero-text-layer PDFs, confirming they are genuinely image-only. Every extracted `.txt` was grepped for `https?://`, `github`, `gitlab`, `bitbucket`, `pypi`, `pip install`, `git clone`. All candidate repo URLs were then checked live via `curl -o /dev/null -w "%{http_code}"` and the GitHub REST API (`api.github.com/repos/...`), not assumed from book text. Repo contents were read via `raw.githubusercontent.com` and `api.github.com/repos/.../contents`. No repository was cloned locally — reading raw files over HTTPS was sufficient and faster; the `research/repos/` clone folder was not needed. No downloaded code was executed.

---

## 1. REPOS FOUND IN THE BOOKS

| Book / PDF | Location | URL | Resolves? | What's in it |
|---|---|---|---|---|
| *The Agentic AI Bible* — `00 - Front Matter.pdf` | "The companion repository" section, p.4 | `https://github.com/trcaldwell/agentic-ai-bible` | **200 OK** | The author's canonical companion repo. Real GitHub repo, `agentic-ai-bible`, owned by user `trcaldwell`, Apache/MIT not set (`license: null`), 1 commit (`7de080e…`, msg "Initial release: companion code for The Agentic AI Bible", 2026-05-13). Populated: `chapters/ch01`–`ch21/`, `appendix_d/`, `resources/`, `.github/workflows/ci.yml`, `requirements.txt`, `CHANGELOG.md`, `README.md`. Confirmed real files exist (fetched `ch09_02_mcp_server.py`, `ch06_04_order_info.py`, READMEs — see §4). **Curiosity, not load-bearing**: front matter signs off "Thomas R. Caldwell", but the repo's own README says "by Jordan Caldwell" — an internal inconsistency in the source material, noted for completeness. |
| *The Agentic AI Bible* — `Practice-Questions-and-Code.pdf` | Intro, p.1, and per-exercise "Source (your fork)" links throughout | `https://github.com/aliisaaispecialist-lang/agentic-ai-bible` | **200 OK** | A **fork** of `trcaldwell/agentic-ai-bible`, explicitly labeled "(your fork)" — this appears to be a personalized/reader-specific fork baked into this particular copy of the PDF, not a separate canonical resource. Same directory structure as the parent. Confirmed a real file resolves at `.../blob/main/chapters/ch03/ch03_01_web_search.py` (a ReAct-style research agent using Brave Search + Anthropic Messages API). Given it's a fork with only the parent's single initial commit, **treat `trcaldwell/agentic-ai-bible` as the canonical source and this as informational only.** |
| *The Agentic AI Bible* — every code file's docstring header, both PDFs above | e.g. ch03/ch06/ch09 file headers: `"Companion repository: github.com/agentic-ai-bible/code"` | `https://github.com/agentic-ai-bible/code` | **404 — DEAD** | Referenced by ~40 repeated file-header comments across the Practice-Questions PDF but the org/repo does not exist. This is boilerplate baked into every code file's docstring and was never updated to point at the real repo (`trcaldwell/agentic-ai-bible`). **Do not use this URL — it is a dead link left in copy-paste boilerplate.** |
| O'Reilly early-release, `953807192-AI-Agents-With-MCP.pdf` (Kyle Stratis, *AI Agents with MCP*, ISBN 9798341639546) | Ch.1 and Ch.3 preambles: "There is a GitHub repository in progress with code examples" / "You can find this script and all other code for this chapter in ch3 in the book's Github repo." | **No URL given in text** — the "Using Code Examples"-equivalent preface never states the repo URL explicitly (unusual for O'Reilly; likely an artifact of this being an early-release draft). Located via web search instead: `https://github.com/kylestratis/ai_agents_mcp_examples` | **200 OK** (found via search, not text) | MIT license, 56 stars / 25 forks, last pushed 2026-07-15. Real, actively maintained. **Flagged as inferred, not confirmed in-text** — the PDF itself never prints this URL, so treat the book→repo mapping as probable-but-unconfirmed. The same author's GitHub also hosts `spotify-mcp` and `making-intelligent-apps-agentic` (workshop code for MCP-driven agentic apps), both plausibly relevant but not directly cited by this book. |
| Further-Reading.pdf | MCP section, "Python SDK" and "MCP Servers" rows | `https://github.com/modelcontextprotocol/python-sdk` and `https://github.com/modelcontextprotocol/servers` | **200 / 200** | These are exactly the two authoritative repos independently mandated in Phase 2 — the book's own further-reading list agrees with the brief. See §3. |
| Further-Reading.pdf | MCP section, "awesome-mcp-servers" row | `https://github.com/wong2/awesome-mcp-servers` | **200 OK** | Community-maintained curated index of third-party MCP servers. Useful for a broader competitive scan later; not read in depth here (index page, not a server to imitate). |
| Practice-Questions-and-Code.pdf, Ch.9 exercises | Exercise 37 | `github.com/modelcontextprotocol/servers` (same as above, cited again as an exercise prompt: "Connect an open-source MCP server ... to the [agent]") | 200 | Confirms the book itself points students at the official servers repo for real examples — reinforces §3 as the right place to study, not the book's own toy examples. |

**Repos found but explicitly NOT used as sources** (dead or out of scope): `github.com/agentic-ai-bible/code` (404, dead boilerplate, above).

---

## 2. BOOKS WITH NO REPO REFERENCE

Swept in full (pdftotext -layout, text-layer confirmed present, then grepped for `https?://|github|gitlab|bitbucket|pypi`) — **zero matches, confirmed by direct re-grep of each file individually**, not just absence from a combined listing:

- `C:\Users\Admin\Desktop\The Agentic AI Bible - PDF\Part 2 - Core Capabilities\Chapter 06 - Tool Use and Function Calling\Chapter 06 - Tool Use and Function Calling.pdf` — chapter prose has no repo/URL references at all (all its code listings point at the companion repo only via the *other* PDFs above, not from within this chapter file itself).
- `C:\Users\Admin\Desktop\books\clean code and coding\Clean-Code-Zero-to-One-Shahan-Chowdhury.pdf` — no URLs of any kind.
- `C:\Users\Admin\Desktop\books\Agentic ai\903842879-Agentic-Ai-Frameworks.pdf` — no URLs of any kind (165KB of extracted text, framework-comparison content, no citations to source repos for the frameworks it discusses).
- `C:\Users\Admin\Desktop\books\Agentic ai\935719040-agentic-ai.pdf` — thin book (9 pages, 14.6K chars via PyMuPDF after pdftotext initially undercounted it), no URLs.

**Chapter 09 — Model Context Protocol.pdf** (`Part 2 - Core Capabilities\Chapter 09...`) is **not** repo-reference-free — it names `github.com/modelcontextprotocol/python-sdk`, `github.com/modelcontextprotocol/servers`, and `github.com/wong2/awesome-mcp-servers` directly in-chapter (see §1/§3), plus references "the Python SDK's Github repository" generically at line 5856 of the extracted text.

**Image-only PDFs — no text layer, confirmed by both `pdftotext` (0 lines) and PyMuPDF (0 extracted chars); both are lower-priority "companion slide deck" PDFs, not top-priority, so per instructions they were not rendered to images and read visually:**
- `Part 2 - Core Capabilities\Chapter 06...\Production_LLM_Tool_Architecture.pdf` (14 pages, pure infographic deck)
- `Part 2 - Core Capabilities\Chapter 09...\MCP_Production_Engineering.pdf` (12 pages, pure infographic deck)

(A prior research pass — `research/04-tool-design-and-security.md` — already rendered and read the *Chapter 06* and *Chapter 16* companion decks visually; the two above were not among those, and given they're marked lower-priority in this task's brief, they were left unread this round. If their content becomes load-bearing later, they can be rendered to PNG and read visually the same way.)

**`clean-code-book.pdf`** (Robert C. Martin, *Clean Code*) — technically has ~20 URL hits, but every one is a historical footnote/citation link (Wikipedia articles, `objectmentor.com`, `pragmaticprogrammer.com`, JFreeChart project pages, IEEE DOIs) — **no companion source-code repository is referenced**; the book predates GitHub-era companion-repo conventions. Treated as "no repo reference" for this hunt's purposes.

**`AI-Engineering-System-Guidebook.pdf`** (DailyDoseofDS.com) — has URLs but none are repos: a Bit.ly assessment link, an exchangerate-api.com signup link, `localhost` dev-server examples, and a `pip install litellm` instruction. It discusses building MCP servers with **`mcp-use`** (a wrapper toolkit) and its `mcp-use.run` tunneling service, and demonstrates multi-provider LLM calls via **LiteLLM** (`from litellm import completion`) — genuinely useful pattern material (see §4) but not a repo citation.

---

## 3. AUTHORITATIVE REPOS

All four mandated repos found and read; metadata pulled live via `api.github.com`, not assumed.

| Repo | Resolves? | Stars | Last push | License | Notes |
|---|---|---|---|---|---|
| `modelcontextprotocol/python-sdk` | 200 | 23,913 | 2026-08-05 | MIT | **v2.0.0** (released 2026-07-28, tracks the 2026-07-28 MCP spec revision). This is a *major* rework vs. v1 — see the discrepancy flagged in §4/§7. `pip install "mcp[cli]"`. |
| `modelcontextprotocol/servers` | 200 | 89,274 | 2026-08-05 | — | Official reference server implementations. **Current `src/` only has 7 servers**: `everything`, `fetch`, `filesystem`, `git`, `memory`, `sequentialthinking`, `time` — most of the historically-referenced servers (GitHub, Slack, Postgres, etc.) have been split into separately-maintained repos and archived out of this monorepo. Of the remaining 7, only `fetch` genuinely wraps an external, arbitrary-endpoint HTTP resource with auth-adjacent concerns (robots.txt honoring, User-Agent headers) — read in full, see §4. `git`/`filesystem` are local-resource wrappers, not REST-API wrappers, so were read only for resource/tool-declaration shape, not for REST-wrapping patterns. |
| `langchain-ai/langchain-mcp-adapters` | 200 | 3,623 | 2026-08-06 | — | `MultiServerMCPClient`, `load_mcp_tools`, stdio + streamable-HTTP transport examples. **Its own README still shows `from mcp.server.fastmcp import FastMCP`** — i.e. the LangChain adapters' documentation has not yet been updated for MCP Python SDK v2's `MCPServer` rename (see §7 discrepancy). Functionally the adapter layer itself (`load_mcp_tools`, `MultiServerMCPClient`) is transport/protocol-level and unaffected by the server-side rename — only the *README's own server example* is stale. |
| Salesforce MCP servers (searched, not assumed) | — | — | — | See §6 for full breakdown: found the **official** `salesforcecli/mcp` (Apache-2.0, Node/TS, CLI-wrapping) plus community Python and TS servers. |

---

## 4. CODE PATTERNS TO ADOPT

### 4.1 FastMCP-equivalent server skeleton — **use the current SDK's `MCPServer`, not the book's `Server`**

The book (`trcaldwell/agentic-ai-bible`, `chapters/ch09/ch09_02_mcp_server.py`, `requirements.txt` pins `mcp[cli]==1.5.0`) uses the **low-level** v1 API:

```python
# trcaldwell/agentic-ai-bible, chapters/ch09/ch09_02_mcp_server.py (as fetched)
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

app = Server("product-catalog")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [types.Tool(name="get_product", description="...", inputSchema={...})]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    ...
```

This is verbose, hand-writes JSON Schema, and is what the SDK's own docs now call the "low-level" server API — appropriate only when you need protocol-level control (e.g. custom pagination, see 4.4). **For our ~40+ REST-endpoint tool surface, the SDK's current top-level API is the right default**:

```python
# modelcontextprotocol/python-sdk, README.md, "A server in 15 lines" (v2.0.0, read live)
from mcp.server import MCPServer

mcp = MCPServer("Demo")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

@mcp.resource("greeting://{name}")
def greeting(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"
```

Why this matters for us: typed Python signatures → JSON Schema automatically, docstring → tool description automatically. No hand-written `inputSchema` dicts across 40+ tools — this alone removes a whole class of schema-drift bugs the book's approach is exposed to (its hand-written schemas already have doc/code drift — see §5).

**Naming**: the SDK's own class is `MCPServer`, imported from `mcp.server`. `FastMCP` was the v1 name; it is **not** an alias in v2 — the import path was fully removed, not deprecated (confirmed via the SDK's own "what's new" migration doc). Any code (including `langchain-mcp-adapters`'s own README, and every third-party tutorial written before mid-2026) that does `from mcp.server.fastmcp import FastMCP` will fail on `mcp>=2.0`. **Pin and verify** which major version we target before writing a line of server code.

### 4.2 Lifespan + dependency injection (shared HTTP client)

```python
# modelcontextprotocol/python-sdk, docs_src/lifespan/tutorial002.py (read live)
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from mcp.server import MCPServer
from mcp.server.mcpserver import Context

class Database:
    def __init__(self) -> None:
        self.connected = False
    async def connect(self) -> None: self.connected = True
    async def disconnect(self) -> None: self.connected = False

@dataclass
class AppContext:
    db: Database

database = Database()

@asynccontextmanager
async def app_lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    await database.connect()
    try:
        yield AppContext(db=database)
    finally:
        await database.disconnect()

mcp = MCPServer("Bookshop", lifespan=app_lifespan)

@mcp.tool()
def database_status(ctx: Context[AppContext]) -> str:
    """Report whether the database connection is up."""
    db = ctx.request_context.lifespan_context.db
    return "connected" if db.connected else "disconnected"
```

**Directly applicable to us**: swap `Database` for a shared `httpx.AsyncClient` (Salesforce REST base URL + auth headers), constructed once at startup, torn down on shutdown, and handed to every tool via `ctx.request_context.lifespan_context.client` — instead of each of 40+ tool functions constructing its own client (connection-pool waste, inconsistent auth handling). Note: `ctx.fastmcp` was renamed `ctx.mcp_server` in v2 (per SDK migration notes) — do not carry over v1-era `ctx.fastmcp` snippets from older blog posts/tutorials.

**Alternative DI style — `Resolve()`** (v2-only, no v1 equivalent, no book equivalent):

```python
# modelcontextprotocol/python-sdk, docs_src/dependencies/tutorial002.py (read live)
from typing import Annotated
from pydantic import BaseModel
from mcp.server import MCPServer
from mcp.server.mcpserver import Resolve

mcp = MCPServer("Bookshop")

class Stock(BaseModel):
    title: str
    copies: int

async def check_stock(title: str) -> Stock:
    return Stock(title=title, copies=INVENTORY.get(title, 0))

@mcp.tool()
async def order_book(
    title: str,
    stock: Annotated[Stock, Resolve(check_stock)],
) -> str:
    """Order a book from the shop."""
    ...
```

Worth considering for tools that need a "look up the object description / picklist values first" step before the main call — e.g. a `create_record` tool that needs the object's field metadata resolved before validating `data`.

### 4.3 Typed error → MCP error mapping

```python
# modelcontextprotocol/python-sdk, docs_src/handling_errors/tutorial002.py (read live)
from mcp import MCPError
from mcp.server import MCPServer
from mcp.types import INVALID_PARAMS

mcp = MCPServer("Bookshop")

@mcp.tool()
def get_author(title: str) -> str:
    """Look up the author of a book in the catalog."""
    if title not in CATALOG:
        raise MCPError(code=INVALID_PARAMS, message=f"No book titled {title!r} in the catalog.")
    return CATALOG[title]
```

This is the pattern we should use to map Salesforce REST error bodies (`INVALID_FIELD`, `REQUIRED_FIELD_MISSING`, `DUPLICATE_VALUE`, `INSUFFICIENT_ACCESS`, expired-session 401s) to structured, typed MCP errors — rather than letting a raw `simple_salesforce`/`httpx` exception string bubble to the model. **None of the repos surveyed here (book or community) actually do this mapping** — see §5 for the gap this leaves.

### 4.4 REST-wrapping reference: `fetch` server (httpx client reuse, auth-adjacent headers, error mapping, response shaping)

```python
# modelcontextprotocol/servers, src/fetch/src/mcp_server_fetch/server.py (read live)
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData, INTERNAL_ERROR

async def fetch_url(url: str, user_agent: str, force_raw: bool = False, proxy_url: str | None = None) -> Tuple[str, str]:
    from httpx import AsyncClient, HTTPError
    async with AsyncClient(proxy=proxy_url) as client:
        try:
            response = await client.get(url, follow_redirects=True, headers={"User-Agent": user_agent}, timeout=30)
        except HTTPError as e:
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Failed to fetch {url}: {e!r}"))
        if response.status_code >= 400:
            raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Failed to fetch {url} - status code {response.status_code}"))
        page_raw = response.text
    ...
```

Adopt: explicit `timeout=`, explicit HTTPError→McpError mapping with the failing URL/status embedded in the message (not a bare traceback), and a `Fetch` Pydantic model (`max_length`, `start_index` fields) used for **response truncation with resumability** — `start_index` lets the caller ask for "more of the same result starting where I left off" instead of the server guessing a smaller page size blind. This is the direct analog of the "response truncation" requirement in our brief: apply the same `max_length` + `start_index` shape to any Salesforce list/query tool that can return large result sets.

### 4.5 Resources declaration (for our describe/limits/picklists use case)

```python
# modelcontextprotocol/python-sdk, docs_src/resources/tutorial002.py (read live)
from mcp.server import MCPServer
mcp = MCPServer("Bookshop")

@mcp.resource("config://app")
def get_config() -> str:
    """The active shop configuration."""
    return "theme=dark\nlanguage=en"

@mcp.resource("users://{user_id}/profile")
def get_user_profile(user_id: str) -> str:
    """A customer's profile."""
    return f"User {user_id}: 12 orders since 2021."
```

Directly maps to our plan to serve `describe`/`limits`/picklists as resources rather than tools: e.g. `salesforce://describe/{object_name}`, `salesforce://limits`, `salesforce://picklist/{object_name}/{field_name}`.

### 4.6 Prompts declaration

```python
# modelcontextprotocol/python-sdk, docs_src/prompts/tutorial001.py (read live)
@mcp.prompt()
def review_code(code: str) -> str:
    """Review a piece of code."""
    return f"Please review this code:\n\n{code}"
```

Same `@mcp.prompt()` decorator pattern as tools/resources — trivial to add once we know which canned prompts (e.g. "summarize this Opportunity", "draft a follow-up Task") we want to ship.

### 4.7 Transport wiring — stdio and streamable HTTP

```python
# modelcontextprotocol/python-sdk, docs_src/run/tutorial001.py and tutorial002.py (read live)
if __name__ == "__main__":
    mcp.run()                                        # stdio, default
    # mcp.run(transport="streamable-http", port=3001) # HTTP, alternative
```

Note (from the migration-guide fetch, §7): in v2, transport/port config moved from the `MCPServer(...)` constructor to the `run()` call — `MCPServer("name", port=9000)` now raises `TypeError`. Any code snippet (including possibly older cached knowledge) that passes `port=` to the constructor is v1-era and wrong for v2.

### 4.8 Client-side: converting MCP tools to a provider's tool schema, and the agent loop

```python
# trcaldwell/agentic-ai-bible, chapters/ch09/ch09_03_mcp_client.py (read live) — book pattern, still structurally valid
def mcp_tool_to_anthropic(tool) -> dict:
    return {"name": tool.name, "description": tool.description, "input_schema": tool.inputSchema}
```
and, for LangChain/LangGraph specifically, prefer the maintained adapter over hand-rolling this conversion:
```python
# langchain-ai/langchain-mcp-adapters, README.md (read live)
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "salesforce": {"url": "http://localhost:8000/mcp", "transport": "http"},
})
tools = await client.get_tools()
```
`MultiServerMCPClient` is the adopted pattern for our provider-agnostic client wanting to load Salesforce MCP tools alongside other MCP servers (e.g. a second server for non-Salesforce systems) without hand-writing per-provider tool-schema converters.

### 4.9 Multi-provider LLM pattern (from `AI-Engineering-System-Guidebook.pdf`, not a repo but worth carrying into `01-mcp-and-multi-provider-client.md`)

The book uses **LiteLLM** (`from litellm import completion`, `pip install litellm`) as a single call surface across OpenAI/Anthropic/Ollama/local models — consistent with what our own `01-mcp-and-multi-provider-client.md` research is already tracking. No specific repo cited for this beyond the `litellm` PyPI package itself; flagged here so the multi-provider research doc can cross-reference it if not already covered.

### 4.10 Token-efficient response formatting + auth fallback chain (Salesforce-specific — see §6 for full context)

```python
# smn2gnt/MCP-Salesforce, src/salesforce/server.py (read live, MIT license)
def format_records(records: list[dict], format_type: str = "csv", include_total: bool = True) -> str:
    """... 'csv' (default, most compact), 'compact' (JSON without attributes), 'json' (full) ..."""
    clean_records = [_strip_attributes(r) for r in records]
    if format_type == "json":   return json.dumps(clean_records, indent=2)
    if format_type == "compact": return json.dumps(clean_records, separators=(',', ':'))
    # default: CSV — most token-efficient
```
and tool descriptions that actively coach the model toward cheap calls:
```python
description="""Executes a SOQL query against Salesforce.
TOKEN OPTIMIZATION GUIDELINES:
- Always SELECT only the fields you need (never SELECT *)
- Use LIMIT to restrict results (start with LIMIT 10, increase if needed)
- Default output is CSV format (most token-efficient)
Example efficient query: SELECT Id, Name FROM Account WHERE IsActive = true LIMIT 20"""
```
Adopt both ideas: (a) a `format` parameter defaulting to the cheapest representation, with `_strip_attributes()` stripping Salesforce's verbose `attributes: {type, url}` envelope from every record before it reaches the model; (b) tool *descriptions* that teach token-efficient usage inline, not just correctness. Also worth adopting: the **4-method auth fallback chain** (OAuth access token → OAuth client-credentials → Salesforce CLI `sf org display`/`sf org auth show-access-token` → username+password+security-token legacy), tried in that order — gives local dev (via `sf` CLI) and production (via OAuth) the same code path.

---

## 5. PATTERNS TO AVOID

1. **No error-type mapping in any surveyed Salesforce server.** `smn2gnt/MCP-Salesforce` imports `simple_salesforce.exceptions.SalesforceError` but never catches it — every SOQL/SOSL/CRUD tool only guards for *missing arguments* (`raise ValueError("Missing 'query' argument")`); a real Salesforce API error (`INVALID_FIELD`, `MALFORMED_QUERY`, `REQUIRED_FIELD_MISSING`, expired session) propagates as a raw exception string with no MCP-typed error code and no guidance to the model about what to do next. This directly contradicts the `MCPError(code=INVALID_PARAMS, ...)` pattern the SDK itself demonstrates (§4.3) and our own tool-design doctrine's "state what the model should do on failure" rule (`research/04-tool-design-and-security.md`, A.2). **Do not copy this gap** — wrap every Salesforce call site and translate known Salesforce error codes into typed `MCPError`s with actionable messages.
2. **No pagination/truncation on `query_all()`.** `smn2gnt/MCP-Salesforce`'s `run_soql_query` calls `sf.query_all(query)`, which transparently follows Salesforce's `nextRecordsUrl` and can pull an unbounded number of records into memory and then into the tool response — no `max_length`/`start_index`-style truncation like the `fetch` server has (§4.4). A large SOQL result with a forgotten `LIMIT` will blow the context window. Description text tries to coach the model into adding `LIMIT` itself (§4.10) but nothing enforces it server-side. **We should enforce a hard server-side cap** regardless of what the model puts in the query, and support Salesforce's actual REST pagination (`nextRecordsUrl`) via a `next_cursor`-style MCP-level continuation, not blind full materialization.
3. **Low-level `Server` API for a large, uniform tool surface (book pattern).** The book's `ch09_02_mcp_server.py`/`ch09_04...` hand-write `types.Tool(...)` and `inputSchema` dicts per tool. For 2–3 tools this is fine; for our ~40+ endpoint surface it produces exactly the kind of doc/code drift already visible in the book's own repo (§5.4 below) and forces manual JSON Schema maintenance the current SDK's typed-signature approach eliminates. Use `MCPServer` + decorators (§4.1) instead.
4. **Doc/code drift inside the book's own companion repo.** `chapters/ch09/README.md` lists file names (`ch09_01_example_01.py`, `ch09_04_list_tools.py`) that do not match the actual files in the directory (`ch09_01_list_tools.py`, `ch09_04_mcp_tool_to_anthropic.py`); same mismatch in `chapters/ch06/README.md` vs. actual `ch06_04_order_info.py`. Minor in isolation, but a concrete example of exactly the "docstring says one thing, code says another" failure mode our clean-code standard should catch in review — a reminder to keep generated docs in CI-checked sync with actual filenames if we ever auto-generate a tool index.
5. **Secrets handling — nothing egregious found, but note the boundary.** None of the repos read (book or community) hardcode credentials; all use environment variables (`ANTHROPIC_API_KEY`, `SALESFORCE_ACCESS_TOKEN`, etc.) or CLI-mediated auth. `smn2gnt/MCP-Salesforce` does print connection-failure messages to stderr (`print(f"Salesforce connection failed: {str(e)}", file=sys.stderr)`) — the exception string could in principle include a token if the underlying library's exception repr embeds request details; worth auditing `simple_salesforce`'s exception `__str__` before copying this stderr-logging pattern verbatim, rather than assuming it's always safe.
6. **God-function tool dispatch.** `smn2gnt/MCP-Salesforce`'s `call_tool` handler is a single ~250-line function with a long `if name == "..."` / `elif` chain for all 10+ tools (visible from the grep at lines 603–742 and continuing beyond). Functional, but exactly the "single dispatch god-function" shape our clean-code standard (`research/02-clean-code-standard.md`, presumably) would flag — prefer per-tool registered functions (which `@mcp.tool()` decorators give us for free) over a hand-rolled dispatch table.
7. **CLI-shell-out auth path runs `subprocess.run([...sf/sfdx...])` with a 30s timeout and JSON-parses stdout** — reasonable, but it is the kind of "command execution" mechanic that should live in one narrow, tested module if we adopt anything like it, not be inlined into the MCP tool layer.

---

## 6. EXISTING SALESFORCE MCP SERVERS

Searched live (not assumed) via GitHub search; metadata pulled from `api.github.com`.

| Repo | Owner | Language | License | Stars | Last push | What it covers | What we'd do differently |
|---|---|---|---|---|---|---|---|
| `salesforcecli/mcp` (npm: `@salesforce/mcp`) | Salesforce (official, `forcedotcom` org) | Node.js/TypeScript | Apache-2.0 | 451 | 2026-07-31 | **The official one.** Wraps the Salesforce CLI (`sf`), not the raw REST API directly — requires a locally CLI-authenticated org. Organizes tools into **toolsets** (`orgs`, `metadata`, `data`, `users`) that must be explicitly enabled via `--toolsets`/`--tools` flags, plus an `--allow-non-ga-tools` gate for beta tools. Ships client-config recipes for Claude Code, Cline, Cursor, VS Code/Copilot. | We're building a **Python**, **direct-REST** (not CLI-shell-out), **provider-agnostic** server — different shape entirely. The one pattern worth stealing outright: **explicit toolset/tool allow-listing as a security control**, gating non-GA/beta functionality behind a flag rather than exposing everything by default. Our tool surface (~40+ endpoints) should ship with the equivalent of `--toolsets`/`--tools` so an operator can shrink the active tool set below the 10–12-tool accuracy inflection point noted in `research/04-tool-design-and-security.md`, not just at build time but per-deployment. |
| `smn2gnt/MCP-Salesforce` | community (`smn2gnt`) | **Python**, `mcp` (low-level `Server`) + `simple_salesforce` | MIT | 179 | 2026-07-29 | Read in full (§4.10, §5). SOQL/SOSL, CRUD, Tooling API, Apex REST passthrough, 4-method auth chain, CSV-first token-efficient formatting. Closest architectural cousin to what we're building. | Fix the gaps in §5: typed error mapping, server-side result caps/pagination, decorator-based (`MCPServer`) tool registration instead of the god-function dispatcher, and — since we're wrapping the REST API directly rather than `simple_salesforce`'s ORM-ish layer — full control over pagination cursors and per-endpoint response shaping rather than being at the mercy of `query_all()`'s auto-follow behavior. |
| `tsmztech/mcp-server-salesforce` | community | Node.js/TypeScript (`jsforce`) | — (has `SECURITY.md`, OpenSSF Scorecard badge) | 165 | 2026-07-31 | Object/field CRUD, schema description, cross-object SOSL, Apex class/trigger read+write, `.dxt` Claude Desktop extension packaging. Notably documents a **known runtime incompatibility**: "the server must run under Node — bun is not supported: jsforce's HTTP transport hangs under bun ... every Salesforce API call stalls until the MCP host times out" (their issue #118). | Worth remembering as a class of bug to test for explicitly in our own httpx-based client: silent hangs under an unexpected runtime, rather than a clean error. Not itself a Python-relevant pattern (TS/jsforce-specific), but the OpenSSF Scorecard + `SECURITY.md` practice is worth adopting for our own repo hygiene. |
| `smn2gnt`/`uday210`/`kablewy`/`AiondaDotCom`/`SurajAdsul` variants | community | mixed | mixed | 50–180 range | 2026 | A crowded field — at least 5 independent "Salesforce MCP server" implementations exist, all covering roughly the same surface (SOQL, CRUD, describe, Apex). Only `smn2gnt`'s was read in full given time budget; the others were identified by search but not read line-by-line. | The market gap none of them clearly fill (based on the one read in full, plus README skims of the others via search snippets): **provider-agnostic client-side design** (these are all Claude-Desktop/`.mcp.json`-first), **typed error mapping**, and **enforced response truncation independent of the model remembering to add `LIMIT`**. This is exactly our stated differentiation. |

---

## 7. VERSIONS

Everything below was read live on 2026-08-06 via `curl`/`api.github.com`/`raw.githubusercontent.com` against each repo's default branch (`main` unless noted) — not from memory or training data.

| Repo | Ref read | Key version signal |
|---|---|---|
| `modelcontextprotocol/python-sdk` | `main` @ HEAD (pushed 2026-08-05) | **Latest release `v2.0.0`, published 2026-07-28**, tracking the 2026-07-28 MCP spec revision. `pip install "mcp[cli]"` installs 2.x by default now; v1.x lives on a separate `v1.x` branch and needs an explicit `mcp>=1.28,<2` pin. |
| `modelcontextprotocol/servers` | `main` @ HEAD (pushed 2026-08-05) | `src/` currently contains exactly 7 servers: `everything, fetch, filesystem, git, memory, sequentialthinking, time`. (Most previously-documented reference servers, e.g. for GitHub/Slack/Postgres, have been split into their own repos/orgs and are no longer in this monorepo — don't expect the historical full list from older tutorials to still be here.) |
| `langchain-ai/langchain-mcp-adapters` | `main` @ HEAD (pushed 2026-08-06) | 3,623 stars. README's own server example still imports `from mcp.server.fastmcp import FastMCP` — **stale relative to python-sdk v2's `MCPServer` rename**; flagged explicitly per instructions (SDK wins over any tutorial/README that disagrees with it). |
| `trcaldwell/agentic-ai-bible` | `main`, commit `7de080e8b17de5c702bf51e3f89bab1e49f41de7` (2026-05-13) | Its own `requirements.txt` pins `mcp[cli]==1.5.0` and `anthropic==0.49.0` — **roughly 3 major SDK versions behind current `mcp` (2.0.0)**. Its `ch09_02_mcp_server.py`/`ch09_03_mcp_client.py` code comments self-report "Tested against mcp[cli]>=1.5.0 ... as of April 2026." Treat every book MCP code sample as v1-API and re-verify against the current SDK before use — do not port `Server`/`stdio_server` low-level calls forward without checking the v2 migration guide. |
| `aliisaaispecialist-lang/agentic-ai-bible` | `main` (fork of the above, same single commit) | Same version exposure as the parent — informational only, per §1. |
| `salesforcecli/mcp` | `main` (pushed 2026-07-31) | Apache-2.0, distributed as npm `@salesforce/mcp`, versioned/released independently of this doc's read (README doesn't print an npm version pin; check `npm view @salesforce/mcp version` at implementation time). |
| `smn2gnt/MCP-Salesforce` | `master` (its default branch is `master`, not `main`) | MIT. `server.py` header pins `dependencies = ["mcp", "simple-salesforce", "python-dotenv"]` via PEP 723 inline script metadata — no version pins at all, so it always installs whatever `mcp`/`simple-salesforce` are current at run time. Given it still imports `from mcp.server import Server` (low-level v1-style API), it should be assumed **not yet updated for `mcp` v2** and may currently be broken against `mcp>=2.0` — worth a live pip-install check before treating any of its patterns as "known-working against current SDK," even though the *design* patterns (§4.10) are sound regardless of SDK version. |
| `tsmztech/mcp-server-salesforce` | `main` (pushed 2026-07-31) | Node 20+ required; explicitly documents a bun incompatibility (issue #118) — TS/npm ecosystem, no Python version relevance. |
| `kylestratis/ai_agents_mcp_examples` | (not individually version-pinned; repo-level: pushed 2026-07-15) | MIT. Located via web search, not confirmed as the in-text-cited repo for `953807192-AI-Agents-With-MCP.pdf` (the PDF itself never prints a URL) — flag this mapping as probable, not certain, if it's cited downstream. |

**Overall discrepancy to carry forward into the build**: our source books (both *The Agentic AI Bible* and, implicitly, any pre-2026-07 MCP tutorial content) were written against MCP Python SDK v1's `FastMCP`/`Server` API. The SDK is now on **v2.0.0** with `MCPServer` (renamed, not aliased), `ctx.mcp_server` (renamed from `ctx.fastmcp`), `MCPServerError` (renamed from `FastMCPError`), constructor-vs-`run()` config split, and the new `Resolve()` DI mechanism. **Every code pattern in this doc's §4 is drawn from the live v2 SDK/repos, not the books, for exactly this reason — build against §4, and treat §1's book snippets as historical illustration only.**
