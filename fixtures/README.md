# Recorded responses

Empty until an org exists. `python scripts/record_fixtures.py` fills it.

Every mocked response elsewhere in this repository was written from
documentation, which is the best anyone can do without an org and is not the
same as knowing. A field that is absent rather than null, an error body with
one more layer of nesting, a date that is not quite ISO — none of those appear
until Salesforce answers for itself.

These files are those answers, with everything specific to one org removed:
record ids replaced, instance hosts replaced, credential-shaped keys redacted.
A contributor with no org can then write tests against shapes that genuinely
came back, rather than shapes someone imagined.

## Before committing anything here

**Read every file.** The scrubber removes ids, hosts, and known secret keys. It
cannot know that a contact in your org is a real person, that a description
field quotes a customer, or that an account name is commercially sensitive.

`.gitignore` blocks `fixtures/raw/` for exactly this reason: put anything
unscrubbed there and it cannot be committed by accident.

## What gets recorded, and why each one

| File | Why it is worth having |
|---|---|
| `limits.json` | The endpoint `testConnection` reads, and the `Sforce-Limit-Info` header the quota metadata is parsed from |
| `describe_opportunity.json` | The stage picklist, which is read per org rather than hard-coded — see ADR-008 |
| `search_no_matches.json` | An empty search result, which must be a success rather than an error |
| `error_record_not_found.json` | The error body shape `errors/mapping.py` classifies against |
| `error_required_field_missing.json` | Whether Salesforce names the field that was wrong, which the tool descriptions promise it does |
