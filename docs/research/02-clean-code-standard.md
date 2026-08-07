# Clean Code Standard — Salesforce MCP Server & Provider-Agnostic LLM Client

**Status:** Normative. This document is the code-review gate.

**Sources:** Robert C. Martin, *Clean Code* (cited `[Clean Code, p.N]` — **book pages**, not PDF pages) and Shahan Chowdhury, *Clean Code: Zero to One* (cited `[CCZTO, p.N]`). Anything not carrying a citation is `[PROJECT ADAPTATION]` — invented for this project and open to challenge. Examples are translated to Python even where the source used Java/JS.

**How to read a rule:** `RULE → WHY → violation/fix`. A reviewer should get a yes/no without a judgement call. Where a rule is inherently a judgement call, it says so and gives the tie-breaker.

**Precedence when rules conflict** — Kent Beck's four rules of Simple Design, in priority order `[Clean Code, p.172-176]`:
1. Runs all the tests
2. Contains no duplication
3. Expresses the intent of the programmer
4. Minimizes the number of classes and methods

Rule 4 is last deliberately: it exists to stop rules 1–3 being taken to a dogmatic extreme (an interface for every class, a class for every noun) `[Clean Code, p.176]`. "Too many small classes" does not win an argument against a change that improves testability or removes duplication.

---

## 0. Premises

**0.1 — Reading dominates writing.** The ratio of time spent reading vs. writing code is *well over 10:1* `[Clean Code, p.14]`. Every rule below trades writing time for reading time. That trade is always correct.

**0.2 — LeBlanc's Law: "Later equals never"** `[Clean Code, p.4]`. There is no cleanup sprint. Code is cleaned as it is written, or not at all.

**0.3 — The Boy Scout Rule.** *Leave the campground cleaner than you found it* `[Clean Code, p.14]`. Touching a file obliges you to improve one thing — a name, a dead branch, a stale comment. Not a rewrite `[CCZTO, p.29-34]`.

**0.4 — Write dirty, then clean.** "To write clean code, you must first write dirty code and then clean it" `[Clean Code, p.200]`. First drafts are expected to be long and duplicated. The standard applies to what you *submit*, not what you type. Refactoring is iterative and non-monotonic — later steps often reverse earlier ones `[Clean Code, p.265]`.

**0.5 — Team rule beats personal taste.** Every developer has favourite formatting rules; on a team, the team rules. Martin's own team settled their entire style in ~10 minutes and encoded it in the formatter `[Clean Code, p.90]`. §13 is our encoded version. Personal preference is not a review argument.

**0.6 — Bad code compounds.** Cost per change rises toward ~100% of effort in the legacy phase for bad code vs. ~45% for clean code `[CCZTO, p.10-11]`; global technical debt is estimated ~$1.5 trillion `[CCZTO, p.12-14]`.

---

## 1. Naming

> Names are roughly 90% of what makes software readable `[Clean Code, N1, p.309]`.

**Rule 1.1 — Use intention-revealing names.** A name answers why it exists, what it does, how it's used. **If a name needs a comment, the name has failed.** `[Clean Code, p.18]`
```python
# Violation
d = 7  # elapsed time in days
# Fix
elapsed_time_in_days = 7
```
Martin's worked example: `getThem()` → `getFlaggedCells()`, `theList` → `gameBoard`, `x[0] == 4` → `cell.is_flagged()` — identical complexity and nesting, radically more explicit `[Clean Code, p.18-19]`.

**Rule 1.2 — Avoid disinformation.** Don't use names whose established meaning conflicts with what they hold, and don't use names differing only in small, hard-to-spot ways. `[Clean Code, p.19-20]`
```python
# Violation
account_list = {"a": Account()}     # it's a dict, not a list
XmlControllerForEfficientHandlingOfStrings
XmlControllerForEfficientStorageOfStrings   # near-identical, easy to confuse
# Fix
accounts: dict[str, Account] = {}
```
Also banned: `l`, `O`, `I` as names — indistinguishable from `1`/`0` `[Clean Code, p.20]`.

**Rule 1.3 — Make meaningful distinctions; no noise words or number-series names.** `Info`, `Data`, `Object`, `Variable`, `a1`/`a2` add no meaning — if two names must differ, they must *mean* something different. `[Clean Code, p.20-21]`
```python
# Violation
def copy_chars(a1: list[str], a2: list[str]) -> None: ...
customer_info  # vs customer — indistinguishable
# Fix
def copy_chars(source: list[str], destination: list[str]) -> None: ...
```
Martin's real-world horror: `getActiveAccount()`, `getActiveAccounts()`, `getActiveAccountInfo()` in one codebase — nobody can tell which to call `[Clean Code, p.21]`.

**Rule 1.4 — Use pronounceable, searchable names.** Single-letter names and magic literals can't be grepped or discussed aloud; reserve single letters for tiny loop scopes. **Name length scales with scope length** `[Clean Code, N5, p.312]`. `[Clean Code, p.21-23]`
```python
# Violation
genymdhms = ...    # unpronounceable
for j in range(34): s += t[j] * 4 / 5
# Fix
generation_timestamp = ...
WORK_DAYS_PER_WEEK = 5
for task_index in range(NUMBER_OF_TASKS): ...
```

**Rule 1.5 — Avoid encodings (Hungarian notation, type/scope prefixes, `m_`, `I`-prefixed interfaces).** Type checkers and editors already track types; encodings rot when the type changes (`phone_string: PhoneNumber`). `[Clean Code, p.23-24]`
```python
# Violation
class ILLMProvider(Protocol): ...
class Part:
    m_dsc: str
# Fix
class LLMProvider(Protocol): ...   # abstraction stays unadorned
class Part:
    description: str
```
`[PROJECT ADAPTATION]` For Protocols standing in for "interfaces", leave the abstraction unadorned (`SalesforceClient`, `LLMProvider`) and qualify the concrete implementation (`RestSalesforceClient`, `AnthropicProvider`) — matching the book's preference for decorating the implementation, never the interface `[Clean Code, p.24]`.

**Rule 1.6 — Avoid mental mapping.** Don't make readers translate a placeholder (`c`) into the real concept. "Clarity is king. Professionals use their powers for good." `[Clean Code, p.25]`

**Rule 1.7 — Classes are noun phrases, functions are verb phrases.** Avoid `Manager`, `Processor`, `Data`, `Info` in class names — they signal a class with no single responsibility. **A class name is never a verb.** `[Clean Code, p.25]`
```python
# Violation
class DataManager: ...
class ProcessRecords: ...
# Fix
class Account: ...
class RecordProcessor: ...
def post_payment(...) -> None: ...
```
When construction is overloaded, use named factory classmethods that describe the arguments `[Clean Code, p.25]`:
```python
@classmethod
def from_client_credentials(cls, client_id: str, secret: str) -> "SalesforceClient": ...
@classmethod
def from_refresh_token(cls, token: str) -> "SalesforceClient": ...
```

**Rule 1.8 — Don't be cute; say what you mean.** No jokes, slang, or culture-dependent names (`whack()` for `kill()`). `[Clean Code, p.26]`

**Rule 1.9 — Pick one word per concept, project-wide.** Don't mix `fetch`/`retrieve`/`get` for the same operation, or `Manager`/`Controller`/`Driver` for the same role. `[Clean Code, p.26]`

`[PROJECT ADAPTATION]` **Reserved project lexicon** — each word means exactly one thing:

| Word | Means | Never used for |
| --- | --- | --- |
| `fetch_` | read that hits an external API (Salesforce, an LLM SDK) | local/in-memory reads |
| `get_` | read from local/in-memory state; raises if absent | network calls, optional results |
| `find_` | read returning zero-or-one; the only place `\| None` is allowed | the raising variant |
| `list_` | read returning many; returns `[]`, never `None` | single results |
| `build_` / `make_` | pure construction, no I/O | anything performing I/O |
| `create_` / `update_` / `delete_` | writes/mutations | reads |
| `client` | our wrapper around one external system | a raw SDK object |
| `provider` | one LLM vendor implementation | the Protocol itself |
| `tool` | one MCP-exposed callable | an internal helper |
| `adapter` | boundary translation layer | business logic |

**Rule 1.10 — Don't pun.** Never reuse one word for two different operations. If `add` means "sum two values" elsewhere, the method that puts an item into a collection is `insert`/`append`. `[Clean Code, p.26-27]`

**Rule 1.11 — Solution-domain names for technical concepts, problem-domain names for business concepts.** Readers are programmers, so `RetryQueue`/`TokenBucket`/`AccountVisitor` are good; use Salesforce/LLM vocabulary (`SoqlQuery`, `ToolCall`, `GovernorLimit`) where there's no crisper technical term. `[Clean Code, p.27]`

**Rule 1.12 — Add context through a class/module, not a prefix; add no gratuitous context.** Group related fields into a class (`Address`) rather than prefixing each variable (`addr_street`); don't prefix every class with a project acronym (`SFMCP_Account`). `[Clean Code, p.27-30]`

**Rule 1.13 — Names describe side effects.** A name must describe *everything* the thing does, including what it mutates. A `get_connection()` that lazily opens one is `get_or_open_connection()` — or better, is refactored so it doesn't. `[Clean Code, N7, p.313]`

### `[PROJECT ADAPTATION]` Concrete conventions

