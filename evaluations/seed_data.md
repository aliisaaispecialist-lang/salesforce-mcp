# Seed dataset for evaluations/questions.xml

This is the fixed dataset the ten questions in `questions.xml` are written
against. Every answer in that file was derived from these exact values, not
from a live org — see the caveat in `README.md`. Anyone who wants to actually
run the evaluation must load this data into a Salesforce org first, using the
setup notes at the bottom.

All names, emails, phone numbers, and titles below are invented for this
document. `example.com` is used throughout because it is reserved by IANA for
documentation and cannot resolve to a real address.

## Org state assumption

The questions assume the org contains **only** the records below and nothing
else reachable by `salesforce_search_contact`. Use a fresh scratch org or a
Developer Edition org with any pre-loaded sample Contacts (Salesforce ships a
few by default, e.g. "Rose Gonzalez") deleted first. If other Contact records
are present, searches that expect an exact count (question 3) or a single
match (questions 1, 2, 4, 5, 6) may return extra results and the documented
answers will no longer hold.

## Contacts

Seven Contact records, created with `salesforce_create_contact` or by any
other means (Setup UI, Data Loader, anonymous Apex) before the evaluation
runs. Fields not listed (account, address, etc.) are left blank.

| First name | Last name | Email | Phone | Title |
|---|---|---|---|---|
| Alex | Novak | alex.novak@example.com | +973 1700 3001 | Warehouse Manager |
| Alex | Petrossian | alex.petrossian@example.com | +973 1700 3002 | Regional Sales Manager |
| Alex | Dumont | alex.dumont@example.com | +973 1700 3003 | Marketing Coordinator |
| Priya | Narayanan | priya.narayanan@example.com | +973 1700 2001 | VP Operations |
| Grace | Okafor | grace.okafor@example.com | +973 1700 2003 | Finance Director |
| Tomas | Varga | tomas.varga@example.com | +973 1700 2002 | Procurement Lead |
| Hassan | Al-Fardan | hassan.alfardan@example.com | +973 1700 2005 | IT Director |

Three contacts share the first name "Alex" and no other last name in the set
starts with or contains "Alex", "Priya", "Grace", "Tomas", or "Hassan" — each
of those five names is otherwise unique in the dataset. This is deliberate:
`salesforce_search_contact` matches whole words in Name, Email, Phone, and
Account Name (per its own description), so a single-word query for one of
those five names returns exactly one contact, and a query for "Alex" returns
exactly three.

The following three people are named in the questions but are **not** in this
dataset and must not be created — the questions rely on them being absent:

- Amara Chen
- Youssef Haddad
- Noor Sabbagh

## Opportunity (for completeness, not used by the current ten questions)

The connector has no read or search action for opportunities, so nothing in
`questions.xml` can verify an opportunity's fields — there is no way for a
model equipped only with these five tools to look one up again after creating
it. It is documented here anyway, for whoever extends this dataset later or
adds an opportunity-read action:

| Field | Value |
|---|---|
| Name | Meridian Textiles - Annual Renewal |
| Stage | Negotiation/Review |
| Close date | 2026-11-30 |
| Amount | 48000 |
| Linked contact | Grace Okafor |
| Description | Multi-year renewal, pending finance sign-off. |

The stage value above is a plausible one, not a requirement. `stage_name` is
a plain string in the tool's schema, not an enum, precisely because every org
configures its own picklist — `salesforce_create_opportunity` reads the
org's actual values at call time rather than assuming a fixed list (see
`src/salesforce_connector/actions/create_opportunity.py`). Whatever stage
values this org's Opportunity.StageName picklist actually holds are the only
correct ones to send; do not assume the value above, or any other list, is
authoritative.

## Activity (for completeness, same caveat as above)

| Field | Value |
|---|---|
| Related to | Grace Okafor (Contact) |
| Subject | Renewal call - discussed pricing |
| Body | Discussed multi-year discount; Grace to confirm budget by Friday. |
| Kind | Call |
| Date | 2026-08-03 |

Like the opportunity, this Task cannot be read back through any of the five
tools once created — `salesforce_add_activity_note` is write-only — so no
question in `questions.xml` depends on it existing.

## Setup notes for running the evaluation live

1. Create a scratch org or a clean Developer Edition org and delete any
   sample Contact records.
2. Create the seven contacts above, either directly in Salesforce or by
   running `salesforce_create_contact` once against a known-working
   connector instance (each call needs its own `idempotency_key` and
   `approved: true`).
3. Do not create contacts for Amara Chen, Youssef Haddad, or Noor Sabbagh.
4. Point the connector at this org (`SF_LOGIN_URL`, `SF_USERNAME`, etc., per
   `.env.example`) and confirm `testConnection` succeeds before running
   `questions.xml` through `scripts/evaluation.py`.
5. The opportunity and activity rows above are optional for the current ten
   questions; create them only if extending the suite to cover the actions
   that read them back.
