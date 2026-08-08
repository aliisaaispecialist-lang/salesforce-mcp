# Examples

Five runnable scripts, one per action, plus a paste-and-connect block for an
MCP host. Each script builds a real `ActionRequest`, sends it through
`SalesforceConnector.execute()` - the same call an MCP tool invocation makes -
and prints the envelope: the payload on success, or `reason` and `next_step`
on failure. No script needs Salesforce reachable to be read or reviewed; they
need a configured `.env` only to actually run.

## Setup

From the repository root:

```bash
cp .env.example .env
# fill in SF_CLIENT_ID, SF_USERNAME, SF_PRIVATE_KEY (see .env.example)
PYTHONPATH=src python examples/search_contact.py
```

Every script is standalone: `PYTHONPATH=src python examples/<name>.py`. None
of them import each other.

If `.env` is missing or invalid, `load_settings()` raises
`ConfigurationError` before any network call happens - the same fail-fast
behaviour the MCP server itself has at startup. That is expected; it is not a
bug in the example.

## Scripts

| Script | Action | Kind | Needs approval + idempotency key |
| --- | --- | --- | --- |
| `search_contact.py` | `salesforce.search_contact` | read | no |
| `create_contact.py` | `salesforce.create_contact` | write | yes |
| `update_contact.py` | `salesforce.update_contact` | write | yes |
| `create_opportunity.py` | `salesforce.create_opportunity` | write | yes |
| `add_activity_note.py` | `salesforce.add_activity_note` | write | yes |

All record ids used in the write scripts (`003XX...`, `001XX...`) are
placeholders in Salesforce's own id shape - they do not point at real
records. `search_contact.py` is how a caller would find a real id before
running any of the writes.

Every write script generates one `idempotency_key` (a UUID) and sets
`approved=True` on the request. Both are required by design: `approved=True`
stands in for the confirmation an MCP host collects from a person before a
write tool runs, and the idempotency key is what lets a retried call after a
timeout return the original result instead of creating a second record. Omit
either and the action refuses the call and explains why in `next_step`.

## Connecting an MCP host

`mcp_client_config.json` has two entries - paste whichever one you use (or
both) into your host's `mcpServers` object, for example
`claude_desktop_config.json`:

- **`salesforce-docker`** - runs the connector from a built image:
  `docker build -t salesforce-connector .` once, then the host launches
  `docker run -i --rm --env-file .env salesforce-connector` per connection.
  The `-i` is required: this server speaks stdio, and without it the
  container's stdin is closed and the server never sees a request.
- **`salesforce-python`** - runs `mcp/server.py` directly with the interpreter
  already on `PATH`. Since there is no shell to load `.env` here, the
  variables from `.env.example` are passed through the config's `env` block
  instead.

`mcp_client_config.json` carries the same server under three key names, because
that is the only thing clients disagree about: most read `mcpServers`, VS Code
reads `servers`, and Zed reads `context_servers`. The command, the arguments,
and the environment are identical in all three. Keep the block your client
wants and delete the rest.

Replace every `/absolute/path/to/salesforce-mcp` placeholder with the
real path on your machine before pasting.
