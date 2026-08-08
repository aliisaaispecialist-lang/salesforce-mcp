# Download it, set it up, use it

Written for someone who has never seen this repository.

There are two ways to run it — Python directly, or Docker. Both speak the same
protocol over the same transport. Docker is here for reproducibility: it is
still a local subprocess reading stdin and writing stdout, not a server you
deploy and point clients at.

---

## The whole thing, before the detail

Seven steps, one of them in four parts. Only one is slow, and it is not any of
the code.

| # | What you do | What you end up holding | How long |
|---|---|---|---|
| **1** | Unzip or clone the repository | The project folder | 1 min |
| **2** | `pip install .` (or `docker build`) | A working install | 3 min |
| **3a** | Generate a certificate and private key with `openssl` | `salesforce.key` (yours) + `salesforce.crt` (Salesforce's) | 2 min |
| **3b** | Create an **External Client App** in your org, uploading `salesforce.crt` | An app that trusts your key | 10 min |
| **3c** | Pre-authorise your user for that app | Permission to log in without a browser | 5 min |
| **3d** | Copy the **Consumer Key** from the app | `SF_CLIENT_ID` | 1 min |
| **4** | Put three values in `.env` | A configured connector | 3 min |
| **5** | Run the connection check | Proof it works, before any client | 1 min |
| **6** | Point Claude (or any MCP client) at it | Five Salesforce tools | 2 min |
| **7** | Ask it something in plain language | A working assistant | — |

### The three values everything comes down to

There is no single "API key" in Salesforce. You collect three things, and only
one of them is a secret:

| Value | Secret? | Comes from | Goes to |
|---|---|---|---|
| **Consumer Key** (`SF_CLIENT_ID`) | No — it only identifies the app | Step 3d | `.env` |
| **Username** (`SF_USERNAME`) | No | Your org's user record | `.env` |
| **Private key** (`SF_PRIVATE_KEY`) | **Yes** | Step 3a, `openssl`, on your machine | `.env`, and nowhere else |

The private key never leaves your machine and never travels to Salesforce.
Salesforce holds only the *certificate* — its public half — and uses it to
check a signature the connector makes. That is what "no password, no secret in
transit" means here, and it is why step 3a comes before everything else.

> **Nothing in this repository contains a credential, and nothing you download
> from anyone else should.** `.env`, `*.key`, `*.pem`, `*.crt` and `secrets/`
> are all gitignored and excluded from the Docker image, and `gitleaks` runs
> over the full history in CI. You bring your own org and your own key.

### What if you only want to review it?

Steps 1 and 2 are enough. `pytest` runs 443 tests with **no credentials, no
org, and no network** — they are mocked end to end. You can read
`openapi.yaml`, inspect the five tool schemas, and build the Docker image
without ever touching Salesforce. Credentials are needed only from step 5
onward, the moment you want to touch a real org.

**Time:** about ten minutes for steps 1–2, twenty to forty for step 3 the
first time you ever configure an External Client App. Step 3 is the only part
that genuinely takes time, and none of it is this connector's fault.

---

## 1. Get the code

**From the ZIP:** unzip it anywhere. The folder you get is the project root —
the one containing `connector.yaml` and `pyproject.toml`.

**From a clone:**

```bash
git clone <repository-url> salesforce-mcp
cd salesforce-mcp
```

Everything below runs from that folder.

---

## 2. Install

You need **Python 3.12 or newer**. Check with `python --version`.

```bash
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS, Linux, Git Bash
source .venv/bin/activate

pip install .
```

That is the whole install. If you plan to run the tests or change anything,
use `pip install -e ".[dev]"` instead.

**Or use Docker and skip the virtualenv:**

```bash
docker build -t salesforce-connector .
```

The image is named `salesforce-connector` because that is what the connector
is; the folder is named `salesforce-mcp`. Both are correct and they refer to
the same thing.

---

## 3. Set up Salesforce

This connector authenticates with the **OAuth 2.0 JWT Bearer flow**: it signs
an assertion with a private key and exchanges it for an access token. No
password is ever sent, and no secret travels over the wire. Salesforce began
retiring the username-password flow in 2026, which is why it is not offered
here.

You will produce three values: a **Consumer Key**, a **username**, and a
**private key**.

### 3a. Make a certificate and private key

On any machine with OpenSSL (Git Bash on Windows includes it):

```bash
mkdir -p secrets && cd secrets
openssl req -x509 -sha256 -nodes -days 365 -newkey rsa:2048 \
  -keyout salesforce.key -out salesforce.crt \
  -subj "/CN=salesforce-mcp"
```

**On Windows, prefix that with `MSYS_NO_PATHCONV=1`.** Git Bash rewrites any
argument beginning with `/` into a Windows path, so `/CN=salesforce-mcp`
arrives as `C:/Program Files/Git/CN=salesforce-mcp` and OpenSSL rejects it.
The error names the format and not the cause, which is why it is worth saying
here.

`salesforce.key` is the private key — the connector reads this. `salesforce.crt`
is the certificate — Salesforce reads this. **Never commit either.** `secrets/`,
`*.key`, and `*.crt` are all in `.gitignore` and `.dockerignore`.

Check they belong to each other before uploading anything — a mismatched pair
fails later as `invalid_grant`, which reads like a wrong username:

```bash
openssl x509 -in salesforce.crt -noout -pubkey | openssl md5
openssl pkey -in salesforce.key -pubout | openssl md5   # same hash = a pair
```

### 3b. Create an External Client App — not a Connected App

> **This changed under us, and it will catch you out.** Salesforce disabled
> connected app creation in all new orgs in Winter '26, and from Spring '26
> will not re-enable it without a support request. A new org answers
> *"You can't create a connected app. To enable connected app creation,
> contact Salesforce Customer Support."* — to the API as well as the UI. This
> guide originally said Connected App and was wrong for anyone starting today.
> **External Client Apps** are the replacement and support the same JWT bearer
> flow.

**Setup → App Manager → New External Client App**

- **External Client App Name:** anything, e.g. `Salesforce MCP`
- **Contact Email:** your own
- **Distribution State:** `Local`
- Under **API (Enable OAuth Settings)**, tick **Enable OAuth**
- **Callback URL:** `http://localhost/callback` — unused by this flow, but the
  form requires one
- **Enable JWT Bearer Flow**, then **Upload Files** and choose `salesforce.crt`
- **Scopes:** exactly two — **Manage user data via APIs (api)** and **Perform
  requests at any time (refresh_token, offline_access)**. Nothing more.
  `connector.yaml` declares only these two and a reviewer will compare.
- Save, then wait **2–10 minutes**. Salesforce says so and means it; trying
  immediately gives `invalid_grant`, which reads like a wrong key.

### 3c. Pre-authorise the user

**Setup → External Client App Manager → your app → Policies → Edit → OAuth
Policies**

- **Permitted Users:** `Admin approved users are pre-authorized`
- Save, then assign the app to a profile or permission set that includes the
  user the connector acts as.

This is what lets JWT Bearer work with no interactive login. Skip it and you
get `user hasn't approved this consumer`. Do it but assign nobody, and you get
`user is not admin approved to access this app` — two different messages for
the two halves of the same step.

### 3d. Collect the Consumer Key

**External Client App Manager → your app → Settings → OAuth → Consumer Key and
Secret.** Copy the **Consumer Key**. That is your `SF_CLIENT_ID`.

### 3e. Or do all of 3b–3d from the CLI

Every step above is scriptable, and this is how the org this connector was
verified against was actually built. It needs the Salesforce CLI
(`npm install -g @salesforce/cli`) and one browser login:

```bash
sf org login web --alias myorg --set-default
```

Then deploy an External Client App as metadata — three components, in
`externalClientApps/`, `extlClntAppGlobalOauthSets/`, and
`extlClntAppOauthSettings/`. Two things to know before you try:

- **Omit `consumerKey` from the deploy.** Salesforce generates it and rejects a
  deploy that carries one. Retrieve the component afterwards to read it back.
- **Deploy the OAuth policy separately, after retrieving the key.** The
  pre-authorisation policy is a fourth component
  (`ExtlClntAppOauthConfigurablePolicies`, `permittedUsersPolicyType` set to
  `AdminApprovedPreAuthorized`).

Assigning the user is not expressible in PermissionSet metadata. Create the
permission set, grant it the app, and assign it — three records:

```bash
sf data query --query "SELECT Id, DeveloperName FROM ExternalClientApplication"
sf data create record --sobject PermissionSet \
  --values "Name=Salesforce_MCP_Access Label='Salesforce MCP Access'"
sf data create record --sobject SetupEntityAccess \
  --values "ParentId=<permission set id> SetupEntityId=<app id>"
sf data create record --sobject PermissionSetAssignment \
  --values "AssigneeId=<user id> PermissionSetId=<permission set id>"
```

`SetupEntityAccess` is on the standard API, not the Tooling API — asking
Tooling for it returns *"The requested resource does not exist"*, which sounds
like the record is wrong when it is the endpoint.

---

## 4. Configure

```bash
cp .env.example .env
```

Fill in three values. Every other line already has a working default.

| Variable | What it is |
|---|---|
| `SF_CLIENT_ID` | The Consumer Key from step 3d |
| `SF_USERNAME` | The user the connector acts as — the one you pre-authorised |
| `SF_PRIVATE_KEY` | The contents of `salesforce.key`, header and footer lines included |

**The private key needs care.** A `.env` file is line-oriented: a PEM pasted
across thirty lines parses as one assignment and twenty-nine syntax errors.
Put it on **one line, in double quotes, with `\n` between the lines**:

```
SF_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nMIIEvQIBAD...\n-----END PRIVATE KEY-----"
```

The quotes are what make the escapes expand back into real newlines on the way
in; the connector repairs anything they miss. To convert the file without doing
it by hand:

```bash
python -c "print(repr(open('secrets/salesforce.key').read().strip()))"
```

`SF_LOGIN_URL` defaults to `https://test.salesforce.com`, the sandbox host.
Pointing it at production additionally requires `SF_ALLOW_PRODUCTION=true`, so
a typo cannot send writes somewhere real.

The connector reads `.env` from whatever directory it is started in, so the
next step works with nothing exported. An environment variable of the same
name wins over the file — that is what lets an MCP client hand the server its
credentials without a `.env` in some unrelated folder overriding them.

---

## 5. Check it works before wiring any client

```bash
PYTHONPATH=src python -c "
import asyncio
from salesforce_connector.auth.jwt_bearer import JwtBearerAuth
from salesforce_connector.client import SalesforceClient
from salesforce_connector.config import load_settings
from salesforce_connector.connector import SalesforceConnector, load_manifest

async def main():
    settings = load_settings()
    client = SalesforceClient.open(settings, JwtBearerAuth())
    connector = SalesforceConnector(client, load_manifest(settings))
    print(await connector.test_connection(settings))
    await client.aclose()

asyncio.run(main())
"
```

On Windows PowerShell, set the variable first: `$env:PYTHONPATH="src"`.

`test_connection` reads the org's limits endpoint and writes nothing, so it is
safe to run as often as you like. A success tells you the credentials, the
External Client App, and the pre-authorisation are all correct — which is the part
worth knowing before a client is involved.

If it fails, the error says which of the three it was.

---

## 6. Point a client at it

Copy `examples/mcp_client_config.json` into your MCP client's configuration
and replace every `/absolute/path/to/salesforce-mcp` with wherever you put the
folder. It contains both variants; keep the one you want.

**Claude Desktop** — `claude_desktop_config.json`:

- macOS: `~/Library/Application Support/Claude/`
- Windows: `%APPDATA%\Claude\`

**Claude Code** — one command, run from the project folder:

```bash
claude mcp add salesforce \
  -e SF_CLIENT_ID=<your consumer key> \
  -e SF_USERNAME=<your integration user> \
  -e SF_PRIVATE_KEY="<PEM, \n between lines>" \
  -e PYTHONPATH=src \
  -- python mcp/server.py
```

Check it with `claude mcp list`. The `-e` flags matter: Claude Code launches
the server with its own environment, not yours, so the credentials have to be
handed over here rather than left in `.env`.

Anything else that speaks MCP over stdio works the same way: it launches
`mcp/server.py` as a subprocess and talks JSON-RPC to it. Restart the client
after editing its config — most read it only at startup.

Once connected you should see five tools: `salesforce_search_contact`,
`salesforce_create_contact`, `salesforce_update_contact`,
`salesforce_create_opportunity`, `salesforce_add_activity_note`.

---

## 7. Using it

Ask in plain language. The tool descriptions carry a worked example each, so
a model rarely needs to be told the shape of a call.

> "Is there a contact called Ada Lovelace in Salesforce?"

> "Add Grace Hopper at Example Corp as a contact, her email is
> grace@example.com."

> "Log a call against Ada Lovelace: discussed pricing, wants a quote Friday."

Three things will happen that are deliberate, and are worth expecting:

**Writes ask first.** If your client supports elicitation, every create,
update, and note will put a confirmation to you before anything is written.
Decline it and nothing happens. If your client does not support elicitation,
the write is refused instead, and the refusal explains that `approved` must be
set — that is the fallback for hosts that confirm elsewhere.

**Retries do not duplicate.** Every write carries an idempotency key the model
generates. If a call times out and is retried with the same key, you get the
original record back rather than a second one.

**Record text is fenced.** Anything read out of Salesforce arrives marked as
data, because notes and descriptions are written by other people and are not
instructions.

### The five tools, and when each is the right one

| Tool | Does | Needs approval |
|---|---|---|
| `salesforce_search_contact` | Finds people by name, email, phone, or account | no |
| `salesforce_create_contact` | Adds a person | yes |
| `salesforce_update_contact` | Changes fields on an existing person | yes |
| `salesforce_create_opportunity` | Opens a deal, optionally linked to a contact | yes |
| `salesforce_add_activity_note` | Logs a call, email, meeting, or note against a contact or a deal | yes |

**Search before you create.** A duplicate person is the costliest mistake this
connector can make, and the tool descriptions push a model towards searching
first — but it is worth knowing yourself.

### One thing that differs per org

`create_opportunity` needs a **sales stage your org actually has**. There is no
universal list; every org configures its own. Send a wrong one and the error
returns the exact values your org accepts, so a model corrects itself in one
step rather than guessing:

```
'Prospecting' is not a sales stage in this Salesforce org.
Use one of these exact values: Qualify, Meet & Present, Propose,
Negotiate, Closed Won, Closed Lost.
```

Most Salesforce documentation uses `Prospecting` as its example. Plenty of orgs
do not have it. To see yours before you start:

```bash
sf data query --query "SELECT Id FROM Opportunity LIMIT 1"   # any query, to confirm access
sf org open --path lightning/setup/ObjectManager/Opportunity/FieldsAndRelationships/view
```

---

## Running it with Docker instead

Same three environment variables, passed through `--env-file`:

```bash
docker run -i --rm --env-file .env salesforce-connector
```

The `-i` matters — it keeps stdin open, which is how the client talks to it.
The container exits cleanly when the client closes the stream.

For a client config, use the `salesforce-docker` block in
`examples/mcp_client_config.json`. The image runs as a non-root user and
contains only `src/`, `mcp/`, and `connector.yaml` — no `.env`, no keys, no
git history.

---

## When something is wrong

| What you see | What it means |
|---|---|
| `user hasn't approved this consumer` | Step 3c's Permitted Users setting was skipped |
| `user is not admin approved to access this app` | Permitted Users is set, but nobody was assigned |
| `You can't create a connected app` | You are creating the wrong kind of app — see step 3b |
| `invalid_grant` right after setup | The app's 2–10 minute propagation has not elapsed |
| `invalid_grant` later | The username, the Consumer Key, or the key/certificate pair do not match |
| Refuses to start, mentions production | `SF_LOGIN_URL` points at `login.salesforce.com`; set `SF_ALLOW_PRODUCTION=true` only if you mean it |
| Client shows no tools | Wrong path in the config, or the client was not restarted |
| A write is refused as unapproved | Working as intended — see step 7 |

Logs go to **stderr** as JSON, never to stdout, because stdout carries the
protocol and nothing else. Secrets are masked before a line is written. To
read them while a client is running, check the client's own MCP server log.

---

## What this does not do

Five actions, not the whole Salesforce API — the reasoning is
[ADR-002](README.md#adr-002-five-actions-not-the-90-endpoint-salesforce-surface).
stdio only, no hosted HTTPS endpoint
([ADR-010](README.md#adr-010-stdio-and-docker-not-a-hosted-https-endpoint)).
Idempotency memory lives in the process and does not survive a restart. The
full list is under
[Known limitations](README.md#known-limitations-and-access-blockers), stated
rather than discovered.