| Kind | Convention | Example |
| --- | --- | --- |
| Module | `snake_case.py`, one noun/verb phrase | `sf_client.py`, `retry_policy.py` |
| Package | `snake_case`; singular for one concept, plural for genuine collections | `salesforce/`, `llm/`, `tools/`, `adapters/` |
| Class | `PascalCase` noun phrase | `SalesforceRestClient`, `ToolDefinition` |
| Protocol / ABC | `PascalCase`, **no `I` prefix** | `LLMProvider`, `TokenStore` |
| Function / method | `snake_case` verb phrase | `fetch_opportunity`, `build_tool_schema` |
| Predicate | reads as a question | `is_expired`, `has_more_pages` |
| Private | single leading underscore | `_build_headers` |
| Constant | `UPPER_SNAKE_CASE` at module scope | `DEFAULT_API_VERSION`, `MAX_SOQL_BATCH_SIZE` |
| Type alias | `PascalCase` | `RecordId = NewType("RecordId", str)` |
| Exception | `PascalCase`, ends in `Error` | `SalesforceAuthError` |
| Test module | `test_<module under test>.py` | `test_client.py` |
| Test function | `test_<unit>__<scenario>__<expected>` | `test_fetch_opportunity__not_found__raises_not_found_error` |
| Fixture | noun, no `test_` prefix | `salesforce_client` |

**Banned module names** `[PROJECT ADAPTATION]`: `utils.py`, `helpers.py`, `common.py`, `misc.py`, `manager.py`, unqualified `base.py`. **WHY:** they are noise words `[Clean Code, p.20]` and become dumping grounds with no single reason to change `[Clean Code, p.138]`. A helper with no home means you haven't found its concept yet.

---

## 2. Functions

**Rule 2.1 — Functions are small.** "They should hardly ever be 20 lines long" `[Clean Code, p.34]`. Blocks inside `if`/`while`/`for` should be one line — ideally a call. Indent depth within a function "should not be greater than one or two" `[Clean Code, p.35]`.
`[PROJECT ADAPTATION]` **20 lines target / 30 lines hard fail** (body, excluding signature and docstring); **max nesting depth 3**.

**Rule 2.2 — Do one thing, at one level of abstraction, and follow the stepdown rule.** Each function is followed by the functions one level of abstraction down, so the file reads top-to-bottom as a narrative `[Clean Code, p.35-37]`.
**Mechanical test:** if you can extract a sub-function whose name is not merely a restatement of its implementation, the original did more than one thing `[Clean Code, p.35-36; G30, p.302]`.
**Second test:** a function that does one thing cannot be divided into sections (declarations / init / work) `[Clean Code, p.36]`.
```python
# Violation — mixes policy, HTTP mechanics, and string surgery
def sync_accounts(self) -> None:
    token = self._token or self._http.post("/oauth2/token", data={...}).json()["access_token"]
    rows = self._http.get(f"{self.base}/query?q=SELECT+Id+FROM+Account").json()["records"]
    for r in rows:
        self._db.execute("INSERT INTO account VALUES (?)", (r["Id"],))

# Fix — every line is one step of the same story
def sync_accounts(self) -> None:
    accounts = self._salesforce.fetch_accounts()
    self._store.upsert_accounts(accounts)
```

**Rule 2.3 — Prefer polymorphism to a repeated `switch`/`if-elif` chain on type.** Tolerable *only* if it appears exactly once, builds polymorphic objects, and is hidden behind a factory. `[Clean Code, p.37-39; G23, p.299]`
```python
# Violation — this chain gets duplicated for every new capability
def call_llm(provider: str, prompt: str) -> str:
    if provider == "anthropic": ...
    elif provider == "openai": ...
    elif provider == "cohere": ...

# Fix — one switch, in the factory, producing polymorphic objects
_PROVIDERS: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "cohere": CohereProvider,
}

def build_provider(name: str, config: ProviderConfig) -> LLMProvider:
    try:
        return _PROVIDERS[name](config)
    except KeyError:
        raise UnknownProviderError(name) from None
```

**Rule 2.4 — Argument count: 0 best, then 1, then 2; 3 "should be avoided where possible"; more than three "requires very special justification — and then shouldn't be used anyway."** `[Clean Code, p.40]`, `[F1, p.288]`
`[PROJECT ADAPTATION]` **Max 3 positional parameters excluding `self`/`cls`. At 4+, introduce a frozen dataclass/pydantic params object. Anything past position 3 is keyword-only (`*`).**
```python
# Violation
def create_record(sobject, fields, api_version, timeout, retries, trace_id): ...
# Fix — the group that travels together becomes a concept
@dataclass(frozen=True)
class RequestOptions:
    api_version: str = DEFAULT_API_VERSION
    timeout_seconds: float = 30.0
    retries: int = 3
    trace_id: str | None = None

def create_record(sobject: str, fields: Mapping[str, Any], *, options: RequestOptions) -> RecordId: ...
```

**Rule 2.5 — No flag (boolean) arguments.** Passing a boolean is "truly terrible practice" — it announces the function does more than one thing. `[Clean Code, p.41]`, `[F3/G15, p.288, p.294]`, `[CCZTO, p.55-58]`
```python
# Violation
def render(page_data, is_suite: bool): ...
# Fix
def render_for_suite(page_data): ...
def render_for_single_test(page_data): ...
```
`[PROJECT ADAPTATION]` **Narrow exception:** a keyword-only boolean that is pure *configuration data* forwarded verbatim into a request body (never branched on) is allowed. **If it appears in an `if`, it is a flag argument and is banned.** Mechanically enforced by ruff `FBT`.

**Rule 2.6 — No output arguments.** Readers expect arguments to be inputs; a mutated argument forces a double-take. Information flows out via the return value. `[Clean Code, p.41-45]`, `[F2, p.288]`
```python
# Violation
def append_footer(report: list[str]) -> None:
    report.append(footer_text())
# Fix
def with_footer(report: str) -> str:
    return report + footer_text()
```

**Rule 2.7 — No side effects; Command-Query Separation.** A function either *does* something (command) or *answers* something (query) — never both. Side effects are lies that create temporal couplings. `[Clean Code, p.44-46]`
`[CCZTO, p.59-60]` gives the explicit three-part test — a side effect occurs when a function (1) changes a variable outside its scope, (2) alters application state (global, database, config object), or (3) interacts with the environment unexpectedly (logging, an API call). Mitigations `[CCZTO, p.66]`: avoid modifying external state; return a new value rather than mutating the input; keep computation in locals.
```python
# Violation — hidden side effect: initializes a session as well as checking a password
def check_password(username: str, password: str) -> bool:
    user = find_user(username)
    if user and decrypt(user.phrase, password) == "Valid Password":
        Session.initialize()   # surprise!
        return True
    return False
# Fix — split command from query
def is_valid_password(username: str, password: str) -> bool: ...
def start_session(user: User) -> Session: ...
```
Also banned: `if config.set("api_version", "v60.0"):` — does `set` assign or test existence? Split into `has_attribute` / `set_attribute` `[Clean Code, p.45-46]`.

**Rule 2.8 — Prefer exceptions to error codes; extract try/except bodies into their own functions.** **If `try` appears in a function, it should be the first statement, and nothing follows the `except`/`finally` blocks** — error handling is one thing, so a function that handles errors does nothing else. `[Clean Code, p.46-47]`, `[CCZTO, p.99-100]`
```python
# Violation
def delete_page(page) -> int:
    if registry.delete_reference(page.name) != OK:
        return ERROR
    ...
# Fix
def delete(page) -> None:
    try:
        delete_page_and_all_references(page)
    except DeletionError as e:
        log_error(e)

def delete_page_and_all_references(page) -> None:
    delete_page(page)
    registry.delete_reference(page.name)
    config_keys.delete_key(page.name)
```

**Rule 2.9 — DRY.** Duplication — including duplicated *algorithm shape*, not just literal text — "may be the root of all evil in software"; every duplication is a missed abstraction and an N-fold error-of-omission risk. `[Clean Code, p.48]`, `[G5, p.289]`, `[CCZTO, p.35-41]`
**Guard against over-DRY** `[CCZTO, p.38]`: don't merge unrelated logic to save lines. Two things that look alike but change for different reasons are not duplication.

**Rule 2.10 — Early returns are encouraged.** Dijkstra's single-entry/single-exit rule "gives real benefit only in large functions"; with small functions, occasional multiple returns/`break`/`continue` are fine and often more expressive `[Clean Code, p.48-49]`. `[PROJECT ADAPTATION]` Guard clauses are the primary tool for meeting the nesting-depth-3 limit.

**Rule 2.11 — Write functions badly first, then refactor.** Get it working with tests backing it, then split, rename, and deduplicate until rules 2.1–2.10 hold. `[Clean Code, p.49]`

---

## 3. Comments

**Project rule: comments are a last resort, not a first instinct.** "The proper use of comments is to compensate for our failure to express ourselves in code" `[Clean Code, p.54]`. "The only truly good comment is the comment you found a way not to write" `[Clean Code, p.55]`.

**Comments rot.** "The older a comment is, and the farther from the code it describes, the more likely it is wrong." An inaccurate comment is worse than none `[Clean Code, p.54]`.

```python
# Violation
# check if employee is eligible for full benefits
if employee.flags & HOURLY_FLAG and employee.age > 65: ...
# Fix
if employee.is_eligible_for_full_benefits(): ...
```

