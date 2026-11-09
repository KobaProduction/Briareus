# Briareus Coolify MCP

Standalone coolify provider MCP in the infrastructure group. Its `/mcp` endpoint exposes only coolify tools. Provider accounts and credentials are resolved by the private Control Panel client; this service does not access its database directly.

`coolify_get_deployment_logs(account_id, uuid, offset=None, max_chars=20000)` reads
the journal from `GET /api/v1/deployments/{uuid}` using the selected account's
existing token. Coolify only returns logs with `read:sensitive` or `root` and the
required team access. Briareus does not grant or bypass those permissions.
Missing/null logs are reported as unavailable, separately from an empty journal.

The default response is the last 20,000 characters. Use `offset=0` and follow
`next_offset` to read from the beginning; each page allows up to 100,000 characters.
Offsets refer to the redacted text. Structured Coolify log entries retain timestamp,
stream and output, including hidden/debug output, without commands or configuration
snapshots. Configured API credentials and common secret patterns are masked on a
best-effort basis; logs may still contain operational data. Journal text is omitted
from Management invocation audit. Existing deployment metadata tools retain their
safe field projections.

Deploy this owner with `docker-compose.yaml` or generated `docker-compose.coolify.yaml` on the node network. No other provider service is required. Common MCP middleware, provider-account caching, configuration, telemetry and ASGI hosting are reused from shared packages.
