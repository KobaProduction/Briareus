# V1 runtime architecture

## Service ownership

Briareus V1 is a collection of independently deployed applications on one node network, not a monolithic MCP Bridge. Its deployment catalog (`deploy/services.json`) currently declares **15 resources: 4 core services and 11 optional MCP Hands**. The list is a source catalog, **not** a statement that all Hands run on every node.

Core services:

- **Control Panel UI** — static browser SPA under `/admin/*`, with provider-issued OIDC state.
- **Control Panel API** — `/api/*`, accounts, encrypted provider credentials, invocation audit, workspace administration, persistence and discovery.
- **Gateway** — public HTTPS edge, MCP resource metadata, bearer authorization and routing.
- **Dependencies** — private PostgreSQL, Valkey and persistent Chromium containers.

Hands implement MCP capabilities (source control, files/jobs, browser, analysis, telemetry and infrastructure). Their per-resource details are in [Hands](../hands/README.md); public URLs are defined by [the service catalog](../../shared/services/catalog/), and the panel exposes actual connected endpoints.

## Trust and routing

Clients authenticate with the **external OIDC provider**. Gateway and API validate access-token issuer, audience, lifetime, node role and signatures locally by default; explicitly configured token introspection is an alternative. Gateway publishes the resource metadata and routes independently to available Hands. There is no local user/password authority, local OAuth issuer, standalone Management service, root aggregate `/mcp`, separate Files MCP, Terminal MCP, Curl MCP, or Chrome DevTools MCP.

The shared Valkey holds discovery leases and bounded caches, **not user authorization authority**. Each Hand resolves selected provider credentials through Control Panel API rather than opening its database. A Hand being registered, connected, enabled and callable are distinct states. Missing optional Hands must not prevent healthy providers from serving callers.

## Persistence and failure isolation

Control Panel API owns application data and Alembic schema updates. Production defaults to PostgreSQL; **SQLite is an explicit lightweight local/test backend**, never an implicit production fallback or migration mechanism. See [API database tests](../../services/control-panel/api/tests/README.md). Server and authorized consumers share the configured persistent workspace; Chromium's browser profile and transfer storage are separately owned. Ghidra native project data is external and does not become a shared Files directory.

Deployments have independent builds, locks, Watch Paths and image lifecycles. Rebuilding a Hand should not select the Dependencies application. Coolify's live network, persistent volumes, variables, saved Watch Paths and rollout state remain separate from source declarations.

## Identity and versioning

`BRIAREUS_NODE_ID` selects the external identity-provider role for one V1 node; users require that assignment. Multiple deployed V1 nodes are separate deployments and do not imply V2's autonomous Node control channel. See [OIDC](../oidc.md), [MCP OAuth](../oauth-chatgpt.md), [deployment](../operations/deployment.md).

**V2 is intentionally separate.** Its design includes Infrastructure/Hands, Node-local Project isolation, Cedar session grants, standalone Nodes and gRPC/WSS management. V1 documentation does not authorize implementing those V2 requirements in the currently deployed services.