### `[PROJECT ADAPTATION]` The docstring rule, stated explicitly

This is the one place the book pulls both ways — "mandated comments" are forbidden `[Clean Code, p.63]` while public-API docs are legitimate `[Clean Code, p.59]`. Our resolution:

**REQUIRED on, and only on:**
1. Every **public module** — one line saying what lives there.
2. Every **public** class/function/method — anything importable without touching an underscore name.
3. Every **MCP tool handler**, without exception. **WHY:** a tool docstring is not a comment — it is the *runtime tool description sent to the model*. It is shipped behaviour, covered by tests, and outside this section's discretion.
4. Every **custom exception class** — stating the caller-facing condition it represents.

**FORBIDDEN on:**
- Private functions/methods (`_name`) — a good name suffices `[Clean Code, p.71]`.
- Test functions — the test name is the sentence.
- Anything that would restate the signature. `"""Get the name."""` above `def get_name(self) -> str:` is a redundant comment (C3) and must be deleted or upgraded.

**Content rule:** document **why**, **raises**, and **units/ranges**. Do not restate types — annotations carry those. Google convention, `D401` (imperative mood) on.
```python
# Violation — mandated + redundant + restates types
def get_access_token(self) -> str:
    """
    Gets the access token.

    Returns:
        str: The access token.
    """

# Fix — says only what the signature cannot
def get_access_token(self) -> str:
    """Return a valid access token, refreshing it if within the expiry skew.

    Raises:
        SalesforceAuthError: If the refresh token has been revoked.
    """
```

**TODO format** `[PROJECT ADAPTATION]`: `# TODO(<owner>, <issue-url>): <what>`. A TODO without an owner and a tracked issue fails review — otherwise it's a journal comment with better marketing.

**Rule 3.1 — Legitimate comment categories (the closed list)** `[Clean Code, p.55-59]`:
- **Legal** — short copyright/licence header referencing an external licence rather than reproducing it.
- **Informative** — explains a regex/format string when it truly can't be moved into a name (rename first).
- **Explanation of intent** — documents *why* a nonobvious decision was made.
- **Clarification** — translates an opaque expression, especially in code you don't control. Verify it; clarifying comments are often wrong.
- **Warning of consequences** — e.g. "not thread-safe — do not hoist to module scope".
- **TODO** — tracked, temporary; never camouflage for bad code; grep and prune regularly.
- **Amplification** — flags that an easy-to-miss line (a `.strip()`) is load-bearing.
- **Public API docstrings** — legitimate and expected (see above), but reviewed with the same scepticism as any comment: they can lie too.

**Rule 3.2 — Forbidden comment categories; remove on sight** `[Clean Code, p.59-71]`:
- **Mumbling** — too vague to convey the author's reasoning.
- **Redundant** — restates the code (`i += 1  # increment i`); takes longer to read and is less precise.
- **Misleading** — describes behaviour the code doesn't have.
- **Mandated** — required by blanket policy regardless of information added.
- **Journal comments** — changelogs in source. Git is authoritative; delete.
- **Noise** — restates the obvious (`"""Default constructor."""`).
- **Scary noise** — copy-pasted doc blocks with wrong content; proof the author wasn't careful.
- **Comment where a function or variable would do.**
- **Position markers / banners** — `# --- Actions ---`. Very sparingly, or not at all.
- **Closing-brace / end-of-block markers** — the fix is a shorter block.
- **Attribution/bylines** (`# Added by Rick`) — `git blame` is authoritative.
- **Commented-out code** — "few practices are as odious." It accumulates because nobody dares delete it. **Hard review blocker** (C5).
- **Markup in comments** — HTML makes comments unreadable where they must be read.
- **Nonlocal information** — a comment describing a fact owned by another module.
- **Too much information** — pasting a spec/RFC instead of linking it.
- **Inobvious connection** — a comment that itself needs explaining.
- **Function headers** — short well-named functions don't need them.
- **API-doc formality on non-public code** — "cruft and distraction."

---

## 4. Formatting

**Purpose:** formatting is communication, and communication is the professional developer's first order of business. Functionality changes; style and discipline survive `[Clean Code, p.76]`.

### The numbers we adopt

**What the book actually measured.** Across seven Java projects: FitNesse (~50,000 lines total) averages ~65 lines/file, a third of files fall between 40 and ~100, largest ~400, smallest 6 `[Clean Code, p.76]`. Martin's conclusion: significant systems can be built from files "typically 200 lines long, with an upper limit of 500" — "should not be a hard and fast rule... should be considered very desirable" `[Clean Code, p.77]`. On line width: ~40% of lines are 20–60 chars and the drop-off above 80 is significant; "I'm not opposed to lines edging out to 100 or even 120. But beyond that is probably just careless... I personally set my limit at 120" `[Clean Code, p.85-86]`.

| Setting | Value | Basis |
| --- | --- | --- |
| Line length | **100** | Stricter end of Martin's 100–120 band `[p.85-86]`; `[CCZTO, p.49]` agrees |
| Indent | **4 spaces**, never tabs | PEP 8; `[CCZTO, p.48]` |
| Module length | **200 target / 400 hard fail** | `[p.77]`, tightened for Python's higher density per line |
| Function length | **20 target / 30 hard fail** | `[p.34]` |
| Max nesting depth | **3** | `[p.35]` "one or two" + Python's module-level baseline |
| Max positional args | **3** (excl. `self`) | `[p.40]`, `[F1, p.288]` |
| Max cyclomatic complexity | **8** | `[PROJECT ADAPTATION]` — proxy for "do one thing" |
| Blank lines | 2 between top-level defs, 1 between methods | PEP 8 + vertical openness |
| Quote style | double | formatter default; consistency (G11) |
| Trailing commas | required in multiline | smaller diffs `[PROJECT ADAPTATION]` |

**Rule 4.1 — The newspaper metaphor.** A file reads like a newspaper article: the name is the headline, topmost code carries high-level concepts, detail increases downward, lowest-level functions last. `[Clean Code, p.77-78]`

**Rule 4.2 — Vertical openness between concepts.** Groups of lines forming a complete thought are separated by blank lines; each blank line is a visual cue that a new concept begins. `[Clean Code, p.78]`

**Rule 4.3 — Vertical density.** Tightly related lines stay dense — don't break up related declarations with noise comments. Code that fits in "an eye-full" is comprehended without moving your head. `[Clean Code, p.79]`

**Rule 4.4 — Vertical distance.** `[Clean Code, p.80-84]`, `[G10, p.292]`
- **Locals** — declared as close to first use as possible; at the top of the function, since functions are short.
- **Loop control variables** — inside the loop statement.
- **Instance/class attributes** — one well-known place: the top of the class. (Martin's cautionary example is JUnit's `TestSuite`, which buries two instance variables halfway down — "it would be hard to hide them in a better place.")
- **Dependent functions** — vertically close, **caller above callee**.
- **Conceptual affinity** — functions sharing a naming scheme and performing variations of the same task stay together even without a call relationship.

**Rule 4.5 — Vertical ordering.** Call dependencies point downward, so a reader can skim the first few functions and get the gist. `[Clean Code, p.84-85]`

**Rule 4.6 — Horizontal openness and density.** Whitespace associates and disassociates: spaces around assignment (two distinct sides); **no** space between a function name and its opening paren (conjoined); space after commas. Operator-precedence spacing (`b*b - 4*a*c`) reads well but "most tools for reformatting code are blind to the precedence of operators" `[Clean Code, p.86]`. `[PROJECT ADAPTATION]` **The formatter wins** — don't hand-tune; `ruff format` output is the standard.

**Rule 4.7 — Horizontal alignment is banned.** Martin did this for years and stopped: alignment "emphasize[s] the wrong things and leads my eye away from the true intent" — you read down the names without seeing the types; tools destroy it anyway; and a list long enough to need alignment is telling you **the class should be split**. `[Clean Code, p.87-88]`
```python
# Violation
socket   : Socket        = ...
has_error: bool          = ...
# Fix
socket: Socket = ...
has_error: bool = ...
```

**Rule 4.8 — Never collapse a scope onto one line.** Martin has always regretted it and put the indentation back. `[Clean Code, p.89]`
```python
# Violation
def render(self) -> str: return ""
if not token: raise SalesforceAuthError("missing token")
# Fix
def render(self) -> str:
    return ""

if not token:
    raise SalesforceAuthError("missing token")
```

**Rule 4.9 — Dummy scopes get their own line.** A body hidden on the same line as its loop header is "just too hard to see" `[Clean Code, p.90]`. In Python: `pass` on its own line, never `while advance(): pass`.

**Rule 4.10 — Team rule over personal taste.** The formatter config is the single source of truth; nobody hand-formats against it, and **no PR comment may demand a style the formatter doesn't enforce.** `[Clean Code, p.90]`

---

## 5. Objects vs. Data Structures

**Rule 5.1 — Data abstraction is about abstractions, not accessors.** Hiding implementation is not putting a layer of getters in front of variables. "The worst option is to blithely add getters and setters." `[Clean Code, p.93-95]`
```python
# Violation — exposes that fuel is tracked in gallons
class Vehicle:
    def get_fuel_tank_capacity_in_gallons(self) -> float: ...
    def get_gallons_of_gasoline(self) -> float: ...
# Fix — expresses the essence, hides the representation
class Vehicle:
    def get_percent_fuel_remaining(self) -> float: ...
```

