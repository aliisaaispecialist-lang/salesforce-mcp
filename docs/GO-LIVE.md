# Going live: the ordered run

Everything in this repository was built and verified without a Salesforce org.
That is not a boast, it is a limitation, and this is the document that removes
it. Follow it top to bottom the first time an org exists.

Two values are missing and nothing else. Fill them in and every step below is
already written.

```
.env line 14:  SF_CLIENT_ID=      <- Consumer Key from the Connected App
.env line 18:  SF_USERNAME=       <- the Salesforce username, not necessarily an email you recognise
```

The private key is already in `.env`, converted and tested. The certificate is
in `secrets/` and valid until August 2027.

---

## 0. Before anything, know what you are pointing at

```bash
sf org display --target-org mcp-org
```

Read the **Username** and the **Instance Url**. The username is what goes in
`SF_USERNAME`, and getting it wrong is the single most common cause of an
`invalid_grant` that looks like a broken key.

A Developer Edition org logs in at `login.salesforce.com`, which this
connector's own guard refuses by design. It is not real production, so:

```
SF_LOGIN_URL=https://login.salesforce.com
SF_ALLOW_PRODUCTION=true   # a Developer Edition org, not a real one
```

Say it explicitly rather than weakening the guard. A sandbox needs neither
line — `https://test.salesforce.com` is already the default.

---

## 1. Prove the JWT flow independently

Before involving any of our code, ask the Salesforce CLI the same question:

```bash
sf org login jwt \
  --username <the username from step 0> \
  --client-id <the Consumer Key> \
  --jwt-key-file secrets/salesforce.key \
  --instance-url https://login.salesforce.com \
  --alias mcp-jwt
```

This is the identical OAuth 2.0 JWT Bearer flow the connector uses, from a
tool with no stake in the outcome. It separates two questions that otherwise
look the same: *is the org set up wrong* or *is the connector wrong*.

| It says | It means |
|---|---|
| `Successfully authorized` | The org side is correct. Anything that fails later is ours. |
| `user hasn't approved this consumer` | Permitted Users is not set to *Admin approved users are pre-authorized*, or the profile was not added |
| `invalid_grant` immediately after creating the app | The 2–10 minute propagation has not finished. Wait. |
| `invalid_grant` later | Username, Consumer Key, or the key/certificate pair do not match |
| `invalid_client_id` | The Consumer Key is wrong or the app was deleted |

**Do not proceed until this passes.** Everything after it assumes the org side
works.

---

## 2. The connector's own connection test

```bash
make check-connection
```

Reads the org's limits endpoint and writes nothing. It should report `ok=True`
with the instance URL and API version.

---

## 3. The live suites

```bash
make live
```

Runs `tests/integration/` and `tests/learning/` — 30 tests that are skipped in
every other run. Expect them to take a minute; each creates real records and
deletes them again.

### What to watch for

**`test_the_second_page_is_not_the_first_page_again`** is the one to read
first. It is the most likely failure here and the only one that would mean a
connector change rather than a setup problem. `search_contact` sends an
`offset` to `parameterizedSearch`; SOSL-backed search has not historically
honoured offset the way a SOQL query does. If page two repeats page one, the
cursor never advances and a caller walking it would loop forever — so the
pagination mechanism needs replacing, and
[ADR-003](../README.md#adr-003-parameterizedsearch-instead-of-soql-or-sosl)
needs revisiting.

**The learning tier's failures are information, not bugs.** Each test names an
assumption and where the code leans on it. A red one means something believed
about Salesforce is untrue; record what actually happened in
`docs/research/03-salesforce-api-map.md`, and write an ADR if it changes a
decision.

**`records left behind in the org`** means cleanup failed. The message lists
what survived, with ids. Delete them before rerunning, or the next run's
assertions about "the contact we just made" will find two.

---

## 4. Run the evaluation for real

The ten question/answer pairs in `evaluations/questions.xml` were worked out by
hand from `evaluations/seed_data.md`. They have never been run against an org.

1. Load the seed contacts (see the setup notes at the bottom of
   `seed_data.md`).
2. Run the harness from the mcp-builder skill — the command is in
   `evaluations/README.md`.
3. A mismatch is either a bad answer in that file **or** a real gap in a tool's
   schema or description. Fix whichever it actually is; the guide's own
   verification process says to prefer fixing the tool.

---

## 5. Record fixtures

```bash
python scripts/record_fixtures.py
```

Captures real Salesforce responses, scrubbed of ids and org-specific values,
into `fixtures/`. These let a future contributor with no org write tests
against shapes that genuinely came back from Salesforce rather than shapes
someone imagined.

Read what it writes before committing it. The scrubber is deliberately
aggressive, but it cannot know that a Contact called `Bianca` in your org is a
real person.

---

## 6. Update what the documents claim

Three things say "never run against a real org" and will be untrue afterwards:

- `README.md` — the Testing section, and the `learning`/`integration` tier
  notes that currently say no test carries those markers
- `evaluations/README.md` — the honest caveat at the top
- `CHANGELOG.md` — the Blocked section

Definition of Done item 9 — *"one real sandbox test where access permits"* —
is met the moment step 3 passes. Say so in the changelog rather than leaving a
reader to infer it.
