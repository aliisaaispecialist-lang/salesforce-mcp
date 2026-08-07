# Research 05 — Packaging & README Doctrine
Project: Python Salesforce MCP server + provider-agnostic LLM client (pip-installable, PyPI-publishable)
Status: RESEARCH ONLY — no application code, no final README written here.

---

## D. PEP 621 — the normative spec behind `[project]`
Source: https://peps.python.org/pep-0621/ ("Storing project metadata in pyproject.toml")

PEP 621 is the origin spec for the `[project]` table. Its own header notes it is now a **historical document**: "the up-to-date, canonical spec... is maintained on the PyPA specs page" (i.e. https://packaging.python.org/en/latest/specifications/pyproject-toml/). Where PEP 621 and the packaging.python.org guides in Sections A-C differ in *detail*, PEP 621 is treated here as authoritative for the *original* semantics, and later PEPs (639, 685 — below) are flagged explicitly wherever they amend it. This section fills in the normative detail the guides in Section B summarized loosely.

### D1. Full `[project]` field list — type and semantics (PEP 621, verbatim/paraphrased)

| Field | Type | Semantics |
|---|---|---|
| `name` | string | The project name. **Must** be statically specified — cannot be listed in `dynamic` (see D3). |
| `version` | string | PEP 440-valid version string. |
| `description` | string | "The summary description of the project." |
| `readme` | string \| table | Full project description — see D2. |
| `requires-python` | string | Python version requirement. |
| `license` | table (PEP 621 original) | See D4 — **superseded by PEP 639**. |
| `authors` | array of inline tables | Each entry optionally has `name` and/or `email`. |
| `maintainers` | array of inline tables | Same shape as `authors`. |
| `keywords` | array of strings | Search keywords. |
| `classifiers` | array of strings | Trove classifiers. |
| `urls` | table | key = URL label, value = URL. |
| `scripts` | table | `[project.scripts]` — console-script name → object reference. |
| `gui-scripts` | table | `[project.gui-scripts]` — same format as `scripts`, GUI-flagged on Windows. |
| `entry-points` | table of tables | `[project.entry-points.<group>]` — arbitrary plugin groups, **one level deep only** (no nested sub-tables). |
| `dependencies` | array of PEP 508 strings | Required runtime deps. |
| `optional-dependencies` | table of arrays of PEP 508 strings | Extras — see D6. |
| `dynamic` | array of strings | Fields intentionally left for the build backend to fill in — see D3. |

Note: `license-files` is **not** part of original PEP 621 at all — confirmed absent from the PEP text; it was introduced later by PEP 639 (D4).

### D2. The `readme` field's two forms — exact rule for when the table form is required
Verbatim from PEP 621:

**Form 1 — plain string (shorthand)**, a relative file path:
```toml
readme = "README.md"
```
> "If the file path ends in a case-insensitive `.md` suffix, then tools MUST assume the content-type is `text/markdown`. If the file path ends in a case-insensitive `.rst`, then tools MUST assume the content-type is `text/x-rst`."
> "For all unrecognized suffixes when a content-type is not provided, tools MUST raise an error."

So the string shorthand is a hard error for any extension other than `.md`/`.rst` (e.g. `README.txt` cannot use the shorthand).

**Form 2 — table**, required whenever you need to (a) supply inline text instead of a file, (b) use a non-`.md`/`.rst` filename, or (c) be explicit about content-type:
```toml
readme = {file = "README.md", content-type = "text/markdown"}
# or, inline text instead of a file:
readme = {text = "... full description ...", content-type = "text/markdown"}
```
> "The `file` key has a string value representing a relative path to a file containing the full description. The `text` key has a string value which is the full description. These keys are mutually-exclusive, thus tools MUST raise an error if the metadata specifies both keys."
> "A table specified in the `readme` field also has a `content-type` field which takes a string specifying the content-type of the full description. A tool MUST raise an error if the metadata does not specify this field in the table." — i.e. **`content-type` is mandatory whenever the table form is used**, unlike the string shorthand where it's inferred.

This ties directly back to Section A3: whichever form is used, the resulting `Description-Content-Type` core-metadata field is what PyPI's renderer keys off, and getting it wrong/omitted degrades to raw-text rendering.

### D3. The `dynamic` field — exact rules
Verbatim from PEP 621:
- Purpose: "Specifies which fields listed by this PEP were intentionally unspecified so another tool can/will provide such metadata dynamically. This clearly delineates which metadata is purposefully unspecified."
- **`name` can never be dynamic**: "Build back-ends MUST raise an error if the metadata specifies the `name` in `dynamic`."
- **Mutual exclusion rule (important)**: "Build back-ends MUST raise an error if the metadata specifies a field statically as well as being listed in `dynamic`." — a field is either given a static value in `[project]` **or** listed in `dynamic`, never both.
- **Required-field rule**: "If the core metadata specification lists a field as 'Required', then the metadata MUST specify the field statically or list it in `dynamic`" — you cannot silently omit a required field altogether.
- **Backend authority**: "If the metadata does not list a field in `dynamic`, then a build back-end CANNOT fill in the requisite metadata on behalf of the user" — `dynamic` is the only sanctioned escape hatch for backend-computed values; a backend is not allowed to override a field that's simply absent-but-not-declared-dynamic.

**Should we use `dynamic` for `version`?** Per Section B7's recommendation: not initially. Pre-1.0, hard-code `version = "0.1.0"` statically (simplest, matches PEP 621's default expectation). Once we're cutting frequent tagged releases, switch to `dynamic = ["version"]` plus a VCS-based backend plugin (`hatch-vcs`) — which is exactly the mechanism `dynamic` exists for: letting the backend compute the version from git tags at build time instead of hand-editing the file per release.