**Rule 5.2 — Data/object anti-symmetry.** Memorise this; it settles most design arguments. `[Clean Code, p.95-97]`

> **Objects** hide their data behind abstractions and expose functions that operate on that data.
> **Data structures** expose their data and have no meaningful functions.

> Procedural code makes it easy to add new *functions* without changing existing data structures; hard to add new *data structures*.
> OO code makes it easy to add new *classes* without changing existing functions; hard to add new *functions*.

"The idea that everything is an object is a myth" `[Clean Code, p.97]`.

`[PROJECT ADAPTATION]` **Our application:**
- **Salesforce records, MCP tool payloads, LLM request/response envelopes → data structures.** We add new *operations* over these constantly and new *shapes* rarely.
- **Clients, providers, adapters, the tool registry → objects.** We add new *providers* constantly and new *operations on a provider* rarely.

**Rule 5.3 — Don't build hybrids.** A class with real behaviour *and* public fields/trivial accessors letting outsiders manipulate its internals is "the worst of both worlds" — hard to add data shapes *and* hard to add operations. `[Clean Code, p.99]`
```python
# Violation — hybrid
class Order:
    def __init__(self):
        self.line_items: list = []   # public, freely mutated from anywhere
    def total(self) -> Money: ...    # but also real behavior
# Fix — pick one. Pure data structure:
@dataclass(frozen=True)
class OrderLine:
    sku: str
    quantity: int
# Or behavioral object with private internals:
class Order:
    def __init__(self): self._line_items: list[OrderLine] = []
    def add_line(self, line: OrderLine) -> None: self._line_items.append(line)
    def total(self) -> Money: ...
```

**Rule 5.4 — Law of Demeter.** A method `f` of class `C` may call methods only of: `C` itself; an object created by `f`; an object passed as an argument to `f`; an object held in an instance variable of `C`. **It must not call methods on objects returned by any of those.** *Talk to friends, not strangers.* `[Clean Code, p.97-100]`, `[CCZTO, p.119-121]`
```python
# Violation — train wreck
output_dir = ctx.options().scratch_dir().absolute_path()
# Fix — tell, don't ask
output_dir = ctx.create_scratch_file_stream(class_file_name)
```
Splitting the chain across three lines does **not** fix it — the calling function still knows how to navigate three objects deep `[Clean Code, p.98]`.
**Crucial nuance:** this applies to *objects*, not data structures. `record.attributes.type` on a plain pydantic model is fine; `client.get_session().get_transport().close()` is not `[Clean Code, p.98-99]`.

**Rule 5.5 — DTOs and Active Record.** A DTO is a class with public variables and no functions — useful at DB/socket/API boundaries as the first of several translation stages `[Clean Code, p.100-101]`. **Active Record must be treated as a data structure**; putting business rules on it creates exactly the hybrid banned above — business rules go in separate objects `[Clean Code, p.101]`.
`[PROJECT ADAPTATION]` Our pydantic Salesforce models are DTOs. They may carry **validation and parsing** (that is what pydantic is for) but **no business rules, no I/O, no network calls.**

---

## 6. Error Handling

> "Error handling is important, but if it obscures logic, it's wrong" `[Clean Code, p.103]`.

**Rule 6.1 — Use exceptions, never sentinel/error-code returns.** Error codes clutter the caller, who must check immediately — and it's easy to forget. Exceptions separate the algorithm from its error handling. `[Clean Code, p.104-105]`, `[CCZTO, p.99-100]`

**Rule 6.2 — Write the `try`/`except` scope first; treat it as a transaction boundary.** A try block defines a scope where execution can abort at any point; your handler must leave the program consistent regardless. Start from a test that forces the exception, then fill in the happy path. `[Clean Code, p.105-106]`

**Rule 6.3 — Provide context with every exception.** State the operation that failed and why; a stack trace tells you *where*, not *what was being attempted*. `[Clean Code, p.107]`
```python
# Violation
raise ValueError("bad input")
# Fix
raise InvalidSoqlQueryError(f"SOQL query rejected by Salesforce: {query!r}: {reason}") from exc
```
`[PROJECT ADAPTATION]` **`raise ... from exc` is mandatory** when re-raising inside an `except` — losing the cause chain destroys exactly the context this rule demands. Enforced by ruff `B904`.

**Rule 6.4 — Define exception classes by the caller's needs, not by source.** Classify by **how they will be caught** — one exception type per *distinct required response*, not one per internal cause. "Often a single exception class is fine for a particular area of code... Use different classes only if there are times when you want to catch one exception and allow the other one to pass through." `[Clean Code, p.107-109]`

**Rule 6.5 — Never swallow an exception.** Silently discarding an error creates an invisible, undebuggable problem. `[CCZTO, p.100]`
```python
# Violation — all three are review rejections
try: refresh()
except: pass
try: refresh()
except Exception: pass
try: refresh()
except Exception as e: log.debug(e)   # debug-level swallow of a real failure
# Fix — handle, or re-raise with context
try:
    refresh()
except SalesforceAuthError:
    raise
except httpx.HTTPError as exc:
    raise SalesforceTransportError("token refresh failed") from exc
```
`[PROJECT ADAPTATION]` Bare `except:` is banned outright. `except Exception` is permitted **only** at the top-level MCP request boundary, where it must log with traceback and convert to an MCP error response.

**Rule 6.6 — Define the normal flow; use a Special Case object.** Where an "exceptional" case is really a business rule, encapsulate it so the client has no special case to handle. `[Clean Code, p.109-110]`
```python
# Violation
try:
    total += expense_report.get_meals(employee.id).total
except MealExpensesNotFoundError:
    total += get_meal_per_diem()
# Fix — DAO always returns a MealExpenses-shaped value; "no meals" is a
# PerDiemMealExpenses whose .total is already the per-diem default
total += expense_report.get_meals(employee.id).total
```

**Rule 6.7 — Don't return `None`; don't pass `None`.** Every `None` return forces a defensive check on every caller, and one missed check is a crash. "The problem is not that it is missing a null check — the problem is that it has too many." Return an empty collection, a Special Case object, or raise. `[Clean Code, p.110-112]`
Martin's honest conclusion on *passing* null: in most languages there is **no good way** to handle it — neither a custom exception nor an assert actually solves it — so the rule is prevention, not handling `[Clean Code, p.112]`.
```python
# Violation
def get_employees() -> list[Employee] | None: ...
# Fix
def get_employees() -> list[Employee]:
    return []  # never None
```
`[PROJECT ADAPTATION]` `-> T | None` is permitted **only** on functions named `find_*`, where absence is a documented, expected outcome. Our prevention mechanism for *passing* `None` is `mypy --strict` + `no_implicit_optional`.

**Rule 6.8 — Wrap third-party errors at the boundary.** No raw vendor exception type escapes the adapter that wraps that dependency. (Full detail in §7.) `[Clean Code, p.107-109]`

### `[PROJECT ADAPTATION]` Our exception hierarchy

Designed per Rule 6.4 — by how callers catch, not by where errors originate.
```
SalesforceMCPError                  # one root: callers can catch everything we raise
├── ConfigurationError              # startup/config — not retryable, fail fast
├── SalesforceError
│   ├── SalesforceAuthError         # re-auth required
│   ├── SalesforceRateLimitError    # retryable, carries retry_after
│   ├── SalesforceQueryError        # caller's SOQL is wrong — not retryable
│   └── SalesforceTransportError    # retryable
└── LLMError
    ├── LLMAuthError
    ├── LLMRateLimitError           # retryable, carries retry_after
    ├── LLMContextLengthError       # caller must shrink input
    └── LLMTransportError           # retryable
```

---

## 7. Boundaries — Wrapping Salesforce and LLM SDKs

The most consequential section for this project. Every rule here is an anti-corruption-layer requirement.

**Rule 7.0 — The boundary tension.** Providers aim for broad generality; users want narrow, focused APIs. That mismatch is where boundary problems live. `[Clean Code, p.114]`

**Rule 7.1 — Never pass a third-party type across an internal boundary.** Don't return or accept one in a public API; keep it inside the class (or small family) that uses it. **WHY:** Martin's `Map` example — when Java 5 changed `Map`'s interface, every site holding a raw `Map` had to change. Wrapping made the change an implementation detail, let the wrapper constrain the API to what the app needs, and made it harder to misuse. `[Clean Code, p.114-115]`
```python
# Violation — leaks the SDK's raw dict shape into domain code
def get_open_opportunities(sf) -> list[dict]:
    return sf.query("SELECT Id, Name FROM Opportunity WHERE StageName != 'Closed'")["records"]
# Fix — wrap it behind our own type
@dataclass(frozen=True)
class Opportunity:
    id: str
    name: str

class SalesforceOpportunities(Protocol):
    def open_opportunities(self) -> list[Opportunity]: ...
```

