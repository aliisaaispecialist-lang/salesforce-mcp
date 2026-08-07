# Evaluations

`questions.xml` is ten question/answer pairs for testing whether an LLM
equipped with this connector's five MCP tools can use them correctly. It
follows the format and question guidelines in the mcp-builder skill's
evaluation guide. `seed_data.md` is the fixed dataset the questions and
answers were derived from.

## The honest caveat

**These answers have not been run against a live Salesforce org.** There is
no org, no credentials, and no sandbox available in this environment. Every
answer in `questions.xml` was worked out by hand from `seed_data.md` plus the
connector's schemas and action code — the same reasoning an LLM using only
these tools would have to do — not by actually calling the tools against
Salesforce.

To verify this suite for real:

1. Follow the setup notes at the bottom of `seed_data.md` to load the seed
   contacts into a clean scratch org or Developer Edition org.
2. Configure the connector against that org (see `.env.example`) and confirm
   `testConnection` succeeds.
3. Run the harness from the mcp-builder skill:

   ```bash
   pip install -r <path-to-ai-company>/.claude/skills/mcp-builder/scripts/requirements.txt
   export ANTHROPIC_API_KEY=...
   python <path-to-ai-company>/.claude/skills/mcp-builder/scripts/evaluation.py \
     -t stdio -c python -a mcp/server.py \
     -e SF_CLIENT_ID=... -e SF_USERNAME=... -e SF_PRIVATE_KEY=... \
     -e SF_LOGIN_URL=https://test.salesforce.com \
     -o evaluations/report.md \
     evaluations/questions.xml
   ```

   (stdio mode launches `mcp/server.py` as a child process, so the `SF_*`
   variables from `.env.example` must reach it via `-e`, not just be exported
   in the parent shell, unless the harness also inherits the environment.)

4. Any mismatch is either a bad answer in this file (fix it) or a real gap in
   a tool's schema or description (fix that instead, per the evaluation
   guide's verification process).

## Why every question stays inside search_contact or tool schemas

The evaluation guide requires questions to need only non-destructive,
idempotent tool use, and to not depend on modifying state to reach the
answer. Of the five tools, only `salesforce_search_contact` is read-only and
approval-free. The four writes are all `requires_approval: true` in their
`ActionSpec`.

While reading `mcp_server.py` for this task, the approval path looked broken:
`_as_request` puts the full raw MCP `arguments` mapping (including `approved`
and `idempotency_key`) into `ActionRequest.params`, and `Action._validated`
then runs that same mapping through the tool's Pydantic input model, which is
declared `extra="forbid"` and has no `approved` field. A client that follows
the tool's own error text — "call again with approved set to true" — and adds
`approved: true` to the call arguments should get `connector.invalid_input`
for an unexpected field, not the write it asked for. Confirmed directly at
the validation layer, no credentials needed:

```
$ PYTHONPATH=src python -c "
from salesforce_connector.schemas.create_contact import CreateContactInput
CreateContactInput.model_validate({'last_name':'X','idempotency_key':'12345678','approved':True})"
ValidationError: 1 validation error for CreateContactInput
approved
  Extra inputs are not permitted [type=extra_forbidden, input_value=True, input_type=bool]
```

I did not change `src/`; this is flagged here and in the task report so it
can be fixed and re-verified, and it's the reason this evaluation makes no attempt to exercise
any of the four write tools, even in a way meant to fail safely (e.g.
deliberately sending an unknown `stage_name` to read back the org's picklist
from the error, which the code otherwise supports safely — see
`_reject_unknown_stage` in `create_opportunity.py`, which runs its check
before any record is created).

As a result, six of the ten questions are designed to need two or more
`salesforce_search_contact` calls: duplicate-avoidance checks against two
candidate names, a pagination walk, and cross-record comparisons that need
separate searches because the two people share no common search word. Only
one of the six (the pagination question) strictly cannot be answered in one
call, since nothing in the response reports a total match count without
following the cursor to the end. The other five instruct checking both
candidates, which is the honest way to test whether a model actually
verifies rather than assumes — but a model that searches the right name
first and trusts the question's premise that "exactly one exists" could stop
after one call and still land on the right answer. The remaining four
questions are answerable from the tool schemas alone (`tools/list`, zero
tool executions) and test specific things the connector's docstrings care
about: exact idempotency-key reuse on retry, that `stage_name` is a free
string rather than a hard-coded enum (because stage picklists are configured
per org), which tool is the only one without an idempotency concept at all,
and the record-id prefix a note must attach to.

## Why the complexity ceiling is lower than the guide's examples

The evaluation guide's own examples (GitHub, a project tracker) assume dozens
of tools and paging through large, varied datasets, with answers needing
"potentially dozens" of tool calls. This connector has five tools, one of
which is read-only, over a seed dataset small enough to load by hand into a
Developer org. Given that, no question here needs more than two or three
tool calls to answer honestly — asking for more would mean padding the
dataset artificially rather than testing the tools. The guide's diversity and
verifiability requirements (stable answers, single-string verification, mixed
answer types: emails, phone numbers, names, job titles, a count, a boolean, a
tool name, an id prefix, an idempotency key) are still met.

## Other things worth knowing before running this live

- `search_contact`'s output schema (`ContactSummary`) declares an
  `account_name` field, but the action (`actions/search_contact.py`) never
  requests `AccountName` in `_FIELDS` and never populates it in `_as_summary`
  — it will always come back `null`. None of the ten questions depend on it,
  but it means a question about account name could not currently be answered
  even on a live org.
- The pagination question (question 3) assumes Salesforce's
  `parameterizedSearch` endpoint honors the `offset` field the way
  `actions/search_contact.py` sends it. SOSL search results have not
  historically supported an offset parameter the way SOQL queries do; if the
  live API ignores `offset`, page two would repeat page one's three records
  instead of returning the rest, and a live run of that question would need
  investigation before trusting a failure as the tool's fault rather than the
  question's.