### D4. `license` — original PEP 621 form vs. current PEP 639 form (supersession, stated plainly)
**Original PEP 621 form (legacy — do not use for new projects):**
```toml
license = {file = "LICENSE.txt"}
# or
license = {text = "... full license text or SPDX-like identifier as free text ..."}
```
Verbatim: "The table may have one of two keys. The `file` key has a string value that is a relative file path to the file which contains the license for the project... The `text` key has a string value which is the license of the project whose meaning is that of the `License` field from the core metadata. These keys are mutually exclusive." PEP 621 itself flagged this as provisional: "A practical string value for the `license` key has been purposefully left out to allow for a future PEP to specify support for SPDX expressions" — i.e. the authors already knew this table form was a placeholder.

**That future PEP arrived: PEP 639 ("Improving License Clarity with Better Package Metadata").** Source: https://peps.python.org/pep-0639/ (via search-result corroboration, consistent with Section B1a of this doc). PEP 639 **adds and deprecates** the corresponding PEP 621 keys:
- Adds `License-Expression` (core metadata) / `license` **as a bare SPDX string** (not a table) at the `pyproject.toml` level:
  ```toml
  license = "MIT"
  # or a compound SPDX expression:
  license = "MIT AND (Apache-2.0 OR BSD-2-Clause)"
  ```
- Adds `license-files` (glob patterns for files to ship, replacing the old single `file` key):
  ```toml
  license-files = ["LICEN[CS]E*"]
  ```
- **Deprecates** the legacy `License:` core-metadata field and the `License ::` trove classifiers.

**Current authority / recommendation: use the PEP 639 form** (`license = "<SPDX-expr>"` + `license-files = [...]`), exactly as already recommended in Section B1/B1a of this document. Do **not** use the PEP 621 `license = {file=...}`/`{text=...}` table form for a new project — it is the legacy form. (Build-backend version floors for PEP 639 support were already noted in B1: Hatchling ≥1.27, setuptools ≥77.0.3, flit-core ≥3.12, pdm-backend ≥2.4.0, poetry-core ≥2.2.0, uv-build ≥0.7.19.)

### D5. `entry-points` / `scripts` / `gui-scripts` — normative syntax
Verbatim from PEP 621:
- `[project.scripts]`: "The key of the table is the name of the entry point and the value is the object reference." Example: `spam-cli = "spam:main_cli"`.
- `[project.gui-scripts]`: "Its format is the same as `[project.scripts]`." Example: `spam-gui = "spam:main_gui"`.
- `[project.entry-points]`: "a collection of tables. Each sub-table's name is an entry point group. The key and value semantics are the same as `[project.scripts]`. Users MUST NOT create nested sub-tables but instead keep the entry point groups to only one level deep." Example: `[project.entry-points."spam.magical"]` with `tomatoes = "spam:main_tomatoes"`.
- **Explicit collision guard**: "Build back-ends MUST raise an error if the metadata defines a `[project.entry-points.console_scripts]` or `[project.entry-points.gui_scripts]` table, as they would be ambiguous in the face of `[project.scripts]` and `[project.gui-scripts]`, respectively." — i.e. you cannot spell the console-scripts group out manually under `[project.entry-points]`; you MUST use the dedicated `[project.scripts]` table for it.

Applied to us, this confirms the declaration already used in Section B4 is the only legal spelling:
```toml
[project.scripts]
salesforce-mcp = "salesforce_mcp.server:main"
```
and confirms *why*: writing `[project.entry-points.console_scripts]` instead would be a spec violation a conformant backend must reject.

### D6. `optional-dependencies` — syntax and extra-name normalization (PEP 621 + PEP 685 amendment)
PEP 621 verbatim: "it is a table where each key specifies an extra and whose value is an array of strings. The strings of the arrays must be valid PEP 508 strings. The keys MUST be valid values for the `Provides-Extra` core metadata." Example:
```toml
[project.optional-dependencies]
test = [
  "pytest < 5.0.0",
  "pytest-cov[all]"
]
```
**Gap in PEP 621 itself**: it requires extra names to be "valid" per `Provides-Extra` but does not specify how two spellings of an extra name (e.g. `long-description-test` vs `long_description_test` vs `LONG.DESCRIPTION.TEST`) should be compared/deduplicated.

**That gap is closed by PEP 685** ("Comparison of extra names for optional distribution dependencies"), source: https://peps.python.org/pep-0685/ (via search corroboration). Key points:
- The problem: `Provides-Extra` metadata requires an extra's name to be "a valid Python identifier," but PEP 508's extra-marker syntax additionally allows letters, digits, `.`, `-`, and `_` — so there was no single agreed normalization for comparing names.
- The fix: extra names are normalized using **PEP 503 normalization** (the same case-insensitive, `.`/`-`/`_`-collapsing rule already used for distribution/package names on PyPI) applied on top of PEP 508's accepted character set — i.e. `Anthropic-SDK`, `anthropic_sdk`, and `anthropic.sdk` are all the **same extra** after normalization, and tools MUST treat them as identical / MUST NOT allow a package to define two extras that normalize to the same string.

**Why this matters for us directly**: our extras are `anthropic`, `openai`, `gemini`, `cohere`, `all`, `dev` (Section B8). These are already simple lowercase single-word names, so normalization is a non-issue in practice — but the rule means we must **not** later add a second, differently-punctuated extra that collides after normalization (e.g. defining both `google-genai` and `google_genai` as separate extras would be non-conformant / ambiguous), and it means users can invoke extras case/punctuation-insensitively (`pip install salesforce-mcp[Anthropic]` and `pip install salesforce-mcp[anthropic]` are equivalent under PEP 685).

