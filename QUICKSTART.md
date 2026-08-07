# Download it, set it up, use it

Written for someone who has never seen this repository. It assumes you have a
Salesforce sandbox or Developer Edition org and administrator rights on it,
because step 3 is the only part that genuinely takes time.

There are two ways to run it — Python directly, or Docker. Both speak the same
protocol over the same transport. Docker is here for reproducibility: it is
still a local subprocess reading stdin and writing stdout, not a server you
deploy and point clients at.

**Time:** about ten minutes for steps 1–2, twenty to forty for step 3 the
first time you ever configure a Connected App.

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
openssl req -x509 -sha256 -nodes -days 365 -newkey rsa:2048 \
  -keyout salesforce.key -out salesforce.crt \
  -subj "/CN=salesforce-mcp"
```

`salesforce.key` is the private key — the connector reads this. `salesforce.crt`
is the certificate — Salesforce reads this. **Never commit either.** Both
patterns are already in `.gitignore`.

### 3b. Create the Connected App

In your Salesforce org: **Setup → App Manager → New Connected App**
(on newer orgs this may appear as **External Client App**).

- **Connected App Name:** anything, e.g. `Salesforce MCP`
- **Contact Email:** your own
- Tick **Enable OAuth Settings**
- **Callback URL:** `http://localhost/callback` — unused by this flow, but the
  form requires one
- Tick **Use digital signatures** and upload `salesforce.crt`
- **Selected OAuth Scopes:** add exactly two — **Manage user data via APIs
  (api)** and **Perform requests at any time (refresh_token, offline_access)**.
  Nothing more. `connector.yaml` declares only these two, and a reviewer will
  compare.
- Save. Salesforce warns that changes take **2–10 minutes** to take effect.
  It means it.

### 3c. Pre-authorise the user

Still in Setup: **App Manager → your app → Manage → Edit Policies**

- **Permitted Users:** `Admin approved users are pre-authorized`
- Save, then **Manage Profiles** or **Manage Permission Sets** and add the
  profile of the user the connector will act as.

This step is what makes JWT Bearer work without any interactive login. Skip it
and you get `user hasn't approved this consumer`.

### 3d. Collect the Consumer Key

**App Manager → your app → View → Manage Consumer Details.** Copy the
**Consumer Key**. That is your `SF_CLIENT_ID`.

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

On the private key: keep the `-----BEGIN PRIVATE KEY-----` and
`-----END PRIVATE KEY-----` lines. If your `.env` format needs it on one line,
put `\n` between the lines — the connector repairs that on the way in.

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
Connected App, and the pre-authorisation are all correct — which is the part
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
| `user hasn't approved this consumer` | Step 3c was skipped, or the profile was not added |
| `invalid_grant` right after setup | The Connected App's 2–10 minute wait has not elapsed |
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