**Rule 7.2 — Write learning tests for every third-party API, and keep them permanently.** A learning test calls the vendor SDK exactly as we intend to use it and asserts our understanding — "controlled experiments." **Better than free** `[Clean Code, p.118]`: you had to learn the API anyway, so they cost nothing; they *verify* your understanding is correct; and on a version bump you re-run them and learn immediately whether behaviour changed — instead of being stuck on an old version out of fear. `[Clean Code, p.116-118]`
```python
# tests/learning/test_salesforce_auth_learning.py
def test_simple_salesforce_returns_records_key_on_query():
    """Pins simple_salesforce's query() response shape. If this breaks after
    a library upgrade, our SalesforceRestClient adapter needs updating."""
    sf = connect_to_sandbox()
    result = sf.query("SELECT Id FROM Account LIMIT 1")
    assert "records" in result
    assert "totalSize" in result
```
`[PROJECT ADAPTATION]` One module per wrapped SDK in `tests/learning/`, marked `@pytest.mark.learning`, excluded from the default run, executed on a schedule and on **every dependency bump touching that SDK**.

**Rule 7.3 — Design the interface you wish you had, before the vendor API is finalized or fully understood.** Define `LLMProvider` first, in terms our domain needs, and only then write adapters translating to each vendor's wire format. This also creates the test seam — a fake lets you test the client with no network. `[Clean Code, p.118-119]`

**Rule 7.4 — One adapter class per vendor; it is the *only* place that vendor's SDK types may appear.** `[Clean Code, p.119-120]`
```python
class LLMProvider(Protocol):
    def complete(self, messages: list[Message], tools: list[ToolSpec]) -> LlmResponse: ...

class AnthropicAdapter:
    """The ONLY module allowed to import `anthropic`."""
    def __init__(self, client: "anthropic.Anthropic") -> None: ...
    def complete(self, messages, tools) -> LlmResponse:
        raw = self._client.messages.create(...)   # vendor-specific call
        return self._to_llm_response(raw)          # translate at the edge, immediately
```

**Rule 7.5 — Wrap third-party exceptions into our hierarchy at the adapter boundary.** A domain-level `except` must never need to know a vendor's exception class name. Martin's own conclusion from the `ACMEPort` example: **"wrapping third-party APIs is a best practice"** — it minimises dependency, eases mocking, and frees you from a vendor's API design choices. `[Clean Code, p.108-109]`
```python
try:
    return self._sf.query(soql)
except simple_salesforce.exceptions.SalesforceExpiredSession as e:
    raise SalesforceAuthError("session expired") from e
except simple_salesforce.exceptions.SalesforceMalformedRequest as e:
    raise SalesforceQueryError(str(e)) from e
```

**Rule 7.6 — Depend on something you control.** "It's better to depend on something you control than on something you don't control, lest it end up controlling you." Have very few places referring to a vendor API directly. `[Clean Code, p.120]`, `[CCZTO, p.145]`
**Dependencies point inward** `[CCZTO, p.146-147]`: core domain logic is central and abstract; frameworks, DBs and APIs depend on it, never the reverse.

### `[PROJECT ADAPTATION]` The boundary law for this repo

1. **Exactly one module per external system may import its SDK.** `salesforce/client.py` may import `simple_salesforce`/`httpx`; `llm/adapters/<vendor>.py` may import that vendor's SDK. Nothing else, anywhere.
2. **No SDK type crosses an adapter boundary**, in or out. Adapters take and return our own dataclasses/pydantic models.
3. **No SDK exception escapes an adapter** — translate to our hierarchy with `raise ... from exc`.
4. **Every adapter has a Fake** in `tests/fakes/` implementing the same Protocol. Service-layer tests use the Fake; the adapter itself is tested against recorded HTTP.
5. **Adapters carry no business logic** — translation, transport/retry concerns, and error mapping only. If a decision could differ per customer, it isn't adapter code.
6. **Coverage on adapters is 100%** — the one place the type checker can't help, because the data is untyped at the wire.

Mechanically enforced by **import-linter** (§13), not by reviewer vigilance.

---

## 8. Tests

**Project testing policy** `[PROJECT ADAPTATION]`: every module under `src/` gets a corresponding `tests/` module. **Tests are first-class code, reviewed to the same standard as production code.** A "quick and dirty" test is treated as equivalent to no test — dirty tests rot, become a maintenance liability, and get deleted, taking the safety net with them `[Clean Code, p.123]`.

**Rule 8.1 — Three Laws of TDD.** (1) No production code before a failing test exists; (2) write only enough of a test to fail (not importing counts); (3) write only enough production code to pass the currently-failing test. `[Clean Code, p.122]`
`[PROJECT ADAPTATION]` Default workflow for new business logic; exploratory spike code is exempt but must be rewritten test-first before merge.

**Rule 8.2 — Tests enable everything else.** Tests are what keep production code flexible, maintainable and reusable, because **they remove the fear of change** `[Clean Code, p.124]`. With coverage you can improve tangled code "with near impunity"; without, every improvement is a risk nobody takes.

**Rule 8.3 — F.I.R.S.T.** `[Clean Code, p.132-133]`, `[CCZTO, p.122-131]`
- **Fast** — the unit suite runs in seconds; slow tests get skipped and stop catching regressions `[T9, p.314]`.
- **Independent** — no test depends on another's execution, ordering, or shared mutable state; cascading failures obscure root causes.
- **Repeatable** — passes identically on any machine, with no dependency on wall-clock, network, or environment-specific paths. Direct implication: tests hitting real Salesforce/LLM APIs are **integration tests**, never in the default unit run.
- **Self-Validating** — boolean pass/fail; never "read the console to see if it worked."
- **Timely** — written just before the code they cover; tests written long after reveal untestable designs too late.

**Rule 8.4 — Readability, via BUILD-OPERATE-CHECK.** Every test has three visible parts: build the data, operate on it, check the result `[Clean Code, p.127]`. Build a **domain-specific testing language** — helper functions atop the system API so tests read as intent, not mechanics. This API is *not* designed up front; it evolves by refactoring cluttered tests `[Clean Code, p.125-127]`.

**Rule 8.5 — One concept per test, not necessarily one assert.** "One assert per test" is **a good guideline, not a law** — Martin says plainly he is "not afraid to put more than one assert in a test," because splitting can create duplication `[Clean Code, p.130-131]`. The better rule: **minimise asserts per concept, and test exactly one concept per function** `[Clean Code, p.131-132]`. Splitting also surfaces missing cases — his `testAddMonths` example was silently missing a boundary.
```python
# Violation — three unrelated concepts in one test
def test_add_months():
    assert add_months(SerialDate(31, 5, 2004), 1).day == 30
    assert add_months(SerialDate(30, 6, 2004), 1).day == 30
    assert add_months(SerialDate(28, 2, 2004), 1).day == 28
# Fix — one concept, named for what it proves
def test_add_months__lands_on_shorter_month__clamps_to_last_day(): ...
def test_add_months__already_at_month_end__stays_at_month_end(): ...
```

**Rule 8.6 — A dual standard.** Test code may be less *efficient* than production code — the test environment isn't resource-constrained `[Clean Code, p.127-130]`. **This applies to efficiency only, never to cleanliness.** Tests must still be simple, succinct, expressive.

**Rule 8.7 — Mock/fake all I/O in unit tests** (Salesforce, LLM providers, filesystem, clock). Real calls belong only in the integration/learning suites — required by "Fast" and "Repeatable" and made trivial *because* the vendor SDK is confined to one adapter. `[CCZTO, p.123-124]`

### `[PROJECT ADAPTATION]` Policy table

| Policy | Value |
| --- | --- |
| Framework | `pytest` (+ `pytest-asyncio`, `pytest-cov`) |
| Layout | `tests/unit/`, `tests/integration/`, `tests/learning/`, `tests/fakes/` mirroring `src/` |
| Coverage gate | **85% overall**, **100% on `**/adapters/**` and the exception hierarchy** |
| Network | Banned in `unit/`; enforced by a `socket`-blocking autouse fixture |
| Live credentials | Only in `tests/learning/` — opt-in, never in the default run |
| Mocking | Prefer hand-written **Fakes** implementing our Protocols over `unittest.mock`. **WHY:** `Mock` asserts on call shape, coupling tests to implementation; a Fake asserts on behaviour |
| Test length | The 30-line function limit **does not** apply to test bodies; the one-concept rule does |
| Flaky tests | Never retried, never skipped. A spurious failure is a real defect until proven otherwise `[Clean Code, p.187]` |
| Boundary cases | Every boundary condition gets an explicit test `[G3, p.289; T5, p.314]` |
| Bug protocol | A fixed bug requires a regression test **plus** extra tests around that function — bugs congregate `[T6, p.314]` |
| Skipped tests | `@pytest.mark.skip` only to record a genuine requirements ambiguity, with the question in the reason string `[T4, p.313]`. Any other skip fails review |

---

## 9. Classes & Systems

**Rule 9.1 — Class organization.** Order: public constants → class-level variables → instance variables → public methods, with each private helper immediately below the public method that uses it (the stepdown rule). Keep things private; loosening for tests is the one accepted pressure — "tests rule" — but look for a way to preserve privacy first. `[Clean Code, p.135-136]`

**Rule 9.2 — Single Responsibility Principle: one reason to change.** `[Clean Code, p.138]`, `[CCZTO, p.157-159]`
**Mechanical tests** `[Clean Code, p.138]`:
- If you can't derive a concise name, it has too many responsibilities.
- If the name needs `Manager`/`Processor`/`Super`, it has too many responsibilities.
- **You must be able to describe it in ~25 words without "if", "and", "or", or "but".**