### D7. What PEP 621 explicitly leaves to the build backend / `[tool.*]`
Verbatim: "This PEP does not attempt to standardize all possible metadata required by a build back-end, only the metadata covered by the core metadata specification." And: "specifying what files should end up in a source distribution or wheel file is out of scope for this PEP" — i.e. everything in Section B9 (data-file inclusion, `package-data`, `MANIFEST.in`, Hatchling's `[tool.hatch.build]`) is deliberately backend-specific and lives under `[tool.<backend-name>]`, not `[project]`.

For tool-specific settings generally: "For tools wishing to store their own settings in `pyproject.toml`, they may use the `[tool]` table as defined in PEP 518." This is where our lint/format/type-check config lives, e.g.:
```toml
[tool.ruff]
line-length = 100

[tool.mypy]
strict = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
```
None of this is standardized by PEP 621 — each tool (`ruff`, `mypy`, `pytest`, `hatch`) owns and documents its own `[tool.X]` schema independently.

### D8. Where PEP 621 has been amended/superseded — summary table

| Area | PEP 621 original | Current authority | Status |
|---|---|---|---|
| `license` | `license = {file=...}` / `{text=...}` table | **PEP 639**: `license = "<SPDX-expr>"` + `license-files = [...]` | Superseded — use PEP 639 form (already the recommendation in B1a) |
| `optional-dependencies` extra-name comparison | Unspecified how to compare/normalize names | **PEP 685**: PEP 503-style normalization mandatory | Amended/clarified — PEP 621 gap closed, no syntax change needed on our end |
| Everything else in Section D1 (`name`, `version`, `readme`, `requires-python`, `authors`, `keywords`, `classifiers`, `urls`, `scripts`/`gui-scripts`/`entry-points`, `dependencies`, `dynamic`) | — | Still current as originally specified in PEP 621, now maintained verbatim in the PyPA pyproject.toml specification page (https://packaging.python.org/en/latest/specifications/pyproject-toml/) | Unchanged |

---

## A. README specifics (PyPI rendering)

### A1. Markup formats PyPI accepts
Source: https://packaging.python.org/en/latest/guides/making-a-pypi-friendly-readme/

> "Formats supported by PyPI's README renderer are: plain text, reStructuredText (without Sphinx extensions), Markdown (GitHub Flavored Markdown by default, or CommonMark)."

- Plain text
- reStructuredText — **without Sphinx extensions**. Sphinx directives/roles such as `:py:func:`getattr`` or `:ref:`my-reference-label`` are **not allowed** and produce errors like `Error: Unknown interpreted text role "py:func"`.
- Markdown — GitHub Flavored Markdown (GFM) by default, or CommonMark.

We will use **Markdown (GFM)** — it's what most engineers expect and it's what renders the same on both GitHub and PyPI.

### A2. Declaring `Description-Content-Type` — verbatim `pyproject.toml`
Source: https://packaging.python.org/en/latest/guides/writing-pyproject-toml/ and https://packaging.python.org/en/latest/specifications/core-metadata/

Simple form (format auto-detected from file extension `.md`/`.rst`):
```toml
[project]
readme = "README.md"
```

Explicit form (use when you need to force the content type or the extension is ambiguous):
```toml
[project]
readme = {file = "README.md", content-type = "text/markdown"}
```

Core-metadata spec, verbatim allowed `Content-Type` values (https://packaging.python.org/en/latest/specifications/core-metadata/):
- `text/plain`
- `text/x-rst`
- `text/markdown`

Optional parameters:
- `charset` — "The only legal value is `UTF-8`."
- `variant` (markdown only) — `GFM` or `CommonMark`. **"If the `Description-Content-Type` is `text/markdown` and `variant` is not specified or is set to an unrecognized value, then the assumed `variant` is `GFM`."**

Full explicit declaration with variant, as it would appear in the built metadata (and can be set via the table form):
```toml
readme = {file = "README.md", content-type = "text/markdown"}
```
(Setuptools/Hatchling append `; charset=UTF-8` automatically; you don't write it yourself in `pyproject.toml`.)

### A3. What happens if content-type is wrong or missing
Source: https://packaging.python.org/en/latest/specifications/core-metadata/ and the PyPI-friendly-readme guide.

- **Missing entirely**: "applications should attempt to render it as `text/x-rst; charset=UTF-8` and fall back to `text/plain` if it is not valid rst." So a Markdown README with no content-type declared will render as **raw, unformatted text** on PyPI (or garbled RST parsing) — headings/bold/links show up as literal `#`/`**`/`[]()` characters.
- **Unrecognized value**: "the assumed content type is `text/plain`" — same failure mode, raw text dump.
- **Invalid markup for the declared type**: "any invalid markup will prevent it from rendering, causing PyPI to instead just show the README's raw source." I.e. PyPI does not "best-effort" render — it falls back to showing the raw, un-rendered file.

Because our project uses the `readme = "README.md"` short form via a modern build backend, the content-type is inferred correctly from the `.md` extension — but we should still explicitly set `readme.content-type` if we ever rename the file or extract a subset, to avoid silent fallback to raw text.

### A4. PyPI renderer restrictions (readme_renderer / Warehouse sanitization)
Source: https://github.com/pypa/readme_renderer/blob/main/readme_renderer/clean.py (the library Warehouse/PyPI uses to sanitize rendered README HTML)

PyPI does **not** render arbitrary HTML. `readme_renderer` runs the converted HTML through an allow-list sanitizer (`bleach`-based). Verbatim from the source:

```python
ALLOWED_TAGS = {
    "a", "abbr", "acronym", "b", "blockquote", "code", "em", "i", "li", "ol",
    "strong", "ul", "br", "caption", "cite", "col", "colgroup", "dd", "del",
    "details", "div", "dl", "dt", "h1", "h2", "h3", "h4", "h5", "h6", "hr",
    "img", "p", "pre", "span", "sub", "summary", "sup", "table", "tbody", "td",
    "th", "thead", "tr", "tt", "kbd", "var", "input", "section", "aside", "nav",
    "figure", "figcaption", "picture"
}
```
Allowed attributes are per-tag (`img`: `src, width, height, alt, align, class`; `a`: `href, title`; table cells: `align, colspan, rowspan`; inputs: `type, checked, disabled`) plus a wildcard `"*": {"id"}` on every tag.

Allowed URL schemes: `{"http", "https", "mailto"}` — no `javascript:`, `data:`, `file:`, etc.

Consequences for us:
- **No `<script>`, `<style>`, `<iframe>`** tags — they are stripped entirely (confirmed by GitHub Discussions and readme_renderer's allow-list, which excludes them).
- Every `<a href="...">` link is force-rewritten with `rel="nofollow"`.
- Raw HTML embeds for things like YouTube videos, collapsible custom widgets with JS, or `<style>`-scoped theming **will not survive** — use plain Markdown/allowed-HTML equivalents (`<details><summary>` is explicitly allowed, so PyPI-safe collapsible sections are fine).
- Anchor-based heading links (`#some-heading` auto-ids that GitHub generates) are **not guaranteed** on PyPI — Warehouse does not run the same heading-slug/TOC-anchor generator GitHub does, so in-page "jump to section" links written for GitHub may 404/no-op on PyPI. Don't rely on internal anchor navigation for a PyPI-critical README.
- `<div>`, `<span>`, `<section>`, `<aside>`, `<nav>` are technically allowed tags but carry no CSS (styles are stripped) — using them for layout tricks (badges-in-a-flex-row, colored boxes) will not look like it does on GitHub.

### A5. Images — the relative-path rule
Sources: https://github.com/pypa/readme_renderer/issues/163, https://glasnt.com/blog/new-images/, https://github.com/GillesPy2/GillesPy2/issues/213 (corroborating independent sources; packaging.python.org's own guide does not cover this, so external sources are cited)

**Exact rule:** PyPI renders the README as a standalone document with no knowledge of your repository's file tree. A relative image path (`![diagram](docs/img/arch.png)` or `![diagram](./assets/logo.png)`) resolves against `https://pypi.org/project/<name>/`, which does not host your repo files — the image **404s and shows a broken-image icon**. GitHub resolves the same relative path against your repo tree and shows it fine, which is why this bug is invisible until you check PyPI specifically.

**Fix:** use **fully-qualified absolute URLs** to a permanently-hosted copy of the image, e.g.:
```
https://raw.githubusercontent.com/<user>/<repo>/<branch-or-tag>/docs/img/arch.png
```
Preferably pin to a tag/commit SHA rather than a branch, so images don't silently change/break after future commits. This is the standard workaround; there is no PyPI-native asset upload for README images.

### A6. Badges, tables, code blocks, emoji, footnotes, admonitions
Derived from A4's allow-list plus general Markdown/RST support in `readme_renderer`:

| Element | Survives on PyPI? | Notes |
|---|---|---|
| Badges (shields.io etc.) | Yes | They're just `<img>` inside a link — both `img` and `a` are allowed tags, and shields.io URLs are absolute `https://` already, so no relative-path problem. |
| Tables (GFM `\|`-tables) | Yes | `table, thead, tbody, tr, th, td, caption, col, colgroup` are all allow-listed. |
| Fenced code blocks | Yes | `pre`, `code` allowed. Syntax highlighting (language-specific coloring) is **not guaranteed** — Warehouse's Pygmentize support for fenced-code language hints is inconsistent/limited compared to GitHub; treat PyPI code blocks as plain monospace. |
| Emoji (unicode / GH `:shortcode:`) | Unicode emoji: yes (plain text). GitHub `:shortcode:` syntax: **no** — that's a GitHub-only Markdown extension, not part of GFM/CommonMark as PyPI parses it; shortcodes will render literally as `:tada:`. | Use literal unicode emoji characters if you want them to show, not colon-codes. |
| Footnotes (`[^1]`) | Not part of core GFM/CommonMark — unreliable on PyPI. Avoid. |
| Admonitions (`> [!NOTE]` GitHub alert syntax) | **No** — GitHub's `> [!NOTE]`/`[!WARNING]` alert blocks are a GitHub-only extension. On PyPI they render as an ordinary blockquote with the literal `[!NOTE]` text showing. Avoid, or accept the degraded rendering. |
| `<details><summary>` collapsible sections | Yes | Both tags are in `ALLOWED_TAGS`. |
| Mermaid / other `<script>`-rendered diagrams | No | Requires JS, which is stripped. Use a pre-rendered image (hosted absolute URL, per A5) instead. |

### A7. Validating the README before publishing
Source: https://packaging.python.org/en/latest/guides/making-a-pypi-friendly-readme/

Exact procedure:
```bash
python3 -m pip install --upgrade twine   # twine >= 1.12.0 required
python3 -m build                          # produces dist/*.whl and dist/*.tar.gz
twine check dist/*
```
> "This command will report any problems rendering your README. If your markup renders fine, the command will output `Checking distribution FILENAME: Passed`."

`twine check` validates that the metadata is well-formed and the declared content-type is parseable — it does **not** catch broken relative image links or GitHub-only Markdown extensions (admonitions, shortcodes, anchors) silently degrading, since those still "render" without erroring. For those, the only reliable check is uploading to **TestPyPI** first (`twine upload --repository testpypi dist/*`) and visually inspecting the rendered project page before doing a real PyPI release.

### A8. Length / size considerations
Not explicitly quantified in the packaging.python.org guide. Practical constraint we should still respect: PyPI's overall metadata/upload size limits apply to the whole distribution, and an extremely long `long_description` bloats every `pip download`/index metadata fetch. There's no official hard cap called out in the primary source, but the community norm (see Section C below) is to keep the **PyPI-facing** README short and link out to full docs for anything long-form (design decisions, ADRs) rather than testing an unstated limit.

---

## B. Packaging

### B1. Complete annotated `pyproject.toml` template
Synthesized from: https://packaging.python.org/en/latest/guides/writing-pyproject-toml/, https://packaging.python.org/en/latest/tutorials/packaging-projects/, https://packaging.python.org/en/latest/specifications/entry-points/, https://packaging.python.org/en/latest/specifications/core-metadata/

```toml
[build-system]
# hatchling: modern, PEP 621-native, simple config, good src-layout defaults.
# See B2 for the setuptools-vs-hatchling trade-off.
requires = ["hatchling >= 1.26"]
build-backend = "hatchling.build"

[project]
name = "salesforce-mcp"                       # PyPI distribution name (pip install salesforce-mcp)
version = "0.1.0"                              # or `dynamic = ["version"]` — see B7
description = "Model Context Protocol server for Salesforce with a provider-agnostic LLM client"
readme = "README.md"                           # content-type auto-detected as text/markdown
requires-python = ">=3.10"                     # pick the floor your async/MCP SDK needs
license = "Apache-2.0"                         # SPDX expression (PEP 639) — see B1a
license-files = ["LICENSE"]
authors = [
  { name = "Your Name", email = "you@example.com" },
]
keywords = ["mcp", "model-context-protocol", "salesforce", "llm", "anthropic", "openai", "ai-agent"]
classifiers = [                                # see B5 for the full recommended list
  "Development Status :: 4 - Beta",
  "Intended Audience :: Developers",
  "License :: OSI Approved :: Apache Software License",
  "Programming Language :: Python :: 3",
  "Programming Language :: Python :: 3.10",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "Topic :: Software Development :: Libraries :: Python Modules",
  "Topic :: Office/Business :: Financial",
]

dependencies = [
  # core, always-installed deps only — the MCP SDK + Salesforce client + HTTP stack.
  # NOT any specific LLM provider SDK — see B8.
  "mcp>=1.0",
  "simple-salesforce>=1.12",
  "httpx>=0.27",
  "pydantic>=2.0",
]

[project.optional-dependencies]
# Provider extras — install only what you use. See B8.
anthropic = ["anthropic>=0.40"]
openai    = ["openai>=1.50"]
all       = ["salesforce-mcp[anthropic,openai]"]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.24",
  "ruff>=0.7",
  "mypy>=1.11",
  "build>=1.2",
  "twine>=5.0",
]

[project.urls]
Homepage      = "https://github.com/<org>/salesforce-mcp"
Documentation = "https://github.com/<org>/salesforce-mcp#readme"
Repository    = "https://github.com/<org>/salesforce-mcp.git"
Issues        = "https://github.com/<org>/salesforce-mcp/issues"
Changelog     = "https://github.com/<org>/salesforce-mcp/blob/main/CHANGELOG.md"

[project.scripts]
# console_scripts entry point — an MCP host launches this over stdio.
salesforce-mcp = "salesforce_mcp.server:main"

[tool.hatch.build.targets.wheel]
packages = ["src/salesforce_mcp"]
```

Notes on fields (why each matters for us):
- `name` — must be a valid PyPI identifier (ASCII letters/digits/`_`/`-`/`.`, no leading/trailing separators); this is what `pip install X` uses, independent of the importable package name.
- `readme` — see Section A in full.
- `requires-python` — pin a realistic floor; MCP Python SDK and modern async features typically want 3.10+.
- `license` / `license-files` — PEP 639 SPDX-expression form, supported by Hatchling ≥1.27, setuptools ≥77.0.3, flit-core ≥3.12, etc. (Source: writing-pyproject-toml guide.) Prefer this over the legacy `license = {text = "..."}` table form, which is being phased toward deprecation.
- `dependencies` vs `optional-dependencies` — see B8.
- `[project.scripts]` — the console-script mechanism; see B6.

#### B1a — license field caveat
The **old** table form still exists and works with older backends:
```toml
license = {text = "Apache-2.0"}
```
but the **current recommended** form is the bare SPDX string (`license = "Apache-2.0"`), which requires a modern-enough build backend (see version floors above). Since we're free to pin backend versions in a new project, use the SPDX string form.

### B2. Build backend recommendation + trade-off
Source: https://packaging.python.org/en/latest/tutorials/packaging-projects/, https://packaging.python.org/en/latest/guides/writing-pyproject-toml/

Options and what the docs say:
- **setuptools** (`requires = ["setuptools >= 77.0.3"]`, `build-backend = "setuptools.build_meta"`) — the historical default, most battle-tested, most third-party plugin ecosystem (`setuptools-scm` for VCS-based versioning, complex `package_data`/`MANIFEST.in` machinery). Heavier config surface, legacy quirks (`setup.py`/`setup.cfg` era baggage still visible in docs).
- **Hatchling** (`requires = ["hatchling >= 1.26"]`, `build-backend = "hatchling.build"`) — modern, PEP 621-native `[project]` table, minimal config for the common case, first-class `hatch-vcs` for dynamic versioning, good defaults for src-layout. Smaller/newer ecosystem than setuptools but is what the official tutorial itself defaults to: *"this tutorial uses Hatchling by default, but it will work identically with setuptools, Flit, PDM, and others that support the `[project]` table."*
- **Flit** (`flit_core`) — deliberately minimal, best for pure-Python packages with no build steps/extension modules; less flexible if we ever need custom build hooks.
- **PDM-backend** / **poetry-core** — fine but tie you toward that tool's own dependency-management workflow (PDM/Poetry) rather than plain pip/venv.

**Recommendation: Hatchling.** Trade-off accepted: we give up setuptools' deepest legacy-compat and largest plugin ecosystem in exchange for a much smaller, PEP 621-native `pyproject.toml` with fewer footguns and no `setup.py`/`setup.cfg` needed — a good fit since this project has no compiled extensions and a straightforward src-layout.

### B3. src-layout vs flat-layout — recommendation + trade-off
Source: https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/

- **Flat layout**: `awesome_package/` sits next to `pyproject.toml` at repo root. No install step needed to run code locally (`python -m awesome_package` works from the repo root without installing).
- **src layout**: importable code lives under `src/awesome_package/`. **"The src layout requires installation of the project to be able to run its code, and the flat layout does not."**

Key trade-off, verbatim: **"if an import package exists in the current working directory with the same name as an installed import package, the variant from the current working directory will be used"** — flat layout is exposed to this accidental-shadowing bug (you think you're testing the installed package, you're actually running stale local files); src layout structurally prevents it because the package isn't importable unless actually installed (typically via `pip install -e .`). Also: **"The src layout helps enforce that an editable installation is only able to import files that were meant to be importable"** — with flat layout, `setup.py`, `noxfile.py`, `README.md` etc. can end up shadowed onto `sys.path` accidentally.

**Recommendation: src-layout** (`src/salesforce_mcp/...`). Trade-off accepted: we require `pip install -e .` for local dev (one extra step, standard in any modern CI/tooling anyway) in exchange for eliminating an entire class of "works on my machine because of CWD pollution" bugs — valuable for a package that will be `pip install`-ed by third parties and launched by an MCP host as a subprocess (where CWD is not guaranteed to be the repo root at all).

### B4. Console-script entry point for an MCP server over stdio
Sources: https://packaging.python.org/en/latest/guides/writing-pyproject-toml/, https://packaging.python.org/en/latest/specifications/entry-points/

Declaration:
```toml
[project.scripts]
salesforce-mcp = "salesforce_mcp.server:main"
```

Mechanics (verbatim from the entry-points spec): the `object_ref` (`salesforce_mcp.server:main`) is resolved as
```python
import importlib
modname, qualname_separator, qualname = object_ref.partition(':')
obj = importlib.import_module(modname)
if qualname_separator:
    for attr in qualname.split('.'):
        obj = getattr(obj, attr)
```
and the generated console-script wrapper is functionally:
```python
import sys
from salesforce_mcp.server import main
sys.exit(main())
```
> "The object reference points to a function which will be called with no arguments when this command is run. The function may return an integer to be used as a process exit code, and returning `None` is equivalent to returning `0`."

For us: `main()` in `src/salesforce_mcp/server.py` must take no arguments, set up the MCP stdio transport (reading stdin/writing stdout per the MCP protocol), block on the server loop, and return an int (or `None`) exit code when the host closes the pipe. Once installed (`pip install salesforce-mcp`), any MCP host config can invoke it simply as the command `salesforce-mcp` — no `python -m ...` path-guessing required, which is exactly what MCP host configs (e.g. Claude Desktop's `command`/`args`) expect.

### B5. Trove classifiers to use
Source: general PyPI classifier taxonomy (referenced by writing-pyproject-toml guide; full list lives at https://pypi.org/classifiers/, linked from that guide)
```toml
classifiers = [
  "Development Status :: 4 - Beta",
  "Intended Audience :: Developers",
  "License :: OSI Approved :: Apache Software License",
  "Operating System :: OS Independent",
  "Programming Language :: Python :: 3",
  "Programming Language :: Python :: 3.10",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "Topic :: Software Development :: Libraries :: Python Modules",
  "Topic :: Office/Business :: Financial",
  "Typing :: Typed",
]
```
(`Typing :: Typed` if we ship a `py.typed` marker; `License ::` classifier is optional/redundant once using the SPDX `license` field on newer PyPI, but harmless to include for back-compat with tooling that still reads classifiers.)

### B6. Dependency pinning strategy — library vs application
Not explicitly detailed with exact wording in the fetched pages, but is the standard, universally-documented PyPA guidance implicit in the `dependencies` examples shown (loose specifiers like `httpx`, `gidgethub[httpx]>4.0.0`, `django>2.1`):

- **We are a library** (an installable package that other people's environments will pip-install, including as a dependency of an MCP host setup) — **not** a pinned application/deployment.
- **Library strategy (what we should do)**: use **loose, compatible lower/upper bounds** (`httpx>=0.27`, `mcp>=1.0`) in `[project.dependencies]`, not exact pins (`httpx==0.27.0`). Exact pins in a library force every downstream consumer's resolver into conflicts the moment two libraries pin different exact versions of the same transitive dependency ("dependency hell"). Leave exact-pin lockfiles to the **application** side.
- **Application strategy (not us, but noted for completeness)**: an application (e.g. a deployed service) should pin exact versions via a lockfile (`pip freeze`, `uv.lock`, `poetry.lock`, `pip-tools` `requirements.txt`) for reproducible deploys — that discipline belongs in a separate lockfile, not in the library's own `pyproject.toml` dependency specifiers.

### B7. Versioning / single-sourcing
Source: https://packaging.python.org/en/latest/discussions/single-source-version/

Three sanctioned strategies:
1. **Extract from VCS** — e.g. `hatch-vcs`/`setuptools-scm` derive the version from git tags (`v1.2.3`) at build time. Declared via `dynamic = ["version"]` in `[project]` plus backend-specific config (e.g. `[tool.hatch.version] source = "vcs"` for Hatchling).
2. **Hard-code in `pyproject.toml`** — `version = "0.1.0"`; the build backend copies it into the installed metadata; simplest, manual bump per release.
3. **Hard-code in source** — a `__version__` attribute in `__init__.py` (or a dedicated `_version.py`) that the build backend reads to populate the built metadata.

Runtime-consistency guidance (verbatim): projects should test that **`import_name.__version__` and `importlib.metadata.version("dist-name")` report the same value** — i.e. whichever strategy we pick, the installed package's runtime `__version__` attribute must match what `pip show`/PyPI metadata reports, so users/debuggers/MCP hosts can trust either source.

**Recommendation for us**: start with strategy 2 (hard-coded `version = "0.1.0"` in `pyproject.toml`) for simplicity pre-1.0; migrate to `hatch-vcs` (strategy 1) once we're cutting frequent tagged releases, so we stop hand-bumping the file on every release.

### B8. Optional-dependency groups for the multi-provider LLM client
Source: https://packaging.python.org/en/latest/guides/writing-pyproject-toml/

Mechanism (verbatim example from the guide):
```toml
[project.optional-dependencies]
gui = ["PyQt5"]
cli = [
  "rich",
  "click",
]
```
installed via `pip install package[gui]`.

Applied to us — the provider-agnostic LLM client must **not** force-install every provider SDK (Anthropic's, OpenAI's, etc.) just to install the MCP server:
```toml
[project.optional-dependencies]
anthropic = ["anthropic>=0.40"]
openai    = ["openai>=1.50"]
all       = ["salesforce-mcp[anthropic,openai]"]   # extras can reference the project's own other extras
dev       = ["pytest>=8.0", "ruff>=0.7", "mypy>=1.11", "build>=1.2", "twine>=5.0"]
```
Users then do `pip install salesforce-mcp[anthropic]` if they only want Claude support, `pip install salesforce-mcp[anthropic,openai]` for both, or plain `pip install salesforce-mcp` to get just the MCP/Salesforce core with no LLM SDK at all (e.g. if the LLM call is proxied elsewhere). The core `[project.dependencies]` list must stay free of any provider SDK for this to work.

### B9. Including non-Python data files (e.g. JSON schemas, prompt templates)
Sources: https://packaging.python.org/en/latest/guides/using-manifest-in/ (redirects to setuptools docs) and https://setuptools.pypa.io/en/latest/userguide/datafiles.html

Modern pyproject.toml-native approach (setuptools ≥61):
```toml
[tool.setuptools]
include-package-data = true      # default true as of setuptools 61+ when using pyproject.toml

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
salesforce_mcp = ["schemas/*.json", "prompts/*.md"]
```
`MANIFEST.in` is still consulted (e.g. `include src/salesforce_mcp/schemas/*.json`) for **source distribution** (`sdist`) inclusion when not using automatic VCS-based inclusion; `package-data`/`include-package-data` govern what actually ends up **inside the built wheel**. Since we chose Hatchling (B2) rather than setuptools, the equivalent Hatchling mechanism is `[tool.hatch.build.targets.wheel] packages = [...]` plus, if needed, `include`/`artifacts` keys in `[tool.hatch.build]` to force-include non-Python globs — same requirement (make sure data files ship inside the wheel, not just the sdist), different backend-specific config surface.

### B10. Publishing: build → check → TestPyPI → PyPI → Trusted Publishing
Source: https://packaging.python.org/en/latest/tutorials/packaging-projects/, https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/

```bash
python3 -m pip install --upgrade build twine
python3 -m build                                  # -> dist/*.whl, dist/*.tar.gz
twine check dist/*                                 # -> "Checking distribution FILENAME: Passed"
python3 -m twine upload --repository testpypi dist/*   # dry run, inspect rendered page
python3 -m twine upload dist/*                          # real PyPI (no --repository needed)
```

**Trusted Publishing** (recommended over long-lived API tokens): configure a "pending publisher" at `https://pypi.org/manage/account/publishing/` (and separately at `https://test.pypi.org/manage/account/publishing/` for TestPyPI) binding the PyPI project name to a specific GitHub repo owner/name/workflow filename. The GitHub Actions job then needs no stored secret — it authenticates via short-lived OIDC:
```yaml
publish-to-pypi:
  if: startsWith(github.ref, 'refs/tags/')
  needs: [build]
  runs-on: ubuntu-latest
  environment:
    name: pypi
    url: https://pypi.org/p/<package-name>
  permissions:
    id-token: write        # required to mint the OIDC token
  steps:
    - uses: actions/download-artifact@v6
      with:
        name: python-package-distributions
        path: dist/
    - uses: pypa/gh-action-pypi-publish@release/v1
```
Verbatim note: "These are obsolete now" regarding the older `PYPI_API_TOKEN`/`TEST_PYPI_API_TOKEN` secrets pattern — Trusted Publishing is the current recommended path and avoids storing any long-lived credential in CI at all.

---

## C. README structure for this project

### C1. Constraint driving the structure
PyPI renders Markdown but: (1) doesn't support GitHub-only extensions (admonitions, `:shortcode:` emoji, TOC-anchor links — Section A6), (2) breaks on relative images (Section A5), (3) has no explicit documented length cap but community norm avoids very long PyPI-facing descriptions (Section A8), and (4) the project owner's hard requirement is a **comprehensive** README that answers **every single design decision and its trade-off** (an ADR-style record per decision) — which is inherently long-form.

### C2. Recommendation: short PyPI-safe front section + full ADR log in the same README (single file), with heavy internal signposting — NOT a split into a separate docs site for v1
Trade-off stated explicitly:
- **Option A — one long README** (chosen): Simplest to maintain (one source of truth, no docs-site build step, no link rot between README and external docs), and satisfies "comprehensive README" literally as the owner phrased it. Cost: the file is long; GitHub-only niceties (admonitions, anchor TOC links) degrade on PyPI (Section A6), so the in-README table of contents must use plain-Markdown reference links resolved manually rather than relying on auto-generated anchors, and it must be periodically checked with `twine check` + a TestPyPI dry run (Section A7) since a long file has more surface area for an accidental Sphinx-role or GitHub-only construct to sneak in and break rendering.
- **Option B — short PyPI blurb + full docs elsewhere** (e.g. a `docs/` folder rendered via Read the Docs/MkDocs, or a wiki): Keeps the PyPI project page fast to skim and immune to the GitHub-vs-PyPI rendering gap for the deep content (since that content isn't parsed by PyPI's renderer at all). Cost: a second thing to build/host/keep in sync (a docs site or wiki), and it does not literally satisfy "comprehensive README" — it satisfies "comprehensive documentation," which is a different artifact than what was asked for.

Given the owner's literal instruction ("in the readme we need to make comprehensive readme answering every single design decision"), **Option A** is the correct call for this project: one long, well-sectioned `README.md`, kept PyPI-safe (Section A) end-to-end, with the ADR log as a clearly delimited section near the bottom (after the practical "get started" content) so a first-time visitor isn't forced to scroll through design rationale before finding install instructions.

### C3. Proposed section-by-section outline
1. **Title + one-line description** (matches `[project].description`) + badges (PyPI version, Python versions, license, CI status — all via absolute shields.io URLs, Section A6)
2. **What this is** — 2-4 sentences: MCP server for Salesforce + a provider-agnostic LLM client, who it's for
3. **Features** — bullet list
4. **Installation** — `pip install salesforce-mcp[anthropic]` etc., with the extras table explained (Section B8)
5. **Quickstart** — minimal working config for an MCP host (e.g. Claude Desktop config snippet) + a minimal code example for the LLM client
6. **Configuration** — env vars / auth (Salesforce OAuth, API keys per provider), table format
7. **Architecture overview** — one diagram (as an absolute-URL hosted image, Section A5) + short prose; this is the on-ramp into the deep-dive section
8. **Design Decisions (ADR log)** — the comprehensive section the owner asked for; one entry per significant decision (transport choice, sync vs async Salesforce client, provider-abstraction interface shape, error-handling/retry policy, auth/credential storage, packaging choices themselves e.g. src-layout/Hatchling — this doc's own conclusions get cited here). Format below (C4).
9. **API / tool reference** — the MCP tools exposed, their schemas
10. **Development** — src-layout note, `pip install -e .[dev]`, running tests, `ruff`/`mypy`
11. **Publishing / release process** — build/check/TestPyPI/PyPI/Trusted Publishing steps (Section B10), for maintainers
12. **Contributing**
13. **License**
14. **Changelog link** (points to `CHANGELOG.md`, kept out of the README itself to avoid bloating it further)

### C4. Decision-record template (for Section 8, one block per decision)
```markdown
### ADR-00X: <short decision title>

**Context.** What problem/constraint forced a choice here. What was true about the
project at the time (e.g. "MCP hosts spawn the server as a subprocess with an
unpredictable CWD").

**Options considered.**
1. <Option 1> — one-line description
2. <Option 2> — one-line description
3. <Option 3, if any>

**Decision.** Which option was chosen, stated in one sentence.

**Trade-offs accepted.** What we deliberately gave up by not choosing the
alternative(s) — be concrete (e.g. "gives up setuptools' larger plugin ecosystem
in exchange for a smaller, PEP 621-native config").

**Consequences.** What this implies going forward — constraints it puts on future
code, migration cost if we ever reverse it, what a contributor must know before
touching the affected area.
```
Example instantiation (packaging choice, drawn from this research):
```markdown
### ADR-001: Build backend — Hatchling over setuptools

**Context.** The project has no compiled extensions, needs a clean PEP 621
`[project]` table, and will be maintained by a small team that doesn't want
`setup.py`/`setup.cfg`-era config surface.

**Options considered.**
1. setuptools — most mature, largest plugin ecosystem, legacy config baggage
2. Hatchling — modern, PEP 621-native, minimal config, official tutorial default
3. Flit — simplest, but less flexible for future build hooks

**Decision.** Hatchling.

**Trade-offs accepted.** Smaller plugin ecosystem and shorter track record than
setuptools; if we ever need a setuptools-only plugin (e.g. a niche C-extension
build step) we'd need to migrate backends.

**Consequences.** New contributors configure data files via
`[tool.hatch.build]`, not `MANIFEST.in`/`package_data`. Version bumps and
data-file inclusion rules are Hatchling-specific — see CONTRIBUTING.md.
```

---

## HARD RULES

- [ ] `pyproject.toml` MUST declare `readme = "README.md"` (or the explicit `{file=..., content-type="text/markdown"}` table) — never omit it, or PyPI falls back to `text/x-rst`/`text/plain` and shows raw, unrendered Markdown source. (Source: core-metadata spec)
- [ ] Never rely on Sphinx-style RST directives/roles anywhere the README might be interpreted as RST — they error out. We're using Markdown, so this mainly matters if content-type detection ever misfires. (Source: making-a-pypi-friendly-readme)
- [ ] Every image in the README MUST use an absolute URL (e.g. `raw.githubusercontent.com/...`), never a relative repo-local path — relative paths 404 on PyPI even though they work fine on GitHub. (Source: readme_renderer issue #163 / community corroboration)
- [ ] No `<script>`, `<style>`, `<iframe>`, or JS-dependent embeds (e.g. live Mermaid) in the README — they're stripped by PyPI's sanitizer allow-list. Use `<details><summary>` for collapsible content (allowed) and static hosted images for diagrams.
- [ ] Do not depend on GitHub-only Markdown extensions (`> [!NOTE]` admonitions, `:emoji_shortcode:`, auto-generated heading-anchor TOC links) for anything that must work correctly on PyPI — they degrade silently (no error, just wrong-looking output).
- [ ] Before every release: run `twine check dist/*` (must print "Passed") AND do a `--repository testpypi` dry-run upload and visually inspect the rendered page — `twine check` does not catch broken image links or degraded GitHub-extension rendering.
- [ ] `[project.dependencies]` MUST NOT include any specific LLM provider SDK (no unconditional `anthropic`/`openai` dependency) — those belong exclusively in `[project.optional-dependencies]` extras, so `pip install salesforce-mcp` alone stays provider-agnostic.
- [ ] Use loose/bounded version specifiers (`>=`) in library dependencies, not exact pins (`==`) — we are a library, not a pinned application; exact pins belong in a separate lockfile if/when we ship a deployable service around this.
- [ ] The `[project.scripts]` console-script target function must take no arguments and return an int/`None` exit code — required by the entry-points resolution contract so MCP hosts can invoke `salesforce-mcp` directly as a subprocess command.
- [ ] Use src-layout (`src/salesforce_mcp/...`) so the installed/importable package can never be accidentally shadowed by CWD-local files — important because an MCP host spawns this as a subprocess with an unpredictable working directory.
- [ ] Keep `name` (PyPI distribution name) valid per PyPI's identifier rules (ASCII letters/digits/`_`/`-`/`.`, no leading/trailing separator) — decide it once and keep it stable; renaming a published PyPI project is disruptive.
- [ ] Prefer Trusted Publishing (OIDC via GitHub Actions) over long-lived `PYPI_API_TOKEN` secrets for the release workflow — the tokens pattern is explicitly called obsolete in current PyPA guidance.
- [ ] Use the PEP 639 `license` form (`license = "<SPDX-expr>"` + `license-files = [...]`), never the legacy PEP 621 `license = {file=...}`/`{text=...}` table — the table form is superseded. (Source: PEP 621 D4, PEP 639)
- [ ] Never mark `name` as `dynamic`, and never give a field both a static value in `[project]` and a `dynamic` listing at the same time — both are spec violations a conformant backend must reject. (Source: PEP 621 D3)
- [ ] Console-script entry points MUST be declared via `[project.scripts]`, never as a hand-written `[project.entry-points.console_scripts]` table — the latter is an explicit spec violation. (Source: PEP 621 D5)
- [ ] Do not define two extras (in `[project.optional-dependencies]`) whose names collide after PEP 503-style normalization (case-insensitive, `.`/`-`/`_` treated as equivalent) — e.g. `google-genai` and `google_genai` cannot coexist as distinct extras. (Source: PEP 685, D6)
