# Evaluations

`questions.xml` is ten question/answer pairs for testing whether an LLM
equipped with this connector's five MCP tools can use them correctly. It
follows the format and question guidelines in the mcp-builder skill's
evaluation guide. `seed_data.md` is the fixed dataset the questions and
answers were derived from.

## The honest caveat

**These answers have still not been run against a live Salesforce org.** An
org now exists, and the connector is verified against it, 30 live tests pass
but that verifies the *tools*, not these answers. Every answer in
`questions.xml` was worked out by hand from `seed_data.md` plus the
connector's schemas and action code: the same reasoning an LLM using only
these tools would have to do, not by actually calling the tools against
Salesforce. Running them needs the seed contacts loaded first, which is the
remaining step.

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

**Now fixed.** What follows is the finding as it stood while these questions
were written, kept because it is why no question exercises a write, and because
how it survived is worth recording. `approved` is now declared on all four
write schemas, and `tests/unit/test_approval_path.py` walks the client's real
path, raw tool arguments through to model validation, for every write in both
states. Fixed in commit `2dcc0d4`.

While reading `mcp_server.py` for this task, the approval path looked broken:
`_as_request` puts the full raw MCP `arguments` mapping (including `approved`
and `idempotency_key`) into `ActionRequest.params`, and `Action._validated`
then runs that same mapping through the tool's Pydantic input model, which is
declared `extra="forbid"` and has no `approved` field. A client that follows
the tool's own error text, "call again with approved set to true", and adds
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

That was reported rather than fixed here, and has since been fixed in `src/`.
It remains the reason this evaluation makes no attempt to exercise
any of the four write tools, even in a way meant to fail safely (e.g.
deliberately sending an unknown `stage_name` to read back the org's picklist
from the error, which the code otherwise supports safely, see
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
verifies rather than assumes, but a model that searches the right name
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
tool calls to answer honestly, asking for more would mean padding the
dataset artificially rather than testing the tools. The guide's diversity and
verifiability requirements (stable answers, single-string verification, mixed
answer types: emails, phone numbers, names, job titles, a count, a boolean, a
tool name, an id prefix, an idempotency key) are still met.

## Other things worth knowing before running this live

- **Resolved.** This section used to record that `ContactSummary` declared an
  `account_name` the action never populated. The field is gone: the schema now
  declares `account_id`, which `_FIELDS` requests and `_as_summary` fills, so
  every field the schema promises is delivered. The reasoning is
  ADR-023 in the root README. None of the ten questions asked for an account
  name, so nothing here changes, but a question about one still cannot be
  answered, because the connector returns the id and offers no action that
  resolves it to a name.
- **Answered.** The pagination question (question 3) assumed
  `parameterizedSearch` honours the `offset` that `actions/search_contact.py`
  sends, which SOSL-backed search has not historically done. It does:
  `tests/integration/test_live_read.py::test_the_second_page_is_not_the_first_page_again`
  creates five contacts, reads three at a time, and confirms no id repeats
  across pages. The question stands as written.
- **`stage_name` values differ per org, and question 3's premise depends on
  it.** The org this was verified against offers `Qualify, Meet & Present,
  Propose, Negotiate, Closed Won, Closed Lost`, not `Prospecting`, which most
  Salesforce documentation uses as its example. Any question quoting a
  specific stage must be checked against the org it will run on. This is
  ADR-008's whole point and it caught a hard-coded value in the live tests
  themselves.