**Rule 9.3 — Classes are small, measured by responsibilities, not lines; high cohesion is the signal.** A class is maximally cohesive when each method uses many of its instance variables. **The split signal:** when extracting a function requires promoting many locals to instance variables, cohesion has dropped — and when a subset of methods and variables clusters together and stops touching the rest, that cluster **is a class waiting to be born.** "When classes lose cohesion, split them." `[Clean Code, p.136-141]`
Many small classes beat a few large ones: total complexity is the same, but a developer then only needs to understand the one relevant piece `[Clean Code, p.139-146]`, `[CCZTO, p.114-116]`.

**Rule 9.4 — Open/Closed Principle.** New behaviour arrives as new classes, not by editing existing tested ones — opening a working class risks breaking it and forces a full retest. `[Clean Code, p.147-149]`, `[CCZTO, p.160-161]`
```python
# Violation — every new statement type requires editing Sql
class Sql:
    def generate(self, kind: str) -> str:
        if kind == "select": ...
        elif kind == "insert": ...
# Fix — closed to modification, open to extension
class SqlStatement(Protocol):
    def generate(self) -> str: ...
class SelectSql: ...
class InsertSql: ...
```

**Rule 9.5 — Dependency Inversion Principle.** Depend on abstractions (Protocols), not concretions; inject via constructor rather than instantiating inside. This is the mechanism that makes §7's wrapping and §8's faking possible. `[Clean Code, p.149-150]`, `[CCZTO, p.117-118, 166-168]`
```python
# Violation — untestable, un-swappable
class CompletionService:
    def __init__(self) -> None:
        self._sdk = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
# Fix
class CompletionService:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider
```

**Rule 9.6 — Separate construction from use.** Compose the object graph in one place; everything else assumes it already has what it needs. Ad-hoc lazy initialization hard-codes dependencies, complicates testing, and violates SRP by making one method do two things. Dependency arrows point **away** from `main`. `[Clean Code, p.154-157]`, `[CCZTO, p.117-118]`
`[PROJECT ADAPTATION]` `salesforce_mcp/__main__.py` is the **only** module that reads environment variables and constructs adapters. **Constructor injection only — no DI framework, no service locator, no global registry.** WHY: with `main` doing the wiring, a container adds a dependency and an indirection to solve a problem we don't have, and Martin's warning about adopting standards only when they add demonstrable value applies `[Clean Code, p.168]`.

**Rule 9.7 — Cross-cutting concerns.** Persistence, security, logging and transactions cut across object boundaries; per-object implementation produces duplicated, non-modular code `[Clean Code, p.157-161]`. Martin's Java answers (dynamic proxies, Spring AOP, AspectJ) don't translate `[Clean Code, p.161-166]`.
`[PROJECT ADAPTATION]` **Python translation:** **decorators** for retry/timing/tracing, **context managers** for resource and transaction scope, **middleware** at the MCP request boundary for auth and logging. Never metaclasses or monkey-patching — they hide control flow, violating "expresses intent".

**Rule 9.8 — Architecture grows incrementally; no BDUF.** Build the simplest thing satisfying today's requirement, keep concerns separated so growth doesn't require rework, and **defer irreversible decisions to the last responsible moment** — so they're made with the most information. BDUF is harmful partly for psychological reasons: people resist discarding prior effort, and early choices bias later thinking. `[Clean Code, p.166-168]`

**Rule 9.9 — Use standards wisely, only when they add demonstrable value.** Teams get obsessed with hyped standards and lose sight of delivering value. `[Clean Code, p.168]`

**Rule 9.10 — Kent Beck's Four Rules of Simple Design, in priority order.** `[Clean Code, p.172-176]` (reproduced at the top of this document as the conflict-resolution order)
1. **Runs all the tests** — an unverifiable design is worthless; testability itself pushes toward SRP and low coupling.
2. **Contains no duplication** — extraction, and Template Method for structural duplication.
3. **Expresses the intent of the programmer** — good names, small units, standard nomenclature, expressive tests as documentation.
4. **Minimizes the number of classes and methods** — lowest priority; guards against dogma, never overrides 1–3.

---

## 10. Concurrency

Applies wherever we run concurrent MCP tool calls, parallel Salesforce requests, or async LLM streaming.

**Rule 10.1 — Concurrency is a decoupling strategy (what vs. when), not a default performance switch.** It helps only when there is real wait time to overlap; it always adds design and testing cost. `[Clean Code, p.178-180]`
**Myths to reject** `[Clean Code, p.179-180]`: "concurrency always improves performance"; "design doesn't change"; "you needn't understand it if a framework handles it." Truths: it adds overhead in performance *and* code; correctness is hard even in simple cases; **bugs are not repeatable and get dismissed as one-offs.**

**Rule 10.2 — Apply SRP to concurrency.** Concurrency-related code has its own lifecycle, challenges and failure modes — keep it separate from business logic, which stays plain and independently testable. `[Clean Code, p.181]`

**Rule 10.3 — Minimize and encapsulate shared mutable state.** Prefer independent tasks; where sharing is unavoidable, pass copies/immutable values, and confine mutations to as few and as small critical sections as possible. `[Clean Code, p.181-182, 185]`, `[CCZTO, p.104-113]`

**Rule 10.4 — Beware dependencies between synchronized methods.** Avoid calling more than one method on a shared object; if unavoidable, use client-based locking, server-based locking, or an adapted server. `[Clean Code, p.185]`

**Rule 10.5 — Know the execution models and vocabulary.** Producer-Consumer, Readers-Writers, Dining Philosophers; mutual exclusion, starvation, deadlock, livelock, bound resources. `[Clean Code, p.183-185]`

**Rule 10.6 — Shutdown code is hard.** Think about graceful shutdown **early**; the classic failure is a consumer blocked forever waiting on a producer that already exited. `[Clean Code, p.186]`

**Rule 10.7 — Test concurrent code deliberately.** Run with more concurrent tasks than production; **treat any intermittent failure as a real concurrency bug, never a one-off to re-run away**; get non-threaded code working first; keep business logic 100% testable without an event loop; run on every target platform. `[Clean Code, p.186-189]`

**Rule 10.8 — `[PROJECT ADAPTATION]` Python translation.**
- `asyncio` throughout the I/O path; never mix a sync SDK into an async path without `asyncio.to_thread`.
- Structured concurrency (`asyncio.TaskGroup`/`anyio`) over fire-and-forget tasks; `asyncio.Lock`/`Queue` over hand-rolled flags.
- Concurrency lives in dedicated modules, never sprinkled through business logic (Rule 10.2).
- **Shared mutable module-level state is banned.** Config is frozen and injected; caches are explicit objects with explicit locks.
- Every `asyncio.gather` fan-out is bounded by a `Semaphore` — an unbounded fan-out against Salesforce governor limits is a defect.
- Graceful shutdown implemented and tested from the first milestone, not retrofitted.
- `pytest-asyncio` runs in `--asyncio-mode=strict`.

---

## 11. Code Smells & Heuristics Checklist — the Review Gate

Reproduced from `[Clean Code, Ch.17, p.285-314]`. Used mechanically: any diff introducing one of these gets a comment citing the code.

**Comments**
- **C1 — Inappropriate Information**: metadata (author, changelog, ticket ref) belongs in git/issue tracker `[p.286]`
- **C2 — Obsolete Comment**: no longer matches the code; update or delete `[p.286]`
- **C3 — Redundant Comment**: says only what the code already says `[p.286]`
- **C4 — Poorly Written Comment**: if worth writing, write it well — brief, correct grammar `[p.287]`
- **C5 — Commented-Out Code**: delete it; git remembers `[p.287]`

**Environment**
- **E1 — Build Requires More Than One Step**: checkout, then one command `[p.287]`
- **E2 — Tests Require More Than One Step**: one command or one button runs the full suite `[p.287]`

**Functions**
- **F1 — Too Many Arguments**: zero best; three is the ceiling `[p.288]`
- **F2 — Output Arguments**: arguments are inputs; mutate the owning object instead `[p.288]`
- **F3 — Flag Arguments**: a boolean parameter announces the function does more than one thing `[p.288]`
- **F4 — Dead Function**: never-called functions get deleted `[p.288]`

