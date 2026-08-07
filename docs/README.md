# Where the decisions came from

The root `README.md` states what was decided and why. These are the notes it
was decided from: what the sources actually said, read before any code
existed, so a claim in an ADR can be traced back to the page it came from
rather than taken on trust.

They are kept rather than deleted because a decision you cannot trace is a
decision you cannot revisit. When Salesforce changes an endpoint or the MCP
specification moves again, the question is not "what did we do" — the code
answers that — but "what did we believe when we did it, and is it still
true".

| File | What it is |
|---|---|
| `PLAN.md` | The build plan as it stood before the first line of code |
| `OPEN-QUESTIONS.md` | Questions raised during the build, with their answers or their status |
| `research/01-mcp-and-multi-provider-client.md` | The MCP SDK and LangChain's client, read from their own docs |
| `research/02-clean-code-standard.md` | The line, function, and argument limits this repo holds itself to |
| `research/03-salesforce-api-map.md` | Roughly 90 REST endpoints catalogued, and why five was the right number |
| `research/04-tool-design-and-security.md` | Tool description design, prompt injection, untrusted record data |
| `research/05-packaging-and-readme.md` | PEP 621, PyPI-friendly READMEs |
| `research/06-doo-assignment.md` | The assignment itself, read from the site's own embedded data |
| `research/07-reference-repos.md` | Reference implementations worth reading |
| `research/08-doo-presentation.md` | The kickoff deck, slide by slide |
| `research/09-mcp-spec-compliance.md` | The MCP specification draft, clause by clause — the highest-priority source |

Nothing here ships in the Docker image: it copies only `src/`, `mcp/`, and
`connector.yaml`.