**General**
- **G1 — Multiple Languages in One Source File**: minimise embedded SQL/HTML/JSON in a Python module `[p.288]`
- **G2 — Obvious Behavior Is Unimplemented**: Principle of Least Surprise `[p.288]`
- **G3 — Incorrect Behavior at the Boundaries**: don't trust intuition; test every boundary `[p.289]`
- **G4 — Overridden Safeties**: don't disable warnings or turn off failing tests to unblock a merge `[p.289]`
- **G5 — Duplication**: every duplication is a missed abstraction `[p.289]`
- **G6 — Code at Wrong Level of Abstraction**: separate high and low concepts cleanly; never fake it `[p.290]`
- **G7 — Base Classes Depending on Their Derivatives**: a Protocol/ABC must never reference its implementations `[p.291]`
- **G8 — Too Much Information**: small tight interfaces; hide data, helpers, constants `[p.291]`
- **G9 — Dead Code**: unreachable branches, unused imports/variables; delete `[p.292]`
- **G10 — Vertical Separation**: declare variables and helpers close to their use `[p.292]`
- **G11 — Inconsistency**: same concept, same name, every time `[p.292]`
- **G12 — Clutter**: no empty `__init__`s, unused variables, no-op comments `[p.293]`
- **G13 — Artificial Coupling**: don't stash a general constant/enum inside an unrelated module for convenience `[p.293]`
- **G14 — Feature Envy**: a method mostly reaching into another object's data belongs on that object `[p.293]`
- **G15 — Selector Arguments**: includes non-boolean "mode" arguments used to select behaviour `[p.294]`
- **G16 — Obscured Intent**: no dense one-liners, no unexplained magic numbers/abbreviations `[p.295]`
- **G17 — Misplaced Responsibility**: put code where a reader would naturally look `[p.295]`
- **G18 — Inappropriate Static/`@staticmethod`**: if behaviour might ever vary by type, it isn't static `[p.296]`
- **G19 — Use Explanatory Variables**: name intermediate steps instead of one dense expression `[p.296]`
- **G20 — Function Names Should Say What They Do**: including whether they mutate in place `[p.297]`
- **G21 — Understand the Algorithm**: passing tests isn't enough — know *why* it works `[p.297]`
- **G22 — Make Logical Dependencies Physical**: ask the module for a value, don't hardcode the assumption `[p.298]`
- **G23 — Prefer Polymorphism to If/Else or Switch/Case**: the "ONE SWITCH" rule `[p.299]`
- **G24 — Follow Standard Conventions**: the formatter/linter config *is* the convention `[p.299]`
- **G25 — Replace Magic Numbers with Named Constants**: applies to any non-self-evident literal `[p.300]`
- **G26 — Be Precise**: no floats for money, no assuming the first result is the only result `[p.301]`
- **G27 — Structure over Convention**: a Protocol that *forces* implementers beats a naming convention `[p.301]`
- **G28 — Encapsulate Conditionals**: extract a named predicate instead of an inline boolean `[p.301]`
- **G29 — Avoid Negative Conditionals**: `if is_ready:` over `if not is_not_ready:` `[p.302]`
- **G30 — Functions Should Do One Thing** `[p.302]`
- **G31 — Hidden Temporal Couplings**: if B must follow A, make A's output B's required input `[p.302]`
- **G32 — Don't Be Arbitrary**: structure needs a reason a reader can infer `[p.303]`
- **G33 — Encapsulate Boundary Conditions**: name `next_index = index + 1` once `[p.304]`
- **G34 — Functions Should Descend Only One Level of Abstraction** `[p.304]`
- **G35 — Keep Configurable Data at High Levels**: defaults live at the entry point and pass down `[p.306]`
- **G36 — Avoid Transitive Navigation**: know only immediate collaborators `[p.306]`

**Names**
- **N1 — Choose Descriptive Names**: ~90% of readability `[p.309]`
- **N2 — Choose Names at the Appropriate Level of Abstraction**: don't leak implementation `[p.311]`
- **N3 — Use Standard Nomenclature Where Possible**: pattern names, Python idioms, our ubiquitous language `[p.311]`
- **N4 — Unambiguous Names**: long and clear beats short and ambiguous `[p.312]`
- **N5 — Use Long Names for Long Scopes** `[p.312]`
- **N6 — Avoid Encodings** `[p.312]`
- **N7 — Names Should Describe Side Effects**: `get_or_create_x`, not `get_x` `[p.313]`

**Tests**
- **T1 — Insufficient Tests**: "that seems like enough" is not a metric `[p.313]`
- **T2 — Use a Coverage Tool** `[p.313]`
- **T3 — Don't Skip Trivial Tests**: cheap, high documentary value `[p.313]`
- **T4 — An Ignored Test Is a Question about an Ambiguity** `[p.313]`
- **T5 — Test Boundary Conditions**: empty input, max batch size, rate-limit edge, token-limit edge `[p.314]`
- **T6 — Exhaustively Test Near Bugs**: bugs congregate `[p.314]`
- **T7 — Patterns of Failure Are Revealing** `[p.314]`
- **T8 — Test Coverage Patterns Can Be Revealing** `[p.314]`
- **T9 — Tests Should Be Fast** `[p.314]`

> Ch.17 also carries a Java-specific J1–J3 (wildcard imports, inherited constants, constants vs enums) `[p.307-309]`, superseded here by §12.

---

## 12. Python-Specific Mapping `[PROJECT ADAPTATION]`

The books predate Python's modern type-hinted style and are Java/JS-centric; this section is our translation and is fully open to challenge.

- **Type hints everywhere.** Every signature fully annotated; `mypy --strict` passes with zero unjustified `# type: ignore`. This is our replacement for the compiler-enforced guarantees Martin assumes, and the mechanism enforcing Rule 6.7. Every `# type: ignore` must be narrowed (`# type: ignore[arg-type]`) with a one-line reason.
- **Dataclasses/pydantic models over raw `dict`s** for any structured value crossing a boundary. **No `dict[str, Any]` crosses a module boundary** — a bare dict is disinformation (Rule 1.2) and defers every error to runtime. Use `pydantic.BaseModel` at wire boundaries (needs runtime validation), `@dataclass(frozen=True, slots=True)` for internal value objects (cheaper, and immutability enforces Rule 2.7), `enum.StrEnum` for closed string sets — never bare literals compared with `==`.
- **Exceptions:** no bare `except:`; no `except Exception` outside the MCP request boundary; `raise ... from exc` mandatory; **never `assert` for runtime validation** (`-O` strips it); custom exceptions end in `Error` and subclass `SalesforceMCPError`.
- **Context managers (`with`) for every acquired resource** — HTTP sessions, file handles, locks, DB connections. This is Rule 6.2 ("define the scope first") expressed in Python's own grammar. Manual `.close()` in a `finally` is a smell; write `@contextmanager`.
- **Standard-library idioms:** `pathlib.Path` over `os.path`; f-strings over `%`/`.format()`; `logging` over `print()`; timezone-aware `datetime.now(tz=UTC)`; `enumerate`/`zip` over manual index counters.
  **Logging exception:** always lazy `%s` formatting — `log.info("id=%s", x)`, **never** `log.info(f"id={x}")` — so unrendered messages cost nothing and structured processors can group by template.
- **Module layout:**
```
src/salesforce_mcp/
├── __init__.py            # version + public re-exports ONLY
├── __main__.py            # the ONLY place reading env vars and wiring objects (Rule 9.6)
├── config.py              # frozen settings objects
├── errors.py              # the exception hierarchy (§6)
├── models/                # dataclasses + pydantic models (data structures, Rule 5.2)
├── salesforce/
│   ├── client.py          # our Protocol — no SDK imports
│   └── adapter.py         # the ONLY module importing the Salesforce SDK
├── llm/
│   ├── client.py          # the LLMProvider Protocol
│   └── adapters/          # one module per vendor; each the ONLY importer of its SDK
├── tools/                 # one module per MCP tool
└── server.py              # MCP wiring, request boundary, middleware
```
  **Layering rule** (dependencies point inward, `[CCZTO, p.146-147]`): `server` → `tools` → `salesforce`/`llm` interfaces → `models`/`errors`. **Never the reverse.** `models` and `errors` import nothing from the project.
- **`__init__.py` policy:** re-exports and `__version__` **only**. No logic, no side effects, no imports-for-side-effects. Sub-package `__init__.py` stays empty unless defining a deliberate public API. **WHY:** logic there runs on import, is invisible at the call site, and is the single largest cause of circular imports.
- **Circular imports are a design defect, not a packaging problem.** Fix the layering. Type-only imports go under `if TYPE_CHECKING:` with `from __future__ import annotations`. A runtime import inside a function body is banned except to break a genuine cycle, and then needs a comment plus a TODO to fix the layering. **WHY:** a cycle means two modules share a reason to change — an SRP violation `[Clean Code, p.138]` in disguise. The Protocol lives in the layer that *uses* it, never the layer that implements it.
- **No hardcoded values** `[CCZTO, p.150-151]`. Constants at module top or in `config.py`; environment-specific values (credentials, endpoints, API versions) come from env vars via one frozen settings object read **only** in `__main__.py` `[CCZTO, p.152-153]`. Secrets never reach a log line or an exception message. This is G35.
- **Dependency hygiene** `[CCZTO, p.139-149]`: limit dependencies to the essential; keep versions current on a fixed cadence; respect SemVer and read changelogs; wrap each one (§7); never let major upgrades pile up. Pinned in `uv.lock`; Dependabot weekly; **every bump re-runs `tests/learning/`** — precisely the payoff Rule 7.2 promises.

---

## 13. Toolchain — Mechanical Enforcement `[PROJECT ADAPTATION]`

Nothing here is enforced by good intentions. These are the actual config values.

### 13.1 `pyproject.toml`

```toml
[project]
requires-python = ">=3.12"

# ─────────────────────── ruff: formatter + linter ───────────────────────
[tool.ruff]
line-length = 100                      # §4 — stricter end of Martin's 100–120 band
target-version = "py312"
src = ["src", "tests"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
skip-magic-trailing-comma = false
docstring-code-format = true

[tool.ruff.lint]
select = [
  "E", "W",    # pycodestyle
  "F",         # pyflakes — dead code, unused imports (G9, G12)
  "I",         # isort — import ordering (G11)
  "N",         # pep8-naming (§1)
  "D",         # pydocstyle (§3)
  "UP",        # pyupgrade — modern idioms (§12)
  "ANN",       # flake8-annotations — type hints everywhere (§12)
  "S",         # flake8-bandit — security; we handle SF/LLM credentials
  "B",         # flake8-bugbear — B904 raise-from (Rule 6.3)
  "A",         # flake8-builtins — no shadowing (G16)
  "C4",        # comprehensions
  "DTZ",       # naive datetimes (§12)
  "T20",       # no print (§12)
  "PT",        # pytest style (§8)
  "RET",       # return consistency (Rule 2.7)
  "SIM",       # simplify (G29 negative conditionals)
  "ARG",       # unused arguments (G12 clutter)
  "PTH",       # pathlib over os.path (§12)
  "ERA",       # ERADICATE — commented-out code (C5) ← non-negotiable
  "PL",        # pylint subset — complexity + arg count
  "TRY",       # tryceratops — exception antipatterns (§6)
  "G",         # logging-format — lazy %s logging (§12)
  "FBT",       # flake8-boolean-trap — FLAG ARGUMENTS (Rule 2.5, F3/G15) ← non-negotiable
  "C90",       # mccabe complexity
  "RUF",
]
ignore = [
  "D203",    # conflicts with D211
  "D213",    # conflicts with D212
  "ANN401",  # explicit Any allowed where genuinely needed — must be justified in review
]

[tool.ruff.lint.per-file-ignores]
"tests/**"           = ["S101", "D103", "ANN201", "PLR2004"]  # asserts ok, no docstrings (§3)
"src/**/__init__.py" = ["D104"]

[tool.ruff.lint.mccabe]
max-complexity = 8                     # §4 — proxy for "do one thing"

[tool.ruff.lint.pylint]
max-args = 3                           # Rule 2.4 — [p.40], [F1 p.288]; excludes self
max-branches = 8
max-statements = 30                    # Rule 2.1 — function hard cap [p.34]
max-returns = 6                        # early-return guards encouraged (Rule 2.10)

[tool.ruff.lint.pydocstyle]
convention = "google"                  # §3

[tool.ruff.lint.flake8-annotations]
mypy-init-return = true
suppress-none-returning = false

[tool.ruff.lint.isort]
known-first-party = ["salesforce_mcp"]
required-imports = ["from __future__ import annotations"]   # §12 circular imports

# ───────────────────────────── mypy: strict ─────────────────────────────
[tool.mypy]
python_version = "3.12"
strict = true
warn_unreachable = true                # G9 dead code
warn_return_any = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
disallow_any_generics = true
no_implicit_optional = true            # Rule 6.7 — don't pass None [p.111-112]
strict_equality = true
enable_error_code = [
  "redundant-expr", "possibly-undefined",
  "truthy-bool", "ignore-without-code",   # forces `# type: ignore[code]`
]

[[tool.mypy.overrides]]
module = ["tests.*"]
disallow_untyped_defs = false

# ─────────────────────────────── pytest ───────────────────────────────
[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
asyncio_mode = "strict"                                    # Rule 10.8
addopts = """
  -ra --strict-markers --strict-config
  --cov=salesforce_mcp --cov-report=term-missing
  --cov-fail-under=85
  -m 'not learning and not integration'
"""
markers = [
  "learning: learning tests against real third-party APIs (Rule 7.2); excluded by default",
  "integration: requires a live dependency; excluded from the fast unit run",
]

[tool.coverage.report]
exclude_also = ["if TYPE_CHECKING:", "raise NotImplementedError", "@overload"]
```

### 13.2 `.importlinter` — the boundary law, mechanically

This is what makes §7.6 real rather than aspirational.

```ini
[importlinter]
root_package = salesforce_mcp

[importlinter:contract:layers]
name = Dependencies point inward
type = layers
layers =
    salesforce_mcp.server
    salesforce_mcp.tools
    salesforce_mcp.salesforce | salesforce_mcp.llm
    salesforce_mcp.models | salesforce_mcp.errors

[importlinter:contract:salesforce-sdk]
name = Only the Salesforce adapter may import the Salesforce SDK
type = forbidden
source_modules = salesforce_mcp
forbidden_modules = simple_salesforce
ignore_imports = salesforce_mcp.salesforce.adapter -> simple_salesforce

[importlinter:contract:llm-sdks]
name = Only each vendor adapter may import its own SDK
type = forbidden
source_modules = salesforce_mcp
forbidden_modules = anthropic, openai, cohere
ignore_imports =
    salesforce_mcp.llm.adapters.anthropic -> anthropic
    salesforce_mcp.llm.adapters.openai -> openai
    salesforce_mcp.llm.adapters.cohere -> cohere
```

### 13.3 `.pre-commit-config.yaml`

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.6
    hooks:
      - id: ruff-format                      # §4.10 — formatter is not reviewed
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.15.0
    hooks:
      - id: mypy
        args: [--strict]
        additional_dependencies: [pydantic, types-requests]

  - repo: https://github.com/seddonym/import-linter
    rev: v2.1
    hooks:
      - id: import-linter                    # §7.6 boundary law

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: end-of-file-fixer
      - id: trailing-whitespace
      - id: check-merge-conflict
      - id: check-added-large-files
      - id: detect-private-key
      - id: check-toml
      - id: check-yaml

  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.23.3
    hooks:
      - id: gitleaks                         # Salesforce creds + LLM API keys
```

### 13.4 CI gates (all blocking)

| Gate | Command | Enforces |
| --- | --- | --- |
| Format | `ruff format --check .` | §4 |
| Lint | `ruff check .` | §1–§3, §11 |
| Types | `mypy --strict src tests` | §12, Rule 6.7 |
| Boundaries | `lint-imports` | §7.6 |
| Tests | `pytest` | §8 |
| Adapter coverage | `pytest --cov=salesforce_mcp.salesforce.adapter --cov=salesforce_mcp.llm.adapters --cov-fail-under=100` | §7.6 rule 6 |
| Module length | fail any `.py` over 400 lines | §4 |
| Secrets | `gitleaks detect` | §12 |
| Deps | `uv lock --check`; weekly Dependabot; learning tests on every bump | §12, Rule 7.2 |

**E1/E2 compliance** `[Clean Code, p.287]`: the whole build is `make check`; the whole suite is `pytest`. One step each.

**On overriding safeties (G4, `[p.289]`):** `# noqa`, `# type: ignore`, and `@pytest.mark.skip` each require a narrowed code and a one-line justification. An unexplained suppression fails review — that is exactly the overridden safety Martin warns about.

---

## THE 20 RULES

The non-negotiable review gate, ranked. A change violating any of these does not merge.

1. **No vendor SDK type, import, or exception escapes its single adapter module** — one adapter per vendor, enforced by import-linter `[Clean Code, p.114-120]`
2. **Failure is signalled by raising** — never a return code, `None`, an error dict, or an `(ok, value)` tuple `[Clean Code, p.46, 104, 110]`
3. **Every exception carries context and preserves its cause with `raise ... from exc`** `[Clean Code, p.107]`
4. **No swallowed exceptions** — no bare `except:`; no `except Exception` outside the MCP request boundary `[CCZTO, p.100]`
5. **`mypy --strict` passes clean** — every signature annotated, every `# type: ignore` narrowed and justified `[PROJECT ADAPTATION]`
6. **Never return or pass `None` for "nothing here"** — empty collection, Special Case object, or raise; `| None` only on `find_*` `[Clean Code, p.110-112]`
7. **Functions ≤30 lines, ≤3 positional args, ≤3 nesting levels, complexity ≤8** `[Clean Code, p.34-35, 40]`
8. **A function does one thing** — you cannot extract a sub-function with a non-restating name `[Clean Code, p.35]`
9. **No flag arguments** — a boolean that selects a code path means two functions `[Clean Code, p.41; F3, p.288]`
10. **Command-Query Separation and no hidden side effects** — a name describes everything the function does, including what it mutates `[Clean Code, p.44-46; N7, p.313]`
11. **Names are intention-revealing, searchable, and unencoded** — if a name needs a comment, the name is wrong `[Clean Code, p.18, 22, 23]`
12. **One word per concept**, per the project lexicon — `fetch_`/`get_`/`find_`/`list_` mean exactly what §1.9 says `[Clean Code, p.26]`
13. **No commented-out code, no journal comments, no redundant comments** — git remembers `[Clean Code, p.68; C5, p.287]`
14. **Docstrings on public API, MCP tools, and exceptions; forbidden on private functions and tests** — document why and raises, never types `[Clean Code, p.59, 63, 71]`
15. **New logic ships with tests** — ≥85% overall, 100% on adapters, no network in unit tests `[Clean Code, p.122; T1, p.313]`
16. **Tests are F.I.R.S.T. and test one concept each; a flaky test is a defect, never a retry** `[Clean Code, p.131-133, 187]`
17. **Every wrapped third-party API has permanent learning tests, re-run on every dependency bump** `[Clean Code, p.116-118]`
18. **Every boundary condition has an explicit test** `[Clean Code, G3 p.289; T5 p.314]`
19. **SRP + DIP + separated construction** — a class describable in ~25 words without "and"/"or"; dependencies constructor-injected against a Protocol; all wiring in `__main__` `[Clean Code, p.138, 149-150, 155]`
20. **No duplication, no magic values, and the formatter/linter is law** — extract the second copy, name every literal, and never suppress a check without a written reason `[Clean Code, p.48, 90; G4 p.289; G5 p.289; G25 p.300]`
